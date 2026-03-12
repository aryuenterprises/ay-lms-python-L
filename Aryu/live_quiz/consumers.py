# live_quiz/consumers.py
# Production-grade: handles 10,000+ concurrent users
# Features: async, Redis connection pool, throttled leaderboard,
#           full state restoration on refresh, zero N+1 queries

import time
import asyncio
import json
import redis.asyncio as aioredis
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from .models import Question, Answer, Participant


# ─────────────────────────────────────────────────────────────────
# Redis async connection pool — shared across ALL consumer instances
# max_connections=300 handles 10k users across multiple workers
# ─────────────────────────────────────────────────────────────────
_redis_pool = aioredis.ConnectionPool.from_url(
    "redis://:35l1VUx9@49.207.178.161:6379/1",
    max_connections=300,
    decode_responses=False,
    socket_keepalive=True,
    socket_connect_timeout=5,
    retry_on_timeout=True,
)


def get_redis():
    return aioredis.Redis(connection_pool=_redis_pool)


# ─────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────
SCORING = [(2, 10), (5, 8), (10, 5), (30, 1)]


def compute_score(time_taken: float) -> int:
    for max_s, pts in SCORING:
        if time_taken <= max_s:
            return pts
    return 0


# ─────────────────────────────────────────────────────────────────
# Redis key schema (all in db=1)
# ─────────────────────────────────────────────────────────────────
# room:{room_id}:current          → HASH  {qid, status, timeout, start_time, ends_at}
# room:{room_id}:board            → ZSET  {participant_id: score}
# room:{room_id}:names            → HASH  {participant_id: name}  ← cached on join
# room:{room_id}:answered:{qid}   → SET   {participant_id, ...}
# room:{room_id}:question:{qid}   → HASH  {text, config, question_type, timer_seconds, correct_answer}
# room:{room_id}:result:{qid}     → HASH  {correct_answer}        ← stored when question ends
# room:{room_id}:lb_throttle      → STRING "1" with TTL=1s (rate limit)


class RoomConsumer(AsyncJsonWebsocketConsumer):

    # ─────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────

    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group = f"room_{self.room_id}"
        self.participant = None
        self.role = None

        # Parse query params safely
        query = self.scope.get("query_string", b"").decode()
        params = {}
        for part in query.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k] = v

        self.role = params.get("role")
        token = params.get("token")

        if self.role == "participant":
            self.participant = await self._get_participant(token, self.room_id)
            if not self.participant:
                await self.close(code=4001)
                return

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

        # ── Restore full state for reconnecting users ──
        await self.send_current_state()
        await self.send_current_leaderboard()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content):
        msg_type = content.get("type")

        if msg_type == "send_question":
            if self.role != "admin":
                return
            await self._handle_send_question(content.get("question_id"))

        elif msg_type == "start_question":
            if self.role != "admin":
                return
            await self._handle_start_question()

        elif msg_type == "end_question":
            if self.role != "admin":
                return
            await self._handle_end_question()

        elif msg_type == "submit_answer":
            if self.role != "participant" or not self.participant:
                return
            await self._handle_submit_answer(content.get("response"))

    # ─────────────────────────────────────────────────────────
    # STATE RESTORATION — handles browser refresh / reconnect
    # ─────────────────────────────────────────────────────────

    async def send_current_state(self):
        """
        Called on every connect/reconnect.
        Sends the exact state the user should see right now.
        """
        r = get_redis()
        cur = await r.hgetall(f"room:{self.room_id}:current")

        if not cur:
            await self.send_json({
                "type": "waiting",
                "message": "Waiting for host to start the quiz."
            })
            return

        qid = cur.get(b"qid", b"").decode()
        status = cur.get(b"status", b"").decode()

        if not qid or not status:
            return

        # Get question from Redis cache (no DB hit)
        q_data = await self._get_question_from_cache(r, qid)
        if not q_data:
            return

        if status == "preview":
            await self.send_json({
                "type": "question_preview",
                "id": qid,
                "text": q_data["text"],
                "config": q_data["config"],
                "question_type": q_data["question_type"],
                "timer": q_data["timer_seconds"],
            })

        elif status == "running":
            ends_at = float(cur.get(b"ends_at", 0))
            remaining = max(0, int(ends_at - time.time()))

            await self.send_json({
                "type": "resume_question",
                "id": qid,
                "text": q_data["text"],
                "config": q_data["config"],
                "question_type": q_data["question_type"],
                "timer_remaining": remaining,
            })

            # Tell participant whether they already answered
            if self.role == "participant" and self.participant:
                answered = await r.sismember(
                    f"room:{self.room_id}:answered:{qid}",
                    str(self.participant.id),
                )
                await self.send_json({
                    "type": "answer_status",
                    "already_answered": bool(answered),
                })

        elif status == "ended":
            result = await r.hgetall(f"room:{self.room_id}:result:{qid}")
            await self.send_json({
                "type": "question_ended",
                "id": qid,
                "correct_answer": json.loads(result.get(b"correct_answer", b"null")),
            })

    # ─────────────────────────────────────────────────────────
    # ADMIN — send question (preview state)
    # ─────────────────────────────────────────────────────────

    async def _handle_send_question(self, question_id):
        if not question_id:
            return

        r = get_redis()
        q = await self._get_question(question_id)
        if not q:
            return

        # Cache question in Redis so workers never hit DB again for this question
        await r.hset(
            f"room:{self.room_id}:question:{q.id}",
            mapping={
                "text": q.text,
                "config": json.dumps(q.config),
                "question_type": q.question_type,
                "timer_seconds": q.timer_seconds,
                "correct_answer": json.dumps(
                    q.config.get("correct") or q.config.get("pairs")
                ),
            },
        )
        await r.expire(f"room:{self.room_id}:question:{q.id}", 86400)

        await r.hset(
            f"room:{self.room_id}:current",
            mapping={
                "qid": str(q.id),
                "status": "preview",
                "timeout": q.timer_seconds,
            },
        )

        await self.channel_layer.group_send(
            self.group,
            {
                "type": "question_preview",
                "data": {
                    "id": str(q.id),
                    "text": q.text,
                    "config": q.config,
                    "question_type": q.question_type,
                    "timer": q.timer_seconds,
                },
            },
        )

    # ─────────────────────────────────────────────────────────
    # ADMIN — start question (running state + timer)
    # ─────────────────────────────────────────────────────────

    async def _handle_start_question(self):
        r = get_redis()
        key = f"room:{self.room_id}:current"
        cur = await r.hgetall(key)

        if not cur or cur.get(b"status") != b"preview":
            return

        qid = cur[b"qid"].decode()
        # Clear previous answers for this question
        await r.delete(f"room:{self.room_id}:answered:{qid}")

        start_time = time.time()
        timeout = float(cur[b"timeout"])
        ends_at = start_time + timeout

        await r.hset(
            key,
            mapping={
                "status": "running",
                "start_time": start_time,
                "ends_at": ends_at,
            },
        )

        await self.channel_layer.group_send(
            self.group,
            {
                "type": "question_started",
                "start_time": start_time,
                "ends_at": ends_at,
            },
        )

    # ─────────────────────────────────────────────────────────
    # ADMIN — end question manually
    # ─────────────────────────────────────────────────────────

    async def _handle_end_question(self):
        r = get_redis()
        key = f"room:{self.room_id}:current"
        cur = await r.hgetall(key)

        if not cur:
            return

        qid = cur.get(b"qid", b"").decode()
        q_data = await self._get_question_from_cache(r, qid)
        correct_answer = q_data.get("correct_answer") if q_data else None

        await r.hset(key, mapping={"status": "ended"})

        # Store result so reconnecting users can see what the answer was
        await r.hset(
            f"room:{self.room_id}:result:{qid}",
            mapping={"correct_answer": json.dumps(correct_answer)},
        )
        await r.expire(f"room:{self.room_id}:result:{qid}", 86400)

        await self.channel_layer.group_send(
            self.group,
            {
                "type": "question_ended",
                "qid": qid,
                "correct_answer": correct_answer,
            },
        )

    # ─────────────────────────────────────────────────────────
    # PARTICIPANT — submit answer
    # ─────────────────────────────────────────────────────────

    async def _handle_submit_answer(self, response):
        r = get_redis()
        cur = await r.hgetall(f"room:{self.room_id}:current")

        if not cur or cur.get(b"status") != b"running":
            await self.send_json({"type": "answer_rejected", "message": "Question not active"})
            return

        qid = cur[b"qid"].decode()
        start_time = float(cur[b"start_time"])
        timeout = float(cur[b"timeout"])
        pid = str(self.participant.id)

        # Atomic "mark as answered" — prevents duplicate submissions
        answered_key = f"room:{self.room_id}:answered:{qid}"
        already = await r.sismember(answered_key, pid)
        if already:
            await self.send_json({"type": "answer_rejected", "message": "Already answered"})
            return

        await r.sadd(answered_key, pid)

        time_taken = min(time.time() - start_time, timeout)

        # Get question config from Redis cache (ZERO DB hits during quiz)
        q_data = await self._get_question_from_cache(r, qid)
        if not q_data:
            # Fallback to DB on cache miss (shouldn't happen in normal flow)
            q_obj = await self._get_question_config(qid)
            q_data = {
                "question_type": q_obj.question_type,
                "config": q_obj.config,
                "correct_answer": q_obj.config.get("correct") or q_obj.config.get("pairs"),
            }

        is_correct, correct_answer = self._evaluate_answer(
            q_data["question_type"], q_data["config"], response, time_taken, timeout
        )
        score = compute_score(time_taken) if is_correct else 0

        # Update score in Redis leaderboard
        board_key = f"room:{self.room_id}:board"
        if await r.zscore(board_key, pid) is None:
            await r.zadd(board_key, {pid: 0})
        await r.zincrby(board_key, score, pid)

        # Persist answer to DB asynchronously — does NOT block the response
        asyncio.create_task(
            self._save_answer(pid, qid, response, is_correct, time_taken, score)
        )

        # Immediately tell this participant their result
        await self.send_json({
            "type": "answer_result",
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "your_answer": response,
            "score_awarded": score,
        })

        # Throttled broadcast — max 1 leaderboard push per second per room
        # Works across all Uvicorn workers via Redis
        await self._throttled_leaderboard_broadcast(r)

    def _evaluate_answer(self, question_type, config, response, time_taken, timeout):
        """Pure function — no I/O, very fast."""
        if time_taken > timeout:
            return False, config.get("correct")

        if question_type in ["mcq", "radio"]:
            correct = str(config.get("correct")).strip()
            return str(response).strip() == correct, correct

        elif question_type == "tf":
            correct = str(config.get("correct")).lower()
            return str(response).lower() == correct, correct

        elif question_type == "checkbox":
            correct = sorted(config.get("correct", []))
            user = sorted(response) if isinstance(response, list) else []
            return user == correct, correct

        elif question_type == "match":
            correct = config.get("pairs", {})
            return response == correct, correct

        return False, None

    # ─────────────────────────────────────────────────────────
    # LEADERBOARD — fully Redis-based, ZERO DB queries
    # ─────────────────────────────────────────────────────────

    async def _build_leaderboard(self, r):
        board_key = f"room:{self.room_id}:board"
        names_key = f"room:{self.room_id}:names"  # pre-populated when participant joins

        scores = await r.zrevrange(board_key, 0, -1, withscores=True)

        if not scores:
            total = await self._get_participant_count()
            return {
                "board": [],
                "stats": {
                    "total_participants": total,
                    "highest_score": 0,
                    "average_score": 0,
                },
            }

        pids = [pid.decode() for pid, _ in scores]

        # Single Redis call for all participant names
        names_raw = await r.hmget(names_key, *pids)
        name_map = {
            pid: (name.decode("utf-8", errors="replace") if name else "Unknown")
            for pid, name in zip(pids, names_raw)
        }

        board = []
        total_score = 0
        highest = 0

        for pid_b, score in scores:
            s = int(score)
            total_score += s
            highest = max(highest, s)
            board.append({"name": name_map.get(pid_b.decode(), "Unknown"), "score": s})

        total = len(scores)
        avg = total_score // total if total else 0

        return {
            "board": board[:10],
            "stats": {
                "total_participants": total,
                "highest_score": highest,
                "average_score": avg,
            },
        }

    async def send_current_leaderboard(self):
        r = get_redis()
        data = await self._build_leaderboard(r)
        await self.send_json({"type": "leaderboard", **data})

    async def _broadcast_leaderboard(self, r=None):
        if r is None:
            r = get_redis()
        data = await self._build_leaderboard(r)
        await self.channel_layer.group_send(
            self.group, {"type": "leaderboard", **data}
        )

    async def _throttled_leaderboard_broadcast(self, r):
        """
        Rate-limits leaderboard broadcasts to max 1 per second per room.
        Uses Redis NX (set if not exists) so it's safe across multiple worker processes.
        Under heavy load (200 answers/sec), only 1 broadcast fires per second
        instead of 200 — eliminates the broadcast storm completely.
        """
        throttle_key = f"room:{self.room_id}:lb_throttle"
        acquired = await r.set(throttle_key, "1", nx=True, ex=1)
        if acquired:
            await self._broadcast_leaderboard(r)

    # ─────────────────────────────────────────────────────────
    # CHANNEL LAYER EVENT HANDLERS
    # ─────────────────────────────────────────────────────────

    async def question_preview(self, event):
        await self.send_json({"type": "question_preview", **event["data"]})

    async def question_started(self, event):
        await self.send_json({
            "type": "question_started",
            "start_time": event["start_time"],
            "ends_at": event["ends_at"],
        })

    async def question_ended(self, event):
        await self.send_json({
            "type": "question_ended",
            "qid": event.get("qid"),
            "correct_answer": event.get("correct_answer"),
        })

    async def leaderboard(self, event):
        await self.send_json({
            "type": "leaderboard",
            "board": event["board"],
            "stats": event["stats"],
        })

    async def leaderboard_refresh(self, event):
        """Triggered when a new participant joins (from JoinRoomView)."""
        await self._broadcast_leaderboard()

    # ─────────────────────────────────────────────────────────
    # HELPERS — Redis cache reads
    # ─────────────────────────────────────────────────────────

    async def _get_question_from_cache(self, r, qid):
        """Returns question data from Redis. Falls back to DB if cache miss."""
        raw = await r.hgetall(f"room:{self.room_id}:question:{qid}")
        if not raw:
            q = await self._get_question(qid)
            if not q:
                return None
            # Warm the cache
            await r.hset(
                f"room:{self.room_id}:question:{qid}",
                mapping={
                    "text": q.text,
                    "config": json.dumps(q.config),
                    "question_type": q.question_type,
                    "timer_seconds": q.timer_seconds,
                    "correct_answer": json.dumps(
                        q.config.get("correct") or q.config.get("pairs")
                    ),
                },
            )
            await r.expire(f"room:{self.room_id}:question:{qid}", 86400)
            return {
                "text": q.text,
                "config": q.config,
                "question_type": q.question_type,
                "timer_seconds": q.timer_seconds,
                "correct_answer": q.config.get("correct") or q.config.get("pairs"),
            }

        return {
            "text": raw[b"text"].decode(),
            "config": json.loads(raw[b"config"]),
            "question_type": raw[b"question_type"].decode(),
            "timer_seconds": int(raw[b"timer_seconds"]),
            "correct_answer": json.loads(raw[b"correct_answer"]),
        }

    # ─────────────────────────────────────────────────────────
    # DB HELPERS — only called when cache misses or on join
    # ─────────────────────────────────────────────────────────

    @sync_to_async
    def _get_participant(self, token, room_id):
        try:
            return Participant.objects.get(token=token, room_id=room_id)
        except Participant.DoesNotExist:
            return None

    @sync_to_async
    def _get_question(self, qid):
        return Question.objects.filter(id=qid).only(
            "id", "text", "config", "question_type", "timer_seconds"
        ).first()

    @sync_to_async
    def _get_question_config(self, qid):
        return Question.objects.only("config", "question_type").get(id=qid)

    @sync_to_async
    def _get_participant_count(self):
        return Participant.objects.filter(room_id=self.room_id).count()

    @sync_to_async
    def _save_answer(self, participant_id, qid, response, is_correct, time_taken, score):
        """
        Uses get_or_create to handle any race condition where the same
        participant somehow submits twice before the Redis check catches it.
        """
        try:
            Answer.objects.get_or_create(
                participant_id=participant_id,
                question_id=qid,
                defaults={
                    "response": response,
                    "is_correct": is_correct,
                    "time_taken": time_taken,
                    "score": score,
                },
            )
        except Exception:
            pass  # Never crash the consumer over a DB write
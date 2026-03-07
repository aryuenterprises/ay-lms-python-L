import time, redis
from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from .models import Question, Answer, Participant

# redis_client = redis.Redis(host="127.0.0.1", port=6379, db=0)

redis_client = redis.Redis(
    host="49.207.178.161",
    port=6379,
    password="35l1VUx9",
    db=1,
    decode_responses=False
)


SCORING = [(2, 10), (5, 8), (10, 5), (30, 1)]


def compute_score(time_taken):
    for max_s, pts in SCORING:
        if time_taken <= max_s:
            return pts
    return 0


class RoomConsumer(JsonWebsocketConsumer):

    def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group = f"room_{self.room_id}"

        query = self.scope["query_string"].decode()
        params = dict(x.split("=") for x in query.split("&") if "=" in x)

        self.role = params.get("role")
        self.token = params.get("token")

        if self.role == "participant":
            try:
                self.participant = Participant.objects.get(
                    token=self.token, room_id=self.room_id
                )
            except Participant.DoesNotExist:
                self.close()
                return
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()
        self.send_current_state()
        self.send_current_leaderboard()

    def disconnect(self, code):
        async_to_sync(self.channel_layer.group_discard)(self.group, self.channel_name)

    def send_current_state(self):
        cur = redis_client.hgetall(f"room:{self.room_id}:current")

        if not cur:
            self.send_json({
                "type": "error",
                "code": "NO_ACTIVE_QUESTION",
                "message": "No question is currently active. Please wait for the host."
            })
            return

        qid = cur.get(b"qid")
        status = cur.get(b"status")

        if not qid or not status:
            self.send_json({
                "type": "error",
                "code": "INVALID_ROOM_STATE",
                "message": "Quiz state is corrupted. Please refresh."
            })
            return

        qid = qid.decode()
        status = status.decode()

        q = Question.objects.filter(id=qid).only(
            "text", "config", "question_type", "timer_seconds"
        ).first()

        if not q:
            self.send_json({
                "type": "error",
                "code": "QUESTION_NOT_FOUND",
                "message": "The current question was removed or does not exist."
            })
            return

        # PREVIEW STATE (admin sent question, timer not started)
        if status == "preview":
            self.send_json({
                "type": "question_preview",
                "id": qid,
                "text": q.text,
                "config": q.config,
                "question_type": q.question_type,
                "timer": q.timer_seconds
            })
            return

        # RUNNING STATE (timer active)
        if status == "running":
            ends_at = float(cur[b"ends_at"])
            remaining = max(0, int(ends_at - time.time()))

            self.send_json({
                "type": "resume_question",
                "id": qid,
                "text": q.text,
                "config": q.config,
                "question_type": q.question_type,
                "timer_remaining": remaining
            })

            if self.role == "participant":
                answered_key = f"room:{self.room_id}:answered:{qid}"
                already_answered = redis_client.sismember(
                    answered_key, str(self.participant.id)
                )

                self.send_json({
                    "type": "answer_status",
                    "already_answered": bool(already_answered)
                })

    def question_preview(self, event):
        self.send_json({
            "type": "question_preview",
            **event["data"]
        })

    def receive_json(self, msg):
        if msg["type"] == "send_question":
            if self.role != "admin":
                return
            self.send_question(msg["question_id"])

        elif msg["type"] == "start_question":
            if self.role != "admin":
                return
            self.start_question()

        elif msg["type"] == "submit_answer":
            if self.role != "participant":
                return
            self.submit_answer(msg["response"])

    def send_question(self, question_id):
        q = Question.objects.only(
            "id", "text", "config", "question_type", "timer_seconds"
        ).get(id=question_id)

        # Store PREVIEW state (NO TIMER)
        redis_client.hset(
            f"room:{self.room_id}:current",
            mapping={
                "qid": str(q.id),
                "status": "preview",
                "timeout": q.timer_seconds
            }
        )

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {
                "type": "question_preview",
                "data": {
                    "id": str(q.id),
                    "text": q.text,
                    "config": q.config,
                    "question_type": q.question_type,
                    "timer": q.timer_seconds
                }
            }
        )

    def start_question(self):
        key = f"room:{self.room_id}:current"
        cur = redis_client.hgetall(key)

        if not cur or cur.get(b"status") != b"preview":
            return

        qid = cur[b"qid"].decode()

        # CLEAR OLD ANSWERS FOR THIS QUESTION
        redis_client.delete(f"room:{self.room_id}:answered:{qid}")

        start_time = time.time()
        timeout = float(cur[b"timeout"])
        ends_at = start_time + timeout

        redis_client.hset(
            key,
            mapping={
                "status": "running",
                "start_time": start_time,
                "ends_at": ends_at
            }
        )

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {
                "type": "question_started",
                "start_time": start_time,
                "ends_at": ends_at
            }
        )

    def question_started(self, event):
        self.send_json({
            "type": "question_started",
            "start_time": event["start_time"],
            "ends_at": event["ends_at"]
        })

    def broadcast_question(self, event):
        self.send_json({"type": "question", **event["data"]})

    def submit_answer(self, response):
        participant = self.participant

        cur = redis_client.hgetall(f"room:{self.room_id}:current")
        if not cur:
            return
        # BLOCK answering unless admin started the question
        if cur.get(b"status") != b"running":
            self.send_json({
                "type": "answer_rejected",
                "message": "Question not started by admin"
            })
            return

        qid = cur[b"qid"].decode()
        start_time = float(cur[b"start_time"])
        timeout = float(cur[b"timeout"])
        
        answered_key = f"room:{self.room_id}:answered:{qid}"
        if redis_client.sismember(answered_key, str(participant.id)):
            return
        
        # Mark answered immediately (anti double submit)
        redis_client.sadd(answered_key, str(participant.id))
        time_taken = time.time() - start_time
        q = Question.objects.only("config", "question_type").get(id=qid)
        is_correct = False
        correct_answer = None

        # ---------------- NORMALIZED COMPARISONS ---------------- #

        if q.question_type in ["mcq", "radio"]:
            correct_answer = str(q.config.get("correct")).strip()
            user_answer = str(response).strip()
            is_correct = user_answer == correct_answer

        elif q.question_type == "tf":
            # Frontend sends boolean, normalize everything to string
            correct_answer = str(q.config.get("correct")).lower()
            user_answer = str(response).lower()
            is_correct = user_answer == correct_answer

        elif q.question_type == "checkbox":
            correct_answer = sorted(q.config.get("correct", []))
            user_answer = sorted(response) if isinstance(response, list) else []
            is_correct = user_answer == correct_answer

        elif q.question_type == "match":
            correct_answer = q.config.get("pairs", {})
            is_correct = response == correct_answer

        # Time exceeded → force wrong
        if time_taken > timeout:
            is_correct = False

        # Time-based scoring
        score = compute_score(time_taken) if is_correct else 0

        # Update leaderboard
        board_key = f"room:{self.room_id}:board"
        pid = str(participant.id)

        # Ensure participant exists in leaderboard
        if redis_client.zscore(board_key, pid) is None:
            redis_client.zadd(board_key, {pid: 0})

        # Increment score (can be 0 or more)
        redis_client.zincrby(board_key, score, pid)

        # Persist answer
        Answer.objects.create(
            participant_id=participant.id,
            question_id=qid,
            response=response,
            is_correct=is_correct,
            time_taken=time_taken,
            score=score
        )

        # Send result to participant
        self.send_json({
            "type": "answer_result",
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "your_answer": response,
            "score_awarded": score
        })

        # Broadcast updated leaderboard
        self.send_leaderboard()

    def build_leaderboard(self):
        # Scores from Redis
        scores = redis_client.zrevrange(
            f"room:{self.room_id}:board", 0, -1, withscores=True
        )

        board = []
        total_score = 0
        highest_score = 0

        for pid, score in scores:
            score = int(score)
            total_score += score
            highest_score = max(highest_score, score)

            name = Participant.objects.only("name").get(id=pid.decode()).name
            board.append({
                "name": name,
                "score": score
            })

        total_participants = Participant.objects.filter(
            room_id=self.room_id
        ).count()

        average_score = (
            total_score // total_participants if total_participants else 0
        )

        return {
            "board": board[:10],
            "stats": {
                "total_participants": total_participants,
                "highest_score": highest_score,
                "average_score": average_score
            }
        }

    def send_leaderboard(self):
        """
        Broadcast leaderboard to everyone in room.
        Used after answer submission.
        """
        data = self.build_leaderboard()

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {
                "type": "leaderboard",
                **data
            }
        )

    def send_current_leaderboard(self):
        """
        Send leaderboard only to current connected client.
        Used on websocket connect.
        """
        data = self.build_leaderboard()

        self.send_json({
            "type": "leaderboard",
            **data
        })

    def leaderboard(self, event):
        self.send_json({
            "type": "leaderboard",
            "board": event["board"],
            "stats": event["stats"]
        })

    def leaderboard_refresh(self, event):
        data = self.build_leaderboard()
        self.send_json({
            "type": "leaderboard",
            **data
        })


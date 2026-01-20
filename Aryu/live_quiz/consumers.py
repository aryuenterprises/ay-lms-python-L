import time, redis
from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from .models import Question, Answer, Participant

redis_client = redis.Redis(host="127.0.0.1", port=6379, db=0)

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
        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()

    def disconnect(self, code):
        async_to_sync(self.channel_layer.group_discard)(self.group, self.channel_name)

    def receive_json(self, msg):
        if msg["type"] == "start_question":
            self.start_question(msg["question_id"])

        elif msg["type"] == "submit_answer":
            self.submit_answer(msg["token"], msg["response"])

    def start_question(self, question_id):
        q = Question.objects.only(
            "id", "text", "config", "timer_seconds", "question_type"
        ).get(id=question_id)

        redis_client.hmset(
            f"room:{self.room_id}:current",
            {
                "qid": str(q.id),
                "start": time.time(),
                "timeout": q.timer_seconds,
                "type": q.question_type
            }
        )

        redis_client.delete(f"room:{self.room_id}:answered:{q.id}")

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {
                "type": "broadcast_question",
                "data": {
                    "id": str(q.id),
                    "text": q.text,
                    "type": q.question_type,
                    "config": q.config,
                    "timer": q.timer_seconds
                }
            }
        )

    def broadcast_question(self, event):
        self.send_json({"type": "question", **event["data"]})

    def submit_answer(self, token, response):
        participant = Participant.objects.only("id").get(token=token)

        cur = redis_client.hgetall(f"room:{self.room_id}:current")
        qid = cur[b"qid"].decode()

        answered_key = f"room:{self.room_id}:answered:{qid}"
        if redis_client.sismember(answered_key, participant.id):
            return

        redis_client.sadd(answered_key, participant.id)

        time_taken = time.time() - float(cur[b"start"])

        q = Question.objects.only("config", "question_type").get(id=qid)
        is_correct = False

        if q.question_type in ["mcq", "radio"]:
            is_correct = response == q.config["correct"]

        elif q.question_type == "tf":
            is_correct = response == q.config["correct"]

        elif q.question_type == "match":
            is_correct = response == q.config["pairs"]

        elif q.question_type == "poll":
            is_correct = False  # no score

        if is_correct:
            score = compute_score(time_taken)

        redis_client.zincrby(
            f"room:{self.room_id}:board", score, participant.id
        )

        Answer.objects.create(
            participant_id=participant.id,
            question_id=qid,
            response=response,
            is_correct=is_correct,
            time_taken=time_taken,
            score=score
        )

        redis_client.zincrby(
            f"room:{self.room_id}:board",
            score,
            participant.id
        )

        self.send_leaderboard()

    def send_leaderboard(self):
        top = redis_client.zrevrange(
            f"room:{self.room_id}:board", 0, 9, withscores=True
        )

        board = []
        for pid, score in top:
            name = Participant.objects.only("name").get(id=pid.decode()).name
            board.append({"name": name, "score": int(score)})

        async_to_sync(self.channel_layer.group_send)(
            self.group,
            {"type": "leaderboard", "board": board}
        )

    def leaderboard(self, event):
        self.send_json({"type": "leaderboard", "board": event["board"]})

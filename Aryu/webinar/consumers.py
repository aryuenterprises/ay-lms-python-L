import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from webinar.models import Webinar
from webinar.services.signaling import start_webinar, end_webinar
from webinar.services.webrtc import *


class WebinarConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.webinar_id = self.scope["url_route"]["kwargs"]["webinar_id"]
        self.room_group_name = f"webinar_{self.webinar_id}"

        # Validate webinar existence
        if not await self.webinar_exists():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Notify join
        await self.broadcast("join", {
            "user": str(self.scope["user"])
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        await self.broadcast("leave", {
            "user": str(self.scope["user"])
        })

    async def receive(self, text_data):
        data = json.loads(text_data)

        msg_type = data.get("type")
        payload = data.get("payload", {})

        if msg_type == "webrtc_offer":
            await self.handle_webrtc_offer(payload)

        elif msg_type == "webrtc_answer":
            await self.handle_webrtc_answer(payload)

        elif msg_type == "ice_candidate":
            await self.handle_ice_candidate(payload)

        elif msg_type == "start":
            await self.handle_start_webinar()

        elif msg_type == "end":
            await self.handle_end_webinar()

    # =========================
    # WebRTC Handlers
    # =========================

    async def handle_webrtc_offer(self, payload):
        message = webrtc_offer_payload(
            offer_sdp=payload.get("sdp"),
            sender_id=str(self.scope["user"])
        )
        await self.broadcast(**message)

    async def handle_webrtc_answer(self, payload):
        message = webrtc_answer_payload(
            answer_sdp=payload.get("sdp"),
            sender_id=str(self.scope["user"])
        )
        await self.broadcast(**message)

    async def handle_ice_candidate(self, payload):
        message = webrtc_ice_payload(payload)
        await self.broadcast(**message)

    # =========================
    # Webinar Lifecycle
    # =========================

    async def handle_start_webinar(self):
        await database_sync_to_async(start_webinar)(
            self.webinar_id,
            self.scope["user"]
        )

    async def handle_end_webinar(self):
        await database_sync_to_async(end_webinar)(
            self.webinar_id
        )

    # =========================
    # Helpers
    # =========================

    async def broadcast(self, type, payload):
        """
        Broadcast message to webinar group
        """
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "webinar_message",
                "event": type,
                "payload": payload,
            }
        )

    async def webinar_message(self, event):
        await self.send(text_data=json.dumps({
            "type": event["event"],
            "payload": event["payload"],
        }))

    # =========================
    # DB Ops
    # =========================

    @database_sync_to_async
    def webinar_exists(self):
        return Webinar.objects.filter(uuid=self.webinar_id).exists()

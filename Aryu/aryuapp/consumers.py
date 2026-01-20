#consumers.py

import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import ChatRoom, Message, Notification
from .serializer import MessageSerializer, NotificationSerializer
import django
import jwt
from django.conf import settings


django.setup()
# ------------------ CHAT CONSUMER ------------------
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import ChatRoom, Message
from .serializer import MessageSerializer


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"chat_{self.room_id}"

        try:
            self.room = await database_sync_to_async(ChatRoom.objects.get)(id=self.room_id)
        except ChatRoom.DoesNotExist:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # Load last 30 messages
        history, has_more = await self.get_messages(limit=30)

        await self.send(json.dumps({
            "success": True,
            "message": "Messages fetched successfully",
            "type": "history",
            "data": history,
            "has_more": has_more,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        # -------- Pagination (load more) ------------
        if action == "load_more":
            before_id = data.get("before_id")

            messages = await self.get_messages(limit=30, before_id=before_id)

            await self.send(json.dumps({
                "success": True,
                "message": "Messages fetched successfully",
                "type": "history",
                "data": messages
            }))
            return

        # -------- Normal send message ---------------
        message = await self.create_message(data)
        serialized = MessageSerializer(message).data

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "message": serialized
            }
        )

    async def chat_message(self, event):
        await self.send(json.dumps({
            "success": True,
            "type": "chat_message",
            "data": event["message"]
        }))

    # -------- Pagination Logic ----------
    @database_sync_to_async
    def get_messages(self, limit=30, before_id=None):
        qs = Message.objects.filter(room=self.room).order_by("-id")

        if before_id:
            qs = qs.filter(id__lt=before_id)

        msgs = list(qs[:limit])
        serialized = [MessageSerializer(m).data for m in msgs[::-1]]

        # Check if more messages exist
        has_more = Message.objects.filter(
            room=self.room,
            id__lt=(msgs[-1].id if msgs else 0)
        ).exists()

        return serialized, has_more

    @database_sync_to_async
    def create_message(self, data):
        return Message.objects.create(
            room=self.room,
            sender_type=data.get("sender_type"),
            sender_id=data.get("sender_id"),
            content=data.get("content", ""),
            upload=data.get("upload"),
            audio_file=data.get("audio_file"),
            created_at=timezone.now(),
        )
    

# ------------------ NOTIFICATION CONSUMER ------------------
class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        from urllib.parse import parse_qs

        qs = parse_qs(self.scope["query_string"].decode())
        token = qs.get("token", [None])[0]

        if not token:
            await self.close()
            return

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            self.user_type = payload.get("user_type")

            if self.user_type == "student":
                self.user_id = payload.get("registration_id")
            elif self.user_type == "tutor":
                self.user_id = payload.get("employee_id")
            elif self.user_type == "employer":
                self.user_id = payload.get("employer_id")
            else:
                await self.close()
                return

        except Exception:
            await self.close()
            return

        self.group_name = f"notifications_{self.user_type}_{self.user_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        latest = await self.get_latest_notifications()

        await self.send(text_data=json.dumps({
            "type": "init_notifications",
            "data": latest
        }))

    async def notify(self, event):
        unread = await self.get_unread_count()

        await self.send(text_data=json.dumps({
            "type": "notification",
            "data": event["notification"],
            "unread_count": unread
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify(self, event):
        await self.send(text_data=json.dumps({
            "type": "notification",
            "data": event["notification"]
        }))

    @database_sync_to_async
    def get_latest_notifications(self):
        from django.db import connection

        try:
            if self.user_type == "student":
                qs = Notification.objects.filter(student__registration_id=self.user_id)
            elif self.user_type == "tutor":
                qs = Notification.objects.filter(trainer__employee_id=self.user_id)
            else:
                qs = Notification.objects.filter(sub_admin__employer_id=self.user_id)

            return NotificationSerializer(qs.order_by("-created_at")[:10], many=True).data

        finally:
            # VERY IMPORTANT
            connection.close()

    @database_sync_to_async
    def get_unread_count(self):
        if self.user_type == "student":
            return Notification.objects.filter(student__registration_id=self.user_id, is_read=False).count()
        elif self.user_type == "tutor":
            return Notification.objects.filter(trainer__employee_id=self.user_id, is_read=False).count()
        else:
            return Notification.objects.filter(sub_admin__employer_id=self.user_id, is_read=False).count()



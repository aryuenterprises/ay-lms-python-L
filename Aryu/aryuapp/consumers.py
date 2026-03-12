# aryuapp/consumers.py
# Chat: WhatsApp-style — WebSocket handles send + receive directly
# Notifications: push-only — no unread fetch on connect, only live pushes

import json
import jwt
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.conf import settings
from .models import ChatRoom, Message, Notification
from .serializer import MessageSerializer, NotificationSerializer


# ══════════════════════════════════════════════════════════════════
# CHAT CONSUMER — WhatsApp style
# Flow:
#   connect()     → join room group, send last 30 messages as history
#   receive()     → save message to DB + broadcast to room group
#   chat_message()→ channel layer handler, sends to this WebSocket
#   disconnect()  → leave room group
# ══════════════════════════════════════════════════════════════════

class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"chat_{self.room_id}"
        self.room = None  # ✅ always initialize before any early return

        self.room = await self._get_room(self.room_id)
        if not self.room:
            await self.close(code=4004)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # Send last 30 messages so user sees chat history immediately on open
        history, has_more = await self._get_messages(limit=30)
        await self.send(json.dumps({
            "success": True,
            "type": "history",
            "data": history,
            "has_more": has_more,
        }))

    async def disconnect(self, close_code):
        # ✅ guard — room_group_name may not be set if connect() failed early
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get("action")

        # ── Load older messages (infinite scroll / pagination) ────
        if action == "load_more":
            before_id = data.get("before_id")
            messages, has_more = await self._get_messages(limit=30, before_id=before_id)
            await self.send(json.dumps({
                "success": True,
                "type": "history",
                "data": messages,
                "has_more": has_more,
            }))
            return

        # ── Send a new message ────────────────────────────────────
        # Student or trainer sends a message via WebSocket directly.
        # We save it to DB first, then broadcast to the room group
        # so BOTH the sender and receiver get it in real time.
        if action == "send_message":
            if not self.room:
                return

            sender_type = data.get("sender_type")  # "student" or "trainer"
            sender_id = data.get("sender_id")
            content = data.get("content", "").strip()

            if not sender_type or not sender_id or not content:
                await self.send(json.dumps({
                    "success": False,
                    "type": "error",
                    "message": "sender_type, sender_id, and content are required",
                }))
                return

            message = await self._create_message(
                sender_type=sender_type,
                sender_id=sender_id,
                content=content,
            )
            serialized = await self._serialize_message(message)

            # Broadcast to ALL connections in this room (sender + receiver)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message": serialized,
                }
            )
            return

        # ── Mark all messages in room as read ─────────────────────
        if action == "mark_read":
            sender_type = data.get("sender_type")
            await self._mark_messages_read(self.room_id, sender_type)
            await self.send(json.dumps({
                "success": True,
                "type": "mark_read",
                "message": "Messages marked as read",
            }))
            return

    async def chat_message(self, event):
        """
        Channel layer handler.
        Called when anyone in the room group sends a message.
        Delivers it to this specific WebSocket connection.
        """
        await self.send(json.dumps({
            "success": True,
            "type": "chat_message",
            "data": event["message"],
        }))

    # ─────────────────────────────────────────────────────────
    # DB HELPERS
    # ─────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_room(self, room_id):
        from django.db import connection
        try:
            return ChatRoom.objects.select_related("student", "trainer").get(id=room_id)
        except ChatRoom.DoesNotExist:
            return None
        finally:
            connection.close()

    @database_sync_to_async
    def _get_messages(self, limit=30, before_id=None):
        from django.db import connection
        try:
            qs = Message.objects.filter(
                room=self.room,
                is_deleted=False,
            ).order_by("-id")

            if before_id:
                qs = qs.filter(id__lt=before_id)

            msgs = list(qs[:limit])
            serialized = [MessageSerializer(m).data for m in reversed(msgs)]

            has_more = (
                Message.objects.filter(
                    room=self.room,
                    is_deleted=False,
                    id__lt=(msgs[-1].id if msgs else 0),
                ).exists()
                if msgs else False
            )
            return serialized, has_more
        finally:
            connection.close()

    @database_sync_to_async
    def _create_message(self, sender_type, sender_id, content):
        from django.db import connection
        try:
            return Message.objects.create(
                room=self.room,
                sender_type=sender_type,
                sender_id=sender_id,
                content=content,
                created_at=timezone.now(),
            )
        finally:
            connection.close()

    @database_sync_to_async
    def _serialize_message(self, message):
        return MessageSerializer(message).data

    @database_sync_to_async
    def _mark_messages_read(self, room_id, sender_type):
        """
        Mark messages as read — only marks messages from the OTHER side.
        If student opens chat → mark trainer messages as read, and vice versa.
        """
        from django.db import connection
        try:
            opposite = "trainer" if sender_type == "student" else "student"
            Message.objects.filter(
                room_id=room_id,
                sender_type=opposite,
                is_read=False,
            ).update(is_read=True)
        finally:
            connection.close()


# ══════════════════════════════════════════════════════════════════
# NOTIFICATION CONSUMER — push only
# Flow:
#   connect()   → join personal group, send unread COUNT only
#   notify()    → channel layer handler called by signals.py on new notification
#   receive()   → handle mark_read from frontend
#   disconnect()→ leave group
#
# NOTE: signals.py calls group_send("type": "notify") when a
#       Notification is saved — this consumer just delivers it live.
#       Full notification list comes from REST API (NotificationListView).
# ══════════════════════════════════════════════════════════════════

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        from urllib.parse import parse_qs

        # Always initialize — prevents AttributeError in disconnect()
        self.group_name = None
        self.user_type = None
        self.user_id = None

        qs = parse_qs(self.scope.get("query_string", b"").decode())
        token = qs.get("token", [None])[0]

        if not token:
            await self.close(code=4001)
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
            elif self.user_type in ["admin", "super_admin"]:
                self.user_id = payload.get("user_id") or payload.get("employee_id")
            else:
                await self.close(code=4002)
                return

        except jwt.ExpiredSignatureError:
            await self.close(code=4003)
            return
        except Exception:
            await self.close(code=4004)
            return

        if not self.user_id:
            await self.close(code=4005)
            return

        self.group_name = f"notifications_{self.user_type}_{self.user_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send only the unread COUNT on connect.
        # Frontend uses REST API (NotificationListView) for full list.
        # WebSocket is only for live pushes after this point.
        unread_count = await self._get_unread_count()
        await self.send(text_data=json.dumps({
            "type": "connected",
            "unread_count": unread_count,
        }))

    async def disconnect(self, close_code):
        # FIXED — self.group_name is always initialized so this never crashes
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """Frontend sends mark_read or mark_all_read via WebSocket."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if data.get("action") == "mark_read":
            notification_id = data.get("notification_id")
            if notification_id:
                await self._mark_notification_read(notification_id)
                unread_count = await self._get_unread_count()
                await self.send(text_data=json.dumps({
                    "type": "unread_count",
                    "unread_count": unread_count,
                }))

        elif data.get("action") == "mark_all_read":
            await self._mark_all_read()
            await self.send(text_data=json.dumps({
                "type": "unread_count",
                "unread_count": 0,
            }))

    async def notify(self, event):
        """
        Channel layer handler — triggered by signals.py via:
            async_to_sync(channel_layer.group_send)(
                group_name, {"type": "notify", "notification": serialized_data}
            )
        Delivers the new notification to this WebSocket in real time.
        """
        unread_count = await self._get_unread_count()
        await self.send(text_data=json.dumps({
            "type": "notification",
            "data": event["notification"],
            "unread_count": unread_count,
        }))

    # ─────────────────────────────────────────────────────────
    # DB HELPERS
    # ─────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_unread_count(self):
        from django.db import connection
        try:
            if self.user_type == "student":
                return Notification.objects.filter(
                    student__registration_id=self.user_id,
                    is_read=False,
                ).count()
            elif self.user_type == "tutor":
                return Notification.objects.filter(
                    trainer__employee_id=self.user_id,
                    is_read=False,
                ).count()
            elif self.user_type == "employer":
                return Notification.objects.filter(
                    sub_admin__employer_id=self.user_id,
                    is_read=False,
                ).count()
            elif self.user_type in ["admin", "super_admin"]:
                return Notification.objects.filter(
                    trainer__employee_id=self.user_id,
                    is_read=False,
                ).count()
            return 0
        finally:
            connection.close()

    @database_sync_to_async
    def _mark_notification_read(self, notification_id):
        from django.db import connection
        try:
            Notification.objects.filter(id=notification_id).update(is_read=True)
        finally:
            connection.close()

    @database_sync_to_async
    def _mark_all_read(self):
        from django.db import connection
        try:
            if self.user_type == "student":
                Notification.objects.filter(
                    student__registration_id=self.user_id,
                    is_read=False,
                ).update(is_read=True)
            elif self.user_type == "tutor":
                Notification.objects.filter(
                    trainer__employee_id=self.user_id,
                    is_read=False,
                ).update(is_read=True)
            elif self.user_type == "employer":
                Notification.objects.filter(
                    sub_admin__employer_id=self.user_id,
                    is_read=False,
                ).update(is_read=True)
            elif self.user_type in ["admin", "super_admin"]:
                Notification.objects.filter(
                    trainer__employee_id=self.user_id,
                    is_read=False,
                ).update(is_read=True)
        finally:
            connection.close()
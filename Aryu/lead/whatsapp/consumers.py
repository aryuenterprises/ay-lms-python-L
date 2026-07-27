import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
import logging

logger = logging.getLogger("whatsapp")

class SmartInboxConsumer(AsyncWebsocketConsumer):
    """
    Security-hardened real-time streaming WebSocket consumer.
    Protects transport connections with strict scope validation and routes high-frequency events.
    """
    async def connect(self):
        # 1. Parse query params ONLY ONCE
        query_string = self.scope["query_string"].decode("utf-8")
        query_params = dict(qc.split("=") for qc in query_string.split("&") if "=" in qc)
        
        self.queue_name = query_params.get("queue", "unassigned")
        test_bypass = query_params.get("bypass", "false")
        self.active_phone = query_params.get("phone_number")

        # Initialize tracking parameters to prevent Disconnect crashes
        self.group_channel_id = None
        self.thread_group_id = None

        # 2. Single, unified authentication check
        is_anonymous = self.scope.get("user") is None or self.scope["user"].is_anonymous
        
        if is_anonymous and test_bypass != "true":
            logger.warning("WebSocket handshake rejected: Request is unauthenticated or missing session scope.")
            await self.close(code=4003)
            return

        # 3. Validate queue
        if self.queue_name not in ["unassigned", "active", "resolved"]:
            await self.close(code=4000)
            return

        # 4. Accept the connection ONCE before adding to groups
        await self.accept()

        # 5. Join the general queue group
        self.group_channel_id = f"chat_queue_{self.queue_name}"
        await self.channel_layer.group_add(
            self.group_channel_id,
            self.channel_name
        )
        logger.info(f"WebSocket Connected successfully to channel group: {self.group_channel_id}")

        # 6. Dynamically join the specific active phone thread (if provided)
        if self.active_phone:
            cleaned_phone = self.active_phone.replace('+', '').replace(' ', '').strip()
            self.thread_group_id = f"chat_thread_{cleaned_phone}"
            await self.channel_layer.group_add(
                self.thread_group_id, 
                self.channel_name
            )
            logger.info(f"Agent subscribed to live chat thread: {self.thread_group_id}")

    async def disconnect(self, close_code):
        # Clean up general queue subscription
        if self.group_channel_id:
            await self.channel_layer.group_discard(
                self.group_channel_id,
                self.channel_name
            )
            logger.info(f"WebSocket Discarded group: {self.group_channel_id}")

        # Clean up active conversation thread subscription to prevent memory leaks in Redis
        if self.thread_group_id:
            await self.channel_layer.group_discard(
                self.thread_group_id,
                self.channel_name
            )
            logger.info(f"WebSocket Discarded thread group: {self.thread_group_id}")

    # Triggered by the Kafka Consumer inside run_kafka_consumer.py
    async def chat_message_inbound(self, event):
        """
        Pushes the live customer message directly to the frontend agent thread panel.
        """
        message_data = event.get("data", {})
        
        # --- ENHANCEMENT: Extract phone number from wrapping event layer if omitted inside data ---
        if "phone_number" not in message_data:
            # Check if phone number is attached to the parent event payload dictionary
            phone = event.get("phone_number") or event.get("phone")
            if phone:
                message_data["phone_number"] = str(phone)

        logger.info(f"📬 [WEBSOCKET OUTGOING] Sending inbound message {message_data.get('id')} to UI client.")
        
        await self.send(text_data=json.dumps({
            "event": "new_message", 
            "data": message_data
        }))

    # Triggered by status updates or queue mutations
    async def queue_message_update(self, event):
        """
        Catches mutations across chat queues and broadcasts to sidebars or main windows.
        """
        logger.info(f"📋 [WEBSOCKET QUEUE UPDATE] Broadcast event routed down to interface client.")
        
        payload_data = event.get("data") or {
            "id": event.get("message_id"),
            "chat_id": event.get("chat_id"),
            "body": event.get("body"),
            "direction": event.get("direction"),
            "sender_type": event.get("sender_type"),
            "created_at": event.get("created_at")
        }

        # --- ENHANCEMENT: Keep phone identity parity uniform ---
        if "phone_number" not in payload_data:
            phone = event.get("phone_number") or event.get("phone")
            if phone:
                payload_data["phone_number"] = str(phone)
        
        await self.send(text_data=json.dumps({
            "event": "new_message", 
            "data": payload_data
        }))

    async def receive(self, text_data):
        """
        Receives structural outbound requests from UI Agents.
        """
        logger.info("WebSocket Incoming: Received command frame payload from client UI.")
        try:
            data = json.loads(text_data)
            action = data.get("action")
            logger.info("WebSocket Action Parser: Processing action request: '%s'", action)
            
            if action == "send_message":
                # 1. Persist to DB and handoff to Kafka safely off the async thread loop
                logger.info("WebSocket: Enqueueing outbound message payload for recipient %s", data.get("phone_number"))
                pending_msg_payload = await self.process_outbound_agent_message(data)
                
                # 2. IMMEDIATELY send an acknowledgment back to the sending agent over the WS connection
                await self.send(text_data=json.dumps({
                    "event": "message_queued",
                    "data": pending_msg_payload
                }))
                logger.info("WebSocket Acknowledgement: Sent 'message_queued' frame back to client.")
                
        except Exception as e:
            logger.error("WebSocket Exception: Message pipeline validation broke down: %s", str(e), exc_info=True)
            await self.send(text_data=json.dumps({
                "event": "error",
                "message": f"Message pipeline validation failed: {str(e)}"
            }))

    @database_sync_to_async
    def process_outbound_agent_message(self, data):
        """
        Pure database transaction wrapper. Never invoke async side-effects (like self.send) inside here.
        """
        from .services.chat_engine import WhatsAppChatEngine
        engine = WhatsAppChatEngine()
        
        # Saves record to DB as 'pending' status and returns a WhatsAppMessage instance
        msg = engine.queue_outbound_message(
            sender=self.scope["user"],
            phone_number=data["phone_number"],
            message_type=data.get("message_type", "text"),
            body=data.get("body"),
            template_name=data.get("template_name"),
            media_url=data.get("media_url"),
            variables=data.get("variables", [])
        )
        
        # Return standard native data structures safe to pass through async loops
        return {
            "id": msg.id,
            "chat_id": msg.chat.id,
            "status": msg.status,
            "body": msg.body,
            "direction": msg.direction,
            "sender_type": msg.sender_type,
            "created_at": msg.created_at.isoformat() if msg.created_at else None
        }
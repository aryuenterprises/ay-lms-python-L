import json
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from confluent_kafka import Consumer, KafkaError
from lead.whatsapp.services.meta_client import MetaClient
from ...models import WhatsAppChat, WhatsAppMessage
from lead.models import Lead

logger = logging.getLogger("whatsapp")

class Command(BaseCommand):
    help = 'Runs the Kafka consumer for live inbound and outbound WhatsApp messages'

    def handle(self, *args, **options):
        conf = {
            'bootstrap.servers': '49.207.178.161:9092',
            'group.id': 'whatsapp_live_group',
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
        }

        consumer = Consumer(conf)
        # Fix: Subscribe to both inbound and outbound streaming topics simultaneously
        consumer.subscribe(['whatsapp_inbound_messages', 'whatsapp_outbound_messages'])
        channel_layer = get_channel_layer()

        # ── FORCE CONSOLE VISIBILITY ──
        print("🚀 [STARTUP] Kafka Consumer initiated. Polling for messages...")
        logger.info("Kafka Consumer started. Listening for live inbound and outbound messages...")

        try:
            while True:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(msg.error())
                        print(f"❌ Kafka Error encountered: {msg.error()}")
                        break

                # Inspect message metadata to extract origin topic
                topic = msg.topic()

                # 1. Safely decode the incoming string/bytes payload
                raw_payload = msg.value().decode('utf-8')
                payload = json.loads(raw_payload)
                
                # Double-serialization resilience fallback
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse double-serialized payload string: {payload}")
                        continue

                # 2. Topic-driven execution routing
                if topic == 'whatsapp_inbound_messages':
                    print(f"📥 New inbound message intercepted from Kafka topic! Processing payload...")
                    self.process_and_broadcast(payload, channel_layer)
                elif topic == 'whatsapp_outbound_messages':
                    print(f"📤 New outbound message intercepted from Kafka topic! Processing payload...")
                    self.process_and_deliver_outbound(payload, channel_layer)

        finally:
            print("🛑 Closing Kafka Consumer connection cleanly.")
            consumer.close()

    def process_and_broadcast(self, message_obj, channel_layer):
        """Saves incoming messages to DB securely and broadcasts to WebSockets."""
        print(f"🔍 [DEBUG] Processing inbound message structure: {json.dumps(message_obj)}")
        logger.info(f"▶ [KAFKA CONSUMER] Received event from Kafka queue: {message_obj}")
        
        from_phone = message_obj.get('from') or message_obj.get('phone') or message_obj.get('phone_number')
        wamid = message_obj.get('id') or message_obj.get('message_id') or message_obj.get('wamid')
        
        text_entry = message_obj.get('text', '')
        if isinstance(text_entry, dict):
            body_content = text_entry.get('body', '')
        else:
            body_content = text_entry or message_obj.get('body', '')

        if not from_phone or not wamid:
            error_msg = f"❌ [KAFKA CONSUMER] Guardrail Triggered! Missing mandatory keys ('from' or 'id') in payload."
            print(error_msg)
            logger.warning(error_msg)
            return

        clean_phone = str(from_phone).replace("+", "").strip()

        try:
            print(f"💾 [DB STEP] Accessing models for phone: +{clean_phone}...")
            lead_obj, _ = Lead.objects.get_or_create(phone=f"+{clean_phone}")
            
            chat_obj, _ = WhatsAppChat.objects.get_or_create(
                whatsapp_id=clean_phone,
                defaults={
                    'lead': lead_obj, 
                    'phone_number': f"+{clean_phone}", 
                    'status': 'unassigned'
                }
            )
            
            msg_instance, created = WhatsAppMessage.objects.get_or_create(
                message_id=wamid,
                defaults={
                    'chat': chat_obj, 
                    'sender_type': 'customer', 
                    'direction': 'incoming', 
                    'message_type': 'text', 
                    'body': body_content
                }
            )

            print(f"✅ [DB SUCCESS] Saved ID: {msg_instance.id} | New Record created: {created}")
            
            thread_group_name = f"chat_thread_{clean_phone}"
            queue_group_name = f"chat_queue_{chat_obj.status}"

            payload_data = {
                "type": "chat_message_inbound",
                "data": {
                    "id": msg_instance.id,
                    "chat_id": chat_obj.id,
                    "body": body_content,
                    "direction": "incoming",
                    "sender_type": "customer",
                    "created_at": msg_instance.created_at.isoformat() if hasattr(msg_instance, 'created_at') else None
                }
            }

            async_to_sync(channel_layer.group_send)(thread_group_name, payload_data)
            async_to_sync(channel_layer.group_send)(queue_group_name, payload_data)
            print(f"🎉 [WS SUCCESS] Live updates broadcast to active channels.")
            
        except Exception as e:
            print(f"💥 [CRITICAL RUNTIME ERROR] Failed execution path inside process_and_broadcast: {str(e)}")
            logger.error(f"❌ [KAFKA CONSUMER] Channels execution pipeline broke down: {str(e)}", exc_info=True)

    def process_and_deliver_outbound(self, payload, channel_layer):
        """Processes pending agent dashboard messages, handles Meta delivery, and patches UI views."""
        db_message_id = payload["message_id"]
        print(f"🔍 [DEBUG] Processing outbound message structure: {json.dumps(payload)}")
        
        meta_client = MetaClient()
        
        try:
            # 1. Execute external handshake via Meta Cloud API
            if payload["message_type"] == "text":
                res = meta_client.send_text_message(
                    phone_number=payload["phone_number"],
                    body=payload["body"]
                )
            elif payload["message_type"] == "template":
                res = meta_client.send_template_message(
                    phone_number=payload["phone_number"],
                    template_name=payload["template_name"],
                    language="en_US", 
                    rendered_body=payload["body"],
                    variables=payload["variables"]
                )
            else:
                raise ValueError(f"Unsupported outbound message type: {payload['message_type']}")
            
            # Extract production message ID from Meta response mapping rules
            meta_wa_id = res.get("messages", [{}])[0].get("id", f"error_fallback_{db_message_id}")
            self.update_outbound_state(db_message_id, "sent", meta_wa_id, channel_layer)
            
        except Exception as e:
            error_msg = f"💥 Failed Meta Delivery Handshake for msg {db_message_id}: {str(e)}"
            print(error_msg)
            logger.error(error_msg)
            self.update_outbound_state(db_message_id, "failed", None, channel_layer, error_details=str(e))

    def update_outbound_state(self, msg_id: int, status: str, meta_id: str, channel_layer, error_details: str = None):
        """Atomically locks the database tracking frame and updates the frontend views via WebSockets."""
        with transaction.atomic():
            msg = WhatsAppMessage.objects.select_related('chat').get(id=msg_id)
            msg.status = status
            if meta_id:
                msg.message_id = meta_id
            if error_details:
                if msg.meta_payload is None:
                    msg.meta_payload = {}
                msg.meta_payload["error"] = error_details
            msg.save(update_fields=["status", "message_id", "meta_payload"])
            
            chat = msg.chat
            chat.last_message_at = msg.created_at
            chat.save(update_fields=["last_message_at"])

        print(f"✅ [DB SUCCESS] Updated Outbound Message ID: {msg.id} to status: {status}")

        clean_phone = str(chat.phone_number).replace("+", "").strip()
        thread_group_name = f"chat_thread_{clean_phone}"
        queue_group_name = f"chat_queue_{chat.status}"

        # Build combined payload mapping block to fulfill any extraction path inside SmartInboxConsumer
        broadcast_payload = {
            "type": "queue_message_update",
            "message_id": msg.id,
            "chat_id": chat.id,
            "status": status,
            "body": msg.body,
            "direction": msg.direction,
            "sender_type": msg.sender_type,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "phone_number": clean_phone,
            "data": {
                "id": msg.id,
                "chat_id": chat.id,
                "status": status,
                "body": msg.body,
                "direction": msg.direction,
                "sender_type": msg.sender_type,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "phone_number": clean_phone
            }
        }

        # Double-route updates: updates both the open active chat screen thread and the global status lists
        async_to_sync(channel_layer.group_send)(thread_group_name, broadcast_payload)
        async_to_sync(channel_layer.group_send)(queue_group_name, broadcast_payload)
        print(f"🎉 [WS SUCCESS] Outbound live updates broadcast successfully.")
import logging
import re
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from aryuapp.models import User
from rest_framework.exceptions import ValidationError
from lead.whatsapp.models import WhatsAppChat, WhatsAppMessage
from lead.whatsapp.apps import KafkaProducerClient

logger = logging.getLogger(__name__)

class WhatsAppChatEngine:
    """
    Orchestration engine for enterprise-grade live-chat messaging.
    Enforces Meta API compliance, handles dynamic lazy initialization for new numbers,
    and publishes jobs to high-throughput message buses.
    """
    
    # Explicitly allow and validate a mandatory or optional leading '+' followed by E.164 digits
    PHONE_REGEX = re.compile(r"^\+?\d{10,15}$") 

    @classmethod
    def validate_and_standardize_phone(cls, phone_number: str) -> str:
        """
        Cleans and standardizes variations like +919677377316, 919677377316, or 9677377316.
        Returns a clean E.164 string ALWAYS starting with a '+' symbol.
        """
        if not phone_number:
            raise ValidationError("Phone number cannot be empty.")

        # 1. Strip out any spaces or hyphens, but retain the string value
        cleaned = str(phone_number).replace(" ", "").replace("-", "").strip()

        # 2. Extract only digits to evaluate base formatting lengths safely
        digits_only = cleaned.replace("+", "")

        # 3. Handle 10-digit local variants (e.g., '9677377316' -> prepend country code)
        if len(digits_only) == 10 and digits_only.isdigit():
            cleaned = f"+91{digits_only}"
        else:
            # For all international formats, explicitly guarantee it starts with a '+'
            cleaned = f"+{digits_only}"

        # 4. Final structural validation check
        if not cls.PHONE_REGEX.match(cleaned):
            raise ValidationError(f"Invalid phone number format structure: '{phone_number}'.")

        return cleaned

    @classmethod
    def check_meta_24h_window(cls, chat: WhatsAppChat) -> bool:
        """
        Enforces Meta compliance: Free-form text messages can only be sent if the 
        customer has sent an incoming message within the last 24 hours.
        """
        if not chat.last_message_at:
            return False
            
        last_inbound = WhatsAppMessage.objects.filter(
            chat=chat, 
            direction="incoming"
        ).order_by("-created_at").only("created_at").first()
        
        if not last_inbound:
            return False
            
        return timezone.now() - last_inbound.created_at <= timedelta(hours=24)

    @transaction.atomic
    def queue_outbound_message(
        self, 
        sender: User, 
        phone_number: str, 
        message_type: str, 
        body: str = None, 
        template_name: str = None, 
        media_url: str = None,
        variables: list = None
    ) -> WhatsAppMessage:
        """
        Pre-saves message frames inside transactional blocks, handles automatic 
        automation-to-human state suspension, and offloads outbound frames to Kafka.
        
        Allows template messages to go out seamlessly even when automation is enabled,
        automatically transferring control back to the human agent.
        """
        from lead.models import Lead
        
        cleaned_phone = self.validate_and_standardize_phone(phone_number)
        local_10_digits = cleaned_phone[-10:]

        # Query using the standardized +E.164 pattern and take an exclusive row lock
        chat = WhatsAppChat.objects.filter(phone_number=cleaned_phone).select_for_update().first()

        if not chat:
            # Match existing leads by checking if their phone contains the same last 10 digits
            lead = Lead.objects.filter(phone__icontains=local_10_digits).first()
            if not lead:
                lead = Lead.objects.create(
                    phone=cleaned_phone,
                    first_name="WhatsApp Lead",
                    last_name=local_10_digits,
                )

            chat = WhatsAppChat.objects.create(
                lead=lead,
                phone_number=cleaned_phone,
                whatsapp_id=f"wa_chat_{cleaned_phone.replace('+', '')}", # keeps whatsapp_id clean without + symbol
                status=WhatsAppChat.STATUS_UNASSIGNED,
                customer_name=f"Lead ({cleaned_phone})",
                is_automated=False, 
                last_message_at=timezone.now()
            )
        else:
            # FIX: If automation is active, cleanly intercept and disable it so the human agent's 
            # message overrides the bot, regardless of message type (text or template).
            if chat.is_automated:
                chat.is_automated = False
                chat.save(update_fields=['is_automated'])
                logger.info(f"Dashboard Outbound Action: Automation suspended for chat {cleaned_phone} by agent {sender.id}")

        # Strict compliance validation guard: Only enforce the 24-hour window check on free-form text messages.
        # Template messages are explicitly allowed outside the window to initiate contact.
        if message_type == "text":
            if not self.check_meta_24h_window(chat):
                raise ValidationError(
                    "Meta Compliance Error: Outbound customer-care window has expired (24-hour rule). "
                    "You must initiate contact using an approved Meta Template Message."
                )

        # Build clean body for templates if not explicitly passed by frontend mapping framework
        display_body = body
        if message_type == "template" and not display_body:
            display_body = f"📄 Template Message Sent: {template_name}"

        # Initialize the pending tracking frame record
        message = WhatsAppMessage.objects.create(
            chat=chat,
            message_id=f"pending_{timezone.now().timestamp()}_{chat.id}",
            sender_type="agent",
            direction="outgoing",
            message_type=message_type,
            body=display_body,
            media_url=media_url,
            template_name=template_name,
            status="pending",
            meta_payload={"variables": variables or []}
        )
        
        # Structure payload package for processing inside the HighThroughputMessageConsumer worker
        payload = {
            "message_id": message.id,
            "chat_id": chat.id,
            "phone_number": cleaned_phone.replace("+", ""),  # Strip + prefix out for direct compatibility with Meta payloads
            "message_type": message_type,
            "body": display_body,
            "template_name": template_name,
            "variables": variables or [],
            "media_url": media_url
        }
        
        # Publish event transaction safely onto the outbound streaming pipeline
        KafkaProducerClient.publish_event(
            topic="whatsapp_outbound_messages",
            key=str(chat.id),
            value=payload
        )
        
        return message
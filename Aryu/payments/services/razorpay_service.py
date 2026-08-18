import hmac
import hashlib
import json
import logging
from django.db import transaction as db_transaction
from django.conf import settings

logger = logging.getLogger("razorpay_webhook")

def get_active_razorpay_gateway(gateway_name="razorpay"):
    """
    Retrieve the active, unarchived Razorpay PaymentGateway object.
    Checks for gatway_name matching razorpay and ensures is_archived=False.
    """
    from payments.models import PaymentGateway

    return PaymentGateway.objects.filter(
        gatway_name__icontains=gateway_name,
        is_archived=False
    ).order_by("-updated_at", "-id").first()

def get_webhook_secret(gateway=None):
    """
    Get stripped webhook secret from gateway model or settings fallback.
    """
    if gateway and getattr(gateway, "webhook_secret", None):
        secret = gateway.webhook_secret.strip()
        if secret:
            return secret

    if gateway and getattr(gateway, "secret_key", None):
        secret = gateway.secret_key.strip()
        if secret:
            return secret

    # Fallback to settings if configured
    settings_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", None) or getattr(settings, "RAZORPAY_KEY_SECRET", None)
    if settings_secret:
        return settings_secret.strip()

    return None

def verify_razorpay_signature(raw_body: bytes, received_signature: str, webhook_secret: str) -> bool:
    """
    Perform Razorpay HMAC-SHA256 signature verification over exact raw request bytes.
    Follows Razorpay's official webhook verification specification:
    HMAC-SHA256(raw_request_bytes, webhook_secret) == received_signature
    Uses constant-time comparison via hmac.compare_digest().
    """
    if not raw_body or not received_signature or not webhook_secret:
        logger.error("Razorpay Signature Verification: Missing body, signature, or webhook secret.")
        return False

    if isinstance(raw_body, str):
        raw_bytes = raw_body.encode("utf-8")
    elif isinstance(raw_body, bytes):
        raw_bytes = raw_body
    else:
        logger.error("Razorpay Signature Verification: Invalid raw_body type %s", type(raw_body))
        return False

    secret_str = str(webhook_secret).strip()
    signature_str = str(received_signature).strip()

    expected_signature = hmac.new(
        key=secret_str.encode("utf-8"),
        msg=raw_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    logger.debug(f'expected_signature: {expected_signature}')

    is_valid = hmac.compare_digest(expected_signature.lower(), signature_str.lower())
    if not is_valid:
        logger.error("Razorpay Signature Verification: Mismatch! Expected len=%d, Received len=%d",
                     len(expected_signature), len(signature_str))

    return is_valid

def process_razorpay_webhook_event(data: dict) -> dict:
    """
    Process verified Razorpay webhook payload idempotently.
    Handles payment.captured, payment.authorized, and payment.failed events.
    Supports Webinar, Ebook, Resume, and general PaymentTransaction flows.
    """
    from payments.models import PaymentTransaction

    event = data.get("event")
    logger.info("Processing Razorpay Webhook Event: %s", event)

    if event in ["payment.captured", "payment.authorized"]:
        entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = entity.get("order_id")
        payment_id = entity.get("id")

        if not order_id:
            logger.error("Razorpay Webhook Event %s: Missing order_id in payload", event)
            return {"status": "error", "message": "Missing order_id", "processed": False}

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.select_for_update().filter(order_id=order_id).first()

            if not txn:
                logger.warning("Razorpay Webhook: No PaymentTransaction found for order_id %s", order_id)
                return {"status": "success", "message": "Transaction not found, safe acknowledge", "processed": False}

            # Idempotency check: if transaction is already marked as done/paid, skip re-processing
            if txn.payment_status in ["done", "paid", "success"]:
                logger.info("Razorpay Webhook: Transaction %s already processed (status=%s). Skipping.",
                            order_id, txn.payment_status)
                return {"status": "success", "message": "Already processed", "processed": True}

            # Update PaymentTransaction status safely
            txn.payment_status = "done"
            if payment_id:
                if not isinstance(txn.metadata, dict):
                    txn.metadata = {}
                txn.metadata["razorpay_payment_id"] = payment_id
            txn.save()

            # 1. Handle Webinar Registration Payment Flow
            metadata = txn.metadata if isinstance(txn.metadata, dict) else {}
            phone = metadata.get("phone")
            webinar_id = metadata.get("webinar_id")

            if webinar_id or getattr(txn, "webinar_registration", None):
                try:
                    from webinar.models import WebinarRegistration
                    web_reg = None
                    if getattr(txn, "webinar_registration", None):
                        web_reg = txn.webinar_registration
                    elif phone and webinar_id:
                        web_reg = WebinarRegistration.objects.filter(
                            phone=phone,
                            webinar__uuid=webinar_id
                        ).first()

                    if web_reg:
                        logger.info("Updating WebinarRegistration ID %s for phone: %s to paid.", web_reg.id, phone)
                        web_reg.is_paid = True
                        web_reg.payment_transaction = txn
                        web_reg.save(update_fields=["is_paid", "payment_transaction"])
                except Exception as e:
                    logger.exception("Error updating WebinarRegistration for transaction %s: %s", txn.id, e)

            # 2. Handle Ebook Registration Payment Flow
            if metadata.get("ebook_id") or metadata.get("registration_id") or getattr(txn, "ebookregistration", None):
                try:
                    from ebook.views import EbookRegistrationViewSet
                    EbookRegistrationViewSet.update_registration_after_payment(txn)
                    logger.info("Updated EbookRegistration for transaction %s", txn.id)
                except Exception as e:
                    logger.exception("Error updating EbookRegistration for transaction %s: %s", txn.id, e)

            # 3. Handle Resume Registration Payment Flow
            if getattr(txn, "resume_registration", None):
                try:
                    resume_reg = txn.resume_registration
                    resume_reg.is_paid = True
                    resume_reg.save(update_fields=["is_paid"])
                    logger.info("Updated ResumeRegistration ID %s to paid.", resume_reg.id)
                except Exception as e:
                    logger.exception("Error updating ResumeRegistration for transaction %s: %s", txn.id, e)

            return {"status": "success", "message": "Payment processed successfully", "processed": True}

    elif event == "payment.failed":
        entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = entity.get("order_id")

        if order_id:
            with db_transaction.atomic():
                updated_count = PaymentTransaction.objects.filter(order_id=order_id).update(payment_status="failed")
                logger.info("Razorpay Webhook: Marked %d transaction(s) for order %s as failed.", updated_count, order_id)
            return {"status": "success", "message": "Transaction marked failed", "processed": True}

    logger.info("Razorpay Webhook: Unhandled or informational event %s", event)
    return {"status": "success", "message": f"Event {event} acknowledged", "processed": False}

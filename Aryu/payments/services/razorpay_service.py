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
    MUST NOT fall back to API Key Secret (secret_key).
    """
    if gateway and getattr(gateway, "webhook_secret", None):
        secret = str(gateway.webhook_secret).strip()
        if secret:
            return secret

    # Fallback to settings if configured
    settings_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", None)
    if settings_secret:
        return str(settings_secret).strip()

    return None

def verify_razorpay_signature(raw_body: bytes, received_signature: str, webhook_secret: str, event_id: str = None) -> bool:
    """
    Perform Razorpay HMAC-SHA256 signature verification over exact raw request bytes.
    Follows Razorpay's official webhook verification specification:
    HMAC-SHA256(raw_request_bytes, webhook_secret) == received_signature
    Uses constant-time comparison via hmac.compare_digest().
    """
    if not raw_body or not received_signature or not webhook_secret:
        logger.error("=== RAZORPAY WEBHOOK DIAGNOSTIC === Signature Verification Failed: Missing body, signature, or webhook secret.")
        return False

    if isinstance(raw_body, str):
        raw_bytes = raw_body.encode("utf-8")
    elif isinstance(raw_body, bytes):
        raw_bytes = raw_body
    else:
        logger.error("=== RAZORPAY WEBHOOK DIAGNOSTIC === Signature Verification Failed: Invalid raw_body type %s", type(raw_body))
        return False

    secret_str = str(webhook_secret).strip()
    signature_str = str(received_signature).strip()

    body_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    secret_fingerprint = hashlib.sha256(secret_str.encode("utf-8")).hexdigest()[:12]

    expected_signature = hmac.new(
        key=secret_str.encode("utf-8"),
        msg=raw_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_signature.lower(), signature_str.lower())

    if is_valid:
        logger.info(
            "=== RAZORPAY WEBHOOK DIAGNOSTIC === MATCH! event_id=%s body_length=%d body_sha256=%s secret_len=%d secret_fp=%s",
            event_id or "N/A", len(raw_bytes), body_sha256, len(secret_str), secret_fingerprint
        )
    else:
        logger.error(
            "=== RAZORPAY WEBHOOK DIAGNOSTIC === MISMATCH! event_id=%s body_length=%d body_sha256=%s secret_len=%d secret_fp=%s expected_sig=%s received_sig=%s",
            event_id or "N/A", len(raw_bytes), body_sha256, len(secret_str), secret_fingerprint, expected_signature, signature_str
        )

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

            # Idempotency check: if transaction is already marked as done/paid/success, skip re-processing
            if txn.payment_status in ["done", "paid", "success"]:
                logger.info("Razorpay Webhook: Transaction %s already processed (status=%s). Skipping.",
                            order_id, txn.payment_status)
                return {"status": "success", "message": "Already processed", "processed": True}

            # Update PaymentTransaction status explicitly to "done"
            txn.payment_status = "done"
            if payment_id:
                if not isinstance(txn.metadata, dict):
                    txn.metadata = {}
                txn.metadata["razorpay_payment_id"] = payment_id
                txn.transaction_id = payment_id
            txn.save()

            # 1. Handle Webinar Registration Payment Flow & Student Creation
            metadata = txn.metadata if isinstance(txn.metadata, dict) else {}
            phone = metadata.get("phone")
            webinar_id = metadata.get("webinar_id")

            if webinar_id or getattr(txn, "webinar_registration", None):
                try:
                    from webinar.views import WebinarRegistrationViewSet
                    WebinarRegistrationViewSet.create_registration_from_transaction(txn)
                except Exception as e:
                    logger.exception("Error processing WebinarRegistration via create_registration_from_transaction for transaction %s: %s", txn.id, e)

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
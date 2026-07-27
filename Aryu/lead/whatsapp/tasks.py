"""
whatsapp/tasks.py

Celery task definitions for the WhatsApp Broadcast Studio pipeline.

Task hierarchy
──────────────
trigger_broadcast_task            ← campaign orchestrator (fan-out)
    └─ send_single_recipient_task ← per-message leaf worker
           (N parallel)
finalize_campaign_task            ← post-broadcast cleanup / status monitor

Retry policy
────────────
MetaRateLimitError (429):
    Exponential backoff  2^n × 30 s, capped at 600 s, up to 10 retries
    (~17 min total wait before permanent fail)

Transient errors (network, 5xx):
    Linear backoff  60 s × 3 retries

Permanent fails:
    No further retry — BroadcastProcessor._on_failure() has already
    persisted the error text and incremented failed_count via F().

Queue routing
─────────────
All broadcast tasks run on the dedicated `whatsapp_broadcast` queue so
high-volume sends never starve the inbound Smart Inbox consumers.

Required Celery settings (add to settings.py):
────────────────────────────────────────────────
CELERY_TASK_ROUTES = {
    "whatsapp.tasks.trigger_broadcast_task":     {"queue": "whatsapp_broadcast"},
    "whatsapp.tasks.send_single_recipient_task": {"queue": "whatsapp_broadcast"},
    "whatsapp.tasks.finalize_campaign_task":     {"queue": "whatsapp_broadcast"},
}
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_BACKEND  = "redis://localhost:6379/1"

Start the dedicated worker:
    celery -A core worker -Q whatsapp_broadcast --concurrency=8 -l info
"""

import logging
import os
import re
import time
import pandas as pd
import phonenumbers

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from lead.models import Lead
from .models import (
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppChat,
    WhatsAppMessage,
)
from .services.broadcast_engine import BroadcastProcessor
from .services.meta_client import MetaClient, MetaRateLimitError

logger = logging.getLogger("whatsapp")

# ── Retry constants ───────────────────────────────────────────────────

RATE_LIMIT_BASE_BACKOFF: int = 30    # seconds — doubles each retry
RATE_LIMIT_MAX_BACKOFF: int = 600    # 10 minute ceiling per retry
RATE_LIMIT_MAX_RETRIES: int = 10

TRANSIENT_RETRY_DELAY: int = 60      # seconds (linear)
TRANSIENT_MAX_RETRIES: int = 3


# ══════════════════════════════════════════════════════════════════════
# Task 1 — Campaign orchestrator (fan-out)
# ══════════════════════════════════════════════════════════════════════

@shared_task(
    bind=True,
    name="whatsapp.tasks.trigger_broadcast_task",
    queue="whatsapp_broadcast",
    acks_late=True,              # ACK only after task body completes
    reject_on_worker_lost=True,  # re-queue if the worker process crashes
    max_retries=TRANSIENT_MAX_RETRIES,
    default_retry_delay=TRANSIENT_RETRY_DELAY,
)
def trigger_broadcast_task(self, campaign_id: int) -> dict:
    """
    Campaign orchestrator.

    Steps:
      1. Atomically transition campaign QUEUED → RUNNING.
         If this CAS fails (campaign already running / cancelled by another
         process), bail immediately — idempotent guard.
      2. Cursor-paginate over PENDING recipients and push one
         send_single_recipient_task per row.
      3. Schedule finalize_campaign_task after an estimated completion window.
    """
    logger.info("trigger_broadcast_task | campaign=%s", campaign_id)
    processor = BroadcastProcessor(campaign_id=campaign_id)

    if not processor.transition_to_running():
        logger.warning(
            "Campaign %s is not QUEUED; skipping trigger.", campaign_id
        )
        return {"campaign_id": campaign_id, "enqueued": 0, "status": "skipped"}

    try:
        enqueued = processor.enqueue_all_recipients()
    except Exception as exc:
        logger.exception(
            "Failed to enqueue recipients for campaign %s", campaign_id
        )
        processor.mark_failed(reason=str(exc))
        raise self.retry(exc=exc)

    # Conservative completion estimate:
    # (enqueued recipients / 20 msg-per-second) + 2 min buffer
    estimated_seconds = max(60, (enqueued // 20) + 120)
    finalize_campaign_task.apply_async(
        args=[campaign_id],
        countdown=estimated_seconds,
        queue="whatsapp_broadcast",
    )

    logger.info(
        "trigger_broadcast_task done | campaign=%s enqueued=%d finalize_in=%ds",
        campaign_id, enqueued, estimated_seconds,
    )
    return {
        "campaign_id": campaign_id,
        "enqueued":    enqueued,
        "status":      "running",
    }


# ══════════════════════════════════════════════════════════════════════
# Task 2 — Per-recipient leaf worker
# ══════════════════════════════════════════════════════════════════════

@shared_task(
    bind=True,
    name="whatsapp.tasks.send_single_recipient_task",
    queue="whatsapp_broadcast",
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_single_recipient_task(self, recipient_id: int) -> None:
    """
    Leaf task: execute the full send pipeline for exactly one recipient.

    Delegates all business logic to BroadcastProcessor.dispatch_single()
    and implements typed retry strategies here:

    • MetaRateLimitError  → exponential backoff (doubles each retry)
    • Any other Exception → linear backoff, max 3 retries
    """
    logger.debug("send_single_recipient_task | recipient=%s", recipient_id)

    processor = BroadcastProcessor(campaign_id=0)

    try:
        processor.dispatch_single(recipient_id=recipient_id)

    except MetaRateLimitError as exc:
        n = self.request.retries
        backoff = min((2 ** n) * RATE_LIMIT_BASE_BACKOFF, RATE_LIMIT_MAX_BACKOFF)

        logger.warning(
            "429 rate limit | recipient=%s retry=%d/%d backoff=%ds",
            recipient_id,
            n + 1,
            RATE_LIMIT_MAX_RETRIES,
            backoff,
        )
        try:
            raise self.retry(
                exc=exc,
                countdown=backoff,
                max_retries=RATE_LIMIT_MAX_RETRIES,
            )
        except MaxRetriesExceededError:
            logger.error(
                "Recipient %s exhausted %d rate-limit retries — permanently failed.",
                recipient_id,
                RATE_LIMIT_MAX_RETRIES,
            )

    except Exception as exc:
        logger.exception(
            "Transient error for recipient %s (attempt %d/%d)",
            recipient_id,
            self.request.retries + 1,
            TRANSIENT_MAX_RETRIES,
        )
        try:
            raise self.retry(
                exc=exc,
                countdown=TRANSIENT_RETRY_DELAY,
                max_retries=TRANSIENT_MAX_RETRIES,
            )
        except MaxRetriesExceededError:
            logger.error(
                "Recipient %s exhausted %d transient retries — permanently failed.",
                recipient_id,
                TRANSIENT_MAX_RETRIES,
            )


# ══════════════════════════════════════════════════════════════════════
# Task 3 — Campaign finalizer / straggler monitor
# ══════════════════════════════════════════════════════════════════════

@shared_task(
    bind=True,
    name="whatsapp.tasks.finalize_campaign_task",
    queue="whatsapp_broadcast",
    acks_late=True,
    max_retries=10,
    default_retry_delay=120,    # re-check every 2 minutes
)
def finalize_campaign_task(self, campaign_id: int) -> dict:
    """
    Post-broadcast cleanup and state monitor.
    """
    in_flight = WhatsAppCampaignRecipient.objects.filter(
        campaign_id=campaign_id,
        status__in=[
            WhatsAppCampaignRecipient.STATUS_PENDING,
            WhatsAppCampaignRecipient.STATUS_QUEUED,
            WhatsAppCampaignRecipient.STATUS_SENDING,
        ],
    ).count()

    if in_flight > 0:
        logger.info(
            "Campaign %s still has %d in-flight recipients — rechecking in 120s.",
            campaign_id, in_flight,
        )
        raise self.retry(countdown=120)

    processor = BroadcastProcessor(campaign_id=campaign_id)
    processor.finalize()

    logger.info("Campaign %s finalized.", campaign_id)
    return {"campaign_id": campaign_id, "status": "completed"}


# ══════════════════════════════════════════════════════════════════════
# Parsing Helpers & File Processing Tasks
# ══════════════════════════════════════════════════════════════════════

def extract_phone_numbers_and_params_from_file(file_path: str) -> list:
    """
    Parses phone numbers and tracks adjacent columns for dynamic template parameters.
    """
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path)
        
    normalized_cols = {col: re.sub(r'[^a-z0-9]', '', col.lower()) for col in df.columns}
    df = df.rename(columns=normalized_cols)
    
    target_patterns = ['phonenumber', 'mobile', 'phone', 'phno', 'ph no', 'contact', 'telephoneno', 'telephone']
    phone_col = None
    
    for pattern in target_patterns:
        if pattern in df.columns:
            phone_col = pattern
            break
            
    if not phone_col:
        raise ValueError("Could not find a valid phone number column in the uploaded file.")
        
    parameter_cols = [col for col in df.columns if col != phone_col]
    records = []
    default_country = getattr(settings, 'DEFAULT_COUNTRY_CODE', 'IN')
    
    for _, row in df.iterrows():
        raw_num = str(row[phone_col])
        if pd.isna(row[phone_col]) or not raw_num.strip():
            continue
        try:
            clean_num = raw_num.split('.')[0].strip()
            parsed = phonenumbers.parse(clean_num, default_country)
            
            if phonenumbers.is_valid_number(parsed):
                e164_number = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                
                row_params = []
                for col in parameter_cols:
                    val = row[col]
                    row_params.append("" if pd.isna(val) else str(val).split('.')[0].strip())
                    
                records.append({"phone": e164_number, "params": row_params})
        except Exception:
            continue
            
    seen = set()
    return [x for x in records if not (x["phone"] in seen or seen.add(x["phone"]))]


@shared_task(bind=True, name='whatsapp.tasks.process_excel_broadcast_task', max_retries=3)
def process_excel_broadcast_task(self, campaign_id: int, file_path: str):
    """
    Processes the broadcast, initializes tracking entries, and pushes outbound 
    records to WhatsAppChat/WhatsAppMessage pools to sync with live support inboxes.
    """
    try:
        campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
    except WhatsAppCampaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found.")
        # Perform cleanup on missing database objects to prevent local storage leaks
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    try:
        recipients = extract_phone_numbers_and_params_from_file(file_path)
        if not recipients:
            raise ValueError("No valid phone numbers found in the file.")
            
        WhatsAppCampaign.objects.filter(pk=campaign_id).update(
            status=WhatsAppCampaign.STATUS_RUNNING,
            total_recipients=len(recipients)
        )
        
        body_text = getattr(campaign.template, 'body', '')
        required_param_count = len(set(re.findall(r'\{\{(\d+)\}\}', body_text)))
        fallback_examples = getattr(campaign.template, 'body_variable_examples', []) or []
        
        meta_client = MetaClient()
        RATE_LIMIT_DELAY = 0.2
        
        for rec in recipients:
            recipient_phone = rec["phone"]
            row_params = rec["params"]
            
            # Recheck campaign status inside flow loops
            current_status = WhatsAppCampaign.objects.filter(pk=campaign_id).values_list('status', flat=True).first()
            if current_status in [WhatsAppCampaign.STATUS_PAUSED, WhatsAppCampaign.STATUS_CANCELLED]:
                return

            final_params = []
            for i in range(required_param_count):
                if i < len(row_params) and row_params[i] != "":
                    final_params.append(row_params[i])
                elif i < len(fallback_examples):
                    final_params.append(fallback_examples[i])
                else:
                    final_params.append("-")

            with transaction.atomic():
                # 1. Resolve or create structural tracking Lead record
                lead_name = final_params[0] if final_params else "Recipient"
                lead_obj, _ = Lead.objects.get_or_create(
                    phone=recipient_phone,
                    defaults={'name': lead_name}
                )
                
                # 2. Setup individual campaign target recipient entry
                recipient_entry, created = WhatsAppCampaignRecipient.objects.get_or_create(
                    campaign=campaign,
                    lead=lead_obj,
                    defaults={
                        'status': WhatsAppCampaignRecipient.STATUS_PENDING,
                        'custom_context': {'params': final_params}
                    }
                )
                
                if not created:
                    recipient_entry.custom_context = {'params': final_params}
                    recipient_entry.save(update_fields=['custom_context'])

            # Strip '+' symbol to establish clean format IDs required by Meta (e.g. "919677377316")
            clean_whatsapp_id = recipient_phone.replace("+", "").strip()

            try:
                # 3. Disseminate outbound payload message via Meta Cloud Channel
                response_data = meta_client.send_template_message(
                    phone_number=clean_whatsapp_id,
                    template_name=campaign.template.meta_template_name,
                    language=campaign.template.language,
                    rendered_body="",
                    variables=final_params
                )
                
                wamid = response_data.get("messages", [{}])[0].get("id")
                
                if wamid:
                    now_timestamp = timezone.now()
                    
                    with transaction.atomic():
                        # 4. Save campaign recipient state changes
                        recipient_entry.status = WhatsAppCampaignRecipient.STATUS_SENT
                        recipient_entry.whatsapp_message_id = wamid
                        recipient_entry.sent_at = now_timestamp
                        recipient_entry.save(update_fields=['status', 'whatsapp_message_id', 'sent_at'])
                        
                        # 5. INTEGRATION: Resolve or create a conversation chat thread record
                        chat_obj, _ = WhatsAppChat.objects.get_or_create(
                            whatsapp_id=clean_whatsapp_id,
                            defaults={
                                'lead': lead_obj,
                                'phone_number': recipient_phone,
                                'customer_name': lead_obj.name or lead_name,
                                'status': WhatsAppChat.STATUS_UNASSIGNED,
                                'is_automated': True
                            }
                        )
                        chat_obj.last_message_at = now_timestamp
                        chat_obj.save(update_fields=['last_message_at'])
                        
                        # 6. INTEGRATION: Append message history line entry into live chat flow logs
                        WhatsAppMessage.objects.create(
                            chat=chat_obj,
                            message_id=wamid,
                            sender_type="system",       # Marked as 'system' because it originates from automation loops
                            direction="outgoing",
                            message_type="template",
                            template_name=campaign.template.meta_template_name,
                            body=body_text,             # Retain the base unrendered text payload layout mapping context
                            status="sent",
                            campaign_recipient=recipient_entry
                        )
                        
                        WhatsAppCampaign.objects.filter(pk=campaign_id).update(sent_count=F('sent_count') + 1)
                else:
                    raise ValueError("Meta accepted payload sequence but tracking ID 'wamid' returned empty.")
                    
            except Exception as api_err:
                logger.error(f"API delivery failed for {recipient_phone}: {str(api_err)}")
                recipient_entry.status = WhatsAppCampaignRecipient.STATUS_FAILED
                recipient_entry.error = str(api_err)
                recipient_entry.save(update_fields=['status', 'error'])
                
                WhatsAppCampaign.objects.filter(pk=campaign_id).update(failed_count=F('failed_count') + 1)
                
            time.sleep(RATE_LIMIT_DELAY)
            
        WhatsAppCampaign.objects.filter(pk=campaign_id).update(status=WhatsAppCampaign.STATUS_COMPLETED)
        
    except Exception as e:
        logger.error(f"Error processing broadcast for campaign {campaign_id}: {str(e)}")
        WhatsAppCampaign.objects.filter(pk=campaign_id).update(status=WhatsAppCampaign.STATUS_FAILED)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
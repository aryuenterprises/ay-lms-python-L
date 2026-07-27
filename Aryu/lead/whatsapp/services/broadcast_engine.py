from __future__ import annotations

import logging
import re
from typing import Generator

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.core.cache import cache  # Added for global compliance rate-limiting tracking

from ..models import (
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppMessage,
)
from ..services.meta_client import MetaClient, MetaAPIError, MetaRateLimitError

logger = logging.getLogger("whatsapp")

# ── Constants ─────────────────────────────────────────────────────────

RECIPIENT_BATCH_SIZE: int = 100   # one B-Tree leaf page worth of rows

# Compiled once at module load; reused by every TemplateTokenizer instance.
_VAR_RE: re.Pattern = re.compile(r"\{\{(\w+)\}\}")


# ══════════════════════════════════════════════════════════════════════
# TemplateTokenizer
# ══════════════════════════════════════════════════════════════════════

class TemplateTokenizer:
    """
    Single-pass O(k) variable injector.

    Replaces {{key}} tokens using a compiled regex + dispatch dict.
    Compared to k separate str.replace() calls this performs exactly ONE
    linear scan of the body string regardless of how many variables exist —
    critical for 1 000+ personalised sends per campaign.

    Missing context keys degrade safely (placeholder is left intact).
    """

    __slots__ = ("_body",)

    def __init__(self, template_body: str) -> None:
        self._body = template_body

    def render(self, context: dict) -> str:
        def _sub(m: re.Match) -> str:
            return str(context.get(m.group(1), m.group(0)))

        return _VAR_RE.sub(_sub, self._body)


# ══════════════════════════════════════════════════════════════════════
# Cursor-paginated recipient iterator
# ══════════════════════════════════════════════════════════════════════

def _pending_recipients_cursor(
    campaign_id: int,
    batch_size: int = RECIPIENT_BATCH_SIZE,
) -> Generator[WhatsAppCampaignRecipient, None, None]:
    """
    Keyset-paginate over PENDING recipients for a campaign.

    Uses the composite index (campaign_id, status, id) — each page seek
    is O(log n) via the B-Tree. Memory footprint is O(batch_size), never
    O(total_recipients).

    Per-page protocol:
      1. SELECT … WHERE id > last_id … LIMIT batch_size FOR UPDATE SKIP LOCKED
         — only this worker's page is locked; others skip it instantly.
      2. Bulk-UPDATE the page to QUEUED before yielding —
         concurrent workers see no PENDING rows in their next scan.
      3. Lock released when atomic block exits.
      4. Rows yielded one-by-one outside the atomic block so each
         downstream send runs in its own independent transaction.
    """
    last_id: int = 0

    while True:
        with transaction.atomic():
            page: list[WhatsAppCampaignRecipient] = list(
                WhatsAppCampaignRecipient.objects
                .select_related("lead")
                .select_for_update(skip_locked=True)
                .filter(
                    campaign_id=campaign_id,
                    status=WhatsAppCampaignRecipient.STATUS_PENDING,
                    id__gt=last_id,
                )
                .order_by("id")[:batch_size]
            )

            if not page:
                break

            ids = [r.id for r in page]
            WhatsAppCampaignRecipient.objects.filter(id__in=ids).update(
                status=WhatsAppCampaignRecipient.STATUS_QUEUED
            )
            last_id = page[-1].id

        yield from page   # yield outside atomic — independent tx per send


# ══════════════════════════════════════════════════════════════════════
# BroadcastProcessor
# ══════════════════════════════════════════════════════════════════════

class BroadcastProcessor:
    """
    End-to-end orchestrator for a WhatsApp broadcast campaign.

    Task-level entry points
    ───────────────────────
    trigger_broadcast_task    →  enqueue_all_recipients()
    send_single_recipient_task →  dispatch_single(recipient_id)
    finalize_campaign_task     →  finalize()
    """

    def __init__(self, campaign_id: int) -> None:
        self.campaign_id = campaign_id
        self._campaign: WhatsAppCampaign | None = None
        self._meta: MetaClient = MetaClient()

    # ── Lazy campaign loader ──────────────────────────────────────────

    def _get_campaign(self) -> WhatsAppCampaign:
        if self._campaign is None:
            self._campaign = (
                WhatsAppCampaign.objects
                .select_related("template")
                .get(pk=self.campaign_id)
            )
        return self._campaign

    # ── Lifecycle transitions ─────────────────────────────────────────

    def transition_to_running(self) -> bool:
        """
        Atomically QUEUED → RUNNING.
        Returns True only if *this* call performed the update.
        Guards against duplicate triggers from concurrent API requests.
        """
        with transaction.atomic():
            rows = WhatsAppCampaign.objects.filter(
                pk=self.campaign_id,
                status=WhatsAppCampaign.STATUS_QUEUED,
            ).update(status=WhatsAppCampaign.STATUS_RUNNING)
        return bool(rows)

    def finalize(self) -> None:
        """RUNNING → COMPLETED."""
        WhatsAppCampaign.objects.filter(pk=self.campaign_id).update(
            status=WhatsAppCampaign.STATUS_COMPLETED,
            updated_at=timezone.now(),
        )
        # Clear out any stale rate limit flags on successful completion
        cache.delete(f"meta_rate_limit_lock_{self.campaign_id}")
        logger.info("Campaign %s → COMPLETED", self.campaign_id)

    def mark_failed(self, reason: str = "") -> None:
        """Any state → FAILED."""
        WhatsAppCampaign.objects.filter(pk=self.campaign_id).update(
            status=WhatsAppCampaign.STATUS_FAILED,
            updated_at=timezone.now(),
        )
        cache.delete(f"meta_rate_limit_lock_{self.campaign_id}")
        logger.error("Campaign %s → FAILED (%s)", self.campaign_id, reason)

    # ── Per-recipient dispatch ────────────────────────────────────────

    def dispatch_single(self, recipient_id: int) -> None:
        """
        Full send pipeline for one recipient:

          load → context → render → mark SENDING → Meta API → persist → counters

        Called from send_single_recipient_task (one Celery task per row).

        Raises MetaRateLimitError so the Celery task can retry with
        exponential backoff. All other errors are absorbed + recorded.
        """
        try:
            recipient = (
                WhatsAppCampaignRecipient.objects
                .select_related("lead", "campaign__template")
                .get(pk=recipient_id)
            )
        except WhatsAppCampaignRecipient.DoesNotExist:
            logger.warning("Recipient %s not found; skipping.", recipient_id)
            return

        campaign  = recipient.campaign
        
        # ── Meta Compliance Guard: Circuit Breaker ────────────────────
        # Before executing network actions, check if a parallel worker triggered a 429 lock.
        # This keeps the application fully compliant with Meta guidelines by stopping further hits.
        lock_key = f"meta_rate_limit_lock_{campaign.id}"
        if cache.get(lock_key):
            logger.warning("Meta rate-limit backoff active for campaign %s. Delaying execution.", campaign.id)
            self._revert_to_queued(recipient_id)
            raise MetaRateLimitError("Meta Rate Limit Active: Circuit breaker engaged.")

        tokenizer = TemplateTokenizer(campaign.template.body)
        context   = self._build_context(recipient)
        body      = tokenizer.render(context)
        variables = self._extract_variables(context, campaign.template.variables)

        # Mark SENDING before network call.
        # If the worker crashes mid-send, a stale-SENDING sweep can re-resolve.
        with transaction.atomic():
            WhatsAppCampaignRecipient.objects.filter(pk=recipient_id).update(
                status=WhatsAppCampaignRecipient.STATUS_SENDING
            )

        try:
            resp = self._meta.send_template_message(
                phone_number=recipient.lead.phone,
                template_name=campaign.template.meta_template_name,
                language=campaign.template.language,
                rendered_body=body,
                variables=variables,
            )
            meta_msg_id: str = resp["messages"][0]["id"]
            self._on_success(recipient, meta_msg_id, body)

        except MetaRateLimitError:
            # Engage circuit breaker immediately for 60 seconds to safeguard the number from spamming bans
            cache.set(lock_key, True, timeout=60)
            
            # Revert so retry picks it up cleanly; re-raise for Celery.
            self._revert_to_queued(recipient_id)
            raise

        except MetaAPIError as exc:
            self._on_failure(recipient, str(exc))

        except Exception as exc:
            logger.exception("Unhandled error for recipient %s", recipient_id)
            self._on_failure(recipient, f"Unhandled: {exc}")

    # ── Outcome handlers ──────────────────────────────────────────────

    def _on_success(
        self,
        recipient: WhatsAppCampaignRecipient,
        meta_msg_id: str,
        body: str,
    ) -> None:
        now = timezone.now()
        with transaction.atomic():
            # Anchor message to the Smart Inbox chat thread.
            WhatsAppMessage.objects.create(
                chat=self._resolve_chat(recipient),
                message_id=meta_msg_id,
                sender_type="system",
                direction="outgoing",
                message_type="template",
                body=body,
                template_name=recipient.campaign.template.meta_template_name,
                status="sent",
                campaign_recipient=recipient,
            )

            WhatsAppCampaignRecipient.objects.filter(pk=recipient.pk).update(
                status=WhatsAppCampaignRecipient.STATUS_SENT,
                whatsapp_message_id=meta_msg_id,
                sent_at=now,
                error=None,
            )

            # F() increment — one UPDATE, zero SELECT, zero lock race.
            WhatsAppCampaign.objects.filter(pk=recipient.campaign_id).update(
                sent_count=F("sent_count") + 1
            )

        logger.debug(
            "Recipient %s → SENT (meta_id=%s)", recipient.pk, meta_msg_id
        )

    def _on_failure(
        self,
        recipient: WhatsAppCampaignRecipient,
        error: str,
    ) -> None:
        with transaction.atomic():
            WhatsAppCampaignRecipient.objects.filter(pk=recipient.pk).update(
                status=WhatsAppCampaignRecipient.STATUS_FAILED,
                error=error,
            )
            WhatsAppCampaign.objects.filter(pk=recipient.campaign_id).update(
                failed_count=F("failed_count") + 1
            )
        logger.warning("Recipient %s → FAILED: %s", recipient.pk, error)

    def _revert_to_queued(self, recipient_id: int) -> None:
        WhatsAppCampaignRecipient.objects.filter(pk=recipient_id).update(
            status=WhatsAppCampaignRecipient.STATUS_QUEUED
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_context(recipient: WhatsAppCampaignRecipient) -> dict:
        """
        Merge lead field defaults with per-recipient custom_context overrides.
        custom_context wins on key collision — enables per-lead A/B variables
        without touching the Lead model.
        """
        lead = recipient.lead
        ctx: dict = {
            "name":  getattr(lead, "name", ""),
            "phone": getattr(lead, "phone", ""),
        }
        ctx.update(recipient.custom_context or {})
        return ctx

    @staticmethod
    def _extract_variables(context: dict, variable_keys: list) -> list[str]:
        """
        Return values in the positional order the Meta template body component
        expects (matches the `variables` list on MessageTemplate).
        """
        return [str(context.get(k, "")) for k in variable_keys]

    @staticmethod
    def _resolve_chat(recipient: WhatsAppCampaignRecipient):
        """
        get_or_create a WhatsAppChat for the lead so broadcast messages
        surface in the Smart Inbox conversation queue.
        """
        from ..models import WhatsAppChat  # local → avoids circular import

        chat, _ = WhatsAppChat.objects.get_or_create(
            lead=recipient.lead,
            defaults={
                "whatsapp_id":   f"bc_{recipient.lead_id}",
                "phone_number":  getattr(recipient.lead, "phone", ""),
                "customer_name": getattr(recipient.lead, "name", ""),
                "status":        WhatsAppChat.STATUS_UNASSIGNED,
            },
        )
        return chat

    # ── Bulk enqueuing (fan-out) ──────────────────────────────────────

    def enqueue_all_recipients(self) -> int:
        """
        Cursor-paginate over PENDING recipients and push one Celery task
        per row into the whatsapp_broadcast queue.

        Token-bucket rate shaping via countdown arithmetic:
            countdown = position // 20
        → spreads dispatch at ~20 msg/s without a separate rate-limiter.
          Adjust the divisor for your Meta BSP tier (verified BSPs: 80/s).

        Returns: total tasks enqueued.
        """
        from ..tasks import send_single_recipient_task  # avoid circular

        count = 0
        for recipient in _pending_recipients_cursor(self.campaign_id):
            send_single_recipient_task.apply_async(
                args=[recipient.id],
                countdown=count // 20,           # token-bucket: 20 msg/s
                queue="whatsapp_broadcast",
            )
            count += 1

        logger.info(
            "Campaign %s → enqueued %d tasks", self.campaign_id, count
        )
        return count
"""
lead/telecrm.py

Centralized service and utilities for TeleCRM integration.
Provides field mapping, standard payload construction, resilient error handling,
transaction-safe on_commit hooks, and bulk synchronization.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Iterable

import requests
from django.conf import settings
from django.db import transaction

# Dedicated telecrm logger configured in settings.py (writes to logs/telecrm.log and console)
logger = logging.getLogger("telecrm")

# Fallback credentials matching settings.py
DEFAULT_TELECRM_API = "https://next-api.telecrm.in"
DEFAULT_TELECRM_ID = "6a13da730fbcb752673e080c"
DEFAULT_TELECRM_TOKEN = "2b5fa0b5-b45c-4150-ab6f-09a001575ca01779800797507:0d16d31d-e820-45fa-aafc-869ef640917d"
DEFAULT_TIMEOUT = 10


def format_telecrm_phone(phone: Any) -> str:
    """
    Standardize a phone number string to digits suitable for TeleCRM.
    If 10 digits, prepends '91' country code.
    """
    if not phone:
        logger.warning("[TeleCRM Phone] Empty or null phone value provided.")
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 10:
        formatted = f"91{digits}"
    else:
        formatted = digits

    if len(formatted) < 10:
        logger.warning(
            f"[TeleCRM Phone] Phone number '{phone}' standardized to '{formatted}' has fewer than 10 digits."
        )
    return formatted


def build_telecrm_payload(
    lead: Any,
    action_type: str | None = None,
    action_note: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Constructs a valid TeleCRM autoupdatelead payload dictionary from a Lead
    instance or dictionary of lead attributes.
    Only maps fields that actually exist on the Lead model.
    """
    is_model = hasattr(lead, "pk")

    def _get_val(attr_name: str, default: Any = None) -> Any:
        if is_model:
            return getattr(lead, attr_name, default)
        if isinstance(lead, dict):
            return lead.get(attr_name, default)
        return default

    raw_phone = _get_val("phone")
    phone_val = format_telecrm_phone(raw_phone)
    name_val = _get_val("name")
    email_val = _get_val("email")

    fields_map: dict[str, Any] = {
        "name": name_val or None,
        "phone": phone_val or None,
        "email": email_val or None,
    }

    # Optional existing Lead fields
    optional_keys = [
        "alternate_phone",
        "gender",
        "qualification",
        "user_type",
        "message",
        "address",
        "city",
        "state",
        "country",
        "pincode",
        "course",
        "course_interested_in",
        "interested",
        "reason_to_join",
        "reason_not_joining",
        "expected_join_month",
        "source",
        "source_campaign",
        "source_platform",
        "source_type",
        "facebook_campaign",
        "profession",
        "rating",
        "status",
        "lead_stage",
        "priority",
        "is_archived",
        "is_duplicate",
        "is_converted",
    ]

    for key in optional_keys:
        val = _get_val(key)
        if val is not None:
            fields_map[key] = val

    # Date fields serialization
    followup_date = _get_val("followup_date")
    if followup_date:
        fields_map["followup_date"] = str(followup_date)

    next_followup_date = _get_val("next_followup_date")
    if next_followup_date:
        fields_map["next_followup_date"] = str(next_followup_date)

    fee_discussed = _get_val("fee_discussed")
    if fee_discussed is not None:
        fields_map["fee_discussed"] = str(fee_discussed)

    # Followup / Handled user resolution
    if is_model:
        followup_by = getattr(lead, "followup_by", None)
        if followup_by:
            fields_map["assigned_to"] = getattr(
                followup_by, "full_name", str(followup_by)
            )

        handled_by = getattr(lead, "handled_by", None)
        if handled_by:
            fields_map["handled_by"] = getattr(
                handled_by, "full_name", str(handled_by)
            )
    elif isinstance(lead, dict):
        if "assigned_to" in lead:
            fields_map["assigned_to"] = lead["assigned_to"]
        if "followup_by" in lead:
            fields_map["assigned_to"] = lead["followup_by"]
        if "handled_by" in lead:
            fields_map["handled_by"] = lead["handled_by"]

    # Merge extra fields if provided
    if extra_fields:
        for k, v in extra_fields.items():
            if v is not None:
                fields_map[k] = v

    # Clean out None values to avoid overwriting with null unless intended
    clean_fields = {k: v for k, v in fields_map.items() if v is not None}

    payload: dict[str, Any] = {"fields": clean_fields}

    if action_note or action_type:
        payload["actions"] = [
            {
                "type": action_type or "ACTION_1001",
                "fields": {
                    "note": action_note or "Lead Update",
                },
            }
        ]

    logger.debug(
        f"[TeleCRM Payload Built] Lead={getattr(lead, 'id', lead)} | "
        f"Fields count={len(clean_fields)} | Phone={clean_fields.get('phone')} | "
        f"Name={clean_fields.get('name')} | Email={clean_fields.get('email')} | "
        f"Status={clean_fields.get('status')} | Source={clean_fields.get('source')}"
    )

    return payload


class TeleCRMService:
    """
    Client for interacting with TeleCRM API.
    """

    @classmethod
    def get_config(cls) -> tuple[str, str, str, int]:
        api_base = getattr(settings, "TELECRM_API", DEFAULT_TELECRM_API) or DEFAULT_TELECRM_API
        enterprise_id = getattr(settings, "TELECRM_ID", DEFAULT_TELECRM_ID) or DEFAULT_TELECRM_ID
        token = getattr(settings, "TELECRM_TOKEN", DEFAULT_TELECRM_TOKEN) or DEFAULT_TELECRM_TOKEN
        timeout = getattr(settings, "TELECRM_TIMEOUT", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT
        return api_base.rstrip("/"), enterprise_id, token, timeout

    @classmethod
    def send_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Sends the autoupdatelead payload to TeleCRM.
        Catches all errors to ensure the caller operation is never broken.
        Logs detailed request payload and response information.
        """
        api_base, enterprise_id, token, timeout = cls.get_config()

        if not enterprise_id or not token:
            logger.error(
                "[TeleCRM Config Error] Missing TeleCRM credentials! "
                f"TELECRM_ID={'configured' if enterprise_id else 'MISSING'}, "
                f"TELECRM_TOKEN={'configured' if token else 'MISSING'}. Skipping sync."
            )
            return {"success": False, "error": "Missing TeleCRM credentials"}

        # Validate that phone exists in payload
        phone_in_payload = payload.get("fields", {}).get("phone")
        if not phone_in_payload:
            logger.warning(
                f"[TeleCRM Payload Warning] Payload does not have a phone number! "
                f"Payload: {json.dumps(payload, default=str)}"
            )

        url = f"{api_base}/enterprise/{enterprise_id}/autoupdatelead"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
        logger.info(
            f"[TeleCRM Request Sending] URL={url} | AuthToken={masked_token} | "
            f"Payload={json.dumps(payload, default=str)}"
        )

        start_time = time.perf_counter()

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            elapsed_seconds = time.perf_counter() - start_time
            status_code = response.status_code

            try:
                resp_json = response.json()
            except Exception:
                resp_json = {"text": response.text}

            if 200 <= status_code < 300:
                logger.info(
                    f"[TeleCRM Success {status_code}] Duration={elapsed_seconds:.3f}s | "
                    f"Phone={phone_in_payload} | Response={json.dumps(resp_json, default=str)}"
                )
                return {
                    "success": True,
                    "status_code": status_code,
                    "data": resp_json,
                }
            else:
                logger.error(
                    f"[TeleCRM API Error {status_code}] Duration={elapsed_seconds:.3f}s | "
                    f"URL={url} | Payload={json.dumps(payload, default=str)} | "
                    f"Response={json.dumps(resp_json, default=str)}"
                )
                return {
                    "success": False,
                    "status_code": status_code,
                    "error": resp_json,
                }

        except requests.Timeout as e:
            elapsed_seconds = time.perf_counter() - start_time
            logger.error(
                f"[TeleCRM Timeout Error] Request to {url} timed out after {elapsed_seconds:.3f}s (timeout limit={timeout}s) | "
                f"Payload={json.dumps(payload, default=str)} | Error: {e}"
            )
            return {"success": False, "error": f"Timeout: {e}"}

        except requests.ConnectionError as e:
            elapsed_seconds = time.perf_counter() - start_time
            logger.error(
                f"[TeleCRM Connection Error] Could not connect to TeleCRM at {url} (after {elapsed_seconds:.3f}s) | "
                f"Payload={json.dumps(payload, default=str)} | Error: {e}"
            )
            return {"success": False, "error": f"ConnectionError: {e}"}

        except requests.RequestException as e:
            elapsed_seconds = time.perf_counter() - start_time
            logger.error(
                f"[TeleCRM Request Exception] Error communicating with {url} (after {elapsed_seconds:.3f}s) | "
                f"Payload={json.dumps(payload, default=str)} | Error: {e}",
                exc_info=True,
            )
            return {"success": False, "error": f"RequestException: {e}"}

        except Exception as e:
            elapsed_seconds = time.perf_counter() - start_time
            logger.exception(
                f"[TeleCRM Unexpected Exception] Unexpected error during TeleCRM sync (after {elapsed_seconds:.3f}s) | "
                f"Payload={json.dumps(payload, default=str)} | Error: {e}"
            )
            return {"success": False, "error": f"Unexpected: {e}"}

    @classmethod
    def sync_lead(
        cls,
        lead: Any,
        action_type: str | None = None,
        action_note: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Synchronously builds and dispatches the payload for a single Lead.
        """
        # If an ID was provided, resolve the Lead model instance if possible
        if isinstance(lead, int):
            from lead.models import Lead

            try:
                lead = Lead.objects.get(pk=lead)
            except Lead.DoesNotExist:
                logger.error(f"[TeleCRM Sync Error] Lead with ID={lead} does not exist in database. Cannot sync.")
                return {"success": False, "error": f"Lead {lead} not found"}

        logger.info(
            f"[TeleCRM Sync Lead] Processing Lead ID={getattr(lead, 'id', 'dict/raw')} | "
            f"ActionType={action_type} | ActionNote={action_note}"
        )

        payload = build_telecrm_payload(
            lead=lead,
            action_type=action_type,
            action_note=action_note,
            extra_fields=extra_fields,
        )

        return cls.send_payload(payload)


def sync_lead_to_telecrm(
    lead: Any,
    action_type: str | None = None,
    action_note: str | None = None,
    extra_fields: dict[str, Any] | None = None,
    run_on_commit: bool = True,
) -> None:
    """
    Main helper function to trigger TeleCRM synchronization.

    If run_on_commit is True and an active database transaction is present,
    the sync call is deferred until the database transaction successfully commits.
    This guarantees:
      1. DB rollback => TeleCRM call is NOT triggered.
      2. TeleCRM failure => DB transaction is NOT rolled back.
    """
    lead_id = getattr(lead, "id", None) or (lead.get("id") if isinstance(lead, dict) else lead)

    def _execute():
        logger.info(f"[TeleCRM Execution] Running sync for Lead={lead_id} | ActionNote={action_note}")
        TeleCRMService.sync_lead(
            lead=lead,
            action_type=action_type,
            action_note=action_note,
            extra_fields=extra_fields,
        )

    connection = transaction.get_connection()
    if run_on_commit and connection.in_atomic_block:
        logger.info(
            f"[TeleCRM on_commit Hook] Registered on_commit hook for Lead={lead_id} | "
            f"ActionNote={action_note}. Will execute upon DB commit."
        )
        transaction.on_commit(_execute)
    else:
        logger.info(
            f"[TeleCRM Direct Execution] Executing sync immediately for Lead={lead_id} | "
            f"ActionNote={action_note} (in_atomic={connection.in_atomic_block})"
        )
        _execute()


def sync_leads_bulk_to_telecrm(
    leads: Iterable[Any],
    action_type: str | None = None,
    action_note: str = "Bulk Lead Upload",
    run_on_commit: bool = True,
) -> None:
    """
    Batch synchronizes a list/queryset of leads to TeleCRM.
    """
    leads_list = list(leads)
    logger.info(
        f"[TeleCRM Bulk Trigger] Received {len(leads_list)} leads for bulk sync | "
        f"ActionNote={action_note}"
    )

    def _execute_bulk():
        logger.info(f"[TeleCRM Bulk Execution] Beginning dispatch of {len(leads_list)} leads to TeleCRM.")
        success_count = 0
        failure_count = 0

        for i, lead_item in enumerate(leads_list, start=1):
            res = TeleCRMService.sync_lead(
                lead=lead_item,
                action_type=action_type,
                action_note=action_note,
            )
            if res.get("success"):
                success_count += 1
            else:
                failure_count += 1

        logger.info(
            f"[TeleCRM Bulk Completed] Total={len(leads_list)} | "
            f"Successful={success_count} | Failed={failure_count}"
        )

    connection = transaction.get_connection()
    if run_on_commit and connection.in_atomic_block:
        logger.info(
            f"[TeleCRM Bulk on_commit Hook] Registered on_commit for {len(leads_list)} leads. "
            f"Will execute upon DB commit."
        )
        transaction.on_commit(_execute_bulk)
    else:
        logger.info(
            f"[TeleCRM Bulk Direct Execution] Executing bulk sync immediately for {len(leads_list)} leads."
        )
        _execute_bulk()

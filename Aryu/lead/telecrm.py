"""
lead/telecrm.py

Centralized service and utilities for TeleCRM integration.
Provides field mapping, standard payload construction, resilient error handling,
transaction-safe on_commit hooks, and bulk synchronization.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

import requests
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

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
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 10:
        return f"91{digits}"
    return digits


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

    phone_val = format_telecrm_phone(_get_val("phone"))
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
                "type": action_type or "ACTION_1002",
                "fields": {
                    "note": action_note or "Lead Update",
                },
            }
        ]

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
        """
        api_base, enterprise_id, token, timeout = cls.get_config()

        if not enterprise_id or not token:
            logger.warning("TeleCRM credentials missing. Skipping TeleCRM sync.")
            return {"success": False, "error": "Missing TeleCRM credentials"}

        url = f"{api_base}/enterprise/{enterprise_id}/autoupdatelead"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )

            status_code = response.status_code
            try:
                resp_json = response.json()
            except Exception:
                resp_json = {"text": response.text}

            if 200 <= status_code < 300:
                logger.info(f"TeleCRM Sync Success [Status {status_code}]")
                return {
                    "success": True,
                    "status_code": status_code,
                    "data": resp_json,
                }
            else:
                logger.warning(
                    f"TeleCRM Sync Returned Non-2xx [Status {status_code}]: {resp_json}"
                )
                return {
                    "success": False,
                    "status_code": status_code,
                    "error": resp_json,
                }

        except requests.Timeout as e:
            logger.error(f"TeleCRM Timeout Error: {e}")
            return {"success": False, "error": f"Timeout: {e}"}
        except requests.ConnectionError as e:
            logger.error(f"TeleCRM Connection Error: {e}")
            return {"success": False, "error": f"ConnectionError: {e}"}
        except requests.RequestException as e:
            logger.error(f"TeleCRM Request Exception: {e}")
            return {"success": False, "error": f"RequestException: {e}"}
        except Exception as e:
            logger.exception(f"Unexpected TeleCRM Error: {e}")
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
                logger.warning(f"TeleCRM Sync skipped: Lead ID {lead} does not exist.")
                return {"success": False, "error": f"Lead {lead} not found"}

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
    def _execute():
        TeleCRMService.sync_lead(
            lead=lead,
            action_type=action_type,
            action_note=action_note,
            extra_fields=extra_fields,
        )

    connection = transaction.get_connection()
    if run_on_commit and connection.in_atomic_block:
        transaction.on_commit(_execute)
    else:
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

    def _execute_bulk():
        for lead_item in leads_list:
            TeleCRMService.sync_lead(
                lead=lead_item,
                action_type=action_type,
                action_note=action_note,
            )

    connection = transaction.get_connection()
    if run_on_commit and connection.in_atomic_block:
        transaction.on_commit(_execute_bulk)
    else:
        _execute_bulk()

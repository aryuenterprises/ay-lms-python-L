"""
whatsapp/services/meta_client.py

Lightweight Meta Cloud API HTTP client built on requests.Session
for persistent TCP connection pooling (one socket per Celery worker
process → ~28ms handshake saving per message on warm paths).

Raises typed exceptions:
  MetaRateLimitError  → 429  (Celery retries with exponential backoff)
  MetaAPIError        → any other non-2xx (permanent fail after retries)
"""

import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── Env config ────────────────────────────────────────────────────────
META_API_VERSION    = os.environ.get("WHATSAPP_API_VERSION", "v19.0")
META_PHONE_ID       = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
META_WABA_ID        = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "") # REQUIRED FOR CREATION
META_ACCESS_TOKEN   = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
META_MESSAGES_URL   = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_ID}/messages"
META_TEMPLATES_URL  = f"https://graph.facebook.com/{META_API_VERSION}/{META_WABA_ID}/message_templates"

_RETRY = Retry(
    total=3,
    backoff_factor=0.3,
    status_forcelist={500, 502, 503, 504},
    allowed_methods={"POST", "GET"},
    raise_on_status=False,
)

class MetaAPIError(Exception):
    """Non-retryable Meta API error."""

class MetaRateLimitError(MetaAPIError):
    """HTTP 429."""

class MetaClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY, pool_connections=4, pool_maxsize=10)
        self._session.mount("https://", adapter)
        self._session.headers.update({
            "Authorization": f"Bearer {META_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        })

    def list_templates(self):

        resp = self._session.get(
            META_TEMPLATES_URL,
            timeout=20,
        )

        return self._raise_for_status(resp)
        

    def create_template(
        self,
        *,
        name: str,
        language: str,
        category: str,
        body_text: str,
        body_examples: list[str] = None,
        header_type: str = "NONE",
        header_text: str = None,
        header_media_url: str = None,
    ) -> dict:
        """
        Registers a new template directly with Meta's Business Account.
        """
        components = []

        # 1. Build Header Component (If applicable)
        if header_type != "NONE":
            header_component = {"type": "HEADER", "format": header_type}
            if header_type == "TEXT" and header_text:
                header_component["text"] = header_text
            elif header_type in ["IMAGE", "VIDEO", "DOCUMENT"] and header_media_url:
                # Meta requires an example URL for media approval
                header_component["example"] = {"header_url": [header_media_url]}
            components.append(header_component)

        # 2. Build Body Component
        body_component = {"type": "BODY", "text": body_text}
        if body_examples:
            # Meta format for body examples: {"body_text": [["example1", "example2"]]}
            body_component["example"] = {"body_text": [body_examples]}
        components.append(body_component)

        payload = {
            "name": name,
            "language": language,
            "category": category,
            "components": components,
        }

        logger.debug("META→CREATE_TEMPLATE | name=%s category=%s", name, category)
        print("=" * 80)
        print("META_TEMPLATES_URL:", META_TEMPLATES_URL)
        print("META_WABA_ID:", META_WABA_ID)
        print("META_PHONE_ID:", META_PHONE_ID)
        print("META_API_VERSION:", META_API_VERSION)
        print("Payload:", payload)
        print("=" * 80)
        resp = self._session.post(META_TEMPLATES_URL, json=payload, timeout=15)
        return self._raise_for_status(resp)

    # ── Public API ────────────────────────────────────────────────────

    def send_template_message(
        self,
        *,
        phone_number: str,
        template_name: str,
        language: str,
        rendered_body: str,       # used only for debug logging
        variables: list[str],
    ) -> dict:
        """
        Dispatch a WhatsApp approved template message.

        Args:
            phone_number:  E.164 without '+' e.g. "919876543210"
            template_name: Approved Meta template identifier
            language:      BCP-47 code e.g. "en", "en_US"
            rendered_body: Pre-rendered body (for logging only)
            variables:     Positional component parameter values

        Returns: parsed Meta API JSON response dict

        Raises:
            MetaRateLimitError  on HTTP 429
            MetaAPIError        on any other non-2xx
        """
        payload = self._build_template_payload(
            phone_number=phone_number,
            template_name=template_name,
            language=language,
            variables=variables,
        )

        logger.debug(
            "META→SEND | to=%s tpl=%s vars_count=%d",
            phone_number, template_name, len(variables),
        )

        resp = self._session.post(META_MESSAGES_URL, json=payload, timeout=10)
        return self._raise_for_status(resp)

    def send_text_message(self, *, phone_number: str, body: str) -> dict:
        """
        Free-form text message (agent replies, not broadcasts).
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": body},
        }
        resp = self._session.post(META_MESSAGES_URL, json=payload, timeout=10)
        return self._raise_for_status(resp)

    # ── Private helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_template_payload(
        *,
        phone_number: str,
        template_name: str,
        language: str,
        variables: list[str],
    ) -> dict:
        components = []
        if variables:
            components.append({
                "type": "body",
                "parameters": [
                    {"type": "text", "text": v} for v in variables
                ],
            })

        return {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> dict:
        if resp.status_code == 429:
            raise MetaRateLimitError(
                f"Rate limited — Retry-After: {resp.headers.get('Retry-After', '?')}"
            )
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise MetaAPIError(f"Meta API {resp.status_code}: {detail}")

        return resp.json()
    
    

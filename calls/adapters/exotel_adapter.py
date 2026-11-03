"""Exotel adapter for Horilla Calls Integration.

Exotel is India's leading cloud telephony platform.
Unlike Twilio, Exotel's Connect API first calls the agent, then bridges to the customer.
Flow: Exotel calls agent (From) → agent answers → Exotel calls customer (To).
"""

import hashlib
import hmac
import logging

import requests

from .base import BaseCallAdapter
from .factory import register_adapter

logger = logging.getLogger(__name__)

EXOTEL_API_BASE = "https://api.exotel.com/v1"


@register_adapter("exotel")
class ExotelAdapter(BaseCallAdapter):
    """
    Adapter for Exotel Voice API.

    Credentials expected on provider:
        account_sid  — Exotel Account SID (shown in Exotel dashboard)
        api_key      — Exotel API Key
        api_secret   — Exotel API Token
        caller_id    — ExoPhone (virtual number assigned to your account)

    Call flow: Exotel first calls the agent (from_number), then once answered,
    bridges to the customer (to_number). Both legs use the ExoPhone as caller ID.
    """

    CAPABILITIES = {
        "click_to_call": True,
        "inbound": True,
        "recording": True,
        "webhook_validation": False,
        "sip": False,
    }

    def _auth(self):
        return (self._val("api_key"), self._val("api_secret"))

    def _sid(self) -> str:
        return self._val("account_sid")

    @staticmethod
    def _e164(number: str) -> str:
        digits = "".join(c for c in number if c.isdigit() or c == "+")
        if digits and not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, **kwargs
    ) -> dict:
        to_e164 = self._e164(to_number)
        from_e164 = self._e164(from_number or self.provider.caller_id)
        caller_id = self._e164(self.provider.caller_id)

        if not to_e164:
            raise ValueError("A destination phone number is required to place a call.")
        if not from_e164:
            raise ValueError(
                "Agent phone number (Caller ID) is required. Set it in your agent settings."
            )
        if not caller_id:
            raise ValueError(
                "ExoPhone (Default Caller ID) is required on the provider configuration."
            )

        sid = self._sid()
        url = f"{EXOTEL_API_BASE}/Accounts/{sid}/Calls/connect.json"
        payload = {
            "From": from_e164,
            "To": to_e164,
            "CallerId": caller_id,
            "StatusCallback": callback_url,
            "StatusCallbackEvents[0]": "terminal",
            "Record": "false",
        }
        try:
            logger.info("Exotel POST %s | From=%s To=%s", url, from_e164, to_e164)
            resp = requests.post(url, data=payload, auth=self._auth(), timeout=15)
            logger.info(
                "Exotel response HTTP %s: %r", resp.status_code, resp.text[:300]
            )
            if not resp.ok:
                try:
                    err = resp.json()
                    msg = err.get("RestException", {}).get("Message", resp.text[:300])
                    code = err.get("RestException", {}).get("Code", resp.status_code)
                except ValueError:
                    msg = resp.text[:300]
                    code = resp.status_code
                logger.error("Exotel initiate_call failed [%s]: %s", code, msg)
                raise requests.HTTPError(f"Exotel error {code}: {msg}", response=resp)
            try:
                data = resp.json()
            except ValueError as exc:
                logger.error(
                    "Exotel returned non-JSON response [HTTP %s]: %r",
                    resp.status_code,
                    resp.text[:300],
                )
                raise ValueError(
                    f"Exotel HTTP {resp.status_code} — unexpected response: {resp.text[:200] or '(empty body)'}"
                ) from exc
            call_data = data.get("Call", {})
            return {
                "call_id": call_data.get("Sid", ""),
                "status": self._map_status(call_data.get("Status", "queued")),
            }
        except Exception as exc:
            logger.error("Exotel initiate_call failed: %s", exc)
            raise

    def webhook_token(self) -> str:
        """Per-provider token derived from SECRET_KEY; Exotel cannot sign its webhooks."""
        from django.conf import settings

        return hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            f"calls-webhook:{self.provider.pk}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def sign_callback_url(self, url: str) -> str:
        """Append the webhook token, since Exotel does not sign its callbacks."""
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}token={self.webhook_token()}"

    def validate_webhook(self, request) -> bool:
        """Exotel sends no signature, so authenticate the token embedded in the callback URL."""
        supplied = request.GET.get("token", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.webhook_token())

    def parse_webhook_payload(self, request) -> dict:
        data = request.POST
        raw_status = data.get("Status", "initiated")
        return {
            "call_id": data.get("CallSid", ""),
            "direction": (
                "inbound"
                if data.get("Direction", "").lower() == "inbound"
                else "outbound"
            ),
            "status": self._map_status(raw_status),
            "from_number": data.get("From", ""),
            "to_number": data.get("To", ""),
            "duration": (
                int(data["ConversationDuration"])
                if data.get("ConversationDuration")
                else None
            ),
            "recording_url": data.get("RecordingUrl"),
        }

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        if not provider_call_id:
            return False
        sid = self._sid()
        url = f"{EXOTEL_API_BASE}/Accounts/{sid}/Calls/{provider_call_id}.json"
        try:
            resp = requests.post(
                url, data={"Status": "canceled"}, auth=self._auth(), timeout=10
            )
            return resp.ok
        except Exception as exc:
            logger.error("Exotel cancel_call failed: %s", exc)
            return False

    def fetch_status(self, provider_call_id: str) -> str | None:
        if not provider_call_id:
            return None
        sid = self._sid()
        url = f"{EXOTEL_API_BASE}/Accounts/{sid}/Calls/{provider_call_id}.json"
        try:
            resp = requests.get(url, auth=self._auth(), timeout=5)
            if resp.ok:
                call_data = resp.json().get("Call", {})
                return self._map_status(call_data.get("Status", ""))
        except Exception as exc:
            logger.warning("Exotel fetch_status failed: %s", exc)
        return None

    def test_connection(self) -> dict:
        if not self.provider.account_sid or not self.provider.api_secret:
            return {
                "success": False,
                "error": "Account SID, API Key and API Token are required.",
            }
        try:
            sid = self._sid()
            url = f"{EXOTEL_API_BASE}/Accounts/{sid}.json"
            resp = requests.get(url, auth=self._auth(), timeout=10)
            if resp.status_code == 200:
                return {"success": True}
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except requests.RequestException as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _map_status(raw: str) -> str:
        mapping = {
            "queued": "initiated",
            "ringing": "ringing",
            "in-progress": "in_progress",
            "completed": "completed",
            "busy": "busy",
            "failed": "failed",
            "no-answer": "no_answer",
            "canceled": "cancelled",
        }
        return mapping.get(raw.lower(), "initiated")

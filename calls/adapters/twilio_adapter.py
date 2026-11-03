"""Twilio adapter for Horilla Calls Integration."""

import logging

import requests

from .base import BaseCallAdapter
from .factory import register_adapter

logger = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


@register_adapter("twilio")
class TwilioAdapter(BaseCallAdapter):
    """
    Adapter for Twilio Voice API.

    Credentials expected on provider:
        account_sid  — Twilio Account SID
        api_secret   — Twilio Auth Token  (stored via EncryptedCharField)
        caller_id    — default outbound number / Twilio phone number
    """

    # Twilio signs webhooks with the account Auth Token, not a separate secret.
    WEBHOOK_SECRET_FIELD = "api_secret"

    CAPABILITIES = {
        "click_to_call": True,
        "inbound": True,
        "recording": True,
        "webhook_validation": True,
        "sip": False,
    }

    def _auth(self):
        return (self._val("account_sid"), self._val("api_secret"))

    @staticmethod
    def _e164(number: str) -> str:
        """Ensure number is E.164 format (+<digits>). Strips spaces/dashes."""
        digits = "".join(c for c in number if c.isdigit() or c == "+")
        if digits and not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, twiml_url: str = ""
    ) -> dict:
        """
        Start an outbound call via Twilio Calls REST API.
        Docs: https://www.twilio.com/docs/voice/api/call-resource#create-a-call-resource

        twiml_url must point to a TwiML endpoint returning <Response><Dial>…</Dial></Response>.
        callback_url is used exclusively as the StatusCallback for call lifecycle events.
        """
        url = f"{TWILIO_API_BASE}/Accounts/{self._val('account_sid')}/Calls.json"
        payload = {
            "To": self._e164(to_number),
            "From": self._e164(from_number or self.provider.caller_id),
            "Url": twiml_url or callback_url,
            "StatusCallback": callback_url,
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": "initiated ringing answered completed",
        }
        try:
            resp = requests.post(url, data=payload, auth=self._auth(), timeout=15)
            if not resp.ok:
                try:
                    err = resp.json()
                    msg = err.get("message", resp.text[:300])
                    code = err.get("code", resp.status_code)
                except Exception:
                    msg = resp.text[:300]
                    code = resp.status_code
                logger.error("Twilio initiate_call failed [%s]: %s", code, msg)
                raise requests.HTTPError(f"Twilio error {code}: {msg}", response=resp)
            data = resp.json()
            return {
                "call_id": data.get("sid", ""),
                "status": self._map_status(data.get("status", "queued")),
            }
        except Exception as exc:
            logger.error("Twilio initiate_call failed: %s", exc)
            raise

    def validate_webhook(self, request) -> bool:
        """
        Validate X-Twilio-Signature (HMAC-SHA1 of URL + sorted POST params) keyed by the Auth Token.
        https://www.twilio.com/docs/usage/webhooks/webhooks-security
        """
        return self.verify_twilio_style_signature(request, "X-Twilio-Signature")

    def parse_webhook_payload(self, request) -> dict:
        """Map Twilio POST fields to canonical dict."""
        data = request.POST
        raw_status = data.get("CallStatus", "initiated")
        status = self._map_status(raw_status)
        return {
            "call_id": data.get("CallSid", ""),
            "direction": self._map_direction(data.get("Direction", "")),
            "status": status,
            "from_number": data.get("From", ""),
            "to_number": data.get("To", ""),
            "duration": int(data["CallDuration"]) if data.get("CallDuration") else None,
            "recording_url": data.get("RecordingUrl"),
        }

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        """Cancel a ringing call or hang up an answered call via Twilio REST API."""
        url = f"{TWILIO_API_BASE}/Accounts/{self._val('account_sid')}/Calls/{provider_call_id}.json"
        status = "completed" if in_progress else "canceled"
        try:
            resp = requests.post(
                url, data={"Status": status}, auth=self._auth(), timeout=10
            )
            return resp.ok
        except Exception as exc:
            logger.error("Twilio cancel_call failed: %s", exc)
            return False

    def fetch_status(self, provider_call_id: str) -> str | None:
        """Query Twilio REST API for the current call status."""
        if not provider_call_id:
            return None
        url = f"{TWILIO_API_BASE}/Accounts/{self._val('account_sid')}/Calls/{provider_call_id}.json"
        try:
            resp = requests.get(url, auth=self._auth(), timeout=5)
            if resp.ok:
                return self._map_status(resp.json().get("status", ""))
            logger.warning(
                "Twilio fetch_status HTTP %s for call %s: %s",
                resp.status_code,
                provider_call_id,
                resp.text[:200],
            )
        except Exception as exc:
            logger.warning(
                "Twilio fetch_status failed for call %s: %s", provider_call_id, exc
            )
        return None

    def test_connection(self) -> dict:
        """Verify Twilio credentials by fetching the account resource."""
        if not self.provider.account_sid or not self.provider.api_secret:
            return {
                "success": False,
                "error": "Account SID and Auth Token are required.",
            }
        url = f"{TWILIO_API_BASE}/Accounts/{self._val('account_sid')}.json"
        try:
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
    def _map_status(twilio_status: str) -> str:
        mapping = {
            "queued": "initiated",
            "initiated": "initiated",
            "ringing": "ringing",
            "in-progress": "in_progress",
            "completed": "completed",
            "busy": "busy",
            "failed": "failed",
            "no-answer": "no_answer",
            "canceled": "cancelled",
        }
        return mapping.get(twilio_status, "initiated")

    @staticmethod
    def _map_direction(twilio_dir: str) -> str:
        if "inbound" in twilio_dir.lower():
            return "inbound"
        return "outbound"

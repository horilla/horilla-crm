"""SignalWire adapter for Horilla Calls Integration.

SignalWire is Twilio-compatible: same REST format, same TwiML XML, same status values.
The only difference is the API base URL (project-specific) and the credential names.
"""

import logging

import requests

from .base import BaseCallAdapter
from .factory import register_adapter

logger = logging.getLogger(__name__)


@register_adapter("signalwire")
class SignalWireAdapter(BaseCallAdapter):
    """
    Adapter for SignalWire Voice API.

    Credentials expected on provider:
        account_sid  — SignalWire Project ID
        api_secret   — SignalWire API Token
        api_base_url — SignalWire Space URL (e.g. https://yourspace.signalwire.com)
        caller_id    — default outbound number (SignalWire DID)
    """

    # Twilio-compatible signature, keyed by the project Signing Key.
    WEBHOOK_SECRET_FIELD = "webhook_secret"

    CAPABILITIES = {
        "click_to_call": True,
        "inbound": True,
        "recording": True,
        "webhook_validation": True,
        "sip": True,
    }

    def _auth(self):
        return (self._val("account_sid"), self._val("api_secret"))

    def _base_url(self) -> str:
        # api_base_url is a plain URLField — access directly, not via _val()/_decrypt()
        base = (getattr(self.provider, "api_base_url", "") or "").strip().rstrip("/")
        if not base:
            raise ValueError("SignalWire api_base_url (Space URL) is required.")
        if not base.startswith("http"):
            base = "https://" + base
        return base

    @staticmethod
    def _e164(number: str) -> str:
        digits = "".join(c for c in number if c.isdigit() or c == "+")
        if digits and not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, twiml_url: str = ""
    ) -> dict:
        to_e164 = self._e164(to_number)
        from_e164 = self._e164(from_number or self.provider.caller_id)
        if not to_e164:
            raise ValueError("A destination phone number is required to place a call.")
        if not from_e164:
            raise ValueError(
                "A caller ID (From number) is required. Set it in your agent settings or provider default."
            )

        project_id = self._val("account_sid")
        url = f"{self._base_url()}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json"
        # Use inline TwiML so SignalWire does not need to reach back to our server.
        # to_e164 is already sanitised — safe to embed directly in XML.
        inline_twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Dial>{to_e164}</Dial></Response>"
        )
        payload = {
            "To": to_e164,
            "From": from_e164,
            "Twiml": inline_twiml,
            "StatusCallback": callback_url,
            "StatusCallbackMethod": "POST",
        }
        try:
            logger.info(
                "SignalWire POST %s | To=%s From=%s",
                url,
                payload.get("To"),
                payload.get("From"),
            )
            resp = requests.post(url, data=payload, auth=self._auth(), timeout=15)
            logger.info(
                "SignalWire response HTTP %s: %r", resp.status_code, resp.text[:500]
            )
            if not resp.ok:
                try:
                    err = resp.json()
                    msg = err.get("message", resp.text[:300])
                    code = err.get("code", resp.status_code)
                except Exception:
                    msg = resp.text[:300]
                    code = resp.status_code
                logger.error("SignalWire initiate_call failed [%s]: %s", code, msg)
                raise requests.HTTPError(
                    f"SignalWire error {code}: {msg}", response=resp
                )
            try:
                data = resp.json()
            except Exception as exc:
                logger.error(
                    "SignalWire returned non-JSON response [HTTP %s]: %r",
                    resp.status_code,
                    resp.text[:500],
                )
                raise ValueError(
                    f"SignalWire HTTP {resp.status_code} — unexpected response: {resp.text[:300] or '(empty body)'}"
                ) from exc
            return {
                "call_id": data.get("sid", ""),
                "status": self._map_status(data.get("status", "queued")),
            }
        except Exception as exc:
            logger.error("SignalWire initiate_call failed: %s", exc)
            raise

    def validate_webhook(self, request) -> bool:
        """Validate X-SignalWire-Signature keyed by the project Signing Key (webhook_secret)."""
        return self.verify_twilio_style_signature(request, "X-SignalWire-Signature")

    def parse_webhook_payload(self, request) -> dict:
        data = request.POST
        raw_status = data.get("CallStatus", "initiated")
        status = self._map_status(raw_status)
        return {
            "call_id": data.get("CallSid", ""),
            "direction": (
                "inbound"
                if "inbound" in data.get("Direction", "").lower()
                else "outbound"
            ),
            "status": status,
            "from_number": data.get("From", ""),
            "to_number": data.get("To", ""),
            "duration": int(data["CallDuration"]) if data.get("CallDuration") else None,
            "recording_url": data.get("RecordingUrl"),
        }

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        project_id = self._val("account_sid")
        url = f"{self._base_url()}/api/laml/2010-04-01/Accounts/{project_id}/Calls/{provider_call_id}.json"
        status = "completed" if in_progress else "canceled"
        try:
            resp = requests.post(
                url, data={"Status": status}, auth=self._auth(), timeout=10
            )
            return resp.ok
        except Exception as exc:
            logger.error("SignalWire cancel_call failed: %s", exc)
            return False

    def fetch_status(self, provider_call_id: str) -> str | None:
        if not provider_call_id:
            return None
        project_id = self._val("account_sid")
        url = f"{self._base_url()}/api/laml/2010-04-01/Accounts/{project_id}/Calls/{provider_call_id}.json"
        try:
            resp = requests.get(url, auth=self._auth(), timeout=5)
            if resp.ok:
                return self._map_status(resp.json().get("status", ""))
        except Exception as exc:
            logger.warning("SignalWire fetch_status failed: %s", exc)
        return None

    def test_connection(self) -> dict:
        if not self.provider.account_sid or not self.provider.api_secret:
            return {"success": False, "error": "Project ID and API Token are required."}
        try:
            project_id = self._val("account_sid")
            url = f"{self._base_url()}/api/laml/2010-04-01/Accounts/{project_id}.json"
            resp = requests.get(url, auth=self._auth(), timeout=10)
            if resp.status_code == 200:
                return {"success": True}
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _map_status(raw: str) -> str:
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
        return mapping.get(raw, "initiated")

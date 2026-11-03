"""Sinch adapter for Horilla Calls Integration."""

import logging

import requests

from .base import BaseCallAdapter
from .factory import register_adapter

logger = logging.getLogger(__name__)

SINCH_API_BASE = "https://calling.api.sinch.com/calling/v1"


@register_adapter("sinch")
class SinchAdapter(BaseCallAdapter):
    """
    Adapter for Sinch Voice API (Application Calling).

    Credentials expected on provider:
        account_sid  — Sinch Application Key
        api_secret   — Sinch Application Secret
        caller_id    — default outbound number (Sinch DID in E.164)
    """

    # Sinch signs callbacks with the Application Secret.
    WEBHOOK_SECRET_FIELD = "api_secret"

    CAPABILITIES = {
        "click_to_call": True,
        "inbound": True,
        "recording": False,
        "webhook_validation": True,
        "sip": False,
    }

    def _auth(self):
        return (self._val("account_sid"), self._val("api_secret"))

    @staticmethod
    def _e164(number: str) -> str:
        digits = "".join(c for c in number if c.isdigit() or c == "+")
        if digits and not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, **kwargs
    ) -> dict:
        url = f"{SINCH_API_BASE}/callouts"
        payload = {
            "method": "ttsCallout",
            "ttsCallout": {
                "cli": self._e164(from_number or self.provider.caller_id),
                "destination": {"type": "number", "endpoint": self._e164(to_number)},
                "locale": "en-US",
                "text": "You have an incoming call from the CRM. Please hold.",
            },
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                auth=self._auth(),
                timeout=15,
            )
            if not resp.ok:
                try:
                    err = resp.json()
                    msg = err.get("message", resp.text[:300])
                    code = err.get("errorCode", resp.status_code)
                except Exception:
                    msg = resp.text[:300]
                    code = resp.status_code
                logger.error("Sinch initiate_call failed [%s]: %s", code, msg)
                raise requests.HTTPError(f"Sinch error {code}: {msg}", response=resp)
            data = resp.json()
            return {
                "call_id": data.get("callId", ""),
                "status": "initiated",
            }
        except Exception as exc:
            logger.error("Sinch initiate_call failed: %s", exc)
            raise

    def validate_webhook(self, request) -> bool:
        import base64
        import hashlib
        import hmac as hmac_mod

        app_secret = self.webhook_secret()
        if not app_secret:
            logger.error("Sinch api_secret not configured")
            return False

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("application "):
            return False

        try:
            encoded = auth_header[len("application ") :]
            decoded = base64.b64decode(encoded).decode("utf-8")
            key, provided_sig = decoded.split(":", 1)
        except Exception:
            return False

        if key != self._val("account_sid"):
            logger.warning(
                "Sinch webhook key mismatch — expected %s", self._val("account_sid")
            )
            return False

        body = request.body
        content_type = request.content_type or ""
        content_md5 = base64.b64encode(
            __import__("hashlib").md5(body).digest()
        ).decode()
        string_to_sign = "\n".join(
            [
                request.method.upper(),
                content_md5,
                content_type,
                "",
                request.path,
            ]
        )
        try:
            expected = base64.b64encode(
                hmac_mod.new(
                    base64.b64decode(app_secret),
                    string_to_sign.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode()
            return hmac_mod.compare_digest(provided_sig, expected)
        except Exception:
            return False

    def parse_webhook_payload(self, request) -> dict:
        import json

        try:
            body = json.loads(request.body)
        except Exception:
            body = {}
        event = body.get("event", "")
        status = self._map_status(event, body.get("result", ""))
        return {
            "call_id": body.get("callid", ""),
            "direction": "inbound" if body.get("applicationKey") else "outbound",
            "status": status,
            "from_number": body.get("cli", ""),
            "to_number": body.get("to", {}).get("endpoint", ""),
            "duration": body.get("duration"),
            "recording_url": None,
        }

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        if not provider_call_id:
            return False
        url = f"{SINCH_API_BASE}/calls/{provider_call_id}"
        try:
            resp = requests.patch(
                url,
                json={"status": "CANCEL"},
                auth=self._auth(),
                timeout=10,
            )
            return resp.ok
        except Exception as exc:
            logger.error("Sinch cancel_call failed: %s", exc)
            return False

    def fetch_status(self, provider_call_id: str) -> str | None:
        if not provider_call_id:
            return None
        url = f"{SINCH_API_BASE}/calls/{provider_call_id}"
        try:
            resp = requests.get(url, auth=self._auth(), timeout=5)
            if resp.ok:
                body = resp.json()
                return self._map_status(body.get("status", ""), body.get("result", ""))
        except Exception as exc:
            logger.warning("Sinch fetch_status failed: %s", exc)
        return None

    def test_connection(self) -> dict:
        if not self.provider.account_sid or not self.provider.api_secret:
            return {
                "success": False,
                "error": "Application Key and Secret are required.",
            }
        try:
            url = "https://calling.api.sinch.com/calling/v1/configuration/numbers/"
            resp = requests.get(url, auth=self._auth(), timeout=10)
            if resp.status_code in (200, 404):
                return {"success": True}
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except requests.RequestException as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _map_status(event: str, result: str) -> str:
        event_map = {
            "ice": "ringing",
            "ace": "in_progress",
            "dice": "completed",
            "pie": "initiated",
        }
        status = event_map.get(event, "initiated")
        if result in ("NOANSWER", "NO_ANSWER"):
            return "no_answer"
        if result == "BUSY":
            return "busy"
        if result in ("FAILED", "ERROR"):
            return "failed"
        if result == "CANCELLED":
            return "cancelled"
        return status

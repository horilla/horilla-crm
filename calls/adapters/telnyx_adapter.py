"""Telnyx adapter for Horilla Calls Integration."""

# Standard library imports
import logging

# Third-party imports
import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# First party imports (Horilla)
from .base import BaseCallAdapter
from .factory import register_adapter

logger = logging.getLogger(__name__)

TELNYX_API_BASE = "https://api.telnyx.com/v2"


@register_adapter("telnyx")
class TelnyxAdapter(BaseCallAdapter):
    """
    Adapter for Telnyx Voice API.

    Credentials expected on provider:
        api_secret     — Telnyx API Key (starts with KEY...)
        caller_id      — default outbound number (Telnyx DID in E.164)

    Required:
        webhook_secret — Telnyx public key for Ed25519 signature verification
                         (found in Telnyx Portal → API Keys → Webhook public key)
    """

    # Ed25519 public key from the Telnyx portal.
    WEBHOOK_SECRET_FIELD = "webhook_secret"

    CAPABILITIES = {
        "click_to_call": True,
        "inbound": True,
        "recording": False,
        "webhook_validation": True,
        "sip": True,
    }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._val('api_secret')}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _e164(number: str) -> str:
        digits = "".join(c for c in number if c.isdigit() or c == "+")
        if digits and not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, **kwargs
    ) -> dict:
        connection_id = self._val("api_key")
        if not connection_id:
            raise ValueError(
                "Connection ID is required for Telnyx. Enter it in the 'Connection ID' field on the provider form."
            )
        payload = {
            "connection_id": connection_id,
            "to": self._e164(to_number),
            "from": self._e164(from_number or self.provider.caller_id),
            "webhook_url": callback_url,
        }
        try:
            resp = requests.post(
                f"{TELNYX_API_BASE}/calls",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )
            if not resp.ok:
                try:
                    err = resp.json()
                    errors = err.get("errors", [{}])
                    msg = (
                        errors[0].get("detail", resp.text[:300])
                        if errors
                        else resp.text[:300]
                    )
                except Exception:
                    msg = resp.text[:300]
                logger.error(
                    "Telnyx initiate_call failed [%s]: %s", resp.status_code, msg
                )
                raise requests.HTTPError(
                    f"Telnyx error {resp.status_code}: {msg}", response=resp
                )
            data = resp.json().get("data", {})
            return {
                "call_id": data.get("call_control_id", data.get("call_leg_id", "")),
                "status": "initiated",
            }
        except Exception as exc:
            logger.error("Telnyx initiate_call failed: %s", exc)
            raise

    def validate_webhook(self, request) -> bool:
        import base64
        import time

        public_key_b64 = self.webhook_secret()
        if not public_key_b64:
            logger.error("Telnyx webhook_secret (public key) not configured")
            return False

        timestamp = request.headers.get("telnyx-timestamp", "")
        signature_b64 = request.headers.get("telnyx-signature-ed25519-v1", "")
        try:
            timestamp_ok = bool(timestamp and signature_b64) and (
                abs(time.time() - int(timestamp)) <= 300
            )
        except ValueError:
            timestamp_ok = False
        if not timestamp_ok:
            return False

        try:
            signed_payload = f"{timestamp}|".encode() + request.body
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public_key_b64)
            )
            public_key.verify(base64.b64decode(signature_b64), signed_payload)
            return True
        except InvalidSignature:
            pass
        except Exception as exc:
            logger.exception("Telnyx webhook validation error: %s", exc)
        return False

    def parse_webhook_payload(self, request) -> dict:
        import json

        try:
            body = json.loads(request.body)
        except Exception:
            body = {}
        payload = body.get("data", {}).get("payload", {})
        status = self._map_event(
            body.get("data", {}).get("event_type", ""),
            payload.get("state", "initiated"),
            payload.get("hangup_cause", ""),
        )
        return {
            "call_id": payload.get("call_leg_id", ""),
            "direction": payload.get("direction", "outbound"),
            "status": status,
            "from_number": payload.get("from", ""),
            "to_number": payload.get("to", ""),
            "duration": None,
            "recording_url": None,
        }

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        if not provider_call_id:
            return False
        url = f"{TELNYX_API_BASE}/calls/{provider_call_id}/actions/hangup"
        try:
            resp = requests.post(url, json={}, headers=self._headers(), timeout=10)
            return resp.ok
        except Exception as exc:
            logger.error("Telnyx cancel_call failed: %s", exc)
            return False

    def test_connection(self) -> dict:
        if not self.provider.api_secret:
            return {"success": False, "error": "API Key is required."}
        try:
            resp = requests.get(
                f"{TELNYX_API_BASE}/phone_numbers",
                headers=self._headers(),
                params={"page[size]": 1},
                timeout=10,
            )
            if resp.status_code in (200, 206):
                return {"success": True}
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except requests.RequestException as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def _map_event(cls, event_type: str, state: str, hangup_cause: str) -> str:
        """Map a Telnyx webhook event to a CallLog status, using the hangup cause on call.hangup."""
        if event_type == "call.hangup":
            hangup_map = {
                "call_rejected": "busy",
                "user_busy": "busy",
                "timeout": "no_answer",
                "no_answer": "no_answer",
                "originator_cancel": "cancelled",
            }
            return hangup_map.get(hangup_cause, "completed")
        if event_type == "call.answered":
            return "in_progress"
        return cls._map_status(state)

    @staticmethod
    def _map_status(raw: str) -> str:
        mapping = {
            "parked": "initiated",
            "bridging": "in_progress",
            "bridged": "in_progress",
            "active": "in_progress",
            "held": "in_progress",
            "completed": "completed",
            "destroyed": "completed",
            "failed": "failed",
            "hangup": "completed",
        }
        return mapping.get(raw, "initiated")

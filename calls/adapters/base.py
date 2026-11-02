"""Base adapter interface for telephony providers."""

import abc
import base64
import hashlib
import hmac
from urllib.parse import urlsplit, urlunsplit


def _decrypt(value: str) -> str:
    """Decrypt a value stored via EncryptedCharField. Returns plain text."""
    if not value:
        return value
    try:
        from horilla.contrib.mail.encryption_utils import decrypt_password

        return decrypt_password(value)
    except Exception:
        return value


class BaseCallAdapter(abc.ABC):
    """
    Abstract base class every telephony provider adapter must implement.

    Subclasses handle one provider (Twilio, Exotel, Asterisk, …).
    The CRM service layer only calls methods defined here, so adding a
    new provider means creating a subclass and registering it — no changes
    elsewhere.
    """

    # Provider field holding the key that webhook requests are verified with
    # (None when the provider cannot sign its webhooks).
    WEBHOOK_SECRET_FIELD = None

    def __init__(self, provider):
        self.provider = provider

    def _val(self, field_name: str) -> str:
        """Return the decrypted value of an EncryptedCharField on the provider."""
        return _decrypt(getattr(self.provider, field_name, "") or "")

    def webhook_secret(self) -> str:
        """Return the decrypted key used to verify this provider's webhooks."""
        if not self.WEBHOOK_SECRET_FIELD:
            return ""
        return self._val(self.WEBHOOK_SECRET_FIELD)

    def webhook_secret_missing(self) -> bool:
        """True when the provider verifies webhooks but no key is configured."""
        return bool(self.WEBHOOK_SECRET_FIELD) and not self.webhook_secret()

    def sign_callback_url(self, url: str) -> str:
        """Return the callback URL handed to the provider (override to add a token)."""
        return url

    @staticmethod
    def request_urls(request) -> list:
        """
        Return the URLs the provider may have signed for this request.

        Behind a reverse proxy the scheme/host Django sees can differ from the
        public ones the provider called, so the forwarded variant is tried too.
        """
        urls = [request.build_absolute_uri()]
        proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
        host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
        if proto or host:
            parts = urlsplit(urls[0])
            urls.insert(
                0,
                urlunsplit(
                    (
                        proto or parts.scheme,
                        host or parts.netloc,
                        parts.path,
                        parts.query,
                        "",
                    )
                ),
            )
        return urls

    def verify_twilio_style_signature(self, request, header_name: str) -> bool:
        """
        Verify a Twilio-compatible signature: base64(HMAC-SHA1(key, URL + sorted POST params)).
        Fails closed when no key is configured.
        """
        secret = self.webhook_secret()
        if not secret:
            return False
        signature = request.headers.get(header_name, "")
        params = "".join(f"{k}{v}" for k, v in sorted(request.POST.items()))
        for url in self.request_urls(request):
            digest = hmac.new(
                secret.encode("utf-8"), (url + params).encode("utf-8"), hashlib.sha1
            ).digest()
            expected = base64.b64encode(digest).decode("utf-8")
            if hmac.compare_digest(signature, expected):
                return True
        return False

    @abc.abstractmethod
    def initiate_call(
        self, from_number: str, to_number: str, callback_url: str, **kwargs
    ) -> dict:
        """
        Start an outbound call.

        Returns a dict with at minimum:
            {"call_id": str, "status": str}
        Raises an exception on failure.
        """

    @abc.abstractmethod
    def validate_webhook(self, request) -> bool:
        """
        Validate the authenticity of an incoming webhook request.

        Returns True if the signature / secret is valid, False otherwise.
        Never raise — return False on any verification failure.
        """

    @abc.abstractmethod
    def parse_webhook_payload(self, request) -> dict:
        """
        Normalise a provider-specific webhook POST into a canonical dict:

        {
            "call_id":       str,
            "direction":     "inbound" | "outbound",
            "status":        str,   # maps to CallLog.STATUS_* constants
            "from_number":   str,
            "to_number":     str,
            "duration":      int | None,
            "recording_url": str | None,
        }
        """

    def cancel_call(self, provider_call_id: str, in_progress: bool = False) -> bool:
        """Cancel an in-progress or ringing call. Override in adapters that support it."""
        return False

    def fetch_status(self, provider_call_id: str) -> str | None:
        """Fetch the current live call status directly from the provider.

        Returns a canonical status string (matching CallLog.STATUS_*) or None
        if the provider doesn't support live status queries.
        Override in adapters that support it.
        """
        return None

    def test_connection(self) -> dict:
        """
        Verify that the provider credentials are valid and the API is reachable.
        Returns {"success": True} on success or {"success": False, "error": str} on failure.
        Override in each adapter for provider-specific health checks.
        """
        return {
            "success": False,
            "error": "test_connection not implemented for this provider",
        }

    def get_agent_for_user(self, user):
        """Return the AgentMapping for this provider + user, or None."""
        from calls.models import AgentMapping

        return AgentMapping.objects.filter(provider=self.provider, user=user).first()

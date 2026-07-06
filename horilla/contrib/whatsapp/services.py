"""
Meta WhatsApp Cloud API client.
"""

# Standard library imports
import logging

# Third-party imports
import requests

logger = logging.getLogger(__name__)

GRAPH_API_BASE_URL = "https://graph.facebook.com"


class WhatsAppAPIError(Exception):
    """Raised when the Meta WhatsApp Cloud API returns an error response."""


class WhatsAppCloudAPIClient:
    """
    Thin wrapper around the Meta WhatsApp Cloud API for a single WhatsAppAccount.
    """

    def __init__(self, account):
        self.account = account
        self.phone_number_id = account.phone_number_id
        self.api_version = account.api_version

    @property
    def _base_url(self):
        return f"{GRAPH_API_BASE_URL}/{self.api_version}/{self.phone_number_id}"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.account.get_decrypted_access_token()}",
            "Content-Type": "application/json",
        }

    def _request(self, method, url, **kwargs):
        response = requests.request(method, url, timeout=30, **kwargs)
        if not response.ok:
            logger.error(
                "WhatsApp Cloud API request failed: %s %s -> %s %s",
                method,
                url,
                response.status_code,
                response.text,
            )
            raise WhatsAppAPIError(
                f"WhatsApp Cloud API request failed with status {response.status_code}: "
                f"{response.text}"
            )
        return response.json()

    def send_text(self, to, body):
        """Send a plain text message to the given phone number."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def send_template(self, to, template_name, language="en_US", components=None):
        """Send an approved template message to the given phone number."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            payload["template"]["components"] = components
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def send_media(self, to, media_id, mime_type, caption=None, filename=None):
        """Send a previously uploaded media object as a message."""
        if mime_type.startswith("image/"):
            media_type = "image"
        elif mime_type.startswith("video/"):
            media_type = "video"
        elif mime_type.startswith("audio/"):
            media_type = "audio"
        else:
            media_type = "document"

        media_payload = {"id": media_id}
        if caption and media_type in ("image", "video", "document"):
            media_payload["caption"] = caption
        if filename and media_type == "document":
            media_payload["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def send_flow(
        self,
        to,
        flow_id,
        flow_cta,
        flow_token,
        header_text=None,
        body_text="Please complete this form.",
    ):
        """
        Send a static WhatsApp Flow message (published Flow, no dynamic
        data-exchange screens) to the given phone number.
        """
        interactive = {
            "type": "flow",
            "body": {"text": body_text},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": flow_token,
                    "flow_id": flow_id,
                    "flow_cta": flow_cta,
                    "flow_action": "navigate",
                    "mode": "published",
                },
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def send_interactive_buttons(self, to, body_text, buttons, header_text=None):
        """
        Send up to 3 quick-reply buttons (Meta's "interactive" type "button").

        `buttons` is a list of {"id": ..., "title": ...} dicts (title max 20
        chars, enforced by Meta).
        """
        interactive = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": button["id"], "title": button["title"]},
                    }
                    for button in buttons
                ]
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def send_interactive_list(
        self, to, body_text, button_text, sections, header_text=None
    ):
        """
        Send a list message (Meta's "interactive" type "list"), up to 10 rows
        total across `sections`.

        `sections` is a list of {"title": ..., "rows": [{"id", "title",
        "description"}, ...]} dicts. A single unnamed section is fine.
        """
        interactive = {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text,
                "sections": sections,
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

    def fetch_template(self, business_account_id, name, language):
        """Return the raw template dict (status, category, components...) from
        WhatsApp Manager for the given name/language, or None if not found."""
        result = self._request(
            "GET",
            f"{GRAPH_API_BASE_URL}/{self.api_version}/{business_account_id}/message_templates",
            params={"name": name},
            headers=self._headers(),
        )
        for template in result.get("data", []):
            if template.get("language") == language:
                return template
        return None

    def list_templates(self, business_account_id, limit=200):
        """Return all APPROVED templates (name, language, category, components)
        from WhatsApp Manager for this business account, across all pages."""
        templates = []
        url = f"{GRAPH_API_BASE_URL}/{self.api_version}/{business_account_id}/message_templates"
        params = {"limit": limit}
        while url:
            result = self._request("GET", url, params=params, headers=self._headers())
            templates.extend(result.get("data", []))
            url = result.get("paging", {}).get("next")
            params = None
        return [t for t in templates if t.get("status") == "APPROVED"]

    def list_flows(self, business_account_id, limit=200):
        """Return all PUBLISHED Flows (id, name, status, categories...) from
        WhatsApp Manager for this business account, across all pages."""
        flows = []
        url = f"{GRAPH_API_BASE_URL}/{self.api_version}/{business_account_id}/flows"
        params = {"limit": limit}
        while url:
            result = self._request("GET", url, params=params, headers=self._headers())
            flows.extend(result.get("data", []))
            url = result.get("paging", {}).get("next")
            params = None
        return [f for f in flows if f.get("status") == "PUBLISHED"]

    def get_flow_field_names(self, flow_id):
        """
        Return the sorted, deduped set of answer field names a published,
        static WhatsApp Flow actually sends back on completion, by
        downloading and parsing its Flow JSON from Meta - so the bot builder
        can suggest {{variables.<prefix>.<field>}} tokens before anyone has
        ever submitted the Flow (session data alone can't help there; see
        _known_variable_prefixes in views/flow_builder.py for the fallback
        that mines real submissions instead).

        The submitted answer keys come from each terminal screen's Footer
        "on-click-action": {"name": "complete", "payload": {...}} - the
        payload's own keys are the actual contract Meta sends to the
        webhook, and can differ from an input component's own "name" (the
        Flow author is free to remap, e.g. payload key "full_name":
        "${form.the_actual_field}"). Reading component names directly would
        both miss remapped keys and wrongly include non-input containers
        (e.g. a Form component has a "name" too, but isn't an answer field).
        """
        assets = self._request(
            "GET",
            f"{GRAPH_API_BASE_URL}/{self.api_version}/{flow_id}/assets",
            headers=self._headers(),
        )
        field_names = set()
        for asset in assets.get("data", []):
            download_url = asset.get("download_url")
            if not download_url:
                continue
            response = requests.get(download_url, timeout=30)
            if not response.ok:
                continue
            try:
                flow_json = response.json()
            except ValueError:
                continue
            field_names.update(self._extract_flow_field_names(flow_json))
        return sorted(field_names)

    @staticmethod
    def _error_text(exc):
        """Meta's human-readable error out of a WhatsAppAPIError message."""
        import json as _json

        text = str(exc)
        start = text.find("{")
        if start != -1:
            try:
                error = _json.loads(text[start:]).get("error", {})
                message = error.get("error_user_msg") or error.get("message")
                if message:
                    code = error.get("code")
                    return f"{message} (code {code})" if code else message
            except ValueError:
                pass
        return text

    def test_connection(self):
        """
        Run live checks against Meta for this account and return a list of
        {"label", "status": "ok"|"warn"|"fail", "detail"} dicts: access token
        and phone number, Business Account access, template access, whether
        Meta currently allows sending, and the webhook app subscription.
        """
        base = f"{GRAPH_API_BASE_URL}/{self.api_version}"
        waba = self.account.business_account_id
        checks = []

        def add(label, status, detail):
            checks.append({"label": label, "status": status, "detail": detail})

        # 1. Access token + phone number
        try:
            info = self._request(
                "GET",
                f"{base}/{self.phone_number_id}",
                params={
                    "fields": "display_phone_number,verified_name,quality_rating,"
                    "status,account_mode,name_status"
                },
                headers=self._headers(),
            )
            parts = [
                info.get("verified_name"),
                info.get("display_phone_number"),
                f"status {info.get('status')}" if info.get("status") else None,
                (
                    f"quality {info.get('quality_rating')}"
                    if info.get("quality_rating")
                    else None
                ),
                (
                    f"mode {info.get('account_mode')}"
                    if info.get("account_mode")
                    else None
                ),
            ]
            add(
                "Access token and phone number",
                "ok" if info.get("status") in (None, "CONNECTED") else "warn",
                " · ".join(p for p in parts if p),
            )
        except WhatsAppAPIError as exc:
            add("Access token and phone number", "fail", self._error_text(exc))
            return checks  # nothing else can work without these

        # 2-5 need the WhatsApp Business Account ID
        if not waba:
            add(
                "Business Account",
                "fail",
                "Business Account ID is not set, so templates, Flows and sending "
                "status can't be checked.",
            )
            return checks

        try:
            account = self._request(
                "GET",
                f"{base}/{waba}",
                params={"fields": "name"},
                headers=self._headers(),
            )
            add("Business Account", "ok", account.get("name") or waba)
        except WhatsAppAPIError as exc:
            add("Business Account", "fail", self._error_text(exc))
            return checks

        try:
            self._request(
                "GET",
                f"{base}/{waba}/message_templates",
                params={"limit": 1},
                headers=self._headers(),
            )
            add("Template access", "ok", "Message templates can be read.")
        except WhatsAppAPIError as exc:
            add("Template access", "fail", self._error_text(exc))

        try:
            health = self._request(
                "GET",
                f"{base}/{waba}",
                params={"fields": "health_status"},
                headers=self._headers(),
            ).get("health_status", {})
            state = health.get("can_send_message")
            problems = [
                error.get("error_description") or error.get("possible_solution")
                for entity in health.get("entities", [])
                for error in entity.get("errors", [])
            ]
            if state == "AVAILABLE":
                add(
                    "Sending allowed",
                    "ok",
                    "Meta allows this account to send messages.",
                )
            else:
                # BLOCKED (e.g. a payment problem) stops business-initiated
                # messages such as templates; replies to a customer who wrote
                # in the last 24 hours still go through. So it is a warning.
                detail = f"Meta reports {state or 'unknown'}. " + " ".join(
                    dict.fromkeys(p for p in problems if p)
                )
                if state == "BLOCKED":
                    detail += (
                        " Templates and other business-started messages are blocked; "
                        "replies inside the 24-hour window can still be sent."
                    )
                add("Sending allowed", "warn", detail)
        except WhatsAppAPIError as exc:
            add("Sending allowed", "warn", self._error_text(exc))

        try:
            subscribed = self._request(
                "GET", f"{base}/{waba}/subscribed_apps", headers=self._headers()
            ).get("data", [])
            if subscribed:
                names = ", ".join(
                    (item.get("whatsapp_business_api_data") or {}).get("name", "app")
                    for item in subscribed
                )
                add("Webhook subscription", "ok", f"App subscribed: {names}")
            else:
                add(
                    "Webhook subscription",
                    "warn",
                    "No app is subscribed to this account, so incoming messages "
                    "and delivery updates won't arrive.",
                )
        except WhatsAppAPIError as exc:
            add("Webhook subscription", "warn", self._error_text(exc))

        return checks

    def get_flow_field_labels(self, flow_id):
        """
        Return {answer_key: on-screen label} for a published Flow, by mapping
        each "complete" payload key (e.g. "full_name": "${form.name_field}")
        to the label of the input component it references. Best effort: an
        empty dict if the Flow JSON can't be fetched.
        """
        labels = {}
        try:
            assets = self._request(
                "GET",
                f"{GRAPH_API_BASE_URL}/{self.api_version}/{flow_id}/assets",
                headers=self._headers(),
            )
        except WhatsAppAPIError:
            return labels
        for asset in assets.get("data", []):
            download_url = asset.get("download_url")
            if not download_url:
                continue
            try:
                response = requests.get(download_url, timeout=30)
                flow_json = response.json() if response.ok else None
            except (requests.RequestException, ValueError):
                continue
            if flow_json:
                labels.update(self._extract_flow_field_labels(flow_json))
        return labels

    @staticmethod
    def _extract_flow_field_labels(flow_json):
        """Map completion-payload keys to the label of the component they reference."""
        component_labels = {}
        payloads = {}

        def _walk(node):
            if isinstance(node, dict):
                name, label = node.get("name"), node.get("label")
                if isinstance(name, str) and isinstance(label, str):
                    component_labels[name] = label
                action = node.get("on-click-action")
                if isinstance(action, dict) and action.get("name") == "complete":
                    payload = action.get("payload")
                    if isinstance(payload, dict):
                        payloads.update(payload)
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(flow_json.get("screens", []))
        result = {}
        for key, ref in payloads.items():
            ref_name = None
            if isinstance(ref, str) and ref.startswith("${") and ref.endswith("}"):
                ref_name = ref[2:-1].split(".")[-1]
            label = component_labels.get(ref_name) or component_labels.get(key)
            if label:
                result[key] = label
        return result

    @staticmethod
    def _extract_flow_field_names(flow_json):
        """Collect every terminal screen's completion-payload keys from a Flow JSON."""
        names = set()

        def _walk(node):
            if isinstance(node, dict):
                action = node.get("on-click-action")
                if isinstance(action, dict) and action.get("name") == "complete":
                    payload = action.get("payload")
                    if isinstance(payload, dict):
                        names.update(payload.keys())
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(flow_json.get("screens", []))
        return names

    def upload_media(self, file):
        """Upload a media file and return the Meta-assigned media ID."""
        files = {"file": (file.name, file, file.content_type)}
        data = {"messaging_product": "whatsapp"}
        headers = {
            "Authorization": f"Bearer {self.account.get_decrypted_access_token()}"
        }
        result = self._request(
            "POST",
            f"{self._base_url}/media",
            data=data,
            files=files,
            headers=headers,
        )
        return result.get("id")

    def download_media(self, media_id):
        """Return the raw bytes of a media object given its media ID."""
        headers = {
            "Authorization": f"Bearer {self.account.get_decrypted_access_token()}"
        }
        media_info = self._request(
            "GET",
            f"{GRAPH_API_BASE_URL}/{self.api_version}/{media_id}",
            headers=headers,
        )
        media_url = media_info.get("url")
        response = requests.get(media_url, headers=headers, timeout=30)
        if not response.ok:
            raise WhatsAppAPIError(
                f"Failed to download media {media_id}: {response.status_code}"
            )
        return response.content

    def mark_as_read(self, wa_message_id):
        """Mark an inbound message as read."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wa_message_id,
        }
        return self._request(
            "POST",
            f"{self._base_url}/messages",
            json=payload,
            headers=self._headers(),
        )

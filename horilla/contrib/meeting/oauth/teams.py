"""Microsoft Teams OAuth2 helpers — authorization, callback, token refresh, meeting creation."""

import os
import secrets

from requests_oauthlib import OAuth2Session

from horilla.contrib.utils.middlewares import get_active_company

MS_AUTH_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MS_TOKEN_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MS_SCOPES = [
    "OnlineMeetings.ReadWrite",
    "User.Read",
    "offline_access",
]

# (connect timeout, read timeout) in seconds for every outbound call to Microsoft Graph.
MS_GRAPH_TIMEOUT = (5, 15)


def _get_redirect_uri(request):
    return request.build_absolute_uri("/meeting/teams/callback/")


def get_or_create_config(user, company=None):
    """Ensure a :class:`~horilla.contrib.meeting.models.MicrosoftTeamsOAuthConfig` exists for ``user``."""
    from horilla.contrib.meeting.models import MicrosoftTeamsOAuthConfig

    target_company = company or user.company
    config, _ = MicrosoftTeamsOAuthConfig.all_objects.get_or_create(
        user=user,
        company=target_company,
    )
    return config


def start_oauth(request):
    """Return authorization_url. Saves state to config."""
    company = get_active_company(request)
    config = get_or_create_config(request.user, company=company)
    if os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") is None:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    tenant = config.tenant_id or "common"
    state = secrets.token_urlsafe(32)
    oauth = OAuth2Session(
        config.client_id,
        redirect_uri=_get_redirect_uri(request),
        scope=MS_SCOPES,
        state=state,
    )
    auth_url, state = oauth.authorization_url(MS_AUTH_BASE.format(tenant=tenant))
    config.oauth_state = state
    config.save(update_fields=["oauth_state"])
    return auth_url


def handle_callback(request):
    """Exchange code for token, fetch user email, save."""
    state = request.GET.get("state")
    from horilla.contrib.meeting.models import MicrosoftTeamsOAuthConfig

    try:
        config = MicrosoftTeamsOAuthConfig.all_objects.get(oauth_state=state)
    except Exception:
        return None, "OAuth state mismatch or invalid OAuth state. Please try again."

    if os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") is None:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    tenant = config.tenant_id or "common"
    oauth = OAuth2Session(
        config.client_id,
        redirect_uri=_get_redirect_uri(request),
        state=state,
    )
    callback_url = request.build_absolute_uri(request.get_full_path())
    try:
        token = oauth.fetch_token(
            MS_TOKEN_BASE.format(tenant=tenant),
            authorization_response=callback_url,
            client_secret=config.client_secret,
            timeout=MS_GRAPH_TIMEOUT,
        )
    except Exception as e:
        return None, str(e)

    config.token = token
    config.oauth_state = None

    try:
        resp = oauth.get(
            f"{MS_GRAPH_BASE}/me?$select=mail,otherMails,userPrincipalName",
            timeout=MS_GRAPH_TIMEOUT,
        )
        data = resp.json()
        other_mails = data.get("otherMails") or []
        upn = data.get("userPrincipalName", "")
        if "#EXT#" in upn:
            # Guest/external account: UPN is a synthesized
            # "<local>_<domain>#EXT#@<tenant>.onmicrosoft.com" placeholder,
            # not the user's real address.
            upn = upn.split("#EXT#")[0].replace("_", "@", 1)
        config.connected_email = (
            data.get("mail") or (other_mails[0] if other_mails else "") or upn
        )
    except Exception:
        pass

    config.save(update_fields=["token", "oauth_state", "connected_email"])
    return config, None


def create_meeting(config, title, start_datetime, end_datetime):
    """Create a Teams online meeting via Graph API and return the join URL."""
    if not config.is_connected():
        return None, "Teams account not connected."

    tenant = config.tenant_id or "common"
    oauth = OAuth2Session(
        config.client_id,
        token=config.token,
        auto_refresh_url=MS_TOKEN_BASE.format(tenant=tenant),
        auto_refresh_kwargs={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        token_updater=lambda t: _save_token(config, t),
    )
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    def _fmt(d):
        if d is None:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=_tz.utc)
        return d.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "subject": title,
    }
    if start_datetime:
        payload["startDateTime"] = _fmt(start_datetime)
    if end_datetime:
        payload["endDateTime"] = _fmt(end_datetime)

    try:
        resp = oauth.post(
            f"{MS_GRAPH_BASE}/me/onlineMeetings",
            json=payload,
            timeout=MS_GRAPH_TIMEOUT,
        )
        if resp.status_code == 403:
            return (
                None,
                "Microsoft Teams meeting creation requires a Microsoft 365 work or school account with a Teams license. Personal accounts are not supported by the Microsoft API.",
            )
        if not resp.ok:
            try:
                detail = resp.json().get("error", {}).get("message")
            except Exception:
                detail = resp.text
            return None, detail or f"{resp.status_code} error from Microsoft Graph."
        data = resp.json()
        url = data.get("joinWebUrl") or data.get("joinUrl")
        return url, None
    except Exception as e:
        return None, str(e)


def _save_token(config, token):
    config.token = token
    config.save(update_fields=["token"])

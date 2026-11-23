"""Zoom OAuth2 helpers — authorization, callback, token refresh, meeting creation."""

import os
import secrets

from requests_oauthlib import OAuth2Session

from horilla.contrib.utils.middlewares import get_active_company

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_SCOPES = ["meeting:write:meeting", "user:read:user"]

# (connect timeout, read timeout) in seconds for every outbound call to Zoom.
ZOOM_API_TIMEOUT = (5, 15)


def _get_redirect_uri(request):
    return request.build_absolute_uri("/meeting/zoom/callback/")


def get_or_create_config(user, company=None):
    """Ensure a :class:`~horilla.contrib.meeting.models.ZoomOAuthConfig` exists for ``user``."""
    from horilla.contrib.meeting.models import ZoomOAuthConfig

    target_company = company or user.company
    config, _ = ZoomOAuthConfig.all_objects.get_or_create(
        user=user,
        company=target_company,
    )
    return config


def start_oauth(request):
    """Return (authorization_url, state). Saves state to config."""
    company = get_active_company(request)
    config = get_or_create_config(request.user, company=company)
    if os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") is None:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    oauth = OAuth2Session(
        config.client_id,
        redirect_uri=_get_redirect_uri(request),
        scope=ZOOM_SCOPES,
        state=secrets.token_urlsafe(32),
    )
    auth_url, state = oauth.authorization_url(ZOOM_AUTH_URL)
    config.oauth_state = state
    config.save(update_fields=["oauth_state"])
    return auth_url


def handle_callback(request):
    """Exchange code for token, fetch user email, save to config."""
    state = request.GET.get("state")
    from horilla.contrib.meeting.models import ZoomOAuthConfig

    try:
        config = ZoomOAuthConfig.all_objects.get(oauth_state=state)
    except Exception:
        return None, "OAuth state mismatch or inavlid OAuth state. Please try again."

    if os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") is None:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    oauth = OAuth2Session(
        config.client_id,
        redirect_uri=_get_redirect_uri(request),
        state=state,
    )
    callback_url = request.build_absolute_uri(request.get_full_path())
    try:
        token = oauth.fetch_token(
            ZOOM_TOKEN_URL,
            authorization_response=callback_url,
            client_secret=config.client_secret,
            timeout=ZOOM_API_TIMEOUT,
        )
    except Exception as e:
        return None, str(e)

    config.token = token
    config.oauth_state = None

    # Fetch connected email
    try:
        resp = oauth.get(f"{ZOOM_API_BASE}/users/me", timeout=ZOOM_API_TIMEOUT)
        data = resp.json()
        config.connected_email = data.get("email", "")
    except Exception:
        pass

    config.save(update_fields=["token", "oauth_state", "connected_email"])
    return config, None


def create_meeting(config, title, start_datetime, end_datetime):
    """Create a Zoom meeting via API and return the join URL."""
    if not config.is_connected():
        return None, "Zoom account not connected."

    oauth = OAuth2Session(
        config.client_id,
        token=config.token,
        auto_refresh_url=ZOOM_TOKEN_URL,
        auto_refresh_kwargs={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        token_updater=lambda t: _save_token(config, t),
    )
    duration = (
        int((end_datetime - start_datetime).total_seconds() / 60)
        if end_datetime
        else 60
    )
    payload = {
        "topic": title,
        "type": 2,  # Scheduled meeting
        "start_time": (
            start_datetime.strftime("%Y-%m-%dT%H:%M:%S") if start_datetime else None
        ),
        "duration": duration,
        "settings": {"join_before_host": True, "waiting_room": False},
    }
    try:
        resp = oauth.post(
            f"{ZOOM_API_BASE}/users/me/meetings",
            json=payload,
            timeout=ZOOM_API_TIMEOUT,
        )
        if not resp.ok:
            try:
                body = resp.json()
                msg = body.get("message") or body.get("reason") or resp.text
            except Exception:
                msg = resp.text
            return None, f"Zoom API error {resp.status_code}: {msg}"
        data = resp.json()
        return data.get("join_url"), None
    except Exception as e:
        return None, str(e)


def _save_token(config, token):
    config.token = token
    config.save(update_fields=["token"])

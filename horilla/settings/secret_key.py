"""Resolve SECRET_KEY without accepting a value shipped in the repository."""

import os
import secrets
import warnings
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Values that have appeared in this repository, Compose, or installer configs.
# Anyone can mint API tokens with them, so they must never sign anything.
PLACEHOLDER_SECRET_KEYS = frozenset(
    {
        "django-insecure-default-key",
        "dev-secret-key-change-in-production",
        "change-this-in-production",
        "auto-generated-key",
        "your-secret-key",
    }
)


def resolve_secret_key(configured, path):
    """
    Return a unique signing key.

    An operator-supplied value is kept. A blank value or a shipped placeholder
    is replaced with the key stored at ``path``, creating that file on first
    use so every process on the same machine shares it.
    """
    configured = (configured or "").strip()
    path = Path(path)
    if configured and configured not in PLACEHOLDER_SECRET_KEYS:
        return configured

    if configured:
        warnings.warn(
            "SECRET_KEY is a shipped placeholder and will not be used to sign "
            "sessions or API tokens.",
            UserWarning,
            stacklevel=2,
        )

    existing = _read_key(path)
    if existing:
        return existing

    key = secrets.token_urlsafe(64)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = _read_key(path)
        if existing:
            return existing
        raise ImproperlyConfigured(
            f"{path} exists but is empty or a shipped placeholder. "
            "Set SECRET_KEY to a unique random value."
        )
    except OSError as exc:
        raise ImproperlyConfigured(
            "SECRET_KEY is unset and "
            f"{path} could not be created ({exc}). "
            "Set SECRET_KEY to a unique random value."
        ) from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)
    except OSError as exc:
        raise ImproperlyConfigured(
            f"SECRET_KEY could not be written to {path} ({exc}). "
            "Set SECRET_KEY to a unique random value."
        ) from exc
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _read_key(path):
    """Return the stored key, or an empty string when it cannot be used."""
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not value or value in PLACEHOLDER_SECRET_KEYS:
        return ""
    return value

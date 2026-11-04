"""
Shared failed-sign-in limits for the page login, the admin login, and the API.

The client address is the connection address unless that peer is listed in
``TRUSTED_PROXIES``. A caller-supplied ``X-Forwarded-For`` is never the first
choice: proxies that append it leave the caller's value in front.
"""

import hashlib
import ipaddress
import logging

from django.conf import settings
from django.core.cache import cache

from horilla.utils.translation import gettext

logger = logging.getLogger(__name__)

LOCKOUT_MESSAGE = "Too many failed login attempts. Please try again in 15 minutes."
UNAVAILABLE_MESSAGE = "Sign-in is temporarily unavailable. Please try again shortly."


class CredentialStoreUnavailable(Exception):
    """The counter could not be read or updated. The attempt must be refused."""


def signin_unavailable_message():
    """Message shown when the lockout counter cannot be reached."""
    return gettext(UNAVAILABLE_MESSAGE)


def lockout_message():
    """Message shown when a sign-in limit has been reached."""
    return gettext(LOCKOUT_MESSAGE)


def client_ip(request):
    """
    Return the address that should own this request's failure counters.

    Forwarded headers are used only when the immediate peer is a trusted
    proxy. ``X-Real-IP`` wins because the shipped proxy config overwrites it
    with the real connection address. Otherwise the rightmost forwarded hop
    is used, which is the one a proxy appends.
    """
    remote = _valid_ip(request.META.get("REMOTE_ADDR", ""))
    if not remote or not _is_trusted(remote):
        return remote or "unknown"

    real = _valid_ip(request.META.get("HTTP_X_REAL_IP", ""))
    if real:
        return real

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") or ""
    hops = [ip for ip in (_valid_ip(part) for part in forwarded.split(",")) if ip]
    if hops:
        return hops[-1]
    return remote


def login_blocked(request, username):
    """
    Return a lockout message when this username and client must not try again.

    Raises ``CredentialStoreUnavailable`` when the counter cannot be read.
    """
    keys = _keyset(client_ip(request), username)
    for lock_key in (keys["pair_lock"], keys["ip_lock"], keys["user_lock"]):
        if lock_key and _cache_get(lock_key):
            return lockout_message()
    return None


def record_login_failure(request, username):
    """
    Count a rejected password.

    Returns a lockout message when this failure reaches a limit, else None.
    Raises ``CredentialStoreUnavailable`` when the counter cannot be updated.
    """
    ip = client_ip(request)
    keys = _keyset(ip, username)
    seconds = _seconds()
    pair_count = _bump(keys["pair_count"], seconds)
    ip_count = _bump(keys["ip_count"], seconds)
    user_count = _bump(keys["user_count"], seconds) if keys["user_count"] else 0

    locked = False
    if pair_count >= _limit("LOGIN_PAIR_LIMIT", 5):
        _cache_set(keys["pair_lock"], True, seconds)
        locked = True
    if ip_count >= _limit("LOGIN_IP_LIMIT", 50):
        _cache_set(keys["ip_lock"], True, seconds)
        locked = True
    if keys["user_lock"] and user_count >= _limit("LOGIN_ACCOUNT_LIMIT", 20):
        _cache_set(keys["user_lock"], True, seconds)
        locked = True
    if locked:
        logger.warning("Login lockout for client %s", ip)
        return lockout_message()
    return None


def clear_login_failures(request, username):
    """Forget this client's failures for a username after a correct password."""
    keys = _keyset(client_ip(request), username)
    names = [keys["pair_count"], keys["pair_lock"]]
    if keys["user_count"]:
        names.extend([keys["user_count"], keys["user_lock"]])
    try:
        cache.delete_many(names)
    except Exception:
        logger.exception("Could not clear login lockout counters")


def _keyset(ip, username):
    """Cache keys for the pair, the address, and the account."""
    user = (username or "").strip()
    pair = _digest(f"{ip}\n{user}")
    user_digest = _digest(user) if user else ""
    return {
        "pair_count": f"login:pair:count:{pair}",
        "pair_lock": f"login:pair:lock:{pair}",
        "ip_count": f"login:ip:count:{_digest(ip)}",
        "ip_lock": f"login:ip:lock:{_digest(ip)}",
        "user_count": f"login:user:count:{user_digest}" if user_digest else None,
        "user_lock": f"login:user:lock:{user_digest}" if user_digest else None,
    }


def _digest(value):
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def _valid_ip(value):
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def _is_trusted(remote):
    try:
        addr = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for entry in getattr(settings, "TRUSTED_PROXIES", ()) or ():
        text = str(entry).strip()
        if not text:
            continue
        try:
            if "/" in text:
                if addr in ipaddress.ip_network(text, strict=False):
                    return True
            elif addr == ipaddress.ip_address(text):
                return True
        except ValueError:
            continue
    return False


def _limit(name, default):
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _seconds():
    seconds = _limit("LOGIN_LOCKOUT_SECONDS", 900)
    return seconds if seconds > 0 else 900


def _cache_get(key):
    try:
        return cache.get(key)
    except Exception as exc:
        logger.exception("Login lockout store is unavailable")
        raise CredentialStoreUnavailable from exc


def _cache_set(key, value, timeout):
    try:
        cache.set(key, value, timeout)
    except Exception as exc:
        logger.exception("Login lockout store is unavailable")
        raise CredentialStoreUnavailable from exc


def _bump(key, timeout):
    """Increase a counter, keeping the window that started with the first hit."""
    try:
        if cache.add(key, 1, timeout):
            return 1
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout)
        return 1
    except Exception as exc:
        logger.exception("Login lockout store is unavailable")
        raise CredentialStoreUnavailable from exc

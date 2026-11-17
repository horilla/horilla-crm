"""
Pluggable exchange rate providers.

Any app can add a rate source without editing Horilla core. In the app's
``AppConfig.ready()`` (or any module that is imported at startup)::

    from decimal import Decimal
    from horilla.contrib.core.services.exchange_providers import register_provider

    @register_provider("mybank", "My Bank API", in_auto=True, priority=50)
    def fetch_my_bank(base_currency, target_currencies):
        # return {"USD": Decimal("0.0106"), ...} for the codes it can supply
        ...

The provider then appears in the "Rate Source" dropdown. With ``in_auto=True``
it is also tried by the "Automatic" option, lowest ``priority`` first.
A provider must return a dict of currency code -> Decimal (empty on failure)
and should never raise.
"""

import json
import logging
import re
from decimal import Decimal, InvalidOperation

import requests

logger = logging.getLogger(__name__)

AUTO_KEY = "auto"
_PROVIDERS = {}


CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3,10}$")
# conversion_rate is DecimalField(max_digits=10, decimal_places=4)
MAX_RATE = Decimal("999999.9999")
MIN_RATE = Decimal("0.0001")
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_TIMEOUT = (3, 7)  # connect, read seconds


def is_valid_currency_code(code):
    """Currency codes are letters only, so they are safe to use in addresses."""
    return isinstance(code, str) and bool(CURRENCY_CODE_RE.match(code))


def sanitize_rates(raw, allowed_codes):
    """
    Keep only usable rates from a provider's answer: for a requested code, a finite
    number between MIN_RATE and MAX_RATE. Zero, negative, NaN, infinite or oversized
    values are dropped, so a faulty or compromised service cannot save a bad rate.
    """
    clean = {}
    allowed = {c.upper(): c for c in allowed_codes}
    for code, value in (raw or {}).items():
        original = allowed.get(str(code).upper())
        if original is None:
            continue
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if not rate.is_finite():
            continue
        rate = rate.quantize(Decimal("0.0001"))
        if MIN_RATE <= rate <= MAX_RATE:
            clean[original] = rate
        else:
            logger.warning("Ignoring out-of-range rate for %s: %s", code, value)
    return clean


def fetch_json(url, params=None):
    """
    GET a small JSON document: HTTPS only, no redirects, short timeouts and a size
    cap. Returns the parsed data, or None if anything is wrong.
    """
    if not url.startswith("https://"):
        return None
    try:
        with requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
            stream=True,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status_code != 200:
                return None
            body = b""
            for chunk in response.iter_content(chunk_size=65536):
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    logger.warning("Rate response from %s is too large", url)
                    return None
        return json.loads(body)
    except Exception as e:
        logger.warning("Rate request to %s failed: %s", url, e)
        return None


def register_provider(key, label, *, in_auto=False, priority=100):
    """Decorator registering ``fetch(base_currency, target_currencies)``."""
    if key == AUTO_KEY:
        raise ValueError(f"'{AUTO_KEY}' is reserved")

    def decorator(fetch):
        _PROVIDERS[key] = {
            "key": key,
            "label": label,
            "fetch": fetch,
            "in_auto": in_auto,
            "priority": priority,
        }
        return fetch

    return decorator


def unregister_provider(key):
    """Remove a provider (mainly for tests and overrides)."""
    _PROVIDERS.pop(key, None)


def _auto_providers():
    return sorted(
        (p for p in _PROVIDERS.values() if p["in_auto"]), key=lambda p: p["priority"]
    )


def get_provider_choices():
    """(value, label) pairs for the Rate Source dropdown."""
    auto = _auto_providers()
    auto_label = "Automatic"
    if auto:
        auto_label += " (" + ", then ".join(p["label"] for p in auto) + ")"
    choices = [(AUTO_KEY, auto_label)]
    ordered = sorted(_PROVIDERS.values(), key=lambda p: (p["priority"], p["label"]))
    choices += [(p["key"], f'{p["label"]} Only') for p in ordered]
    return choices


def get_provider_keys():
    """All valid values for a company's exchange rate source."""
    return [value for value, _label in get_provider_choices()]


def fetch_rates(base_currency, target_currencies, preferred=AUTO_KEY):
    """
    Fetch rates using the chosen provider (or the automatic chain).

    Returns (dict of code -> Decimal, provider label or None).
    """
    if not is_valid_currency_code(base_currency):
        return {}, None
    target_currencies = [
        c for c in (target_currencies or []) if is_valid_currency_code(c)
    ]
    if not target_currencies:
        return {}, None
    if preferred in _PROVIDERS:
        chain = [_PROVIDERS[preferred]]
    else:
        chain = _auto_providers()
    for provider in chain:
        try:
            result = provider["fetch"](base_currency, list(target_currencies))
        except Exception as e:  # a bad plugin must not break the others
            logger.warning("Rate provider %s failed: %s", provider["key"], e)
            continue
        result = sanitize_rates(result, target_currencies)
        if result:
            return result, provider["label"]
    return {}, None


# --------------------------------------------------------------------------
# Built-in providers (free, no API key)
# --------------------------------------------------------------------------


@register_provider("frankfurter", "Frankfurter", in_auto=True, priority=10)
def _fetch_frankfurter(base_currency, target_currencies):
    """Frankfurter (MIT, no key): GET /v2/rates returns a list of rate objects."""
    data = fetch_json(
        "https://api.frankfurter.dev/v2/rates",
        params={"base": base_currency.upper(), "quotes": ",".join(target_currencies)},
    )
    result = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("quote") is not None:
                result[str(item["quote"])] = item.get("rate")
    return result


CURRENCY_API_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base}.json",
    "https://latest.currency-api.pages.dev/v1/currencies/{base}.json",
)


@register_provider("currency_api", "Currency API", in_auto=True, priority=20)
def _fetch_currency_api(base_currency, target_currencies):
    """
    fawazahmed0 currency-api (CC0, no key): one static JSON file per base
    currency, served from jsDelivr with a Cloudflare Pages fallback.
    """
    base = base_currency.lower()
    for url in CURRENCY_API_URLS:
        data = fetch_json(url.format(base=base))
        rates = data.get(base) if isinstance(data, dict) else None
        if isinstance(rates, dict):
            result = {c: rates.get(c.lower()) for c in target_currencies}
            result = {c: v for c, v in result.items() if v is not None}
            if result:
                return result
    return {}

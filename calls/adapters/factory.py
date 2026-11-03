"""Adapter registry and factory for telephony providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from calls.models import CallProvider

    from .base import BaseCallAdapter

_REGISTRY: dict[str, type["BaseCallAdapter"]] = {}


def register_adapter(provider_type: str):
    """
    Class decorator that registers an adapter for a provider type.

    Usage:
        @register_adapter("twilio")
        class TwilioAdapter(BaseCallAdapter):
            ...
    """

    def decorator(cls):
        _REGISTRY[provider_type] = cls
        return cls

    return decorator


def get_adapter(provider: "CallProvider") -> "BaseCallAdapter":
    """
    Return an initialised adapter instance for *provider*.

    Raises ValueError if no adapter is registered for provider.provider_type.
    Import adapters early (e.g. in AppConfig.ready()) so they self-register.
    """
    cls = _REGISTRY.get(provider.provider_type)
    if cls is None:
        raise ValueError(
            f"No call adapter registered for provider type '{provider.provider_type}'. "
            f"Registered types: {list(_REGISTRY.keys())}"
        )
    return cls(provider)


def get_adapter_class(provider_type: str) -> "type[BaseCallAdapter] | None":
    """Return the adapter class registered for *provider_type*, or None."""
    return _REGISTRY.get(provider_type)


def registered_providers() -> list[str]:
    """Return all currently registered provider type keys."""
    return list(_REGISTRY.keys())

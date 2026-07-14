"""
Bot Rule engine: interprets WhatsAppBotRule/Node/Edge graphs at runtime.

Importing this package registers every built-in node handler (see
`nodes/__init__.py`), so it must be imported once at app startup - see
WhatsappConfig.auto_import_modules in apps.py.
"""

from . import nodes  # noqa: F401  (import for registration side effect)

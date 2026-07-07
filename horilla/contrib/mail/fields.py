"""
Custom Django model fields for the mail application.

This module provides encrypted field implementations for storing sensitive
data such as email passwords in an encrypted format.
"""

# Standard library imports
import base64
import binascii

# First party imports (Horilla)
from horilla.db import models

# Local imports
from .encryption_utils import encrypt_password


def _looks_like_fernet_token(value):
    """
    Return True if value is structurally a Fernet token (urlsafe-base64 whose
    decoded bytes start with Fernet's version byte, 0x80), rather than
    guessing from string length — plain-text secrets (e.g. long OAuth access
    tokens) can easily exceed 100 characters and must not be mistaken for
    already-encrypted values.
    """
    if not isinstance(value, str) or not value:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return False
    return len(decoded) > 0 and decoded[0] == 0x80


class EncryptedCharField(models.CharField):
    """
    Custom field that encrypts data but NEVER decrypts automatically.
    Decryption must be done explicitly when needed (e.g., sending emails).
    """

    def from_db_value(self, value, expression, connection):
        """
        Return encrypted value AS-IS.
        DO NOT decrypt automatically - keeps password hidden in forms.
        """
        return value

    def get_prep_value(self, value):
        """Encrypt when saving to database"""
        if value is None or value == "":
            return value

        # If already encrypted, don't re-encrypt
        if _looks_like_fernet_token(value):
            return value

        # Encrypt plain text password
        return encrypt_password(value)

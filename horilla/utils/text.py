"""
Horilla text - re-exports django.utils.text for consistent imports.

Use: from horilla.utils.text import slugify
     from horilla.utils.text import Truncator, capfirst, ...
"""

from django.utils.functional import lazy
from django.utils.text import (
    Truncator,
    camel_case_to_spaces,
    capfirst,
    compress_sequence,
    compress_string,
    get_text_list,
    get_valid_filename,
    normalize_newlines,
    phone2numeric,
    slugify,
    smart_split,
    unescape_string_literal,
    wrap,
)
from django.utils.translation import gettext


def title_words(value):
    """Capitalise the first letter of every word and leave the rest as written."""
    return " ".join(word[:1].upper() + word[1:] for word in str(value).split(" "))


_SMALL_WORDS = {
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "and",
    "or",
    "at",
    "by",
    "as",
}


def _verb_placeholder(verb, label):
    """Build "<verb> <label>" in Title Case, keeping small words like "of" lowercase."""
    words = [
        w if i and w.lower() in _SMALL_WORDS else w[:1].upper() + w[1:]
        for i, w in enumerate(str(label).strip().split(" "))
    ]
    return f"{gettext(verb)} {' '.join(words)}".strip()


def select_placeholder(label):
    """Build a "Select <label>" placeholder for a dropdown."""
    return _verb_placeholder("Select", label)


def enter_placeholder(label):
    """Build an "Enter <label>" placeholder for a text input."""
    return _verb_placeholder("Enter", label)


select_placeholder_lazy = lazy(select_placeholder, str)


__all__ = [
    "enter_placeholder",
    "select_placeholder",
    "select_placeholder_lazy",
    "title_words",
    "Truncator",
    "camel_case_to_spaces",
    "capfirst",
    "compress_sequence",
    "compress_string",
    "get_text_list",
    "get_valid_filename",
    "normalize_newlines",
    "phone2numeric",
    "slugify",
    "smart_split",
    "unescape_string_literal",
    "wrap",
]

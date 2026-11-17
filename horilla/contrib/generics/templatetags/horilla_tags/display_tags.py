"""Template tags for displaying field values and currency."""

# Standard library imports
import ast
import json
import uuid
from urllib.parse import urlencode

# Third-party imports (Django)
from django.db.models.fields.json import JSONField
from django.template.loader import render_to_string
from django.urls import resolve
from django.utils.safestring import SafeString

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import MultipleCurrency
from horilla.contrib.core.utils import get_currency_display_value
from horilla.utils.html import format_html_join

# Local imports
from ._registry import register
from ._shared import _get_request_user_company, format_datetime_value


def _get_country_field_value(obj):
    """Return the ISO country code from the model's declared country field.

    Models with a non-default field name (e.g. Contact's ``address_country``)
    declare it via ``COUNTRY_FIELD_NAME = "address_country"``; defaults to
    ``"country"`` when not declared.
    """
    country_field_name = getattr(obj.__class__, "COUNTRY_FIELD_NAME", "country")
    country_value = getattr(obj, country_field_name, None)
    if not country_value:
        return None
    code = getattr(country_value, "code", country_value)
    return str(code) if code else None


def _build_referrer_params(source_obj):
    """Build referrer_* query params pointing back at source_obj's own detail view.

    Mirrors the convention used for activity-tab row links (see
    ActivityTabListMixin.col_attrs) so a detail view can resolve the current
    URL of the page the user navigated from, instead of trusting a stale
    HX-Current-URL/Referer header captured at click time.
    """
    if source_obj is None or not hasattr(source_obj, "pk") or source_obj.pk is None:
        return ""

    get_detail_url = getattr(source_obj, "get_detail_view_url", None) or getattr(
        source_obj, "get_detail_url", None
    )
    if not callable(get_detail_url):
        return ""

    try:
        detail_path = str(get_detail_url())
        resolved = resolve(detail_path)
        url_name = resolved.url_name or ""
    except Exception:
        return ""

    if not url_name:
        return ""

    return urlencode(
        {
            "referrer_app": source_obj._meta.app_label,
            "referrer_model": source_obj._meta.model_name,
            "referrer_id": source_obj.pk,
            "referrer_url": url_name,
        }
    )


def render_user_chip(target_user, viewer, source_obj=None):
    """
    Render a linked user chip when the viewer can view users; otherwise plain text.

    ``source_obj`` is the record the chip is being displayed on (e.g. the Lead
    whose owner is being shown). When given, it's encoded as referrer_* query
    params on the chip's link so the target user's detail page can send the
    user back to this exact record rather than wherever the browser's address
    bar last happened to point.
    """

    if not isinstance(target_user, User):
        return str(target_user) if target_user is not None else ""

    get_full_name = getattr(target_user, "get_full_name", None)
    full_name = get_full_name().strip() if callable(get_full_name) else ""

    if not full_name:
        full_name = getattr(target_user, "username", None) or str(target_user)

    can_view = (
        viewer
        and viewer.is_authenticated
        and viewer.has_perm(f"{User._meta.app_label}.view_{User._meta.model_name}")
    )

    # Users who cannot open the profile still get the pill, just not linked
    detail_url = ""
    if can_view:
        get_detail_view_url = getattr(target_user, "get_detail_view_url", None)
        detail_url = str(get_detail_view_url()) if callable(get_detail_view_url) else ""

        referrer_params = _build_referrer_params(source_obj)
        if detail_url and referrer_params:
            separator = "&" if "?" in detail_url else "?"
            detail_url = f"{detail_url}{separator}{referrer_params}"

    return render_to_string(
        "user_chip.html",
        {
            "detail_url": detail_url,
            "avatar_url": target_user.get_avatar(),
            "full_name": full_name,
        },
    )


def render_user_chip_list(related_objects, viewer, source_obj, style, label=""):
    """Render many users compactly so a long list never stretches its container.

    ``style="header"`` shows two chips plus a "+N" button; ``style="detail"``
    shows a single line that fades out at the edge with a pinned "+N". Both
    open a searchable dialog listing everyone.
    """
    chips = [
        render_user_chip(item, viewer, source_obj=source_obj)
        for item in related_objects
    ]
    items = [
        {"name": user.get_full_name().strip() or user.username, "chip": chip}
        for user, chip in zip(related_objects, chips)
    ]
    return render_to_string(
        "partials/m2m_user_chips.html",
        {
            "style": style,
            "chips": chips,
            "items": items,
            "label": label,
            "uid": uuid.uuid4().hex[:10],
        },
    )


@register.simple_tag
def display_field_value(obj, field_name, user, style=None):
    """
    Template tag to display field value with automatic currency formatting,
    datetime timezone conversion, and custom formatting

    Usage in template:
    {% display_field_value obj field_name request.user %}

    Works automatically if model has CURRENCY_FIELDS attribute
    Handles datetime fields with user's timezone and format preferences

    A model with a non-default state field name declares it via
    ``STATE_FIELD_NAME = "address_state"`` (defaults to ``"state"``) so its
    code value resolves to the matching subdivision name.
    """
    if (
        hasattr(obj.__class__, "CURRENCY_FIELDS")
        and field_name in obj.__class__.CURRENCY_FIELDS
    ):
        return get_currency_display_value(obj, field_name, user)

    if hasattr(obj, "get_field_display"):
        return obj.get_field_display(field_name, user)

    value = getattr(obj, field_name, None)

    if value is None:
        return ""

    state_field_name = getattr(obj.__class__, "STATE_FIELD_NAME", "state")
    if field_name == state_field_name:
        country_code = _get_country_field_value(obj)
        if country_code:
            from horilla.utils.choices import get_subdivision_choices

            choices = get_subdivision_choices(country_code)
            return dict(choices).get(value, value)

    try:
        _field = obj._meta.get_field(field_name)
    except Exception:
        _field = None
    if isinstance(_field, JSONField):
        if isinstance(value, str) and value.strip():
            s = value.strip()
            if (s.startswith("[") and s.endswith("]")) or (
                s.startswith("{") and s.endswith("}")
            ):
                try:
                    value = json.loads(s)
                except json.JSONDecodeError:
                    try:
                        value = ast.literal_eval(s)
                    except (ValueError, SyntaxError):
                        pass
        if isinstance(value, (list, tuple)):
            return ", ".join(
                str(v).strip() for v in value if v is not None and str(v).strip()
            )
        if isinstance(value, dict):
            if not value:
                return ""
            return ", ".join(f"{k}: {v}" for k, v in value.items())
        return str(value) if value else ""

    _, _, company = _get_request_user_company()

    formatted = format_datetime_value(
        value, user=user, company=company, convert_timezone=True
    )
    if formatted is not None:
        return formatted

    if hasattr(value, "all"):
        related_objects = list(value.all())
        if not related_objects:
            return ""
        if style and all(isinstance(item, User) for item in related_objects):
            try:
                label = str(obj._meta.get_field(field_name).verbose_name)
            except Exception:
                label = ""
            return render_user_chip_list(related_objects, user, obj, style, label)
        if all(isinstance(item, User) for item in related_objects):
            return format_html_join(
                " ",
                "{}",
                (
                    (render_user_chip(item, user, source_obj=obj),)
                    for item in related_objects
                ),
            )
        return ", ".join(str(item) for item in related_objects)

    try:
        field = obj._meta.get_field(field_name)
        if hasattr(field, "choices") and field.choices:
            labels = dict(field.flatchoices)
            if isinstance(value, (list, tuple)):
                return ", ".join(str(labels.get(item, item)) for item in value)
            return labels.get(value, value)
    except Exception:
        pass

    if isinstance(value, User):
        return render_user_chip(value, user, source_obj=obj)

    if hasattr(value, "__str__"):
        return str(value)

    return value


@register.filter
def format_currency(value, user):
    """Template filter for currency formatting"""
    if not value:
        return ""

    user_currency = MultipleCurrency.get_user_currency(user)
    if user_currency:
        return user_currency.display_with_symbol(value, user=user)

    return str(value)


@register.filter
def is_safe_html(value):
    """
    Template filter to detect values that are pre-rendered HTML (e.g. user
    chips) rather than plain text, so callers can avoid placing them inside
    HTML attributes such as an <input value="...">.
    """
    return isinstance(value, SafeString)


@register.filter
def shortname(value):
    """Filter to get short name (initials) from a full name string"""
    if not value:
        return ""

    words = value.strip().split()

    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()

    return words[0][0].upper()

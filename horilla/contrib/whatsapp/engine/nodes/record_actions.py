"""
Generic record-action node handlers: create_record, update_record,
search_record, assign_owner, add_note.

These operate model-agnostically via HorillaContentType - the admin picks
any registered model at flow-design time (restricted to models opted into
the "whatsapp_flow_action_models" feature, see registration.py) and maps
flow variables to its fields. No specific model's name or fields are
hardcoded here - any model registered for the feature works today or in
the future, without touching this file.
"""

# Standard library imports
import logging
import re
from datetime import datetime

# Local imports
from ..base import NodeHandler, NodeResult
from ..interpolation import interpolate_dict
from ..registry import register_node

logger = logging.getLogger(__name__)


def _fk_safe_field_mapping(model_cls, field_mapping):
    """
    Rewrite any ForeignKey entry in field_mapping from "<field>": "<pk>" to
    "<field>_id": "<pk>" - the value widget (see flow_builder.py's
    _render_fk_widget) always stores a bare related-object pk string, but
    Django's forward FK descriptor only accepts an actual model instance (or
    None) via the plain field name; the "_id" attname accepts a raw pk
    directly, with no extra lookup needed.
    """
    from django.db import models as dj_models

    resolved = dict(field_mapping)
    for field_name, value in field_mapping.items():
        try:
            field = model_cls._meta.get_field(field_name)
        except Exception:
            continue
        if isinstance(field, dj_models.ForeignKey) and value not in (None, ""):
            resolved[field.attname] = resolved.pop(field_name)
    return resolved


# Same name-based convention PhoneField/_apply_phone_fields uses (see
# horilla/contrib/generics/forms/form_class_mixin.py) to recognize a phone
# field without needing per-model knowledge here.
_PHONE_FIELD_NAMES = {
    "phone",
    "mobile",
    "contact_number",
    "phone_number",
    "mobile_number",
    "secondary_phone",
    "assistant_phone",
    "fax",
    "whatsapp",
    "telephone",
    "cell",
    "cell_number",
    "alt_phone",
    "alternate_phone",
}


def _normalize_phone_number(raw_value):
    """
    Reformat a bare-digit MSISDN (WhatsApp's `conversation.contact_number`
    convention, e.g. "917558020259") into "+<code> <national number>" (e.g.
    "+91 7558020259") - the format PhoneWidget.decompress() expects in order
    to populate its country-code dropdown (see generics/forms/generics.py).
    Falls back to the original value unchanged if it isn't a plain digit
    string, already starts with "+", or doesn't parse as a valid number.
    """
    if not isinstance(raw_value, str) or not raw_value.isdigit():
        return raw_value
    try:
        import phonenumbers
    except ImportError:
        return raw_value
    try:
        parsed = phonenumbers.parse(f"+{raw_value}", None)
    except phonenumbers.NumberParseException:
        return raw_value
    if not phonenumbers.is_valid_number(parsed):
        return raw_value
    return f"+{parsed.country_code} {parsed.national_number}"


def _phone_normalized_field_mapping(model_cls, field_mapping):
    """Reformat every phone-like field_mapping value via _normalize_phone_number."""
    resolved = dict(field_mapping)
    for field_name, value in field_mapping.items():
        if field_name in _PHONE_FIELD_NAMES:
            resolved[field_name] = _normalize_phone_number(value)
    return resolved


def _digits_only_phone_filters(model_cls, filters):
    """
    Return (queryset, rewritten_filters) so a phone-like filter matches
    regardless of "+91 7558020259" vs "917558020259" formatting on either
    side. create_record/update_record now normalize new/updated phone
    fields to "+<code> <number>" (see _normalize_phone_number), but rows
    written before that change - or by any other path - are still bare
    digit strings; comparing both sides with non-digits stripped means
    search_record keeps matching either format without a data migration.
    """
    from django.db.models import Value
    from django.db.models.functions import Replace

    queryset = model_cls.objects.all()
    rewritten = dict(filters)
    for field_name, value in filters.items():
        if field_name not in _PHONE_FIELD_NAMES or not isinstance(value, str):
            continue
        annotation_name = f"_{field_name}_digits"
        queryset = queryset.annotate(
            **{
                annotation_name: Replace(
                    Replace(field_name, Value("+"), Value("")),
                    Value(" "),
                    Value(""),
                )
            }
        )
        rewritten[annotation_name] = "".join(ch for ch in value if ch.isdigit())
        del rewritten[field_name]
    return queryset, rewritten


_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numeric_coerced_field_mapping(model_cls, field_mapping):
    """
    For fields backed by a numeric column (Decimal/Integer/Float), pull the
    first number out of a non-numeric string value - e.g. a Meta Flow choice
    answer like "10000_plus" becomes 10000 - instead of letting Django's own
    to_python() raise on it. Values that already parse as-is, or that contain
    no digits at all, are left untouched so the field's normal validation
    error still surfaces.
    """
    from django.db import models as dj_models

    resolved = dict(field_mapping)
    for field_name, value in field_mapping.items():
        if not isinstance(value, str) or not value:
            continue
        try:
            field = model_cls._meta.get_field(field_name)
        except Exception:
            continue
        if not isinstance(
            field,
            (dj_models.DecimalField, dj_models.IntegerField, dj_models.FloatField),
        ):
            continue
        try:
            field.to_python(value)
            continue  # already a valid numeric string
        except Exception:
            pass
        stripped = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", value)
        match = _NUMERIC_RE.search(stripped)
        if match:
            resolved[field_name] = match.group()
    return resolved


def _resolve_model(content_type_id):
    """Resolve a Django model class from a HorillaContentType pk."""
    from django.apps import apps

    from horilla.contrib.core.models import HorillaContentType

    content_type = HorillaContentType.objects.filter(pk=content_type_id).first()
    if not content_type:
        return None
    model_cls = content_type.model_class()
    if model_cls is None:
        try:
            model_cls = apps.get_model(content_type.app_label, content_type.model)
        except LookupError:
            return None
    return model_cls


def _link_session_record(session, record):
    """Point session.content_type/object_id at `record` (returned in a NodeResult)."""
    from horilla.contrib.core.models import HorillaContentType

    content_type = HorillaContentType.objects.get_for_model(record)
    return content_type.pk, record.pk


@register_node("create_record")
class CreateRecordNode(NodeHandler):
    """Creates a row on any registered model, with interpolated field values."""

    def execute(self, session, node):
        config = node.config
        model_cls = _resolve_model(config.get("content_type_id"))
        if model_cls is None:
            return NodeResult(status="failed", error="create_record: model not found.")

        field_mapping = interpolate_dict(config.get("field_mapping", {}), session)
        field_mapping = _phone_normalized_field_mapping(model_cls, field_mapping)
        field_mapping = _numeric_coerced_field_mapping(model_cls, field_mapping)
        field_mapping = _fk_safe_field_mapping(model_cls, field_mapping)
        try:
            record = model_cls.objects.create(
                company=session.conversation.company, **field_mapping
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - surfaced as a failed node, not a crash
            logger.exception("create_record failed for node %s", node.node_key)
            return NodeResult(status="failed", error=f"create_record failed: {exc}")

        content_type_id = object_id = None
        if config.get("link_session_record", True):
            content_type_id, object_id = _link_session_record(session, record)

        return NodeResult(
            status="advance", content_type_id=content_type_id, object_id=object_id
        )


@register_node("update_record")
class UpdateRecordNode(NodeHandler):
    """Updates the currently-linked record (session.related_to) with interpolated values."""

    def execute(self, session, node):
        config = node.config
        record = session.related_to
        if record is None:
            return NodeResult(status="failed", error="update_record: no linked record.")

        field_mapping = interpolate_dict(config.get("field_mapping", {}), session)
        update_fields = list(field_mapping.keys()) or None
        field_mapping = _phone_normalized_field_mapping(type(record), field_mapping)
        field_mapping = _numeric_coerced_field_mapping(type(record), field_mapping)
        field_mapping = _fk_safe_field_mapping(type(record), field_mapping)
        try:
            for field_name, value in field_mapping.items():
                setattr(record, field_name, value)
            record.save(update_fields=update_fields)
        except Exception as exc:  # noqa: BLE001
            logger.exception("update_record failed for node %s", node.node_key)
            return NodeResult(status="failed", error=f"update_record failed: {exc}")

        return NodeResult(status="advance")


@register_node("search_record")
class SearchRecordNode(NodeHandler):
    """
    Looks up a row on any registered model by interpolated filters, branching
    to found_branch_handle / not_found_branch_handle.
    """

    def execute(self, session, node):
        config = node.config
        model_cls = _resolve_model(config.get("content_type_id"))
        if model_cls is None:
            return NodeResult(status="failed", error="search_record: model not found.")

        filters = interpolate_dict(config.get("filters", {}), session)
        queryset, filters = _digits_only_phone_filters(model_cls, filters)
        record = queryset.filter(
            company=session.conversation.company, **filters
        ).first()

        found_handle = config.get("found_branch_handle", "found")
        not_found_handle = config.get("not_found_branch_handle", "not_found")

        if record is None:
            return NodeResult(status="advance", source_handle=not_found_handle)

        content_type_id = object_id = None
        if config.get("link_session_record", True):
            content_type_id, object_id = _link_session_record(session, record)

        return NodeResult(
            status="advance",
            source_handle=found_handle,
            content_type_id=content_type_id,
            object_id=object_id,
        )


@register_node("assign_owner")
class AssignOwnerNode(NodeHandler):
    """Assigns the conversation to a human agent (round-robin), reusing bot.py's helper."""

    def execute(self, session, node):
        from ...bot import assign_conversation

        assign_conversation(session.conversation)
        return NodeResult(status="advance")


@register_node("add_note")
class AddNoteNode(NodeHandler):
    """
    Appends a timestamped note into the linked record's additional_info JSON
    field, since not every model has a dedicated Note relation.
    """

    def execute(self, session, node):
        from ..interpolation import interpolate

        config = node.config
        record = session.related_to
        if record is None:
            return NodeResult(status="failed", error="add_note: no linked record.")

        text = interpolate(config.get("text", ""), session)
        notes = (record.additional_info or {}).get("whatsapp_notes", [])
        notes.append({"text": text, "created_at": datetime.now().isoformat()})
        record.additional_info = record.additional_info or {}
        record.additional_info["whatsapp_notes"] = notes
        record.save(update_fields=["additional_info"])
        return NodeResult(status="advance")

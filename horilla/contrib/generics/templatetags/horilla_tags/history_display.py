"""Template filters for history/audit log display (handles M2M and normal changes)."""

# Standard library imports
import html
import re

# Third-party imports (Django)
from auditlog.models import LogEntry
from django.contrib.contenttypes.fields import GenericForeignKey
from django.template.defaultfilters import stringfilter
from django.utils.encoding import smart_str

# First party imports (Horilla)
from horilla.core.exceptions import FieldDoesNotExist
from horilla.utils.html import format_html, strip_tags
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ._registry import register

_BLOCK_TAG_RE = re.compile(r"</(?:li|p|div|h[1-6]|tr)\s*>|<br\s*/?>", re.IGNORECASE)
_LIST_ITEM_OPEN_RE = re.compile(r"<li(?:\s[^>]*)?>", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"(?:\s*,\s*)+")

DIFF_VALUE_PREVIEW_LENGTH = 60

# Auto-managed "last saved" fields, hidden from History diffs.
_BOOKKEEPING_FIELD_NAMES = ("updated_at", "updated_by", "modified_at")


@register.filter
def is_create_entry(entry):
    """True if this log entry's action is CREATE. Checks entry.action directly
    rather than string-matching LogEntry.__str__() output."""
    return getattr(entry, "action", None) == LogEntry.Action.CREATE


@register.filter
def content_type_verbose_name(content_type):
    """Get the verbose name of a ContentType's model, falling back to its raw model name."""
    if not content_type:
        return ""
    model = content_type.model_class()
    if model is None:
        return content_type.model
    return model._meta.verbose_name


@register.filter
@stringfilter
def html_to_text(value):
    """
    Convert a rich-text (HTML) value into a readable plain-text summary for the
    history diff: block-level boundaries (</li>, </p>, <br>, ...) become ", "
    separators before the remaining tags are stripped, so a list like
    "<ol><li>Hello</li><li>Hello</li></ol>" reads as "Hello, Hello" instead of
    "HelloHello".
    """
    text = _BLOCK_TAG_RE.sub(", ", value)
    text = strip_tags(text)
    # strip_tags removes markup but leaves entity references (e.g. "&nbsp;")
    # as literal text rather than decoding them - unescape before collapsing
    # whitespace so a decoded nbsp (U+00A0) folds into a normal space too.
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _SEPARATOR_RE.sub(", ", text).strip(", ").strip()
    return text


@register.filter
@stringfilter
def html_to_paragraphs(value):
    """
    Like html_to_text, but keep each block (paragraph, list item, line break)
    on its own line for the History tab's full-text view, so a long note reads
    as paragraphs and each line can take its own text direction. List items
    are prefixed with a bullet.
    """
    text = _LIST_ITEM_OPEN_RE.sub("• ", value)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = strip_tags(text)
    text = html.unescape(text)
    lines = (_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


@register.filter
@stringfilter
def is_long_diff_value(value):
    """True if truncate_diff_value would shorten this history diff value."""
    return len(value) > DIFF_VALUE_PREVIEW_LENGTH


@register.filter
def has_long_diff_value(values):
    """
    True if the old or new value of a history diff ([old, new, ...]) would be
    shortened, so the template can lay that field out as a block when the full
    text is shown. M2M markers are never shortened.
    """
    if not isinstance(values, (list, tuple)) or not values or values[0] == "__m2m__":
        return False
    return any(is_long_diff_value(html_to_text(value)) for value in values[:2])


@register.filter
@stringfilter
def truncate_diff_value(value):
    """
    Shorten a long history diff value (old/new) to a short preview so entries
    with long text (notes, descriptions, ...) stay scannable instead of showing
    two near-identical walls of text. Keeps the tail of the text, since edits
    to long fields are usually appends/changes near the end, and a plain
    head-truncate would make consecutive edits look identical.
    """
    if not is_long_diff_value(value):
        return value
    return "…" + value[-DIFF_VALUE_PREVIEW_LENGTH:]


@register.filter
def history_diff_value(value):
    """
    Render one side (old or new) of a History diff as plain text, or for a
    long value as its tail preview plus its full text (one line per
    paragraph); the History tab's "Show full text" toggle picks which one is
    visible. Empty values render as "--".

    Returned without surrounding whitespace on purpose: inside the History
    tab's dir="auto" value span, a trailing space lands on the far side of a
    left-to-right value ("--", a phone number) in a right-to-left UI, which
    glues the value to the diff arrow.
    """
    text = html_to_text("" if value is None else value) or "--"
    if not is_long_diff_value(text):
        return text
    return format_html(
        '<span class="history-value-preview" dir="auto">{}</span>'
        '<span class="history-value-full" dir="auto">{}</span>',
        truncate_diff_value(text),
        html_to_paragraphs(value),
    )


def _is_redundant_history_entry(entry):
    """
    Return True if this entry should be hidden: an UPDATE with nothing to
    display - every change it recorded is hidden (bookkeeping fields like
    "Updated At", reverse relations) or not a real change (a re-saved value
    that only differs in formatting). Such a row would only read "X updated",
    which says nothing. Genuine edits (with real field changes) are always
    kept. Works for any model; no model names.
    """
    try:
        if getattr(entry, "action", None) != LogEntry.Action.UPDATE:
            return False
        return not history_changes_display(entry)
    except Exception:
        return False


# A m2m-add UPDATE landing within this many seconds of its object's CREATE is
# treated as part of the same form submission (e.g. form.save_m2m() firing
# right after instance.save()), not a later, separate edit.
_CREATION_TIME_M2M_WINDOW_SECONDS = 10


def _find_creation_time_m2m_target(entry, same_group_entries):
    """
    If `entry` is a pure M2M-add UPDATE (no other field changed) that landed
    within _CREATION_TIME_M2M_WINDOW_SECONDS of a CREATE for the same object in
    `same_group_entries`, return that CREATE entry so the caller can fold this
    UPDATE's change into it. Otherwise return None.
    """
    try:
        if getattr(entry, "action", None) != LogEntry.Action.UPDATE:
            return None
        if getattr(entry, "reassignments", None):
            return None
        changes = history_changes_display(entry)
        if not changes:
            return None
        if not all(
            isinstance(v, (list, tuple))
            and len(v) >= 2
            and v[0] == "__m2m__"
            and v[1] == "add"
            for v in changes.values()
        ):
            return None
        ct = getattr(entry, "content_type", None)
        timestamp = getattr(entry, "timestamp", None)
        if ct is None or timestamp is None:
            return None
        entry_pk = str(
            getattr(entry, "object_pk", None) or getattr(entry, "object_id", "")
        )
        for other in same_group_entries:
            if other is entry:
                continue
            if getattr(other, "action", None) != LogEntry.Action.CREATE:
                continue
            if getattr(other, "content_type", None) != ct:
                continue
            other_pk = str(
                getattr(other, "object_pk", None) or getattr(other, "object_id", "")
            )
            if other_pk != entry_pk:
                continue
            other_timestamp = getattr(other, "timestamp", None)
            if other_timestamp is None:
                continue
            delta = abs((timestamp - other_timestamp).total_seconds())
            if delta <= _CREATION_TIME_M2M_WINDOW_SECONDS:
                return other
    except Exception:
        pass
    return None


# A M2M "delete" UPDATE and "add" UPDATE on the same field/object landing within
# this many seconds of each other are treated as one reassignment (e.g. a form's
# save_m2m()/`.set()` firing post_remove then post_add), not two separate edits.
_M2M_REASSIGN_WINDOW_SECONDS = 5


def _entry_object_key(entry):
    ct = getattr(entry, "content_type", None)
    if ct is None:
        return None
    pk = str(getattr(entry, "object_pk", None) or getattr(entry, "object_id", ""))
    return (ct, pk)


def _pure_m2m_changes(entry):
    """
    Return entry's history_changes_display() only if EVERY changed field is a pure
    M2M marker (add or delete), else None. Used to find entries safe to pair as a
    reassignment (an entry that also changed a normal field is never merged away).
    """
    if getattr(entry, "action", None) != LogEntry.Action.UPDATE:
        return None
    changes = history_changes_display(entry)
    if not changes:
        return None
    if not all(
        isinstance(v, (list, tuple)) and len(v) >= 2 and v[0] == "__m2m__"
        for v in changes.values()
    ):
        return None
    return changes


def _pair_m2m_reassignments(entries):
    """
    Find UPDATE entries that are a pure M2M "delete" on some field paired with a
    pure M2M "add" on the SAME field for the SAME object within
    _M2M_REASSIGN_WINDOW_SECONDS - i.e. Django's `.set()` swapping who's assigned,
    which fires as two separate signals/LogEntry rows. Attach the pairing onto the
    "add" entry as `reassignments`: {field: (old_objects_str, new_objects_str)},
    and return the set of "delete" entries that got absorbed into a pairing (to be
    dropped from the rendered list).
    Generic: keys purely off action/field/timestamp, no model or field names.
    """
    absorbed = set()
    deletes = [e for e in entries if _pure_m2m_changes(e) is not None]
    for add_entry in entries:
        add_changes = _pure_m2m_changes(add_entry)
        if not add_changes:
            continue
        add_key = _entry_object_key(add_entry)
        add_timestamp = getattr(add_entry, "timestamp", None)
        if add_key is None or add_timestamp is None:
            continue
        for field, value in add_changes.items():
            if value[1] != "add":
                continue
            best_match = None
            best_delta = None
            for del_entry in deletes:
                if del_entry is add_entry or id(del_entry) in absorbed:
                    continue
                if _entry_object_key(del_entry) != add_key:
                    continue
                del_changes = _pure_m2m_changes(del_entry)
                del_value = del_changes.get(field)
                if del_value is None or del_value[1] != "delete":
                    continue
                del_timestamp = getattr(del_entry, "timestamp", None)
                if del_timestamp is None:
                    continue
                delta = abs((add_timestamp - del_timestamp).total_seconds())
                if delta > _M2M_REASSIGN_WINDOW_SECONDS:
                    continue
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best_match = del_entry
            if best_match is not None:
                reassignments = getattr(add_entry, "reassignments", None)
                if reassignments is None:
                    reassignments = {}
                    add_entry.reassignments = reassignments
                old_value = _pure_m2m_changes(best_match)[field]
                reassignments[field] = (old_value[3], value[3])
                absorbed.add(id(best_match))
    return absorbed


@register.filter
def collapse_redundant_history(entries):
    """
    Collapse redundant/duplicate history rows so one logical action reads as one
    row instead of several:
      - An UPDATE with no displayed changes (a save that only touched hidden
        fields such as "Updated At", or a no-op re-save) is dropped.
      - A M2M "delete" + "add" UPDATE pair on the same field/object within
        _M2M_REASSIGN_WINDOW_SECONDS (a reassignment, e.g. changing who's
        "Assigned To") is merged into one row showing "Old -> New", matching how
        a normal field edit displays, instead of two separate Removed/Added rows.
      - An UPDATE that is purely an M2M add (e.g. "Assigned To: Added: X") landed
        within seconds of the object's CREATE is folded into that CREATE entry
        (via a `creation_time_additions` attribute) instead of being shown as its
        own separate "edit" row, since it's part of the same form submission
        (e.g. assigning someone while creating a task), not a later edit.
    Use in template: {% for entry in entries|collapse_redundant_history %}
    """
    if not entries:
        return entries
    absorbed_into_reassignment = _pair_m2m_reassignments(entries)
    result = []
    for entry in entries:
        if id(entry) in absorbed_into_reassignment:
            continue
        if _is_redundant_history_entry(entry):
            continue
        target = _find_creation_time_m2m_target(entry, entries)
        if target is not None:
            additions = getattr(target, "creation_time_additions", None)
            if additions is None:
                additions = []
                target.creation_time_additions = additions
            for field, value in history_changes_display(entry).items():
                additions.append((field, value))
            continue
        result.append(entry)
    return result


def _current_field_value(model, entry, attname):
    """
    Look up `attname`'s current value on the live row this log entry is
    for (via its object_pk), for a field whose change isn't part of this
    diff. Returns None if the row was deleted or the pk can't be read.
    """
    pk = getattr(entry, "object_pk", None) or getattr(entry, "object_id", None)
    if pk is None:
        return None
    try:
        return model._base_manager.filter(pk=pk).values_list(attname, flat=True).first()
    except Exception:
        return None


def _resolve_gfk_display(related_model, content_type_id, object_id):
    """
    Resolve a GenericForeignKey's (content_type_id, object_id) pair to the
    related object's display string, the same way auditlog resolves a real
    ForeignKey in `LogEntry._get_changes_display_for_fk_field`.
    """
    if not content_type_id or object_id in (None, "None"):
        return str(object_id)
    try:
        content_type = related_model._base_manager.get(pk=content_type_id)
    except Exception:
        return str(object_id)
    target_model = content_type.model_class()
    if target_model is None:
        return str(object_id)
    try:
        return smart_str(target_model._base_manager.get(pk=object_id))
    except target_model.DoesNotExist:
        return str(
            _("Deleted '%(model)s' (%(pk)s)")
            % {
                "model": target_model.__name__,
                "pk": object_id,
            }
        )
    except Exception:
        return str(object_id)


@register.filter
def history_changes_display(entry):
    """
    Return a display-safe changes dict for a log entry.

    Auditlog stores M2M changes as {"type": "m2m", "operation": "add", "objects": [...]}.
    The default changes_display_dict iterates over that dict and shows keys "type" and
    "operation" as if they were old/new values, and there's no real "old" state for an
    add/remove, so a fake "-- -> Added: X" diff arrow only confuses readers. Instead this
    returns a 3-item marker ["__m2m__", operation, objects_str] that the history template
    renders as a plain "Added/Removed: X" line without a diff arrow.
    """
    if entry is None:
        return {}
    display_dict = getattr(entry, "changes_display_dict", None) or {}
    changes_dict = getattr(entry, "changes_dict", None) or {}
    if not changes_dict:
        return display_dict

    model = None
    try:
        if hasattr(entry, "content_type") and entry.content_type:
            model = entry.content_type.model_class()
    except Exception:
        pass

    result = dict(display_dict)

    # django-auditlog tracks reverse relations (a related model's ForeignKey
    # pointing AT this model, e.g. Opportunity.contact_roles) as if they were
    # trackable fields. On CREATE there's no real value yet, so it stringifies
    # the reverse RelatedManager descriptor into garbage like
    # "app_label.SomeModel.None" instead of a real value. Drop any changed
    # field that is structurally a reverse relation (not a real column on this
    # model) - generic, no field names hardcoded.
    if model:
        for field_name in list(changes_dict.keys()):
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            if getattr(field, "concrete", True):
                continue
            # Matches the same verbose_name auditlog itself used as the
            # changes_display_dict key (auditlog/models.py: changes_display_dict).
            verbose_name = str(getattr(field, "verbose_name", field_name))
            result.pop(verbose_name, None)
            changes_dict.pop(field_name, None)

    # A GenericForeignKey's id column (e.g. Activity.object_id, verbose_name
    # "Related To") is a plain PositiveIntegerField to auditlog, so
    # changes_display_dict has no FK type to key off and leaves it as a raw
    # id ("499" -> "2") instead of resolving it like a real ForeignKey.
    # Resolve it here using the sibling content_type column - the same two
    # columns the GenericForeignKey itself reads - to look up each side's
    # related object.
    if model:
        for gfk in model._meta.private_fields:
            if not isinstance(gfk, GenericForeignKey):
                continue
            if gfk.fk_field not in changes_dict:
                continue
            try:
                ct_field = model._meta.get_field(gfk.ct_field)
                fk_field = model._meta.get_field(gfk.fk_field)
            except FieldDoesNotExist:
                continue
            verbose_name = str(getattr(fk_field, "verbose_name", gfk.fk_field))
            if verbose_name not in result:
                continue

            old_object_id, new_object_id = changes_dict[gfk.fk_field]
            if gfk.ct_field in changes_dict:
                old_ct_id, new_ct_id = changes_dict[gfk.ct_field]
            else:
                # content_type didn't change alongside object_id - both
                # sides of the diff point at the row's current content type.
                old_ct_id = new_ct_id = _current_field_value(
                    model, entry, ct_field.attname
                )

            result[verbose_name] = [
                _resolve_gfk_display(ct_field.related_model, old_ct_id, old_object_id),
                _resolve_gfk_display(ct_field.related_model, new_ct_id, new_object_id),
            ]

    for field_name, value in changes_dict.items():
        if not isinstance(value, dict) or value.get("type") != "m2m":
            continue
        verbose_name = field_name.replace("_", " ").title()
        if model:
            try:
                field = model._meta.get_field(field_name)
                verbose_name = getattr(field, "verbose_name", verbose_name)
                if hasattr(verbose_name, "_proxy____args"):
                    verbose_name = str(verbose_name)
            except FieldDoesNotExist:
                pass
        operation = value.get("operation", "")
        objects = value.get("objects") or []
        objects_str = ", ".join(str(o) for o in objects)
        if operation == "add":
            label = _("Added")
        elif operation == "delete":
            label = _("Removed")
        else:
            label = str(operation)
        result[verbose_name] = ["__m2m__", operation, str(label), objects_str]

    # If this entry was paired with a matching add/delete on the same field (see
    # _pair_m2m_reassignments), show it as a plain "Old -> New" diff instead of
    # the M2M add/remove marker, matching how a normal field edit displays.
    reassignments = getattr(entry, "reassignments", None)
    if reassignments:
        for verbose_name, val in list(result.items()):
            if not (
                isinstance(val, (list, tuple)) and len(val) >= 2 and val[0] == "__m2m__"
            ):
                continue
            pair = reassignments.get(verbose_name)
            if pair is not None:
                result[verbose_name] = [pair[0], pair[1]]

    # Remove bogus entries that are M2M keys shown as "type" -> "operation"
    for key in list(result):
        val = result[key]
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            if val[0] == "type" and val[1] == "operation":
                del result[key]

    # Drop auto-managed bookkeeping fields (when and by whom the row was last
    # saved) - the entry's own time and actor already say that, so they're
    # just noise alongside the real field edit. Matched by field name: the
    # keys are verbose names in the active language ("Updated At" in English,
    # "به‌روزرسانی شده در" in Persian), so a label match only works in English.
    if model:
        for field_name in _BOOKKEEPING_FIELD_NAMES:
            if field_name not in changes_dict:
                continue
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            result.pop(str(getattr(field, "verbose_name", field_name)), None)

    # auditlog stores an empty value as the string "None" (a null ForeignKey,
    # an unset nullable field, ...). Blank it so the template shows its usual
    # "--" placeholder instead of the literal word.
    for key, val in result.items():
        if isinstance(val, (list, tuple)) and len(val) >= 2 and val[0] != "__m2m__":
            result[key] = ["" if v == "None" else v for v in val]

    # Drop fields whose "change" isn't real - e.g. a Decimal re-saved with
    # different precision ("40199.14" -> "40199.1400000000") or "0.00" vs "0".
    # Only the display string differs; the field didn't actually change.
    for key in list(result):
        val = result[key]
        if not (
            isinstance(val, (list, tuple)) and len(val) >= 2 and val[0] != "__m2m__"
        ):
            continue
        if _values_equal(val[0], val[1]):
            del result[key]

    return result


_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def _values_equal(old, new):
    """
    True if `old` and `new` represent the same value despite differing string
    formatting - e.g. Decimal re-quantization ("40199.14" vs "40199.1400000000")
    or "0.00" vs "0", or a rich-text (HTML) field whose markup was
    re-serialized by the editor widget (attribute order, quoting, entity
    encoding, ...) without the visible text actually changing. Used to drop
    no-op diffs from history so a field only shows as changed when it
    actually changed. Falls back to plain string equality for anything that
    isn't numeric or HTML.
    """
    if old == new:
        return True
    old_text = str(old).strip()
    new_text = str(new).strip()
    if old_text == new_text:
        return True
    try:
        from decimal import Decimal, InvalidOperation

        return Decimal(old_text) == Decimal(new_text)
    except (InvalidOperation, ValueError, TypeError):
        pass
    if _HTML_TAG_RE.search(old_text) or _HTML_TAG_RE.search(new_text):
        return html_to_text(old_text) == html_to_text(new_text)
    return False


# Django field classes (by name) whose values are actual date/datetime/time
# instances, as opposed to e.g. DecimalField/IntegerField which just happen to
# render as plain numeric strings.
_DATE_LIKE_FIELD_TYPES = ("DateTimeField", "DateField", "TimeField")


@register.filter
def is_date_field(entry, field_label):
    """
    True if `field_label` (the verbose/display name used as a history_changes_display
    key) corresponds to an actual Date/DateTime/Time field on the entry's model.

    Used to gate the dateutil-based re-parsing fallback in
    user_datetime_format_display so it only ever runs on real date fields,
    never on plain numeric fields (probability, amount, quantity, ...) whose
    string values a fuzzy date parser could otherwise misread as a date.
    """
    if entry is None or not field_label:
        return False
    try:
        model = entry.content_type.model_class()
    except Exception:
        return False
    if model is None:
        return False
    label = str(field_label).strip().lower()
    for field in model._meta.get_fields():
        verbose_name = str(getattr(field, "verbose_name", "") or "").strip().lower()
        name = getattr(field, "name", "").replace("_", " ").strip().lower()
        if label in (verbose_name, name):
            return type(field).__name__ in _DATE_LIKE_FIELD_TYPES
    return False


@register.filter
def related_entry_subject(entry, primary_model_name):
    """
    For a history entry that belongs to a DIFFERENT model than the page's own
    record (e.g. viewing a Lead's History tab, but this entry is one of its
    related Tasks/Activities), return a short subject label like "Task Test
    edited" so the row doesn't read as if it were the primary record's own
    field changing. Only used for update entries (the create case has its own
    "New {Model} created" label), so "edited" always applies here. Returns ""
    when the entry IS the primary record's own history (no qualifier needed)
    or the model/label can't be determined. Generic: works for any model
    pairing, no model names hardcoded.
    """
    if entry is None:
        return ""
    try:
        ct = getattr(entry, "content_type", None)
        if ct is None:
            return ""
        if primary_model_name and ct.model == primary_model_name:
            return ""
        verbose_name = content_type_verbose_name(ct)
        obj = _get_related_object_from_entry(entry)
        if obj is not None:
            obj_label = str(obj)
            if obj_label:
                return _("%(model)s %(label)s edited") % {
                    "model": verbose_name,
                    "label": obj_label,
                }
        return _("%(model)s edited") % {"model": verbose_name}
    except Exception:
        return ""


def _get_history_create_type_field(model):
    """
    Return the name of the model's own "kind/type" discriminator field for history
    display, if it declares one via `HISTORY_CREATE_TYPE_FIELD` (e.g. Activity sets
    this to "activity_type" since one Activity model represents Task/Event/Meeting/
    Log Call). Generic: works for any model that opts in this way; no model names
    or field names are hardcoded here.
    """
    if model is None:
        return None
    field_name = getattr(model, "HISTORY_CREATE_TYPE_FIELD", None)
    if not field_name:
        return None
    try:
        model._meta.get_field(field_name)
    except FieldDoesNotExist:
        return None
    return field_name


def _created_choice_display(entry, model, field_name):
    """
    Return the human-readable value `field_name` had when this CREATE entry
    was logged, read from the entry's own change snapshot, or "" if it wasn't
    recorded. Reading the live row instead would show today's value - a task
    created "In Progress" and completed since would read "Status: Completed"
    on its creation row.
    """
    changes = getattr(entry, "changes_dict", None) or {}
    values = changes.get(field_name)
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        return ""
    value = values[1]
    if value in (None, "", "None"):
        return ""
    try:
        field = model._meta.get_field(field_name)
    except FieldDoesNotExist:
        return ""
    return str(dict(field.flatchoices).get(value, value))


def _get_related_object_from_entry(entry):
    """Return the model instance a log entry refers to, or None."""
    if entry is None:
        return None
    try:
        ct = getattr(entry, "content_type", None)
        if ct is None:
            return None
        model = ct.model_class()
        if model is None:
            return None
        object_pk = getattr(entry, "object_pk", None) or getattr(
            entry, "object_id", None
        )
        if object_pk is None:
            return None
        return model.objects.filter(pk=object_pk).first()
    except Exception:
        return None


@register.filter
def create_type_display(entry):
    """
    For a CREATE log entry whose model declares HISTORY_CREATE_TYPE_FIELD (a
    choices field naming what "kind" of record this is, e.g. Activity's
    activity_type), return a phrase like "New Task created" using that
    field's display value at creation time - matching the generic "New
    {Model} created" badge's wording. Generic: derives the label from the
    model's own field choices, not a hardcoded per-model/per-value mapping.
    Returns empty string when the model doesn't opt in, the entry isn't a
    create, or the creation snapshot has no value for the field.
    """
    if entry is None:
        return ""
    try:
        if getattr(entry, "action", None) != LogEntry.Action.CREATE:
            return ""
    except Exception:
        return ""
    try:
        ct = getattr(entry, "content_type", None)
        model = ct.model_class() if ct else None
    except Exception:
        model = None
    field_name = _get_history_create_type_field(model)
    if not field_name:
        return ""
    type_label = _created_choice_display(entry, model, field_name)
    if not type_label:
        return ""
    return str(_("New %(type)s created") % {"type": type_label})


def _entry_kind(entry):
    """
    Classify a history entry by its actual auditlog action, matching the two
    branches history_tab.html renders (CREATE, everything else). Generic: no
    model names or string-matching on LogEntry.__str__().
    """
    action = getattr(entry, "action", None)
    if action == LogEntry.Action.CREATE:
        return "created"
    if action == LogEntry.Action.UPDATE:
        return "edit"
    return "other"


@register.filter
def history_day_tags(entries):
    """
    Summarize a day's entries into small tag chips (e.g. "2 edits") for the
    collapsed accordion header. Always ordered created, edit, other
    regardless of which kind of entry happened most recently that day. Each
    tag carries its `kind` ("edit"/"created"/"other") so the template can
    give "edit" and "created" distinct, theme-accent-derived colors (matching
    the per-entry subject badges) while "other" stays the neutral grey
    fallback.
    """
    if not entries:
        return []
    counts = {}
    for entry in entries:
        kind = _entry_kind(entry)
        counts[kind] = counts.get(kind, 0) + 1

    labels = {
        "edit": (_("Edit"), _("Edits")),
        "created": (_("Created"), _("Created")),
        "other": (_("Event"), _("Events")),
    }
    tags = []
    for kind in ("created", "edit", "other"):
        if kind not in counts:
            continue
        count = counts[kind]
        singular, plural = labels[kind]
        label = f"{count} {singular if count == 1 else plural}"
        tags.append({"label": label, "kind": kind})
    return tags


@register.filter
def create_status_display(entry, primary_model_name=None):
    """
    For a CREATE log entry belonging to a RELATED object (not the page's own
    record - see related_entry_subject), whose model has a `status` choices
    field, return its human-readable value at creation time so the create
    row can show e.g. "Status: Not Started" - not the record's current
    status. Generic: works for any model with a `status` field.

    When the entry IS the page's own record being created (e.g. viewing this
    Task's own History tab), this returns "" - the current status is already
    shown in the page header, so repeating it in the create row is redundant.
    Returns "" when there is none, the entry isn't a create, or it's the
    page's own record.
    """
    if entry is None:
        return ""
    try:
        if getattr(entry, "action", None) != LogEntry.Action.CREATE:
            return ""
    except Exception:
        return ""
    try:
        ct = getattr(entry, "content_type", None)
        if ct is None:
            return ""
        if primary_model_name and ct.model == primary_model_name:
            return ""
        model = ct.model_class()
    except Exception:
        return ""
    if model is None:
        return ""
    return _created_choice_display(entry, model, "status")


@register.filter
def create_extra_changes(entry, primary_model_name=None):
    """
    For a CREATE log entry belonging to a RELATED object (not the page's own
    record - see related_entry_subject), return its field changes (same shape
    as history_changes_display) MINUS the fields already surfaced via
    create_type_display/create_status_display (the model's HISTORY_CREATE_TYPE_FIELD
    and its `status` field, if any), so the create row can show every other field
    that was set at creation (subject, due date, priority, ...) without repeating
    the type/status badges.

    When the entry IS the page's own record being created (e.g. viewing an
    Opportunity's own History tab and this is the Opportunity's own creation),
    this returns {} - the user is already looking at all of that record's
    fields on the page itself, so dumping every field into the history row
    would just repeat what's already visible. Generic: works for any model,
    no field names hardcoded beyond the same "status" convention
    create_status_display already relies on.
    """
    if entry is None:
        return {}
    try:
        if getattr(entry, "action", None) != LogEntry.Action.CREATE:
            return {}
    except Exception:
        return {}
    try:
        ct = getattr(entry, "content_type", None)
        if ct is not None and primary_model_name and ct.model == primary_model_name:
            return {}
    except Exception:
        pass
    changes = history_changes_display(entry)
    if not changes:
        return {}
    try:
        ct = getattr(entry, "content_type", None)
        model = ct.model_class() if ct else None
    except Exception:
        model = None

    skip_field_names = {"status", "id", "pk"}
    type_field = _get_history_create_type_field(model)
    if type_field:
        skip_field_names.add(type_field)
    try:
        from horilla.contrib.core.models import HorillaCoreModel

        skip_field_names.update(HorillaCoreModel.field_permissions_exclude)
    except Exception:
        pass
    if model:
        try:
            for field in model._meta.private_fields:
                if type(field).__name__ == "GenericForeignKey":
                    skip_field_names.add(field.name)
                    skip_field_names.add(field.ct_field)
                    skip_field_names.add(field.fk_field)
        except Exception:
            pass

    skip_verbose_names = set()
    if model:
        for field_name in skip_field_names:
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            verbose_name = getattr(field, "verbose_name", field_name)
            skip_verbose_names.add(str(verbose_name).lower())
            skip_verbose_names.add(field_name.replace("_", " ").lower())

    def _is_empty(value):
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return False
        if value[0] == "__m2m__":
            return not value[3]
        new_value = value[1]
        if new_value is None:
            return True
        text = str(new_value).strip()
        return text in ("", "None", "null", "[]", "{}", "False")

    result = {}
    for key, value in changes.items():
        if str(key).lower() in skip_verbose_names:
            continue
        if _is_empty(value):
            continue
        result[key] = value
    return result

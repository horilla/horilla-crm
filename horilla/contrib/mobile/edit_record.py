"""
Edit a record's fields on the phone, as Edit Details does on the desktop.

The fields are the desktop Details tab body (``get_effective_body``, so the
user's own choice on the desktop detail page), without the fields the user may
not change (a field permission other than ``readwrite``, the section view's
``non_editable_fields``), then the custom fields. Who may edit is the desktop
rule (``can_edit_all_fields``), and the values are saved by the desktop's own
Edit Details save (``save_all_fields``), with its checks and extensions.
"""

# Third-party imports (Django)
from django.contrib import messages

from horilla.contrib.core.utils import get_field_permissions_for_model
from horilla.contrib.generics.forms.generics import PHONE_COUNTRY_CODES, PhoneWidget
from horilla.contrib.generics.history import is_record_locked
from horilla.contrib.generics.views.helpers.edit_field import (
    get_extra_fields_provider,
    get_field_info_resolver,
    get_update_all_fields_view,
    save_all_fields,
)
from horilla.contrib.utils.middlewares import get_active_company

# First party imports (Horilla)
from horilla.core.exceptions import FieldDoesNotExist
from horilla.db import models
from horilla.shortcuts import redirect
from horilla.urls import reverse
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView

# Local imports
from .access import can_open
from .desktop import DesktopLayout
from .log_activity import LIST_SEPARATOR, unavailable_page
from .records import record_url
from .registry import get_mobile_config
from .views import MobilePageMixin

BOOLEAN_LABELS = {"True": _("Yes"), "False": _("No")}


def phone_codes(request, obj):
    """
    Country codes of the phone number inputs: the desktop list, with the code
    of the record's company country (or the active company's) moved to the
    top. The phone's list has no search box, unlike the desktop one.
    """
    company = getattr(obj, "company", None) or get_active_company(request)
    region = getattr(getattr(company, "country", None), "code", "")
    if not region:
        return PHONE_COUNTRY_CODES
    try:
        import phonenumbers

        own = f"+{phonenumbers.country_code_for_region(region)}"
    except ImportError:
        return PHONE_COUNTRY_CODES
    first = [entry for entry in PHONE_COUNTRY_CODES if entry[0] == own]
    rest = [entry for entry in PHONE_COUNTRY_CODES[1:] if entry[0] != own]
    return PHONE_COUNTRY_CODES[:1] + first + rest


def _is_required(field):
    """Whether model ``field`` must keep a value (custom fields: ``field`` is None)."""
    if field is None:
        return False
    if isinstance(field, models.BooleanField):
        return not field.null
    return not field.blank


def _select_options(field, info, required):
    """
    Options of a plain select. A stored value its choices don't list stays
    selectable, so saving other fields never changes it; a required field
    that has a value offers no empty choice.
    """
    current = "" if info["value"] is None else str(info["value"])
    labels = BOOLEAN_LABELS if isinstance(field, models.BooleanField) else {}
    options = []
    for choice in info["choices"]:
        value = str(choice["value"])
        options.append({"value": value, "label": labels.get(value, choice["label"])})
    if current not in {option["value"] for option in options}:
        options.insert(0, {"value": current, "label": info["display_value"] or ""})
    if required and current:
        options = [option for option in options if option["value"] != ""]
    for option in options:
        option["selected"] = option["value"] == current
    return options


def phone_input(field, info, error=""):
    """
    What the phone form shows for one desktop ``field_info``: a related
    record picker, a select, check boxes, a phone number, a text area or an
    input. ``field`` is the model field, or None for a custom field.
    """
    name = info["name"]
    kind = info["field_type"]
    required = _is_required(field)
    item = {"name": name, "label": info["verbose_name"], "error": error}
    if kind == "select" and info.get("use_select2"):
        multiple = bool(info.get("multiple"))
        item.update(
            kind="related",
            multiple=multiple,
            optional=not required,
            post_name=f"{name}[]" if multiple else name,
            # A record whose name is blank (e.g. a user without one) still shows.
            selected=[
                {
                    "value": choice["value"],
                    "label": str(choice["label"]).strip() or f"#{choice['value']}",
                }
                for choice in info["choices"]
                if choice["value"] not in ("", None)
            ],
            url=reverse(
                "generics:model_select2",
                kwargs={
                    "app_label": info["related_app_label"],
                    "model_name": info["related_model_name"],
                },
            ),
        )
    elif kind == "select" and info.get("multiple"):
        checked = {str(value) for value in info["value"] or []}
        item.update(
            kind="checks",
            options=[
                {
                    "value": choice["value"],
                    "label": choice["label"],
                    "checked": str(choice["value"]) in checked,
                }
                for choice in info["choices"]
            ],
        )
    elif kind == "select":
        item.update(kind="select", options=_select_options(field, info, required))
    elif kind == "phone":
        code, number = PhoneWidget().decompress(info["value"] or "")
        item.update(kind="phone", code=code, number=number)
    elif kind == "textarea":
        item.update(kind="textarea", value=info["value"] or "")
    else:
        value = info["value"]
        item.update(
            kind="input",
            input_type=kind,
            value="" if value is None else value,
            step=info.get("step", ""),
            maxlength=(
                field.max_length if isinstance(field, models.CharField) else None
            ),
            attrs=info.get("input_attrs") or {},
        )
    return item


def _keep_typed(item, data):
    """Show what was typed in a field whose value couldn't be applied, to correct it."""
    name = item["name"]
    if item["kind"] == "phone":
        item["code"] = data.get(f"{name}_0", item["code"])
        item["number"] = data.get(f"{name}_1", item["number"])
    elif item["kind"] in ("input", "textarea") and name in data:
        item["value"] = data[name]


def editable_fields(request, obj, section_view, hooks, errors=None):
    """
    The inputs of the phone form for ``obj``: the Details tab body without
    the fields the user may not change (field permissions,
    ``non_editable_fields``, and what ``hooks.get_allowed_fields`` leaves
    out, e.g. under a pending approval), then the custom fields they may
    change. ``errors`` maps a field name to the message shown under it.
    """
    errors = errors or {}
    user = request.user
    model = obj.__class__
    permissions = get_field_permissions_for_model(user, model)
    non_editable = set(section_view.non_editable_fields)
    allowed = hooks.get_allowed_fields(request, obj)
    resolver = get_field_info_resolver()
    infos = []
    for _label, name in section_view.get_effective_body():
        if name in non_editable or permissions.get(name, "readwrite") != "readwrite":
            continue
        if allowed is not None and name not in allowed:
            continue
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if not getattr(field, "editable", False) or field.auto_created:
            continue
        infos.append((field, resolver.get_field_info(field, obj, user)))
    for entry in get_extra_fields_provider().get_extra_fields(obj, request, True):
        if entry["editable"]:
            infos.append((None, entry["info"]))
    inputs = []
    for field, info in infos:
        item = phone_input(field, info, errors.get(info["name"], ""))
        if item["error"]:
            _keep_typed(item, request.POST)
        inputs.append(item)
    return inputs


class MobileEditRecordView(MobilePageMixin, TemplateView):
    """Edit details: the record's fields the user may change, saved like the desktop."""

    template_name = "mobile/edit_record.html"

    def load_record(self):
        """Set up the record, or return a phone page saying why it can't be edited."""
        request = self.request
        config = get_mobile_config(self.kwargs["app_label"], self.kwargs["model_name"])
        obj = None
        if config is not None:
            obj = config.model.objects.filter(pk=self.kwargs["pk"]).first()
        if obj is None:
            return unavailable_page(
                request, _("This record doesn't exist or was deleted."), 404
            )
        if not can_open(request.user, obj):
            return unavailable_page(
                request, _("You don't have permission to view this record."), 403
            )
        if is_record_locked(obj):
            return unavailable_page(request, _("This record is read-only."), 403)
        layout = DesktopLayout(request, obj, config)
        if not layout.can_edit_fields():
            return unavailable_page(
                request, _("You don't have permission to edit this record."), 403
            )
        self.object = obj
        self.config = config
        self.layout = layout
        # The desktop Edit Details hooks, with their extensions.
        self.hooks = get_update_all_fields_view()
        return None

    def get(self, request, *args, **kwargs):
        """Show the form."""
        return self.load_record() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Save through the desktop Edit Details save, then go back to the record."""
        refused = self.load_record()
        if refused:
            return refused
        obj = self.object
        result = save_all_fields(request, obj, self.layout.section_view, self.hooks)
        if result.ok:
            if result.changed_fields:
                messages.success(request, _("Changes saved."))
            return redirect(record_url(obj))
        return self.render_to_response(self.get_context_data(result=result))

    def get_context_data(self, result=None, **kwargs):
        """The inputs, and why the last save didn't go through."""
        context = super().get_context_data(**kwargs)
        obj = self.object
        stopped = result is not None and (
            result.response is not None or result.save_error is not None
        )
        notes = []
        if stopped:
            # A desktop check stopped the save, or answered it its own way
            # (with desktop markup): show its reason here, with any message
            # it left, and point to the full version.
            if result.save_error is not None:
                notes.extend(str(message) for message in result.save_error.messages)
            notes.extend(
                str(message) for message in messages.get_messages(self.request)
            )
        context.update(
            {
                "obj": obj,
                "config": self.config,
                "fields": editable_fields(
                    self.request,
                    obj,
                    self.layout.section_view,
                    self.hooks,
                    result.errors if result is not None else None,
                ),
                "not_saved": stopped,
                "not_saved_messages": notes,
                "record_url": record_url(obj),
                "desktop_url": self.layout.detail_path,
                "phone_codes": phone_codes(self.request, obj),
                "list_separator": LIST_SEPARATOR,
            }
        )
        return context

"""
Bulk edit-field views for horilla.contrib.generics.

HTMX views backing the "Edit Details" bulk-edit toggle on the details tab:
resolving per-field editable widgets and saving all of a record's editable
fields from a single form submission.
"""

# Standard library imports
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# Third-party imports (Django)
from django.contrib import messages
from django.core.exceptions import ValidationError

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.history import is_record_locked
from horilla.contrib.generics.templatetags.horilla_tags._shared import (
    format_datetime_value,
)
from horilla.db import models
from horilla.extension.view.resolve import resolve_view_class
from horilla.shortcuts import get_object_or_404, render
from horilla.utils import timezone
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import ScriptResponse


class FieldInfoResolver(View):
    """
    Resolve editable-widget metadata and apply submitted values for a model field.

    Subclasses ``View`` (never dispatched via ``as_view()`` — always
    instantiated directly through :func:`get_field_info_resolver`) purely so
    ``_inherit_view`` composition is eligible: ``compose_view_class`` requires
    a real Django ``View`` subclass, and this is the resolvable seam
    per-field-type extensions (e.g. Jalali date parsing) target.

    Shared by :class:`EditAllFieldsView` (rendering) and
    :class:`UpdateAllFieldsView` (saving) so both use identical field-type
    handling.
    """

    def _is_phone_field(self, field):
        """Check if a CharField should render with country-code phone selection."""
        from horilla.contrib.generics.forms.form_class_mixin import HorillaFormMixin

        return field.name in HorillaFormMixin._DEFAULT_PHONE_FIELD_NAMES

    def _is_state_field(self, field, obj):
        """Check if a CharField is the model's declared state/subdivision field.

        Models with a non-default field name (e.g. Contact's ``address_state``)
        declare it via ``STATE_FIELD_NAME = "address_state"``; defaults to
        ``"state"`` when not declared.
        """
        state_field_name = getattr(obj.__class__, "STATE_FIELD_NAME", "state")
        return field.name == state_field_name

    def _get_country_field_value(self, obj):
        """Return the ISO country code from the model's declared country field.

        Models with a non-default field name (e.g. Contact's
        ``address_country``) declare it via
        ``COUNTRY_FIELD_NAME = "address_country"``; defaults to ``"country"``
        when not declared.
        """
        country_field_name = getattr(obj.__class__, "COUNTRY_FIELD_NAME", "country")
        country_value = getattr(obj, country_field_name, None)
        if not country_value:
            return None
        code = getattr(country_value, "code", country_value)
        return str(code) if code else None

    def get_field_info(self, field, obj, user=None):
        """Get field information including type, choices, and current value"""
        field_info = {
            "name": field.name,
            "verbose_name": field.verbose_name,
            "field_type": "text",  # default
            "value": getattr(obj, field.name, ""),
            "choices": [],
            "display_value": str(getattr(obj, field.name, "")),
            "use_select2": False,  # Default to False
            "input_attrs": {},
        }

        if isinstance(field, models.ManyToManyField):
            field_info["field_type"] = "select"
            field_info["multiple"] = True
            field_info["use_select2"] = True

            related_model = field.related_model
            field_info["related_app_label"] = related_model._meta.app_label
            field_info["related_model_name"] = related_model._meta.model_name

            # Get current values
            current_values = getattr(obj, field.name).values_list("pk", flat=True)
            field_info["value"] = list(current_values) if current_values else []

            # Get initial choices for selected items only
            field_info["choices"] = []
            if current_values:
                selected_objects = related_model.objects.filter(pk__in=current_values)
                field_info["choices"] = [
                    {"value": obj.pk, "label": str(obj)} for obj in selected_objects
                ]

            field_info["display_value"] = (
                ", ".join(str(item) for item in getattr(obj, field.name).all())
                if getattr(obj, field.name).exists()
                else ""
            )

        elif isinstance(field, models.ForeignKey):
            field_info["field_type"] = "select"
            field_info["use_select2"] = True

            related_model = field.related_model
            field_info["related_app_label"] = related_model._meta.app_label
            field_info["related_model_name"] = related_model._meta.model_name

            # Get current value
            current_obj = getattr(obj, field.name)
            field_info["value"] = current_obj.pk if current_obj else ""

            # Get initial choices - only the selected item if exists
            field_info["choices"] = [{"value": "", "label": "---------"}]
            if current_obj:
                field_info["choices"].append(
                    {"value": current_obj.pk, "label": str(current_obj)}
                )

            field_info["display_value"] = str(current_obj) if current_obj else ""

        elif hasattr(field, "choices") and field.choices:
            field_info["field_type"] = "select"
            field_info["choices"] = [{"value": "", "label": "---------"}]
            field_info["choices"].extend(
                [{"value": choice[0], "label": choice[1]} for choice in field.choices]
            )
            field_info["display_value"] = getattr(obj, f"get_{field.name}_display")()

        elif isinstance(field, models.BooleanField):
            field_info["field_type"] = "select"
            field_info["choices"] = [
                {"value": "", "label": "---------"},
                {"value": "True", "label": "Yes"},
                {"value": "False", "label": "No"},
            ]
            current_value = getattr(obj, field.name)
            field_info["value"] = (
                str(current_value) if current_value is not None else ""
            )
            field_info["display_value"] = (
                "Yes" if current_value else "No" if current_value is False else ""
            )

        elif isinstance(field, models.CharField) and self._is_state_field(field, obj):
            from horilla.utils.choices import (
                get_subdivision_choices,
                resolve_subdivision_choice,
            )

            country_code = self._get_country_field_value(obj)
            current_value = getattr(obj, field.name, "")
            if country_code:
                choices = get_subdivision_choices(country_code)
                field_info["field_type"] = "select"
                field_info["choices"] = [
                    {"value": code, "label": label} for code, label in choices
                ]
                resolved = resolve_subdivision_choice(choices, current_value)
                field_info["value"] = resolved
                field_info["display_value"] = dict(choices).get(resolved, current_value)
            else:
                field_info["display_value"] = current_value

        elif isinstance(field, models.CharField) and self._is_phone_field(field):
            field_info["field_type"] = "phone"
            from horilla.contrib.generics.forms.generics import PhoneWidget

            field_info["phone_widget_html"] = PhoneWidget().render(
                field.name, field_info["value"] or ""
            )

        elif isinstance(field, models.EmailField):
            field_info["field_type"] = "email"

        elif isinstance(field, models.URLField):
            field_info["field_type"] = "url"

        elif isinstance(
            field,
            (models.IntegerField, models.BigIntegerField, models.SmallIntegerField),
        ):
            field_info["field_type"] = "number"

        elif isinstance(field, (models.DecimalField, models.FloatField)):
            field_info["field_type"] = "number"
            field_info["step"] = "0.01"

        elif isinstance(field, models.DateTimeField):
            field_info["field_type"] = "datetime-local"
            if field_info["value"]:
                dt_value = field_info["value"]

                # Convert to user's timezone if available
                if user and hasattr(user, "time_zone") and user.time_zone:
                    try:
                        user_tz = ZoneInfo(user.time_zone)
                        # Make aware if naive
                        if timezone.is_naive(dt_value):
                            dt_value = timezone.make_aware(
                                dt_value, timezone.get_default_timezone()
                            )
                        # Convert to user timezone
                        dt_value = dt_value.astimezone(user_tz)
                    except Exception:
                        pass

                # Format for datetime-local input (without timezone info)
                field_info["value"] = dt_value.strftime("%Y-%m-%dT%H:%M")

                # Display via composed DateTimeFormatter (Jalali when extended)
                field_info["display_value"] = format_datetime_value(
                    dt_value, user=user, convert_timezone=False
                )

        elif isinstance(field, models.DateField):
            field_info["field_type"] = "date"
            if field_info["value"]:
                date_value = field_info["value"]
                field_info["value"] = date_value.strftime("%Y-%m-%d")

                # Display via composed DateTimeFormatter (Jalali when extended)
                field_info["display_value"] = format_datetime_value(
                    date_value, user=user, convert_timezone=False
                )

        elif isinstance(field, models.TextField):
            field_info["field_type"] = "textarea"

        return field_info

    def parse_datetime_field_value(self, value, user=None):
        """Parse a datetime-local / datetime string for storage (Gregorian by default)."""
        return datetime.fromisoformat(value)

    def parse_date_field_value(self, value, user=None):
        """Parse a date string for storage (Gregorian by default)."""
        return datetime.fromisoformat(value).date()

    def apply_field_value(self, obj, field, field_name, request, save=True):
        """
        Parse, validate and, by default, save a single field's submitted value onto ``obj``.

        Returns ``None`` on success, or an error message string on validation
        failure (leaving ``obj`` unsaved for that field in the failure case).

        When ``save=False``, scalar/phone field values are only ``setattr``'d
        in-memory — the caller is responsible for calling ``obj.save()``
        afterwards. Many-to-many values are always applied immediately
        (a separate-table write with no in-memory equivalent), regardless of
        ``save``.
        """
        if isinstance(field, models.ManyToManyField):
            values = request.POST.getlist(f"{field_name}[]")  # Get list of selected IDs
            try:
                # Clear existing relationships and set new ones
                related_manager = getattr(obj, field_name)
                related_manager.clear()
                if values and values != [""]:  # Only add if there are selected values
                    related_manager.add(*values)
            except Exception as e:
                return _("Error updating field: %(message)s") % {"message": str(e)}
        elif isinstance(field, models.CharField) and self._is_phone_field(field):
            from horilla.contrib.generics.forms.generics import PhoneField

            code = request.POST.get(f"{field_name}_0", "")
            number = request.POST.get(f"{field_name}_1", "")
            try:
                setattr(obj, field_name, PhoneField().compress([code, number]))
            except ValidationError as e:
                return " ".join(str(msg) for msg in e.messages)
            if save:
                obj.save()
        else:
            value = request.POST.get(field_name)

            if value is not None:
                try:
                    # Handle different field types
                    if isinstance(field, models.ForeignKey):
                        if value == "":
                            setattr(obj, field_name, None)
                        else:
                            related_obj = field.related_model.objects.get(pk=value)
                            setattr(obj, field_name, related_obj)

                    elif isinstance(field, models.BooleanField):
                        if value == "":
                            setattr(obj, field_name, None)
                        else:
                            setattr(obj, field_name, value == "True")

                    elif isinstance(
                        field,
                        (
                            models.IntegerField,
                            models.BigIntegerField,
                            models.SmallIntegerField,
                        ),
                    ):
                        setattr(obj, field_name, int(value) if value else None)

                    elif isinstance(field, models.DecimalField):
                        if value:
                            try:
                                setattr(obj, field_name, Decimal(value))
                            except InvalidOperation:
                                return _("Invalid decimal value: %(value)s") % {
                                    "value": value
                                }
                        else:
                            setattr(obj, field_name, None)

                    elif isinstance(field, models.FloatField):
                        setattr(obj, field_name, float(value) if value else None)

                    elif isinstance(field, models.DateTimeField):
                        if value:
                            try:
                                parsed_value = self.parse_datetime_field_value(
                                    value, request.user
                                )
                                if parsed_value is None:
                                    raise ValueError(value)

                                # Get user's timezone
                                user = request.user
                                if hasattr(user, "time_zone") and user.time_zone:
                                    try:
                                        # Convert to UTC or default timezone for storage
                                        user_tz = ZoneInfo(user.time_zone)
                                        # Make the parsed datetime aware in user's timezone
                                        if timezone.is_naive(parsed_value):
                                            parsed_value = parsed_value.replace(
                                                tzinfo=user_tz
                                            )
                                        else:
                                            parsed_value = parsed_value.astimezone(
                                                user_tz
                                            )
                                        parsed_value = parsed_value.astimezone(
                                            timezone.get_default_timezone()
                                        )
                                    except Exception:
                                        # Fallback: make aware with default timezone
                                        if timezone.is_naive(parsed_value):
                                            parsed_value = timezone.make_aware(
                                                parsed_value,
                                                timezone.get_default_timezone(),
                                            )
                                else:
                                    # No user timezone, use default
                                    if timezone.is_naive(parsed_value):
                                        parsed_value = timezone.make_aware(
                                            parsed_value,
                                            timezone.get_default_timezone(),
                                        )

                                setattr(obj, field_name, parsed_value)
                            except ValueError:
                                return _("Invalid datetime format: %(value)s") % {
                                    "value": value
                                }
                        else:
                            setattr(obj, field_name, None)

                    elif isinstance(field, models.DateField):
                        if value:
                            try:
                                parsed_value = self.parse_date_field_value(
                                    value, request.user
                                )
                                if parsed_value is None:
                                    raise ValueError(value)
                                setattr(obj, field_name, parsed_value)
                            except ValueError:
                                return _("Invalid date format: %(value)s") % {
                                    "value": value
                                }
                        else:
                            setattr(obj, field_name, None)

                    else:
                        setattr(obj, field_name, value)

                    if save:
                        obj.save()

                except ValidationError as e:
                    error_messages = (
                        e.message_dict.get(field_name)
                        if hasattr(e, "message_dict")
                        else e.messages
                    )
                    return " ".join(str(msg) for msg in (error_messages or e.messages))
                except Exception as e:
                    return _("Error updating field: %(message)s") % {"message": str(e)}

        return None


def get_field_info_resolver():
    """Return a FieldInfoResolver instance with ``_inherit_mixin`` extensions applied."""
    return resolve_view_class(FieldInfoResolver)()


def _get_section_view_instance(model, request, pk):
    """
    Build a working ``HorillaDetailSectionView`` (sub)class instance for ``model``.

    Looks up the concrete per-model subclass registered via
    ``HorillaDetailSectionView._view_registry`` (the same registry
    ``detail_field.py`` uses to resolve a model's details section), so
    ``include_fields``/``excluded_fields``/``non_editable_fields``/``edit_field``
    and any ``_inherit_detail_section`` extensions are honored exactly as the
    Details tab itself would. Falls back to the base class if a model has no
    registered subclass.
    """
    from horilla.contrib.generics.views.detail_tabs import HorillaDetailSectionView
    from horilla.extension.detail_section.resolve import (
        resolve_detail_section_view_class,
    )

    section_cls = HorillaDetailSectionView._view_registry.get(
        model, HorillaDetailSectionView
    )
    section_cls = resolve_detail_section_view_class(section_cls)

    view = section_cls()
    view.request = request
    view.model = model
    view.kwargs = {"pk": pk}
    return view


def can_edit_all_fields(request, obj):
    """
    Whether ``request.user`` may use Edit Details on ``obj``.

    The record page's own rule, the one its Edit Details button and stage bar
    follow: :meth:`HorillaDetailView.check_update_permission` (an owner with
    ``change_own_<model>``, or anyone with ``change_<model>``; never a
    locked record).
    """
    from horilla.contrib.generics.views.details import HorillaDetailView

    section_view = _get_section_view_instance(obj.__class__, request, obj.pk)
    return HorillaDetailView.check_update_permission(section_view)


class ExtraFieldsProvider(View):
    """
    Extension seam for non-model fields in the bulk "Edit Details" form.

    ``EditAllFieldsView``/``UpdateAllFieldsView`` only know about real model
    fields (``obj._meta.get_fields()``). Anything else that should appear in
    the bulk-edit grid — custom (``cf_*``) fields, for instance — is added by
    an ``_inherit_view`` extension overriding these two methods (resolved via
    :func:`get_extra_fields_provider`, the same late-binding pattern as
    :class:`FieldInfoResolver`). The no-op defaults here mean "nothing extra
    to add." Subclasses ``View`` for the same reason as ``FieldInfoResolver``
    — never dispatched via ``as_view()``, only so ``_inherit_view``
    composition is eligible.
    """

    def get_extra_fields(self, obj, request, can_update):
        """
        Return additional ``{"info": field_info, "editable": bool}`` entries
        to append to the bulk-edit field list for ``obj``.

        ``field_info`` must have the same shape :meth:`FieldInfoResolver.get_field_info`
        produces (``name``, ``verbose_name``, ``field_type``, ``value``,
        ``choices``, ``display_value``, ``use_select2``, ``input_attrs``,
        plus any field-type-specific keys the template branch needs).
        """
        return []

    def apply_extra_field(self, obj, name, request):
        """
        Apply one non-model field's submitted value for ``name``.

        Called by ``UpdateAllFieldsView.post`` for each POSTed key that
        doesn't match a real model field name. Return ``True`` if ``name``
        was recognized and handled (whether or not it actually needed
        saving), ``False`` to let the caller ignore it. Extensions that save
        immediately (rather than deferring to the record's own ``obj.save()``)
        should do so here — there's no in-memory-only equivalent for a
        separate-table value.
        """
        return False


def get_extra_fields_provider():
    """Return an ExtraFieldsProvider instance with ``_inherit_view`` extensions applied."""
    return resolve_view_class(ExtraFieldsProvider)()


def build_edit_all_fields_context(
    request, obj, app_label, model_name, pipeline_field=None, cancel_url=""
):
    """
    Build the ``partials/edit_all_fields.html`` context for ``obj``.

    Shared by :meth:`EditAllFieldsView.get` (fresh object from the DB) and
    any ``_inherit_view`` extension that needs to re-render the bulk-edit
    form with in-memory, not-yet-saved values still on ``obj`` (e.g. a
    duplicate-check hook that blocks a save and wants the form to reappear
    exactly as the user submitted it).
    """
    model = obj.__class__
    section_view = _get_section_view_instance(model, request, obj.pk)
    section_view.object = obj
    body = section_view.get_effective_body()

    from horilla.contrib.core.utils import get_field_permissions_for_model
    from horilla.contrib.generics.views.details import HorillaDetailView

    field_permissions = get_field_permissions_for_model(request.user, model)
    non_editable_fields = section_view.non_editable_fields
    can_update = HorillaDetailView.check_update_permission(section_view)
    # Set by extensions (e.g. approvals) to narrow which fields may be edited.
    allowed_fields = getattr(request, "bulk_edit_allowed_fields", None)

    resolver = get_field_info_resolver()
    fields = []
    for _verbose_name, field_name in body:
        field_perm = field_permissions.get(field_name, "readwrite")
        if field_perm == "hidden":
            continue
        if allowed_fields and field_name not in allowed_fields:
            continue

        field = next((f for f in obj._meta.get_fields() if f.name == field_name), None)
        if field is None:
            continue

        field_info = resolver.get_field_info(field, obj, request.user)
        editable = (
            section_view.edit_field
            and field_name not in non_editable_fields
            and field_perm == "readwrite"
            and can_update
            and (allowed_fields is None or field_name in allowed_fields)
        )
        fields.append({"info": field_info, "editable": editable})

    extra_provider = get_extra_fields_provider()
    fields.extend(
        extra_provider.get_extra_fields(
            obj, request, section_view.edit_field and can_update
        )
    )

    return {
        "obj": obj,
        "object_id": obj.pk,
        "fields": fields,
        "app_label": app_label,
        "model_name": model_name,
        "pipeline_field": pipeline_field,
        "cancel_url": cancel_url,
        "detail_url_name": request.GET.get("detail_url_name", ""),
    }


@method_decorator(htmx_required, name="dispatch")
class EditAllFieldsView(LoginRequiredMixin, View):
    """
    View to render editable widgets for every editable field of an object at once.

    Backs the "Edit Details" bulk-edit toggle on the details tab: instead of a
    pencil icon per field, one button switches the whole field grid into edit
    mode with a single Save/Cancel pair.
    """

    template_name = "partials/edit_all_fields.html"
    model = None

    def can_edit(self, request, obj):
        """Whether the user may use Edit Details on ``obj``; extensions may widen this."""
        return can_edit_all_fields(request, obj)

    def get(self, request, pk, app_label, model_name):
        """Render every field in ``body`` as an editable widget (or plain display for non-editable ones)."""
        from django.utils.http import url_has_allowed_host_and_scheme

        pipeline_field = request.GET.get("pipeline_field", None)
        cancel_url = request.GET.get("return_url", "")
        if not url_has_allowed_host_and_scheme(
            cancel_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            cancel_url = ""
        try:
            if not self.model:
                self.model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(self.model, pk=pk)
        except Exception as e:
            messages.error(self.request, e)
            return ScriptResponse(reload=True)

        if is_record_locked(obj):
            messages.error(request, _("This record is read-only."))
            return ScriptResponse(reload=True)

        if not self.can_edit(request, obj):
            messages.error(request, _("You do not have permission to edit this."))
            return ScriptResponse(reload=True)

        context = build_edit_all_fields_context(
            request, obj, app_label, model_name, pipeline_field, cancel_url
        )
        return render(request, self.template_name, context)


def keep_posted_value(field_info, request):
    """
    Put the value posted for ``field_info`` back into it, so a field whose
    value was refused shows what the user typed instead of the stored value.
    """
    name = field_info["name"]
    if field_info["field_type"] == "phone":
        from horilla.contrib.generics.forms.generics import PhoneWidget

        posted = [request.POST.get(f"{name}_0", ""), request.POST.get(f"{name}_1", "")]
        field_info["phone_widget_html"] = PhoneWidget().render(name, posted)
    elif field_info["field_type"] != "select" and name in request.POST:
        field_info["value"] = request.POST[name]


def get_edit_all_fields_view():
    """Return an EditAllFieldsView instance with ``_inherit_view`` extensions applied."""
    return resolve_view_class(EditAllFieldsView)()


class SaveAllFieldsResult:
    """
    What :func:`save_all_fields` did.

    - ``errors``: field name to message, for submitted values that couldn't
      be applied; the record itself isn't saved then.
    - ``changed_fields``: the fields whose value changed.
    - ``response``: the answer of a ``check_before_save`` hook that stopped
      the save, or of a ``handle_save_error`` hook that took over a failed
      one.
    - ``save_error``: a ``ValidationError`` from ``obj.save()`` that no hook
      handled.
    """

    def __init__(self):
        self.errors = {}
        self.changed_fields = []
        self.response = None
        self.save_error = None

    @property
    def ok(self):
        """True when every value applied and nothing stopped the save."""
        return not self.errors and self.response is None and self.save_error is None


def save_all_fields(request, obj, section_view, hooks):
    """
    Apply and save the Edit Details values of ``obj`` posted in ``request``.

    The save behind :class:`UpdateAllFieldsView`, for any page that edits a
    record's fields (the phone app uses it too). Only fields of the Details
    tab body (``section_view.get_effective_body()``) that the user may
    ``readwrite``, that aren't in ``non_editable_fields`` and that
    ``hooks.get_allowed_fields`` allows are applied, each with :meth:`FieldInfoResolver.apply_field_value` (``save=False``;
    many-to-many values are written at once). Anything else posted goes to
    :class:`ExtraFieldsProvider` (custom fields, saved at once). When every
    value applied and something changed, ``hooks.check_before_save`` may stop
    the save, ``obj.save()`` commits it, and a ``ValidationError`` goes to
    ``hooks.handle_save_error``.

    The caller checks :func:`can_edit_all_fields` first. ``hooks`` is the
    ``UpdateAllFieldsView`` whose hooks run: the view itself, or
    :func:`get_update_all_fields_view` elsewhere, so its ``_inherit_view``
    extensions apply. Returns a :class:`SaveAllFieldsResult`.
    """
    from horilla.contrib.core.utils import get_field_permissions_for_model

    result = SaveAllFieldsResult()
    if not section_view.edit_field:
        return result

    model = obj.__class__
    body = section_view.get_effective_body()
    field_permissions = get_field_permissions_for_model(request.user, model)
    non_editable_fields = section_view.non_editable_fields
    resolver = get_field_info_resolver()
    errors = result.errors
    changed_fields = result.changed_fields
    allowed_fields = hooks.get_allowed_fields(request, obj)
    m2m_changed = False
    for verbose_name, field_name in body:
        field_perm = field_permissions.get(field_name, "readwrite")
        submitted = field_name in request.POST or any(
            key.startswith(f"{field_name}[]") or key.startswith(f"{field_name}_")
            for key in request.POST
        )
        if (
            field_perm != "readwrite"
            or field_name in non_editable_fields
            or not submitted
            or (allowed_fields is not None and field_name not in allowed_fields)
        ):
            continue

        field = next((f for f in obj._meta.get_fields() if f.name == field_name), None)
        if field is None:
            continue

        # M2M fields are applied (and committed) immediately inside
        # apply_field_value — there's no in-memory-only equivalent
        # for a separate-table write, so they're excluded from the
        # pre-save check's "combined field values" and always land
        # even if check_before_save later blocks the rest.
        is_m2m = isinstance(field, models.ManyToManyField)
        if is_m2m:
            old_value = set(getattr(obj, field_name).values_list("pk", flat=True))
        else:
            old_value = getattr(obj, field_name, None)

        error = resolver.apply_field_value(obj, field, field_name, request, save=is_m2m)
        if error:
            errors[field_name] = error
            continue

        if is_m2m:
            new_value = set(getattr(obj, field_name).values_list("pk", flat=True))
        else:
            new_value = getattr(obj, field_name, None)

        if new_value != old_value:
            changed_fields.append(field_name)
            if is_m2m:
                m2m_changed = True

    # Anything submitted that isn't a real model field (e.g. a cf_*
    # custom field) is handled by whatever ``_inherit_view``
    # extension registered on ExtraFieldsProvider recognizes it.
    # These always save immediately (no in-memory-only equivalent
    # for a separate-table value) rather than gating on the
    # in-progress obj.save() below.
    model_field_names = {name for _verbose, name in body}
    extra_provider = get_extra_fields_provider()
    extra_names = set()
    for key in list(request.POST.keys()):
        name = key[:-2] if key.endswith("[]") else key
        if name in model_field_names or name in extra_names:
            continue
        extra_names.add(name)
    for name in extra_names:
        try:
            if extra_provider.apply_extra_field(obj, name, request):
                changed_fields.append(name)
        except Exception as e:
            errors[name] = str(e)

    if errors or not changed_fields:
        return result
    result.response = hooks.check_before_save(request, obj, changed_fields)
    if result.response is not None:
        return result
    try:
        obj.save(force=m2m_changed)
    except ValidationError as e:
        result.response = hooks.handle_save_error(
            request, obj, e, model._meta.app_label, model._meta.model_name
        )
        if result.response is None:
            result.save_error = e
    return result


@method_decorator(htmx_required, name="dispatch")
class UpdateAllFieldsView(LoginRequiredMixin, View):
    """
    View to save every editable field of an object from a single bulk-edit form.

    Reuses :meth:`FieldInfoResolver.apply_field_value` for the per-field
    parsing and validation, collecting all errors before re-rendering so the
    user sees every problem at once instead of one field at a time.

    Saving is two-phase: every submitted value is applied to ``obj``
    in-memory first (``save=False``), then :meth:`check_before_save` runs
    once against the fully-updated (but not yet persisted) object, and only
    if it doesn't block does ``obj.save()`` actually commit. This gives
    ``_inherit_view`` extensions (e.g. duplicate-record checking) a single
    seam to inspect the *combined* result of every field changed in this
    submission before anything is written, instead of one field at a time.

    The save itself is :func:`save_all_fields`, which other pages that edit a
    record's fields call with this view's hooks too.
    """

    template_name = "details_tab.html"
    model = None

    def check_before_save(self, request, obj, changed_fields):
        """
        Hook for ``_inherit_view`` extensions to block a save before it commits.

        Called after every submitted field's value has been applied to
        ``obj`` in-memory (not yet saved). Return ``None`` to let the save
        proceed, or an :class:`HttpResponse` to short-circuit ``post`` with
        that response instead (e.g. a duplicate-warning modal). Other pages
        calling :func:`save_all_fields` don't show that response; they only
        learn that the save was stopped, and any message it queued.

        ``changed_fields`` is the list of field names actually applied in
        this submission (readwrite, editable, present in POST).
        """
        return None

    def can_edit(self, request, obj):
        """Whether the user may use Edit Details on ``obj``; extensions may widen this."""
        return can_edit_all_fields(request, obj)

    def get_allowed_fields(self, request, obj):
        """
        Hook for ``_inherit_view`` extensions to narrow which fields of
        ``obj`` may be saved (e.g. the approvals pending-edit policy).

        Return the allowed field names, or ``None`` for no limit beyond the
        field permissions. Defaults to ``request.bulk_edit_allowed_fields``
        when an extension has set it.
        """
        return getattr(request, "bulk_edit_allowed_fields", None)

    def handle_save_error(self, request, obj, error, app_label, model_name):
        """
        Hook for ``_inherit_view`` extensions to customize the response to a
        ``ValidationError`` raised by ``obj.save()`` (e.g. from a ``pre_save``
        signal such as the approvals pending-edit guard).

        Return an :class:`HttpResponse` to use instead of the default
        behavior (adding ``error`` as a generic form-level message and
        re-rendering the bulk-edit form), or ``None`` to fall back to that
        default. As with :meth:`check_before_save`, other pages calling
        :func:`save_all_fields` only learn that the save failed, and any
        message the hook queued.
        """
        return None

    def post(self, request, pk, app_label, model_name):
        """Parse and save every submitted editable field, then re-render the details tab."""
        try:
            if not self.model:
                self.model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(self.model, pk=pk)
        except Exception as e:
            messages.error(self.request, e)
            return ScriptResponse(reload=True)

        if is_record_locked(obj):
            messages.error(request, _("This record is read-only."))
            return ScriptResponse(reload=True, status=403)

        if not self.can_edit(request, obj):
            messages.error(request, _("You do not have permission to edit this."))
            return ScriptResponse(reload=True, status=403)

        section_view = _get_section_view_instance(self.model, request, pk)
        section_view.object = obj
        result = save_all_fields(request, obj, section_view, self)
        if result.response is not None:
            return result.response
        if result.save_error is not None:
            message = " ".join(str(msg) for msg in result.save_error.messages)
            messages.error(request, message)
            cancel_url_for_error = request.POST.get("return_url", "")
            context = build_edit_all_fields_context(
                request,
                self.model.objects.get(pk=pk),
                app_label,
                model_name,
                pipeline_field=request.POST.get("pipeline_field"),
                cancel_url=cancel_url_for_error,
            )
            return render(request, "partials/edit_all_fields.html", context)

        for field_name, error in result.errors.items():
            messages.error(
                request,
                _("%(field)s: %(message)s") % {"field": field_name, "message": error},
            )

        from django.utils.http import url_has_allowed_host_and_scheme

        self_url = request.POST.get("return_url", "")
        if not url_has_allowed_host_and_scheme(
            self_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            self_url = ""

        context = section_view.get_context_data(object=obj)
        context["self_url"] = self_url
        return render(request, self.template_name, context)


def get_update_all_fields_view():
    """Return an UpdateAllFieldsView instance with ``_inherit_view`` extensions applied."""
    return resolve_view_class(UpdateAllFieldsView)()

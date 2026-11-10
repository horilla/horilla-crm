"""
Forms for the cadences app
"""

# Third-party imports (Django)
from django import forms
from django.conf import settings

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.core.exceptions import ValidationError
from horilla.db import models as horilla_models
from horilla.urls import reverse, reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from . import services
from .followup_types import (
    CHANNEL_SENT_STATUS,
    TEMPLATE_MAIL,
    get_channel_template_kind,
    get_followup_channel,
    get_followup_type_choices,
    get_followup_type_label,
    is_builtin_followup_type,
)
from .models import Cadence, CadenceEnrollment, CadenceFollowUp


def _cadence_mail_to_choices_for_model(model_name):
    """Build Mail to style choices from the platform module model (mirrors automation UX)."""
    field_choices = []
    if not model_name:
        return field_choices
    try:
        model_class = None
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name.lower())
                break
            except (LookupError, ValueError):
                continue
        if not model_class:
            return field_choices
        for field in model_class._meta.get_fields():
            if not hasattr(field, "name"):
                continue
            if isinstance(field, horilla_models.ForeignKey):
                try:
                    related_model = field.related_model
                    is_user_model = False
                    if related_model:
                        if related_model == User:
                            is_user_model = True
                        elif hasattr(related_model, "__bases__"):
                            try:
                                is_user_model = issubclass(related_model, User)
                            except (TypeError, AttributeError):
                                pass
                        if not is_user_model:
                            try:
                                uct = HorillaContentType.objects.get_for_model(User)
                                fct = HorillaContentType.objects.get_for_model(
                                    related_model
                                )
                                if uct == fct:
                                    is_user_model = True
                            except Exception:
                                pass
                        if not is_user_model:
                            user_model_names = ["user", "horillauser"]
                            if hasattr(settings, "AUTH_USER_MODEL"):
                                user_model_names.append(
                                    settings.AUTH_USER_MODEL.split(".")[-1].lower()
                                )
                            if related_model.__name__.lower() in user_model_names:
                                is_user_model = True
                    if is_user_model:
                        verbose_name = (
                            getattr(field, "verbose_name", None)
                            or field.name.replace("_", " ").title()
                        )
                        field_choices.append((f"instance.{field.name}", verbose_name))
                except Exception:
                    continue
            elif isinstance(
                field, (horilla_models.EmailField, horilla_models.CharField)
            ):
                if "email" in field.name.lower():
                    verbose_name = (
                        getattr(field, "verbose_name", None)
                        or field.name.replace("_", " ").title()
                    )
                    field_choices.append((f"instance.{field.name}", verbose_name))
    except Exception:
        pass
    return field_choices


def _has_outgoing_mail_server(cadence):
    """Check whether cadence company (or globally) has an outgoing mail server."""
    return HorillaMailConfiguration.objects.filter(mail_channel="outgoing").exists()


class CadenceForm(HorillaModelForm):
    """Cadence create/update; reload the form on module change so condition field choices rebuild from the selected model (mirrors CustomCalendarForm)."""

    htmx_field_choices_url = "generics:get_model_field_choices"
    CONDITION_INPUT_FIELDS = ("field", "operator", "value")

    field_order = [
        "name",
        "module",
        "description",
        "is_active",
    ]

    class Meta:
        """Meta class for CadenceForm"""

        model = Cadence
        fields = "__all__"
        keep_on_form = ("is_active",)

    def __init__(self, *args, **kwargs):
        # HTMX reload after changing module must NOT use ``data=GET`` - that binds the form and
        # triggers validation, showing "required" on empty fields before Save. Merge GET into
        # ``initial`` instead so the form stays unbound until POST.
        request = kwargs.get("request")
        if (
            request
            and request.method == "GET"
            and request.GET
            and request.headers.get("HX-Request")
        ):
            initial = kwargs.get("initial")
            if initial is None:
                initial = {}
            elif not isinstance(initial, dict):
                initial = dict(initial)
            for key in request.GET.keys():
                initial[key] = request.GET.get(key)
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        if "module" in self.fields and self.request:
            reload_path = self.request.path
            pk = getattr(getattr(self, "instance", None), "pk", None)
            if pk:
                reload_path = reverse("cadences:cadence_update_view", kwargs={"pk": pk})
            self.fields["module"].widget.attrs.update(
                {
                    "hx-get": reload_path,
                    "hx-target": "#cadence-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#cadence-form-view",
                    "hx-trigger": "change",
                }
            )

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_bound:
            return cleaned_data

        row_ids = set()
        for key in self.data.keys():
            for field_name in self.CONDITION_INPUT_FIELDS:
                prefix = f"{field_name}_"
                if key.startswith(prefix):
                    row_id = key[len(prefix) :]
                    if row_id.isdigit():
                        row_ids.add(row_id)

        if not row_ids:
            raise ValidationError(_("At least one condition is required."))

        has_complete_row = False
        has_partial_row = False
        for row_id in sorted(row_ids, key=int):
            row_values = {
                field_name: (self.data.get(f"{field_name}_{row_id}") or "").strip()
                for field_name in self.CONDITION_INPUT_FIELDS
            }
            filled_fields = [name for name, value in row_values.items() if value]
            if not filled_fields:
                continue
            if len(filled_fields) == len(self.CONDITION_INPUT_FIELDS):
                has_complete_row = True
            else:
                has_partial_row = True

        if has_partial_row:
            raise ValidationError(
                _("Each condition row must include Field, Operator, and Value.")
            )
        if not has_complete_row:
            raise ValidationError(_("At least one condition is required."))
        return cleaned_data


class CadenceFollowUpForm(HorillaModelForm):
    """Form for cadence follow-up actions with type-based visible fields."""

    TYPE_FIELD_MAP = {
        "task": [
            "subject",
            "due_after_days",
            "task_status",
            "task_priority",
            "task_owner",
            "task_owner_from_record",
        ],
        "call": [
            "call_start_after_days",
            "call_owner",
            "call_owner_from_record",
            "purpose",
        ],
        "email": ["to", "email_template"],
    }

    field_order = [
        "cadence",
        "followup_number",
        "branch_from",
        "followup_type",
        "do_this_unit",
        "do_this_value",
        "previous_status",
        "subject",
        "due_after_days",
        "task_status",
        "task_priority",
        "task_owner",
        "task_owner_from_record",
        "call_start_after_days",
        "call_owner",
        "call_owner_from_record",
        "purpose",
        "to",
        "email_template",
    ]

    class Meta:
        """Meta class for CadenceFollowUpForm"""

        model = CadenceFollowUp
        fields = "__all__"
        exclude = [
            "call_type",
            "call_status",
            "order",
            "channel_config",
        ]

    def __init__(self, *args, **kwargs):
        form_url = kwargs.pop("form_url", None)
        htmx_trigger_target = kwargs.pop("htmx_trigger_target", None)
        do_this_toggle_url = kwargs.pop("do_this_toggle_url", None)
        super().__init__(*args, **kwargs)
        self._set_followup_type_choices()

        if (
            getattr(self, "request", None)
            and self.request.method == "GET"
            and self.request.GET
            and not self.is_bound
        ):
            for key in self.request.GET:
                if key in self.fields:
                    self.initial[key] = self.request.GET.get(key)
        self.fields["cadence"].widget = forms.HiddenInput()
        for name in ("due_after_days", "call_start_after_days"):
            if name in self.fields:
                self.fields[name].widget.attrs["placeholder"] = _(
                    "Enter number of days"
                )
        if "do_this_value" in self.fields:
            self.fields["do_this_value"].widget.attrs["placeholder"] = _(
                "Enter a number"
            )
        if "branch_from" in self.fields:
            self.fields["branch_from"].widget = forms.HiddenInput()
            self.fields["branch_from"].required = False
        self.fields["followup_type"].widget.attrs[
            "class"
        ] = "js-example-basic-single headselect"
        self.fields["do_this_unit"].widget.attrs[
            "class"
        ] = "js-example-basic-single headselect"

        if form_url and htmx_trigger_target:
            htmx_attrs = {
                "hx-get": form_url,
                "hx-include": "closest form",
                "hx-target": htmx_trigger_target,
                "hx-swap": "outerHTML",
                "hx-trigger": "change",
            }
            if "followup_type" in self.fields:
                self.fields["followup_type"].widget.attrs.update(htmx_attrs)
            if "do_this_unit" in self.fields and do_this_toggle_url:
                self.fields["do_this_unit"].widget.attrs.update(
                    {
                        "hx-get": do_this_toggle_url,
                        "hx-include": "closest form",
                        "hx-target": "#do_this_value_container",
                        "hx-swap": "outerHTML",
                        "hx-trigger": "change,load",
                    }
                )

        cadence_id = None
        if self.is_bound:
            cadence_id = self.data.get("cadence")
        cadence_id = (
            cadence_id
            or self.initial.get("cadence")
            or getattr(self.instance, "cadence_id", None)
        )
        followup_type = None
        if self.is_bound:
            followup_type = self.data.get("followup_type")
        if not followup_type:
            followup_type = self.initial.get("followup_type") or getattr(
                self.instance, "followup_type", None
            )
        if not followup_type:
            followup_type = "task"
            self.initial["followup_type"] = "task"

        visible_type_fields = set(self.TYPE_FIELD_MAP.get(followup_type, []))
        all_type_fields = set().union(*self.TYPE_FIELD_MAP.values())
        for field_name in all_type_fields:
            if field_name not in visible_type_fields and field_name in self.fields:
                self.fields.pop(field_name, None)

        do_this_unit_value = None
        if self.is_bound:
            do_this_unit_value = self.data.get("do_this_unit")
        if not do_this_unit_value:
            do_this_unit_value = (
                self.initial.get("do_this_unit")
                or getattr(self.instance, "do_this_unit", None)
                or "immediately"
            )

        if "do_this_value" in self.fields and do_this_unit_value == "immediately":
            self.fields["do_this_value"].required = False

        followup_number = None
        if self.is_bound:
            followup_number = self.data.get("followup_number")
        if not followup_number:
            followup_number = (
                self.initial.get("followup_number")
                or getattr(self.instance, "followup_number", None)
                or 1
            )
        try:
            followup_number = int(followup_number)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid follow-up number: {followup_number}") from e

        if cadence_id and followup_number > 1:
            previous_exists = CadenceFollowUp.objects.filter(
                cadence_id=cadence_id,
                followup_number=followup_number - 1,
            ).exists()
            if not previous_exists:
                raise ValueError(f"Cannot create follow-up at stage {followup_number}.")
        if cadence_id and "branch_from" in self.fields and followup_number > 1:
            self.fields["branch_from"].queryset = CadenceFollowUp.objects.filter(
                cadence_id=cadence_id,
                followup_number=followup_number - 1,
            )
        elif "branch_from" in self.fields:
            self.fields["branch_from"].queryset = CadenceFollowUp.objects.none()

        if followup_number > 1 and "previous_status" in self.fields:
            previous_type = self._get_previous_followup_type(followup_number)
            self.fields["previous_status"].label = self._get_previous_status_label(
                previous_type
            )
            status_choices = self._get_previous_status_choices(
                previous_type, followup_number
            )
            self.fields["previous_status"].widget = forms.Select(
                choices=[("", "---------"), *status_choices],
                attrs={"class": "js-example-basic-single headselect"},
            )
        else:
            self.fields.pop("previous_status", None)

        if followup_type == "email":
            self._configure_email_followup_fields(cadence_id)
        channel = get_followup_channel(followup_type)
        if channel is not None:
            self._configure_channel_followup_fields(channel, cadence_id)

    def _company(self):
        """The company whose channels the type picker offers."""
        company = getattr(getattr(self, "request", None), "active_company", None)
        if company is None and getattr(self.instance, "cadence_id", None):
            company = self.instance.cadence.company
        return company

    def _set_followup_type_choices(self):
        """
        The type picker lists the built-ins and the delivery channels available
        to the company. A saved follow-up keeps its type in the list even when
        its channel is no longer offered, so editing it does not change it.
        """
        if "followup_type" not in self.fields:
            return
        choices = get_followup_type_choices(self._company())
        saved = getattr(self.instance, "followup_type", None)
        if saved and not any(key == saved for key, _label in choices):
            choices.append((saved, get_followup_type_label(saved)))
        field = self.fields["followup_type"]
        self.fields["followup_type"] = forms.ChoiceField(
            choices=choices,
            label=field.label,
            help_text=field.help_text,
            required=True,
            widget=forms.Select(),
        )

    def _configure_channel_followup_fields(self, channel, cadence_id):
        """
        A delivery channel follow-up: its template (when the channel uses one)
        and its recipient, stored in ``channel_config``.
        """
        from horilla.contrib.notifications.models import NotificationTemplate

        cadence = (
            Cadence.objects.select_related("module").filter(pk=cadence_id).first()
            if cadence_id
            else None
        )
        module_pk = cadence.module_id if cadence and cadence.module_id else None
        config = (self.instance.channel_config or {}) if self.instance.pk else {}
        select_attrs = {"class": "js-example-basic-single headselect w-full"}

        kind = get_channel_template_kind(channel)
        if kind is not None:
            model = (
                HorillaMailTemplate if kind == TEMPLATE_MAIL else NotificationTemplate
            )
            # Templates without a Related Model are reusable across modules.
            templates = model.objects.filter(
                horilla_models.Q(content_type_id=module_pk)
                | horilla_models.Q(content_type__isnull=True)
            ).order_by("title")
            self.fields["channel_template"] = forms.ModelChoiceField(
                queryset=templates,
                required=True,
                label=_("Mail Template") if kind == TEMPLATE_MAIL else _("Template"),
                help_text=_("The text of the message, rendered for the record."),
                initial=config.get("template_id") or None,
                widget=forms.Select(attrs=select_attrs),
            )

        model_class = (
            cadence.module.model_class() if cadence and cadence.module else None
        )
        # No user triggers a cadence step, so "self" is not offered (as for email).
        to_choices = [
            choice
            for choice in channel.get_recipient_choices(model_class)
            if choice[0] != "self"
        ]
        initial_to = config.get("to", "")
        if initial_to not in {key for key, _label in to_choices}:
            initial_to = ""
        self.fields["channel_to"] = forms.ChoiceField(
            choices=[("", "---------"), *to_choices],
            required=True,
            label=_("Send to"),
            help_text=_("Who on the record receives this message."),
            initial=initial_to,
            widget=forms.Select(attrs=select_attrs),
        )

    def _clean_channel_followup(self, cleaned):
        """
        Check a channel follow-up's type against the registry and store its
        template and recipient in ``channel_config``; clear it for the built-ins.
        """
        followup_type = cleaned.get("followup_type")
        if not followup_type or is_builtin_followup_type(followup_type):
            self.instance.channel_config = {}
            return
        channel = get_followup_channel(followup_type)
        if channel is None or not channel.is_available(self._company()):
            self.add_error(
                "followup_type",
                _("%(followup_type)s is not an available follow-up type.")
                % {"followup_type": followup_type},
            )
            return
        template = cleaned.get("channel_template")
        self.instance.channel_config = {
            "template_id": str(template.pk) if template else "",
            "to": cleaned.get("channel_to") or "",
        }

    def _configure_email_followup_fields(self, cadence_id):
        """Scope mail templates to the cadence module; single-select Mail to."""
        cadence = None
        if cadence_id:
            cadence = (
                Cadence.objects.select_related("module").filter(pk=cadence_id).first()
            )
        module_pk = cadence.module_id if cadence and cadence.module_id else None
        if "email_template" in self.fields:
            # Templates without a Related Model are reusable across modules - include them.
            if module_pk:
                self.fields["email_template"].queryset = (
                    HorillaMailTemplate.objects.filter(
                        horilla_models.Q(content_type_id=module_pk)
                        | horilla_models.Q(content_type__isnull=True)
                    ).order_by("title")
                )
            else:
                self.fields["email_template"].queryset = (
                    HorillaMailTemplate.objects.filter(
                        content_type__isnull=True
                    ).order_by("title")
                )
            # The select2 AJAX endpoint reinstantiates this form to read the field's
            # queryset; pipe cadence/followup_type into its URL so the same Q filter
            # is applied when the dropdown loads options.
            if cadence_id:
                base_url = str(
                    self.fields["email_template"].widget.attrs.get("data-url", "")
                )
                if base_url:
                    sep = "&" if "?" in base_url else "?"
                    self.fields["email_template"].widget.attrs[
                        "data-url"
                    ] = f"{base_url}{sep}cadence={cadence_id}&followup_type=email"
        if "to" not in self.fields:
            return
        model_name = None
        if cadence and cadence.module:
            model_name = cadence.module.model
        path_choices = _cadence_mail_to_choices_for_model(model_name)
        label = _("Mail to")
        help_text = _(
            "Choose which user or email field on the record should receive this mail."
        )
        initial_to = ""
        if self.instance and self.instance.pk and self.instance.to:
            raw = str(self.instance.to).strip()
            initial_to = raw.split(",", maxsplit=1)[0].strip() if raw else ""
        elif self.initial.get("to"):
            raw = str(self.initial.get("to")).strip()
            initial_to = raw.split(",", maxsplit=1)[0].strip() if raw else ""
        choice_keys = {c[0] for c in path_choices}
        if initial_to and initial_to not in choice_keys:
            initial_to = ""
        self.fields["to"] = forms.ChoiceField(
            choices=[("", "---------"), *path_choices],
            required=True,
            label=label,
            help_text=help_text,
            initial=initial_to,
            widget=forms.Select(
                attrs={
                    "class": "js-example-basic-single headselect w-full",
                }
            ),
        )

    def clean(self):
        cleaned = super().clean()
        self._clean_channel_followup(cleaned)
        cadence = cleaned.get("cadence")
        if cleaned.get("followup_type") == "email" and not _has_outgoing_mail_server(
            cadence
        ):
            self.add_error(
                "followup_type",
                _(
                    "Email follow-up is unavailable until an outgoing mail server is configured."
                ),
            )
        do_unit = cleaned.get("do_this_unit")
        do_value = cleaned.get("do_this_value")
        if do_unit and do_unit != "immediately" and not do_value:
            self.add_error("do_this_value", _("This field is required."))
        if do_unit == "immediately":
            cleaned["do_this_value"] = None
        followup_number = cleaned.get("followup_number") or 1
        if followup_number > 1 and not cleaned.get("previous_status"):
            self.add_error("previous_status", _("This field is required."))
        if followup_number == 1:
            cleaned["previous_status"] = None
            cleaned["branch_from"] = None
        else:
            bf = cleaned.get("branch_from")
            cadence = cleaned.get("cadence")
            fn = cleaned.get("followup_number") or 1
            if cadence and not bf:
                prev_qs = CadenceFollowUp.objects.filter(
                    cadence_id=cadence.pk, followup_number=fn - 1
                ).order_by("order", "id")
                if prev_qs.count() == 1:
                    cleaned["branch_from"] = prev_qs.first()
                    bf = cleaned["branch_from"]
                else:
                    self.add_error(
                        "branch_from",
                        _("Parent follow-up is required for this stage."),
                    )
            if bf and cadence:
                if bf.cadence_id != cadence.pk:
                    self.add_error("branch_from", _("Invalid cadence for branch."))
                elif bf.followup_number != fn - 1:
                    self.add_error(
                        "branch_from",
                        _("Parent must belong to the previous follow-up stage."),
                    )
        return cleaned

    def save(self, commit=True):
        """Assign the first free order index for this branch (branch_from) so gaps and adds align with the correct parent +."""
        instance = super().save(commit=False)
        if (
            not instance.pk
            and instance.cadence_id
            and instance.followup_number is not None
        ):
            qs = CadenceFollowUp.objects.filter(
                cadence_id=instance.cadence_id,
                followup_number=instance.followup_number,
            )
            if instance.branch_from_id is not None:
                qs = qs.filter(branch_from_id=instance.branch_from_id)
            else:
                qs = qs.filter(branch_from_id__isnull=True)
            existing_orders = set(qs.values_list("order", flat=True))
            slot = 0
            while slot in existing_orders:
                slot += 1
            instance.order = slot
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def _get_previous_followup_type(self, followup_number):
        cadence_id = None
        if self.is_bound:
            cadence_id = self.data.get("cadence")
        cadence_id = (
            cadence_id
            or self.initial.get("cadence")
            or getattr(self.instance, "cadence_id", None)
        )
        if not cadence_id or followup_number <= 1:
            return None
        source = self._get_status_source_followup(cadence_id, followup_number)
        if source:
            return source.followup_type
        previous = (
            CadenceFollowUp.objects.filter(
                cadence_id=cadence_id, followup_number=followup_number - 1
            )
            .order_by("order", "id")
            .first()
        )
        return previous.followup_type if previous else None

    @staticmethod
    def _get_previous_status_label(previous_type):
        labels = {
            "task": _("When the previous Task is"),
            "call": _("When the previous Call is"),
            "email": _("When the previous Email is"),
        }
        if previous_type and not is_builtin_followup_type(previous_type):
            return _("When the previous message is")
        return labels.get(previous_type, _("When the previous follow-up is"))

    def _get_previous_status_choices(self, previous_type, followup_number):
        cadence_id = None
        if self.is_bound:
            cadence_id = self.data.get("cadence")
        cadence_id = (
            cadence_id
            or self.initial.get("cadence")
            or getattr(self.instance, "cadence_id", None)
        )
        used_statuses = set()
        source = self._get_status_source_followup(cadence_id, followup_number)
        if cadence_id and followup_number > 1:
            if source:
                used_statuses = self._get_used_statuses_for_source(
                    cadence_id, source, followup_number
                )
            else:
                # previous_status already taken by any follow-up in this bucket, including
                # branched rows from the parent stage, so the form only offers remaining stages.
                used_qs = CadenceFollowUp.objects.filter(
                    cadence_id=cadence_id, followup_number=followup_number
                ).exclude(pk=getattr(self.instance, "pk", None))
                used_statuses = {
                    s for s in used_qs.values_list("previous_status", flat=True) if s
                }

        if previous_type == "call":
            choices = [
                ("scheduled", _("Scheduled")),
                ("completed", _("Completed")),
                ("overdue", _("Overdue")),
                ("cancelled", _("Cancelled")),
            ]
            return [c for c in choices if c[0] not in used_statuses]
        if previous_type == "task":
            choices = list(Activity.STATUS_CHOICES)
            return [c for c in choices if c[0] not in used_statuses]
        if previous_type and not is_builtin_followup_type(previous_type):
            # A channel message only reaches "sent"; nothing reports it later.
            choices = [(CHANNEL_SENT_STATUS, _("Sent"))]
            return [c for c in choices if c[0] not in used_statuses]
        choices = [
            ("scheduled", _("Scheduled")),
            ("completed", _("Completed")),
            ("overdue", _("Overdue")),
            ("cancelled", _("Cancelled")),
            ("in_progress", _("In Progress")),
            ("not_started", _("Not Started")),
        ]
        return [c for c in choices if c[0] not in used_statuses]

    def _branch_from_id(self):
        branch_from_id = None
        if self.is_bound:
            branch_from_id = self.data.get("branch_from")
        return (
            branch_from_id
            or self.initial.get("branch_from")
            or getattr(self.instance, "branch_from_id", None)
        )

    def _get_status_source_followup(self, cadence_id, followup_number):
        if not cadence_id or followup_number <= 1:
            return None
        branch_from_id = self._branch_from_id()
        if not branch_from_id:
            return None
        source = (
            CadenceFollowUp.objects.filter(
                pk=branch_from_id,
                cadence_id=cadence_id,
                followup_number=followup_number - 1,
            )
            .select_related("branch_from")
            .first()
        )
        # Use the immediate previous-stage card only so labels and status options match the
        # real predecessor (e.g. FU3 when adding FU4), not an ancestor such as FU2.
        return source

    def _resolve_status_source_for_item(self, item):
        return item.branch_from if item.branch_from_id else None

    def _get_used_statuses_for_source(self, cadence_id, source, target_followup_number):
        used = set()
        items = (
            CadenceFollowUp.objects.filter(
                cadence_id=cadence_id,
                previous_status__isnull=False,
                followup_number__lte=target_followup_number,
            )
            .exclude(pk=getattr(self.instance, "pk", None))
            .select_related("branch_from", "branch_from__branch_from")
        )
        for item in items:
            item_source = self._resolve_status_source_for_item(item)
            if item_source and item_source.pk == source.pk:
                used.add(item.previous_status)
        return used


# The record being enrolled is remembered in the session when the form opens, so the
# select2 and picker requests the form triggers (which only know the form class and
# field name) list the same cadences.
ENROLL_RECORD_SESSION_KEY = "cadence_enroll_record"


def cadence_record_ref(model, pk):
    """``"app_label.model_name:pk"`` reference of the record being enrolled."""
    return f"{model._meta.app_label}.{model._meta.model_name}:{pk}"


def load_cadence_record(ref):
    """Return the record for a :func:`cadence_record_ref` string, or ``None``."""
    try:
        label, pk = str(ref).split(":")
        app_label, model_name = label.split(".")
        model = apps.get_model(app_label, model_name)
        return model.objects.filter(pk=pk).first()
    except (ValueError, LookupError, TypeError):
        return None


class CadenceEnrollForm(HorillaModelForm):
    """Pick the cadences a record is enrolled in (Enroll on the record's Cadence tab)."""

    cadences = forms.ModelMultipleChoiceField(
        queryset=Cadence.objects.all(),
        label=_("Cadences"),
        help_text=_(
            "Select one or more cadences. Each starts from its first follow-up, "
            "even if the cadence conditions are not met."
        ),
        widget=forms.SelectMultiple(
            attrs={
                "class": "select2-pagination w-full",
                "data-url": reverse_lazy(
                    "generics:model_select2",
                    kwargs={"app_label": "cadences", "model_name": "Cadence"},
                ),
                "data-placeholder": _("Select cadences"),
                "data-field-name": "cadences",
                "data-form-class": "horilla.contrib.cadences.forms.CadenceEnrollForm",
                "id": "id_cadences",
            }
        ),
    )

    class Meta:
        """Meta class for CadenceEnrollForm"""

        model = CadenceEnrollment
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The base form restyles every widget; the field must stay a select2 dropdown.
        self.fields["cadences"].widget.attrs["class"] = "select2-pagination w-full"
        ref = self.initial.get("record")
        if not ref and self.request is not None and hasattr(self.request, "session"):
            ref = self.request.session.get(ENROLL_RECORD_SESSION_KEY)
        self.record = load_cadence_record(ref) if ref else None
        if self.record is not None:
            self.fields["cadences"].queryset = services.eligible_cadences(self.record)

    def save(self, commit=True):
        """
        Enroll the record in every chosen cadence.

        Returns ``(enrolled, errors)``: the names of the cadences started and the
        messages for the ones that could not be.
        """
        enrolled, errors = [], []
        for cadence in self.cleaned_data["cadences"]:
            try:
                enrollment = services.enroll(cadence, self.record, self.request.user)
            except services.EnrollmentError as exc:
                errors.append(f"{cadence.name}: {exc}")
                continue
            if enrollment.status == "failed":
                errors.append(
                    _(
                        "Could not start %(cadence)s: no follow-up could be created. "
                        "Check that an outgoing mail server is set up for email follow-ups."
                    )
                    % {"cadence": cadence.name}
                )
            else:
                enrolled.append(cadence.name)
        return enrolled, errors

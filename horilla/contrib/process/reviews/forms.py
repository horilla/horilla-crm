"""Forms for Review Process setup."""

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType, Role
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.core.exceptions import ValidationError
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import ReviewCondition, ReviewProcess, ReviewRule, ReviewRuleCondition


class ReviewFieldsField(forms.Field):
    """Multi-select field that tolerates dynamic/label values from Select2."""

    def __init__(self, *args, choices=None, **kwargs):
        self.choices = list(choices or [])
        kwargs.setdefault(
            "widget",
            forms.SelectMultiple(
                attrs={
                    "class": "js-example-basic-multiple headselect w-full h-full",
                    "data-placeholder": _("Select Field(s)"),
                }
            ),
        )
        super().__init__(*args, **kwargs)
        self.widget.choices = self.choices

    def set_choices(self, choices):
        """Update choices dynamically (e.g. after model selection)."""
        self.choices = list(choices or [])
        self.widget.choices = self.choices

    def clean(self, value):
        """Normalize and validate the provided value(s) against allowed choices."""
        if value is None:
            values = []
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            values = [value]

        allowed = {str(v) for v, _ in self.choices}
        label_to_value = {
            str(lbl).strip().lower(): str(val) for val, lbl in self.choices
        }

        normalized = []
        for raw in values:
            sval = str(raw).strip()
            if not sval:
                continue
            if sval in allowed:
                normalized.append(sval)
                continue
            mapped = label_to_value.get(sval.lower())
            if mapped and mapped in allowed:
                normalized.append(mapped)

        seen = set()
        out = []
        for item in normalized:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out


class ReviewProcessForm(HorillaModelForm):
    """Form fro review process create and update"""

    field_order = [
        "title",
        "model",
        "review_fields",
        "trigger_on_create",
        "trigger_on_edit",
        "notify_on_submission",
        "notify_on_approval",
        "notify_on_rejection",
        "is_active",
    ]

    # App-local endpoint so the swapped "Field" select keeps HTMX wiring.
    review_fields = ReviewFieldsField(required=True, label=_("Fields to Review"))

    def __init__(self, *args, **kwargs):
        request = kwargs.get("request")
        kwargs["condition_model"] = ReviewCondition
        super().__init__(*args, **kwargs)

        model_name, selected_model_id = self._get_selected_model_context(
            request=request
        )
        if selected_model_id:
            self.initial["model"] = selected_model_id
        self.fields["review_fields"].set_choices(
            self._get_model_field_choices(model_name)
        )

        if (
            self.instance
            and getattr(self.instance, "pk", None)
            and isinstance(getattr(self.instance, "review_fields", None), list)
            and not self.initial.get("review_fields")
        ):
            self.initial["review_fields"] = self.instance.review_fields

        if "model" in self.fields:
            self.fields["model"].widget.attrs.update(
                {
                    "hx-get": reverse_lazy("reviews:reviews_model_dependent_fields"),
                    "hx-include": "#reviewprocess-form-view-container",
                    "hx-target": "#reviewprocess-form-view-container",
                    "hx-swap": "none",
                    "hx-trigger": "change",
                }
            )

    def _get_selected_model_context(self, request=None):
        selected_model_id = None
        if getattr(self, "is_bound", False):
            selected_model_id = self.data.get("model")
        if not selected_model_id and request and request.method == "GET":
            selected_model_id = request.GET.get("model")
        if not selected_model_id:
            selected_model_id = self.initial.get("model")
        if (
            not selected_model_id
            and self.instance
            and getattr(self.instance, "model_id", None)
        ):
            selected_model_id = self.instance.model_id
        if not selected_model_id:
            return (None, None)
        try:
            content_type = HorillaContentType.objects.filter(
                pk=selected_model_id
            ).first()
        except Exception:
            content_type = None
        return (content_type.model if content_type else None, selected_model_id)

    def _get_model_field_choices(self, model_name):
        field_choices = []
        if not model_name:
            return field_choices

        model_class = None
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name.lower())
                if model_class:
                    break
            except Exception:
                continue
        if not model_class:
            return field_choices

        skip = {
            "id",
            "pk",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "company",
            "additional_info",
        }
        all_forward_fields = list(model_class._meta.fields) + list(
            model_class._meta.many_to_many
        )
        for field in all_forward_fields:
            if field.name in skip or not getattr(field, "editable", True):
                continue
            verbose_name = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            field_choices.append((field.name, str(verbose_name)))
        return field_choices

    def clean_review_fields(self):
        """Ensure that at least one field is selected for review."""
        value = self.cleaned_data.get("review_fields")
        if not value:
            raise ValidationError(_("Please select at least one field to review."))
        return value

    class Meta:
        """Meta class for ReviewProcessForm"""

        model = ReviewProcess
        fields = "__all__"
        exclude = ["method_title"]
        keep_on_form = ["is_active"]


class ReviewProcessRuleForm(HorillaModelForm):
    """configuration form shown in the detail view."""

    def __init__(self, *args, **kwargs):
        kwargs["condition_model"] = ReviewRuleCondition
        super().__init__(*args, **kwargs)

        self.fields["approver_users"].queryset = User.objects.all()
        self.fields["approver_roles"].queryset = Role.objects.all()

        approver_type = (
            self.data.get("approver_type")
            or self.initial.get("approver_type")
            or getattr(self.instance, "approver_type", None)
        )

        # Keep required=False on both fields so the browser doesn't try to focus
        # a hidden required field on submit. Validation is enforced in clean().
        self.fields["approver_users"].required = False
        self.fields["approver_roles"].required = False

        # Hide the inactive approver container via the widget's wrapper attrs so
        # the container div in single_form_view.html starts hidden. The HTMX
        # toggle will update visibility on change, and on initial load the
        # correct field is already visible without waiting for the swap.
        if approver_type != "user":
            self.fields["approver_users"].widget.attrs[
                "container_style"
            ] = "display:none"
        if approver_type != "role":
            self.fields["approver_roles"].widget.attrs[
                "container_style"
            ] = "display:none"

        if "approver_type" in self.fields:
            approver_toggle_url = reverse_lazy("reviews:reviews_approver_fields_toggle")
            if self.instance and getattr(self.instance, "pk", None):
                approver_toggle_url = reverse_lazy(
                    "reviews:reviews_approver_fields_toggle_with_pk",
                    kwargs={"pk": self.instance.pk},
                )

            # Skip "load" trigger when the form is bound with errors — the
            # toggle GET would swap the containers and erase validation messages.
            has_errors = bool(self.is_bound and self.errors)
            hx_trigger = "change" if has_errors else "load, change"

            self.fields["approver_type"].widget.attrs.update(
                {
                    "hx-get": approver_toggle_url,
                    "hx-include": "#reviewrule-form-view-container",
                    "hx-target": "#reviewrule-form-view-container",
                    "hx-swap": "none",
                    "hx-trigger": hx_trigger,
                }
            )

    def clean(self):
        cleaned_data = super().clean()
        approver_type = cleaned_data.get("approver_type")
        approver_users = cleaned_data.get("approver_users")
        approver_roles = cleaned_data.get("approver_roles")

        if approver_type == "user" and not approver_users:
            self.add_error(
                "approver_users", _("Please select at least one approver user.")
            )

        if approver_type == "role" and not approver_roles:
            self.add_error(
                "approver_roles", _("Please select at least one approver role.")
            )

        return cleaned_data

    class Meta:
        """Meta class for ReviewProcessRuleForm"""

        model = ReviewRule
        fields = [
            "reviews",
            "approver_type",
            "approver_users",
            "approver_roles",
        ]

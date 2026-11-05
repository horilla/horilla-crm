"""Forms for managing Opportunity-related models in the CRM application."""

# Standard library imports
import logging

# Third-party imports (Django)
from django import forms

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.mixins import OwnerQuerysetMixin
from horilla.contrib.core.models import TeamRole
from horilla.contrib.generics.forms import HorillaModelForm, HorillaMultiStepForm
from horilla.contrib.generics.forms.form_class_mixin import WIDGET_INPUT_CSS_CLASS
from horilla.core.exceptions import FieldDoesNotExist, ValidationError
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.text import select_placeholder
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.opportunities.models import (
    DefaultOpportunityMember,
    Opportunity,
    OpportunityStage,
    OpportunityTeam,
    OpportunityTeamMember,
)

logger = logging.getLogger(__name__)


# Shared with `StageProbabilityFieldView`, which re-renders this exact input
# (with an updated value) whenever the Stage field changes.
PROBABILITY_FIELD_ID = "id_probability"
PROBABILITY_WIDGET_ATTRS = {
    "id": PROBABILITY_FIELD_ID,
    "step": "0.01",
    "readonly": "readonly",
    "data-readonly": "true",
    "tabindex": "-1",
    "placeholder": _("Auto-Calculated from Stage"),
    "class": (
        f"{WIDGET_INPUT_CSS_CLASS} bg-gray-200 border-gray-300 cursor-not-allowed opacity-75"
    ),
}


def _make_probability_readonly(form):
    """Make the ``probability`` field read-only since it is auto-calculated from the stage."""
    field = form.fields.get("probability")
    if not field:
        return
    field.required = False
    field.widget.attrs.update(PROBABILITY_WIDGET_ATTRS)


def _wire_stage_probability_refresh(form):
    """Refresh the read-only probability field via htmx whenever Stage changes."""
    stage_field = form.fields.get("stage")
    if not stage_field:
        return
    stage_field.widget.attrs.update(
        {
            "hx-get": reverse_lazy("opportunities:stage_probability_field"),
            "hx-trigger": "change",
            "hx-target": f"#{PROBABILITY_FIELD_ID}",
            "hx-swap": "outerHTML",
        }
    )


def render_probability_input(value=None):
    """Render the read-only probability ``<input>`` for the given value.

    Used by the stage-change AJAX endpoint to refresh the field in place.
    """
    widget = forms.NumberInput(attrs=PROBABILITY_WIDGET_ATTRS)
    return widget.render(name="probability", value=value)


class OpportunityFormClass(OwnerQuerysetMixin, HorillaMultiStepForm):
    """Multi-step form for creating/editing Opportunity instances.
    Inherits from HorillaMultiStepForm to preserve all existing behavior.
    """

    class Meta:
        """Meta options for OpportunityFormClass."""

        model = Opportunity
        fields = "__all__"
        exclude = [
            "forecast_category",
            "expected_revenue",
            "opportunity_score",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": _("e.g. Acme Corp - Annual License Renewal")}
            ),
        }

    step_fields = {
        1: [
            "name",
            "amount",
            "email",
            "quantity",
            "close_date",
            "stage",
            "probability",
            "account",
            "lead_source",
            "opportunity_type",
            "primary_campaign_source",
            "next_step",
            "owner",
        ],
        2: [
            "order_number",
            "delivery_installation_status",
            "tracking_number",
            "main_competitors",
        ],
        3: ["description"],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _make_probability_readonly(self)
        _wire_stage_probability_refresh(self)


class OpportunitySingleForm(OwnerQuerysetMixin, HorillaModelForm):
    """
    Custom form for opportunity to add HTMX attributes
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = fields = [
        "name",
        "amount",
        "email",
        "quantity",
        "close_date",
        "stage",
        "probability",
        "account",
        "lead_source",
        "opportunity_type",
        "primary_campaign_source",
        "next_step",
        "owner",
        "order_number",
        "delivery_installation_status",
        "tracking_number",
        "main_competitors",
        "description",
    ]

    class Meta:
        """Meta class for OpportunitySingleForm"""

        model = Opportunity
        fields = "__all__"
        exclude = [
            "forecast_category",
            "expected_revenue",
            "opportunity_score",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": _("e.g. Acme Corp - Annual License Renewal")}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _make_probability_readonly(self)
        _wire_stage_probability_refresh(self)


class OpportunityStageForm(HorillaModelForm):
    """
    Custom form for LeadStatus to add HTMX attributes to is_final field.
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = ["name", "probability", "is_final", "order", "stage_type"]

    class Meta:
        """Meta options for OpportunityStageForm."""

        model = OpportunityStage
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "is_final" in self.fields:
            self.fields["is_final"].widget.attrs.update(
                {
                    "hx-post": reverse_lazy("opportunities:toggle_order_field"),
                    "hx-target": "#order_container",
                    "hx-swap": "outerHTML",
                    "hx-trigger": "change",
                }
            )
        if "order" in self.fields:
            # The order field is hidden client-side when "is_final" is checked,
            # so it may not be submitted at all. The model auto-assigns the
            # next available order on save when left blank.
            self.fields["order"].required = False


class OpportunityTeamForm(HorillaModelForm):
    """Custom form for OpportunityTeam to manage team members for opportunities."""

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        kwargs["condition_model"] = DefaultOpportunityMember
        self.instance_obj = kwargs.get("instance")

        model_name = None
        request = kwargs.get("request")
        if request:
            model_name = request.GET.get("model_name") or request.POST.get("model_name")

        # Set up condition field choices similar to ScoringCriterionForm
        condition_field_choices = self._get_condition_field_choices(request=request)
        kwargs["condition_field_choices"] = condition_field_choices

        super().__init__(*args, **kwargs)
        self.model_name = model_name or ""
        self.condition_field_choices = condition_field_choices

        # Set initial values for condition fields in edit mode
        if self.instance_obj and self.instance_obj.pk:
            self._set_initial_condition_values()

    def _get_condition_field_choices(self, request=None):
        """Get condition field choices for OpportunityTeam form"""
        condition_field_choices = {}

        try:
            user_choices = [("", "---------")]
            user_qs = User.objects.all()
            if (
                request
                and hasattr(request, "active_company")
                and request.active_company
            ):
                user_qs = user_qs.filter(company=request.active_company)
            users = user_qs
            user_choices.extend([(user.pk, str(user)) for user in users])
            condition_field_choices["user"] = user_choices

            # Get choices for team_role field (assuming it has choices)
            team_role_field = DefaultOpportunityMember._meta.get_field("team_role")
            if hasattr(team_role_field, "choices") and team_role_field.choices:
                condition_field_choices["team_role"] = [("", "---------")] + list(
                    team_role_field.choices
                )

            # Get choices for opportunity_access_level field (assuming it has choices)
            access_level_field = DefaultOpportunityMember._meta.get_field(
                "opportunity_access_level"
            )
            if hasattr(access_level_field, "choices") and access_level_field.choices:
                condition_field_choices["opportunity_access_level"] = [
                    ("", "---------")
                ] + list(access_level_field.choices)

        except Exception as e:
            logger.error("Error getting condition field choices: %s", e)

        return condition_field_choices

    def _add_condition_fields(self):
        """Override to add properly configured condition fields"""
        for field_name in self.condition_fields:
            try:
                model_field = self.condition_model._meta.get_field(field_name)

                # Create base field (for row 0 and template access)
                if field_name == "user" and field_name in self.condition_field_choices:
                    form_field = forms.ChoiceField(
                        choices=self.condition_field_choices[field_name],
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": select_placeholder(
                                    model_field.verbose_name
                                ),
                                "id": f"id_{field_name}_0",
                                "name": f"{field_name}_0",
                            }
                        ),
                    )
                elif field_name in self.condition_field_choices:
                    form_field = forms.ChoiceField(
                        choices=self.condition_field_choices[field_name],
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": select_placeholder(
                                    model_field.verbose_name
                                ),
                                "id": f"id_{field_name}_0",
                                "name": f"{field_name}_0",
                            }
                        ),
                    )
                elif isinstance(model_field, models.ForeignKey):
                    # Handle ForeignKey fields
                    related_model = model_field.related_model
                    app_label = related_model._meta.app_label
                    model_name = related_model._meta.model_name

                    initial_choices = []
                    try:
                        queryset = related_model.objects.all()[:100]
                        initial_choices = [(obj.pk, str(obj)) for obj in queryset]
                    except Exception as e:
                        logger.error("Error fetching choices for %s: %s", field_name, e)

                    form_field = forms.ChoiceField(
                        choices=[("", "---------")] + initial_choices,
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "select2-pagination w-full",
                                "data-url": reverse_lazy(
                                    "generics:model_select2",
                                    kwargs={
                                        "app_label": app_label,
                                        "model_name": model_name,
                                    },
                                ),
                                "data-placeholder": select_placeholder(
                                    model_field.verbose_name
                                ),
                                "data-field-name": field_name,
                                "id": f"id_{field_name}_0",
                                "name": f"{field_name}_0",
                            }
                        ),
                    )
                elif hasattr(model_field, "choices") and model_field.choices:
                    form_field = forms.ChoiceField(
                        choices=[("", "---------")] + list(model_field.choices),
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": select_placeholder(
                                    model_field.verbose_name
                                ),
                                "id": f"id_{field_name}_0",
                                "name": f"{field_name}_0",
                            }
                        ),
                    )
                else:
                    # Fallback to text input for other field types
                    form_field = forms.CharField(
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.TextInput(
                            attrs={
                                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                                "placeholder": f"Enter {field_name.replace('_', ' ').title()}",
                                "id": f"id_{field_name}_0",
                                "name": f"{field_name}_0",
                            }
                        ),
                    )

                form_field.is_custom_field = True
                self.fields[field_name] = form_field

            except Exception as e:
                logger.error("Error adding condition field %s: %s", field_name, e)

        # Set initial values for edit mode
        self._set_initial_condition_values()

    def _set_initial_condition_values(self):
        """Set initial values for condition fields in edit mode"""
        if not self.instance_obj or not self.instance_obj.pk:
            return

        # Get existing team members (conditions) ordered by creation
        existing_members = DefaultOpportunityMember.objects.filter(
            team=self.instance_obj
        ).order_by("created_at")

        if hasattr(self, "row_id") and self.row_id != "0":
            return

        if existing_members.exists():
            first_member = existing_members.first()
            for field_name in self.condition_fields:
                if field_name in self.fields:
                    value = getattr(first_member, field_name, "")
                    # Convert FK instances to PKs so ChoiceField initial matches option values
                    if hasattr(value, "pk"):
                        value = value.pk

                    self.fields[field_name].initial = value
                    field_key_0 = f"{field_name}_0"
                    if field_key_0 in self.fields:
                        self.fields[field_key_0].initial = value

    def _extract_condition_rows(self):
        """Extract condition rows from form data"""
        condition_rows = []
        row_ids = set()

        # Identify all row IDs from form data (e.g., user_0, team_role_1)
        for field_name in self.data:
            if "_" in field_name:
                base_name, row_id = field_name.rsplit("_", 1)
                if base_name in self.condition_fields and row_id.isdigit():
                    row_ids.add(row_id)

        for row_id in sorted(row_ids, key=int):
            row_data = {}
            valid_row = True
            for field_name in self.condition_fields:
                form_field_name = f"{field_name}_{row_id}"
                if form_field_name in self.data:
                    value = self.data.get(form_field_name)
                    if value:
                        if field_name == "user":
                            try:
                                value = User.objects.get(pk=value)
                            except (User.DoesNotExist, ValueError):
                                self.add_error(
                                    None, f"Invalid user selected for row {row_id}"
                                )
                                valid_row = False
                                continue
                        if field_name == "team_role":
                            try:
                                value = TeamRole.objects.get(pk=value)
                            except (TeamRole.DoesNotExist, ValueError):
                                self.add_error(
                                    None,
                                    f"Invalid team role selected for row {row_id}",
                                )
                                valid_row = False
                                continue
                        # Validate choices for fields with choices (e.g., opportunity_access_level)
                        model_field = self.condition_model._meta.get_field(field_name)
                        if hasattr(model_field, "choices") and model_field.choices:
                            choice_values = [
                                choice[0] for choice in model_field.choices
                            ]
                            if value not in choice_values:
                                self.add_error(
                                    None,
                                    f"Invalid {field_name} selected for row {row_id}",
                                )
                                valid_row = False
                                continue
                        row_data[field_name] = value
            if row_data:
                # Validate mandatory condition fields so we show form errors
                # instead of defaulting or hitting NOT NULL in the DB
                missing_mandatory = []
                for field_name in self.condition_fields:
                    try:
                        model_field = self.condition_model._meta.get_field(field_name)
                    except FieldDoesNotExist:
                        continue
                    if model_field.null or model_field.blank:
                        continue
                    if not row_data.get(field_name):
                        label = model_field.verbose_name or field_name
                        missing_mandatory.append(str(label) if label else field_name)
                if missing_mandatory:
                    self.add_error(
                        None,
                        _(
                            "%(fields)s is required for each team member (row %(row_id)s)."
                        )
                        % {
                            "row_id": row_id,
                            "fields": ", ".join(missing_mandatory),
                        },
                    )
                    valid_row = False
                if valid_row:
                    condition_rows.append(row_data)
        return condition_rows

    def clean(self):
        """Process multiple condition rows from form data"""
        cleaned_data = super().clean()

        condition_rows = self._extract_condition_rows()

        if not condition_rows:
            raise ValidationError(
                _("At least one valid condition row must be provided.")
            )

        cleaned_data["condition_rows"] = condition_rows

        return cleaned_data

    class Meta:
        """Meta options for OpportunityTeamForm."""

        model = OpportunityTeam
        fields = "__all__"
        exclude = ["owner"]


class OpportunityTeamMemberForm(HorillaModelForm):
    """Form for managing Opportunity Team Members."""

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        request = kwargs.get("request")
        kwargs["condition_field_choices"] = self._get_condition_field_choices(
            request=request
        )
        super().__init__(*args, **kwargs)

    def _get_condition_field_choices(self, request=None):
        """Scope the user condition field to the active company."""
        user_choices = [("", "---------")]
        user_qs = User.objects.all()
        if request and getattr(request, "active_company", None):
            user_qs = user_qs.filter(company=request.active_company)
        user_choices.extend([(user.pk, str(user)) for user in user_qs])
        return {"user": user_choices}

    class Meta:
        """Meta options for OpportunityTeamMemberForm."""

        model = DefaultOpportunityMember
        fields = ["team"]


class OpportunityMemberForm(HorillaModelForm):
    """Form for managing Opportunity Team Members."""

    def __init__(self, *args, **kwargs):
        self.row_id = kwargs.pop("row_id", "0")
        request = kwargs.get("request")
        kwargs["condition_field_choices"] = self._get_condition_field_choices(
            request=request
        )
        super().__init__(*args, **kwargs)

    def _get_condition_field_choices(self, request=None):
        """Scope the user condition field to the active company."""
        user_choices = [("", "---------")]
        user_qs = User.objects.all()
        if request and getattr(request, "active_company", None):
            user_qs = user_qs.filter(company=request.active_company)
        user_choices.extend([(user.pk, str(user)) for user in user_qs])
        return {"user": user_choices}

    class Meta:
        """Meta options for OpportunityMemberForm."""

        model = OpportunityTeamMember
        fields = ["opportunity"]


class AddDefaultTeamForm(forms.Form):
    """Form to select an OpportunityTeam to add its default members"""

    team = forms.ModelChoiceField(
        queryset=OpportunityTeam.objects.none(),
        label=_("Select Team"),
        help_text=_("Select a team to add all its default members to this opportunity"),
        widget=forms.Select(
            {
                "class": "js-example-basic-single headselect w-full",
                "id": "id_team",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        # Remove HorillaSingleFormView specific kwargs
        kwargs.pop("full_width_fields", None)
        kwargs.pop("dynamic_create_fields", None)
        kwargs.pop("condition_fields", None)
        kwargs.pop("condition_model", None)
        kwargs.pop("condition_field_choices", None)
        kwargs.pop("condition_related_name", None)
        kwargs.pop("condition_related_name_candidates", None)
        kwargs.pop("hidden_fields", None)
        kwargs.pop("row_id", None)
        self.request = kwargs.pop("request", None)
        self.opportunity = kwargs.pop("opportunity", None)
        self.condition_hx_include = kwargs.pop("condition_hx_include", "")
        self.field_permissions = kwargs.pop("field_permissions", {})
        self.save_and_new = kwargs.pop("save_and_new", "")
        self.duplicate_mode = kwargs.pop("duplicate_mode", False)
        self.row_id = kwargs.pop("row_id", "0")
        self.instance_obj = kwargs.get(
            "instance"
        )  # Store instance for condition methods
        self.model_name = kwargs.pop("model_name", None)
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = OpportunityTeam.objects.filter(
            owner=self.request.user
        )

"""
Scoring rule and criterion models for lead/opportunity/account/contact scoring.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.utils.dateparse import parse_date, parse_datetime

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.utils.methods import render_template

# First-party / Horilla imports
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class ScoringRule(HorillaCoreModel):
    """Scoring rule for calculating lead/opportunity/account/contact scores."""

    name = models.CharField(max_length=100, verbose_name=_("Rule Name"))
    module = models.ForeignKey(
        HorillaContentType,
        on_delete=models.PROTECT,
        verbose_name=_("Module"),
        limit_choices_to=limit_content_types("scoring_models"),
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    def __str__(self):
        return str(self.name)

    def is_active_col(self):
        """Return HTML for active status column."""
        html = render_template(
            path="components/toggle_active_col.html",
            context={
                "instance": self,
                "toggle_url": reverse_lazy(
                    "scoring_rules:scoring_rule_activate", kwargs={"pk": self.pk}
                ),
            },
        )
        return html

    def get_edit_url(self):
        """Return the edit URL for this scoring rule."""
        return reverse_lazy(
            "scoring_rules:scoring_rule_update_form", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """Return the delete URL for this scoring rule."""
        return reverse_lazy(
            "scoring_rules:scoring_rule_delete_view", kwargs={"pk": self.pk}
        )

    def get_detail_view_url(self):
        """Return the detail view URL for this scoring rule."""
        return reverse_lazy(
            "scoring_rules:scoring_rule_detail_view", kwargs={"pk": self.pk}
        )

    class Meta:
        """Meta options for the Scoring Rule model."""

        verbose_name = _("Scoring Rule")
        verbose_name_plural = _("Scoring Rules")
        indexes = [
            # partial index — only active rules, the ones always queried
            models.Index(
                fields=["module"],
                condition=models.Q(is_active=True),
                name="idx_scoring_rule_active_module",
            )
        ]


class ScoringCriterion(HorillaCoreModel):
    """Main scoring criterion that contains multiple conditions"""

    rule = models.ForeignKey(
        ScoringRule, on_delete=models.CASCADE, related_name="criteria"
    )
    name = models.CharField(
        max_length=200, blank=True, verbose_name=_("Criterion Name")
    )
    points = models.IntegerField(verbose_name=_("Points to Award"))
    operation_type = models.CharField(
        max_length=3,
        choices=[("add", _("Add")), ("sub", _("Sub"))],
        default="and",
        verbose_name=_("Operation Type"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))

    def __str__(self):
        return f"{self.rule.name} - {self.name or f'Criterion {self.pk}'}"

    def evaluate_conditions(self, instance):
        """
        Evaluate all conditions for this criterion against the given instance.
        Returns True if all conditions are met according to their logical operators.

        Uses ``self.conditions.all()`` (rather than re-ordering/calling
        ``.exists()``) so a prefetched ``conditions`` queryset is served from
        cache instead of issuing a fresh query per criterion.
        """
        conditions = list(self.conditions.all())
        if not conditions:
            return False

        # A condition's logical operator joins it to the NEXT condition, which
        # is how the form and detail view present it.
        result = None
        previous_operator = "and"
        for condition in conditions:
            condition_result = condition.evaluate(instance)
            if result is None:
                result = condition_result
            elif previous_operator == "and":
                result = result and condition_result
            else:
                result = result or condition_result
            previous_operator = condition.logical_operator

        return result

    class Meta:
        """Meta options for ScoringCriterion."""

        verbose_name = _("Scoring Criterion")
        verbose_name_plural = _("Scoring Criteria")
        ordering = ["order", "id"]


def _evaluate_date_comparison(op, raw_value, value, is_date_field):
    """Evaluate equals/not_equals/gt/gte/lt/lte for a date/datetime operator."""
    comp = parse_date(value) if is_date_field else parse_datetime(value)
    if op == "equals":
        if comp is None:
            return str(raw_value) == value
        return raw_value is not None and raw_value == comp
    if op == "not_equals":
        if comp is None:
            return str(raw_value) != value
        return raw_value is None or raw_value != comp
    if comp is None or raw_value is None:
        return False
    if op == "greater_than":
        return raw_value > comp
    if op == "greater_than_equal":
        return raw_value >= comp
    if op == "less_than":
        return raw_value < comp
    return raw_value <= comp


def _evaluate_date_between(raw_value, value, is_date_field):
    """Evaluate the "between" operator for a date/datetime field."""
    parts = [p.strip() for p in value.split(",", 1) if p.strip()]
    if len(parts) >= 2:
        start_val = parse_date(parts[0]) if is_date_field else parse_datetime(parts[0])
        end_val = parse_date(parts[1]) if is_date_field else parse_datetime(parts[1])
        if start_val and end_val and raw_value is not None:
            return start_val <= raw_value <= end_val
    return False


def _evaluate_date_operator(op, raw_value, value, is_date_field):
    """
    Evaluate a date/datetime operator (already normalized). Returns True/False
    when the operator is handled, or None to signal that the caller should
    fall through to the generic operator handling.
    """
    if op == "is_empty":
        return raw_value is None
    if op == "is_not_empty":
        return raw_value is not None
    if op in (
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
    ):
        return _evaluate_date_comparison(op, raw_value, value, is_date_field)
    if op == "between":
        return _evaluate_date_between(raw_value, value, is_date_field)
    return None


def _evaluate_text_operator(op, field_value, value):
    if op == "equals":
        return field_value == value
    if op == "not_equals":
        return field_value != value
    if op == "contains":
        return value.lower() in field_value.lower()
    if op == "not_contains":
        return value.lower() not in field_value.lower()
    if op == "starts_with":
        return field_value.lower().startswith(value.lower())
    return field_value.lower().endswith(value.lower())


def _evaluate_numeric_operator(op, field_value, value):
    try:
        if op == "between":
            low, high = (float(p) for p in value.split(",", 1))
            return low <= float(field_value) <= high
        if op == "greater_than":
            return float(field_value) > float(value)
        if op == "greater_than_equal":
            return float(field_value) >= float(value)
        if op == "less_than":
            return float(field_value) < float(value)
        return float(field_value) <= float(value)
    except (ValueError, TypeError):
        return False


def _evaluate_generic_operator(op, field_value, value):
    """Evaluate a generic string/numeric operator and return True/False."""
    if op in (
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
    ):
        return _evaluate_text_operator(op, field_value, value)
    if op in (
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "between",
    ):
        return _evaluate_numeric_operator(op, field_value, value)
    if op == "is_empty":
        return not field_value or field_value.strip() == ""
    if op == "is_not_empty":
        return bool(field_value and field_value.strip())

    return False


# The condition form stores Django-lookup style operators (OPERATOR_CHOICES);
# the evaluators below work with the descriptive names.
_FILTER_TO_SCORING_OPERATOR = {
    "exact": "equals",
    "ne": "not_equals",
    "icontains": "contains",
    "istartswith": "starts_with",
    "iendswith": "ends_with",
    "gt": "greater_than",
    "gte": "greater_than_equal",
    "lt": "less_than",
    "lte": "less_than_equal",
    "isnull": "is_empty",
    "isnotnull": "is_not_empty",
}


def normalize_scoring_operator(op):
    """Map a stored operator (e.g. ``gte``) to the name the evaluators use."""
    return _FILTER_TO_SCORING_OPERATOR.get(op, op)


def _compare_scoring_text(op, left, right):
    """Compare ``left`` and ``right`` (strings) with a scoring operator."""
    return _evaluate_generic_operator(normalize_scoring_operator(op), left, right)


@permission_exempt_model
class ScoringCondition(HorillaCoreModel):
    """Individual conditions within a scoring criterion"""

    criterion = models.ForeignKey(
        ScoringCriterion, on_delete=models.CASCADE, related_name="conditions"
    )
    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50,
        choices=OPERATOR_CHOICES,
        verbose_name=_("Operator"),
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))

    def __str__(self):
        return f"{self.field} {self.operator} {self.value}"

    def evaluate(self, instance):
        """
        Evaluate this condition against the given instance.
        Returns True if the condition is met, False otherwise.
        """
        try:
            from horilla.contrib.generics.forms.condition_fields import (
                evaluate_extension_condition,
            )

            # Fields contributed by other apps (e.g. custom fields) aren't columns.
            handled, extension_result = evaluate_extension_condition(
                self.field, instance, self.operator, self.value, _compare_scoring_text
            )
            if handled:
                return extension_result

            from horilla.contrib.generics.related_fields import resolve_instance_path

            # "owner__department" reads the field off the related record.
            target, field_name = resolve_instance_path(instance, self.field)
            field = target._meta.get_field(field_name)
            raw_value = getattr(target, field_name, None)
            field_type = getattr(field, "get_internal_type", lambda: "")()
            is_date_field = field_type == "DateField"
            is_datetime_field = field_type == "DateTimeField"
            value = self.value or ""
            op = normalize_scoring_operator(self.operator)

            if is_date_field or is_datetime_field:
                date_result = _evaluate_date_operator(
                    op, raw_value, value, is_date_field
                )
                if date_result is not None:
                    return date_result

            field_value = "" if raw_value is None else str(raw_value)

            return _evaluate_generic_operator(op, field_value, value)

        except Exception as e:
            logger.error("Error evaluating condition %s: %s", self, e)
            return False

    class Meta:
        """Meta options for ScoringCondition."""

        verbose_name = _("Scoring Condition")
        verbose_name_plural = _("Scoring Conditions")
        ordering = ["order", "id"]


@permission_exempt_model
class EmailActivityScoring(HorillaCoreModel):
    """Email activity scoring configuration."""

    rule = models.ForeignKey(
        ScoringRule, on_delete=models.CASCADE, related_name="email_activities"
    )
    activity_type = models.CharField(
        max_length=50,
        choices=[
            ("opened", _("Opened")),
            ("clicked", _("Clicked")),
            ("bounced", _("Bounced")),
        ],
    )
    points = models.IntegerField(default=10)

    def __str__(self):
        return f"{self.activity_type} - {self.points} points"

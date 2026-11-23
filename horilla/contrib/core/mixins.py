"""Mixin classes for Django views and forms.

This module provides reusable mixin classes that can be added to Django views,
forms, and filtersets to add common functionality:

- FiscalYearCalendarMixin: Generates fiscal year calendar data with custom configurations
- OwnerQuerysetMixin: Restricts User field querysets based on permissions and role hierarchy
- OwnerFiltersetMixin: Restricts User filter querysets based on permissions and role hierarchy
"""

import calendar as cal_module
from calendar import monthcalendar

# Standard library imports
from datetime import datetime, timedelta

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.utils.middlewares import get_active_company


class FiscalYearCalendarMixin:
    """Mixin to generate fiscal year calendar data based on configuration."""

    def get_calendar_data(
        self,
        fiscal_year_data,
        start_date_month,
        start_date_day,
        week_start_day,
        current_year=None,
    ):
        """Generate fiscal year calendar data."""
        if current_year is None:
            current_year = datetime.now().year

        # Extract fiscal year attributes
        fiscal_year_type = fiscal_year_data.get("fiscal_year_type", "standard")
        format_type = fiscal_year_data.get("format_type", "")
        year_based_format = fiscal_year_data.get("year_based_format", "")
        quarter_based_format = fiscal_year_data.get("quarter_based_format", "")
        number_weeks_by = fiscal_year_data.get("number_weeks_by", "year")
        period_display_option = fiscal_year_data.get(
            "period_display_option", "number_by_year"
        )

        # Month mapping for handling month names and abbreviations
        month_mapping = {
            "january": 0,
            "jan": 0,
            "february": 1,
            "feb": 1,
            "march": 2,
            "mar": 2,
            "april": 3,
            "apr": 3,
            "may": 4,
            "june": 5,
            "jun": 5,
            "july": 6,
            "jul": 6,
            "august": 7,
            "aug": 7,
            "september": 8,
            "sep": 8,
            "october": 9,
            "oct": 9,
            "november": 10,
            "nov": 10,
            "december": 11,
            "dec": 11,
        }

        # Get month index using the mapping
        month_index = month_mapping.get(
            start_date_month.lower(), 0
        )  # Default to January
        start_date = datetime(current_year, month_index + 1, start_date_day)

        # Normalize week_start_day (handles both short codes like "thu" and full names)
        day_code_mapping = {
            "sun": "sunday",
            "mon": "monday",
            "tue": "tuesday",
            "wed": "wednesday",
            "thu": "thursday",
            "fri": "friday",
            "sat": "saturday",
        }
        if week_start_day:
            week_start_day_normalized = week_start_day.lower()
            week_start_day_normalized = day_code_mapping.get(
                week_start_day_normalized, week_start_day_normalized
            )
        else:
            week_start_day_normalized = "monday"

        # Define days of the week and order them based on normalized week_start_day
        days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        if week_start_day_normalized in days:
            start_index = days.index(week_start_day_normalized)
            ordered_days = days[start_index:] + days[:start_index]
        else:
            ordered_days = days

        current_date = start_date

        def create_week_data(
            week_number, start_date, days_in_week, week_start_day_index
        ):
            week_rows = []
            current_week_date = start_date
            days_added = 0

            while days_added < days_in_week:
                current_day_of_week = current_week_date.weekday()
                if week_start_day_normalized == "monday":
                    start_day_index = current_day_of_week
                elif week_start_day_normalized == "sunday":
                    start_day_index = (current_day_of_week + 1) % 7
                else:
                    days_mapping = {
                        "monday": 0,
                        "tuesday": 1,
                        "wednesday": 2,
                        "thursday": 3,
                        "friday": 4,
                        "saturday": 5,
                        "sunday": 6,
                    }
                    week_start_index = days_mapping[week_start_day_normalized]
                    start_day_index = (current_day_of_week - week_start_index) % 7

                row_days = [None] * 7  # Initialize with None for empty cells
                row_months = []

                days_in_this_row = min(7 - start_day_index, days_in_week - days_added)
                for i in range(days_in_this_row):
                    day_index = start_day_index + i
                    row_days[day_index] = current_week_date.day
                    row_months.append(current_week_date.strftime("%b"))
                    current_week_date += timedelta(days=1)
                    days_added += 1

                unique_months = []
                for month in row_months:
                    if month not in unique_months:
                        unique_months.append(month)

                month_display = (
                    unique_months[0]
                    if len(unique_months) == 1
                    else "/".join(unique_months)
                )
                week_rows.append(
                    {
                        "week_number": week_number,
                        "month": month_display,
                        "days": row_days,
                    }
                )

                if days_added < days_in_week:
                    start_day_index = 0

            return week_rows, current_week_date

        calendar_data = []
        period_counter = 1
        week_counter = 1

        if fiscal_year_type == "standard":
            fiscal_months = []
            start_month = month_index + 1
            for i in range(12):
                month_num = ((start_month - 1 + i) % 12) + 1
                year = current_year if (start_month + i - 1) < 12 else current_year + 1
                fiscal_months.append((year, month_num))

            for quarter in range(1, 5):
                quarter_periods = []
                quarter_start_idx = (quarter - 1) * 3
                for p in range(3):
                    month_idx = quarter_start_idx + p
                    year, month_num = fiscal_months[month_idx]
                    month_name = datetime(year, month_num, 1).strftime("%B")

                    if week_start_day_normalized == "sunday":
                        cal_module.setfirstweekday(6)
                        cal = cal_module.monthcalendar(year, month_num)
                        cal_module.setfirstweekday(0)
                    else:
                        cal = monthcalendar(year, month_num)

                    weeks = [
                        [day if day != 0 else None for day in week] for week in cal
                    ]
                    quarter_periods.append(
                        {
                            "period_number": p + 1,
                            "weeks": weeks,
                            "month_name": month_name,
                            "is_standard": True,
                        }
                    )
                calendar_data.append(
                    {"quarter_number": quarter, "periods": quarter_periods}
                )

        elif (
            fiscal_year_type == "custom"
            and format_type == "year_based"
            and year_based_format
        ):
            periods_per_quarter = [int(p) for p in year_based_format.split("-")]
            for quarter, num_periods in enumerate(periods_per_quarter, 1):
                quarter_periods = []
                quarter_week_counter = 1
                for p in range(num_periods):
                    weeks = []
                    period_week_counter = 1
                    for w in range(1, 5):
                        week_number = (
                            week_counter
                            if number_weeks_by == "year"
                            else (
                                quarter_week_counter
                                if number_weeks_by == "quarter"
                                else period_week_counter
                            )
                        )
                        week_start_day_index = days.index(week_start_day_normalized)
                        week_rows, current_date = create_week_data(
                            week_number, current_date, 7, week_start_day_index
                        )
                        weeks.extend(week_rows)
                        week_counter += 1
                        quarter_week_counter += 1
                        period_week_counter += 1
                    period_number = (
                        period_counter
                        if period_display_option == "number_by_year"
                        else p + 1
                    )
                    quarter_periods.append(
                        {
                            "period_number": period_number,
                            "weeks": weeks,
                            "is_standard": False,
                        }
                    )
                    period_counter += 1
                calendar_data.append(
                    {"quarter_number": quarter, "periods": quarter_periods}
                )

        elif (
            fiscal_year_type == "custom"
            and format_type == "quarter_based"
            and quarter_based_format
        ):
            weeks_per_period = [int(w) for w in quarter_based_format.split("-")]
            for quarter in range(1, 5):
                quarter_periods = []
                quarter_week_counter = 1
                for p, num_weeks in enumerate(weeks_per_period, 1):
                    weeks = []
                    period_week_counter = 1
                    for w in range(1, num_weeks + 1):
                        week_number = (
                            week_counter
                            if number_weeks_by == "year"
                            else (
                                quarter_week_counter
                                if number_weeks_by == "quarter"
                                else period_week_counter
                            )
                        )
                        week_start_day_index = days.index(week_start_day_normalized)
                        week_rows, current_date = create_week_data(
                            week_number, current_date, 7, week_start_day_index
                        )
                        weeks.extend(week_rows)
                        week_counter += 1
                        quarter_week_counter += 1
                        period_week_counter += 1
                    period_number = (
                        period_counter
                        if period_display_option == "number_by_year"
                        else p
                    )
                    quarter_periods.append(
                        {
                            "period_number": period_number,
                            "weeks": weeks,
                            "is_standard": False,
                        }
                    )
                    period_counter += 1
                calendar_data.append(
                    {"quarter_number": quarter, "periods": quarter_periods}
                )

        return {
            "calendar_data": calendar_data,
            "ordered_days": [day[:3].capitalize() for day in ordered_days],
            "number_weeks_by": number_weeks_by,
            "period_display_option": period_display_option,
            "fiscal_year_type": fiscal_year_type,
        }


def get_allowed_users_queryset_for_model(user, model):
    """
    Return the allowed User queryset for owner-style fields on the given model,
    based on add/add_own permissions and role hierarchy (same logic as OwnerQuerysetMixin).

    - Superuser or add_<model> permission: all active users.
    - add_own_<model> permission: current user + users in subordinate roles.
    - Otherwise: only the current user.

    Used by OwnerQuerysetMixin and by bulk update/filter views so owner dropdowns
    show the same options as create/edit forms.
    """
    if not user:
        return User.objects.none()

    app_label = model._meta.app_label
    model_name = model._meta.model_name
    change_perm = f"{app_label}.change_{model_name}"
    change_own_perm = f"{app_label}.change_own_{model_name}"

    if user.is_superuser or user.has_perm(change_perm):
        return User.objects.filter(is_active=True)

    if user.has_perm(change_own_perm):
        from horilla.contrib.core.utils import get_allowed_user_ids

        return User.objects.filter(id__in=get_allowed_user_ids(user), is_active=True)

    return User.objects.filter(id=user.id, is_active=True)


class OwnerQuerysetMixin:
    """
    Mixin to dynamically filter any ForeignKey or ManyToManyField
    whose related model is `User`, based on the current user.

    - For superusers: Shows all users.
    - For non-superusers: Shows the current user + their subordinates (recursive via subroles).
    """

    def __init__(self, *args, **kwargs):
        # Get instance from kwargs before super() is called
        # This is important because after super().__init__(), instance might be None for new objects
        instance_from_kwargs = kwargs.get("instance")
        super().__init__(*args, **kwargs)
        request = kwargs.get("request") or getattr(self, "request", None)
        user = request.user if request else None

        if not (user and hasattr(self, "fields")):
            return

        model = self._meta.model

        app_label = model._meta.app_label
        model_name = model._meta.model_name

        # Use change/change_own when editing (instance with pk), add/add_own when creating
        instance = (
            instance_from_kwargs
            or getattr(self, "instance", None)
            or getattr(self, "instance_obj", None)
        )
        is_edit = instance and hasattr(instance, "pk") and instance.pk
        if is_edit:
            action_perm = f"{app_label}.change_{model_name}"
            action_own_perm = f"{app_label}.change_own_{model_name}"
        else:
            action_perm = f"{app_label}.add_{model_name}"
            action_own_perm = f"{app_label}.add_own_{model_name}"

        if user.is_superuser or user.has_perm(action_perm):
            allowed_users = User.objects.all()

        elif user.has_perm(action_own_perm):
            from horilla.contrib.core.utils import get_allowed_user_ids

            allowed_users = User.objects.filter(id__in=get_allowed_user_ids(user))

        else:
            allowed_users = User.objects.filter(id=user.id)

        allowed_users = allowed_users.filter(is_active=True)

        # Get company for filtering foreign key fields
        # Priority: 1. Instance's company (when editing), 2. Active company, 3. User's company
        company = None
        # If editing an existing object, use the object's company
        if (
            instance
            and hasattr(instance, "pk")
            and instance.pk
            and hasattr(instance, "company")
            and instance.company
        ):
            company = instance.company
        elif request:
            company = get_active_company(request)
            if not company and hasattr(request.user, "company"):
                company = request.user.company

        if company:
            allowed_users = allowed_users.filter(company=company)

        for field_name, field in self.fields.items():
            try:
                model_field = self._meta.model._meta.get_field(field_name)
            except Exception:
                continue  # Skip non-model fields

            if model_field.is_relation and model_field.related_model == User:
                field.queryset = allowed_users
            elif model_field.is_relation and hasattr(
                model_field.related_model, "company"
            ):
                if company:
                    if hasattr(field, "queryset") and field.queryset is not None:
                        queryset = field.queryset.filter(company=company)
                    else:
                        queryset = model_field.related_model.objects.filter(
                            company=company
                        )
                    field.queryset = queryset


class OwnerFiltersetMixin:
    """
    Mixin to dynamically filter `User`-related filters
    in a Django FilterSet based on parent model permissions.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get request object
        request = getattr(self, "request", None)
        if not request and hasattr(self, "data") and hasattr(self.data, "_request"):
            request = self.data._request

        user = getattr(request, "user", None)
        if not (user and hasattr(self, "filters")):
            return

        # Get parent model info for permission checking
        parent_model = self._meta.model
        app_label = parent_model._meta.app_label
        model_name = parent_model._meta.model_name

        # Build permission strings
        view_perm = f"{app_label}.view_{model_name}"
        view_own_perm = f"{app_label}.view_own_{model_name}"

        # Determine allowed users based on parent model permissions
        if user.is_superuser or user.has_perm(view_perm):
            # User has full view permission - allow all users
            allowed_users = User.objects.all()
        elif user.has_perm(view_own_perm):
            from horilla.contrib.core.utils import get_allowed_user_ids

            allowed_users = User.objects.filter(id__in=get_allowed_user_ids(user))
        else:
            allowed_users = User.objects.filter(id=user.id)

        # Restrict queryset for filters that reference User
        for field_name, filter_obj in self.filters.items():
            try:
                model_field = self._meta.model._meta.get_field(field_name)
                if model_field.is_relation and model_field.related_model == User:
                    # Restrict the filter's field queryset (used by Select2)
                    if hasattr(filter_obj, "field") and hasattr(
                        filter_obj.field, "queryset"
                    ):
                        filter_obj.field.queryset = allowed_users

                    # Also restrict the filter's queryset if it has one
                    if hasattr(filter_obj, "queryset"):
                        filter_obj.queryset = allowed_users
            except Exception:
                continue

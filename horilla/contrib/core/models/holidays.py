"""
This module defines the Holiday models for holidays in the Horilla platform.
"""

# Standard library imports
import calendar
import logging

# Django imports
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import ordinal
from django.utils import timezone
from django.utils.text import get_text_list

# Third-party imports (Django)
from multiselectfield import MultiSelectField

from horilla.contrib.utils.methods import render_template
from horilla.contrib.utils.middlewares import get_active_company
from horilla.core.exceptions import ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.choices import DAY_CHOICES, MONTH_CHOICES
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.translation import ngettext

# Local imports
from .base import HorillaCoreModel

logger = logging.getLogger(__name__)


def _number_problem(value, bounds, label):
    """Why ``value`` is not a whole number inside ``bounds``, or ``None`` when it is."""
    if value is None:
        return _("%(label)s is required.") % {"label": label}
    low, high = bounds
    if not low <= value <= high:
        return _("%(label)s must be between %(low)s and %(high)s.") % {
            "label": label,
            "low": low,
            "high": high,
        }
    return None


class Holiday(HorillaCoreModel):
    """
    Holiday model for managing company holidays
    """

    FREQUENCY_CHOICES = [
        ("weekly", _("Weekly")),
        ("monthly", _("Monthly")),
        ("yearly", _("Yearly")),
    ]

    MONTHLY_REPEAT_CHOICES = [
        ("day_of_month", _("On Day")),
        ("weekday_of_month", _("On the")),
    ]

    YEARLY_REPEAT_CHOICES = [
        ("day_of_month", _("On every")),  # e.g., July 14th
        ("weekday_of_month", _("On the")),  # e.g., 2nd Monday of July
    ]

    name = models.CharField(max_length=255, verbose_name=_("Holiday Name"))
    start_date = models.DateTimeField(verbose_name=_("Start Date"))
    end_date = models.DateTimeField(verbose_name=_("End Date"))

    all_users = models.BooleanField(default=False, verbose_name=_("All Users"))
    specific_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="holidays",
        verbose_name=_("Specific Users"),
    )

    is_recurring = models.BooleanField(default=False, verbose_name=_("Recurring"))
    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Holiday Frequency"),
    )

    recurs_every_weeks = models.PositiveIntegerField(
        default=1, blank=True, null=True, verbose_name=_("Recurs Every (weeks)")
    )
    weekly_days = MultiSelectField(
        choices=DAY_CHOICES, blank=True, verbose_name=_("Weekly Days")
    )

    monthly_repeat_type = models.CharField(
        max_length=20,
        choices=MONTHLY_REPEAT_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Monthly Repeat Type"),
    )
    monthly_day_of_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Day of Month")
    )
    monthly_interval = models.PositiveIntegerField(
        default=1, blank=True, null=True, verbose_name=_("Monthly Interval")
    )
    monthly_day_of_week = models.CharField(
        max_length=10,
        choices=DAY_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Day of Week"),
    )
    monthly_week_of_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Week of Month")
    )

    yearly_repeat_type = models.CharField(
        max_length=20,
        choices=YEARLY_REPEAT_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Yearly Repeat Type"),
    )
    yearly_week_of_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Week of Month")
    )
    yearly_day_of_month = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Day of Month")
    )
    yearly_day_of_week = models.CharField(
        max_length=10,
        choices=DAY_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Day of Week"),
    )
    yearly_month = models.CharField(
        max_length=15,
        choices=MONTH_CHOICES,
        blank=True,
        null=True,
        verbose_name=_("Month"),
    )

    OWNER_FIELDS = ["specific_users"]

    # Limits shared by ``clean()`` and the number inputs of the form.
    YEAR_RANGE = (1900, 2100)
    MAX_DURATION_DAYS = 366
    WEEKS_INTERVAL_RANGE = (1, 52)
    MONTHS_INTERVAL_RANGE = (1, 12)
    DAY_OF_MONTH_RANGE = (1, 31)
    WEEK_OF_MONTH_RANGE = (1, 5)

    class Meta:
        """
        Meta options for the Holiday model.
        """

        verbose_name = _("Holiday")
        verbose_name_plural = _("Holidays")
        ordering = ["-start_date"]

    def __str__(self):
        return str(self.name)

    def _date_problems(self):
        """``(field, message)`` pairs for the start and end date."""
        problems = []
        low_year, high_year = self.YEAR_RANGE
        for field, label in (
            ("start_date", _("Start date")),
            ("end_date", _("End date")),
        ):
            value = getattr(self, field)
            if value and not low_year <= value.year <= high_year:
                problems.append(
                    (
                        field,
                        _("%(label)s must be in the years %(low)s to %(high)s.")
                        % {"label": label, "low": low_year, "high": high_year},
                    )
                )
        if problems or not (self.start_date and self.end_date):
            return problems
        if self.start_date > self.end_date:
            problems.append(
                ("end_date", _("End date cannot be before the start date."))
            )
        elif (self.end_date - self.start_date).days > self.MAX_DURATION_DAYS:
            problems.append(
                (
                    "end_date",
                    _("A holiday cannot last more than %(days)s days.")
                    % {"days": self.MAX_DURATION_DAYS},
                )
            )
        return problems

    def _weekly_problems(self):
        """``(field, message)`` pairs for a weekly recurrence."""
        problems = []
        if not self.weekly_days:
            problems.append(
                ("weekly_days", _("Select at least one day for weekly recurrence."))
            )
        problems.append(
            (
                "recurs_every_weeks",
                _number_problem(
                    self.recurs_every_weeks,
                    self.WEEKS_INTERVAL_RANGE,
                    _("Recurs every (weeks)"),
                ),
            )
        )
        return problems

    def _monthly_problems(self):
        """``(field, message)`` pairs for a monthly recurrence."""
        kind = self.monthly_repeat_type
        if kind == "day_of_month":
            problems = [
                (
                    "monthly_day_of_month",
                    _number_problem(
                        self.monthly_day_of_month,
                        self.DAY_OF_MONTH_RANGE,
                        _("Day of month"),
                    ),
                )
            ]
            if self.monthly_interval is not None:  # blank means every month
                problems.append(
                    (
                        "monthly_interval",
                        _number_problem(
                            self.monthly_interval,
                            self.MONTHS_INTERVAL_RANGE,
                            _("Monthly interval"),
                        ),
                    )
                )
            return problems
        if kind == "weekday_of_month":
            return self._weekday_of_month_problems(
                "monthly_day_of_week", "monthly_week_of_month"
            )
        return [
            ("monthly_repeat_type", _("Please select a valid monthly repeat type."))
        ]

    def _yearly_problems(self):
        """``(field, message)`` pairs for a yearly recurrence."""
        problems = []
        if not self.yearly_month:
            problems.append(
                ("yearly_month", _("Month is required for yearly recurrence."))
            )
        kind = self.yearly_repeat_type
        if kind == "day_of_month":
            problem = _number_problem(
                self.yearly_day_of_month, self.DAY_OF_MONTH_RANGE, _("Day of month")
            )
            if not problem and self.yearly_month:
                number = [name for name, _label in MONTH_CHOICES].index(
                    self.yearly_month
                )
                # 2024 is a leap year: 29 February is a real date, 30 February is not.
                longest = calendar.monthrange(2024, number + 1)[1]
                if self.yearly_day_of_month > longest:
                    problem = _("%(month)s has at most %(days)s days.") % {
                        "month": dict(MONTH_CHOICES)[self.yearly_month],
                        "days": longest,
                    }
            problems.append(("yearly_day_of_month", problem))
        elif kind == "weekday_of_month":
            problems += self._weekday_of_month_problems(
                "yearly_day_of_week", "yearly_week_of_month"
            )
        else:
            problems.append(
                ("yearly_repeat_type", _("Please select a valid yearly repeat type."))
            )
        return problems

    def _weekday_of_month_problems(self, day_field, week_field):
        """The weekday and the week of the month of an "On the 2nd Monday" rule."""
        problems = []
        if not getattr(self, day_field):
            problems.append((day_field, _("Day of week is required.")))
        problems.append(
            (
                week_field,
                _number_problem(
                    getattr(self, week_field),
                    self.WEEK_OF_MONTH_RANGE,
                    _("Week of month"),
                ),
            )
        )
        return problems

    def clean(self):
        """
        Validate holiday data. Every message is attached to the field it is about, so a
        form shows it under that field and the API or admin can tell which one it is.
        """
        problems = self._date_problems()

        if self.is_recurring:
            if not self.frequency:
                problems.append(
                    (
                        "frequency",
                        _("Frequency is required for recurring holidays."),
                    )
                )
            elif self.frequency == "weekly":
                problems += self._weekly_problems()
            elif self.frequency == "monthly":
                problems += self._monthly_problems()
            elif self.frequency == "yearly":
                problems += self._yearly_problems()

        if self.all_users and not any(
            field.endswith("_date") for field, _m in problems
        ):
            problems.append(
                (
                    "start_date",
                    self.clash_problem(
                        self.company_id,
                        self.start_date,
                        self.end_date,
                        all_users=True,
                        exclude_pk=self.pk,
                    ),
                )
            )

        errors = {}
        for field, message in problems:
            if message:
                errors.setdefault(field, []).append(message)
        if errors:
            raise ValidationError(errors)

    @classmethod
    def clash_problem(
        cls, company_id, start_date, end_date, all_users, user_ids=(), exclude_pk=None
    ):
        """
        The message to show when another holiday already falls on these dates for the
        same people, or ``None``. The name does not matter, only the dates do.

        Company holidays (all users) are unique per dates. Holidays of specific users are
        unique per dates for each user, so two people can still have the same day off.
        A company holiday and a personal one may share dates. ``user_ids`` is only used
        for a holiday of specific users, which is why the form and the API call this with
        the users they were given: a model cannot see them before it is saved.
        """
        company_id = company_id or getattr(get_active_company(), "id", None)
        if not (company_id and start_date and end_date):
            return None
        first = (
            timezone.localtime(start_date)
            if timezone.is_aware(start_date)
            else start_date
        )
        last = timezone.localtime(end_date) if timezone.is_aware(end_date) else end_date
        same = cls.all_objects.filter(
            company_id=company_id,
            start_date__date=first.date(),
            end_date__date=last.date(),
            all_users=all_users,
        )
        if exclude_pk:
            same = same.exclude(pk=exclude_pk)
        if all_users:
            clash = same.first()
            if clash:
                return _(
                    "%(name)s is already a holiday for all users on these dates."
                ) % {"name": clash.name}
            return None
        user_ids = list(user_ids)
        if not user_ids:
            return None
        clash = same.filter(specific_users__in=user_ids).distinct().first()
        if not clash:
            return None
        shared = clash.specific_users.filter(pk__in=user_ids)
        return _("%(name)s is already a holiday on these dates for %(users)s.") % {
            "name": clash.name,
            "users": get_text_list([str(user) for user in shared], str(_("and"))),
        }

    def save(self, *args, **kwargs):
        """
        Override save to perform validation
        """
        self.full_clean()
        super().save(*args, **kwargs)
        if not self.all_users:
            # Business hours only take holidays for all users, so a holiday that was
            # changed to specific users must not stay linked to them.
            self.business_hours.clear()

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.name}&background=random"
        return url

    def get_edit_url(self):
        """
        Get the URL for editing the holiday
        """
        return reverse_lazy("core:holiday_update_form", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """
        Get the URL for holiday detail view
        """
        return reverse_lazy("core:holiday_detail_view", kwargs={"pk": self.pk})

    def get_bh_readonly_detail_url(self):
        """Read-only detail URL used inside the business hour holiday list."""
        return reverse_lazy(
            "core:business_hour_holiday_readonly_detail", kwargs={"pk": self.pk}
        )

    def get_user_detail_url(self):
        """
        Get the URL for holiday detail view for users
        """
        return reverse_lazy("core:user_holiday_detail", kwargs={"pk": self.pk})

    def detail_view_actions(self):
        """
        method for rendering detail view action
        """

        return render_template(
            path="holidays/detail_view_actions.html",
            context={"instance": self},
        )

    def get_delete_url(self):
        """
        Get the URL for deleting the holiday
        """
        return reverse_lazy("core:holiday_delete_view", kwargs={"pk": self.pk})

    def specific_users_enable(self):
        """
        Return user pills if specific users are enabled,
        otherwise a short note when all users are included or none are set
        """
        if self.all_users:
            return "All users are included"
        specific_users = list(self.specific_users.all())
        if specific_users:
            # Local imports: generics template tags import core models
            from horilla.contrib.generics.templatetags.horilla_tags._shared import (
                _get_request_user_company,
            )
            from horilla.contrib.generics.templatetags.horilla_tags.display_tags import (
                render_user_chip_list,
            )

            _request, viewer, _company = _get_request_user_company()
            return render_user_chip_list(
                specific_users,
                viewer,
                self,
                "detail",
                str(self._meta.get_field("specific_users").verbose_name),
            )
        return "No Users specified"

    def holiday_type(self):
        """
        Return comma-separated employee names if specific users are enabled,
        otherwise return 'All users are enabled'
        """
        if self.all_users:
            return "Company Holiday"
        specific_users_qs = self.specific_users.all()
        if specific_users_qs is not None and specific_users_qs.exists():
            # Ensure each user has a valid string representation
            user_names = [str(user) for user in specific_users_qs if str(user).strip()]
            if user_names:
                return "Personal Holiday"
            return "No valid user names found"
        return "No Users specified"

    def get_ordinal_number(self, number):
        """1 -> "1st", 2 -> "2nd", 3 -> "3th", in the active language."""
        return ordinal(number)

    def get_recurrence_description(self):
        """
        How the holiday repeats, in plain words: "Every 2 weeks on Saturday and Sunday",
        "On the 22nd of every month", "On the 2nd Monday of July every year".
        """
        if not self.is_recurring or not self.frequency:
            return _("Not a recurring holiday")

        weekdays, months = dict(DAY_CHOICES), dict(MONTH_CHOICES)

        if self.frequency == "weekly" and self.weekly_days:
            weeks = self.recurs_every_weeks or 1
            return ngettext(
                "Every week on %(days)s", "Every %(count)s weeks on %(days)s", weeks
            ) % {
                "count": weeks,
                "days": get_text_list(
                    [str(weekdays[day]) for day in self.weekly_days], str(_("and"))
                ),
            }

        if self.frequency == "monthly":
            count = self.monthly_interval or 1
            if self.monthly_repeat_type == "day_of_month" and self.monthly_day_of_month:
                which = self.get_ordinal_number(self.monthly_day_of_month)
            elif self.monthly_repeat_type == "weekday_of_month" and (
                self.monthly_week_of_month and self.monthly_day_of_week
            ):
                which = _("%(nth)s %(weekday)s") % {
                    "nth": self.get_ordinal_number(self.monthly_week_of_month),
                    "weekday": weekdays[self.monthly_day_of_week],
                }
            else:
                return _("Recurring holiday")
            return ngettext(
                "On the %(which)s of every month",
                "On the %(which)s of every %(count)s months",
                count,
            ) % {"which": which, "count": count}

        if self.frequency == "yearly" and self.yearly_month:
            month = months[self.yearly_month]
            if self.yearly_repeat_type == "day_of_month" and self.yearly_day_of_month:
                return _("Every year on %(day)s %(month)s") % {
                    "day": self.yearly_day_of_month,
                    "month": month,
                }
            if self.yearly_repeat_type == "weekday_of_month" and (
                self.yearly_week_of_month and self.yearly_day_of_week
            ):
                return _("On the %(nth)s %(weekday)s of %(month)s every year") % {
                    "nth": self.get_ordinal_number(self.yearly_week_of_month),
                    "weekday": weekdays[self.yearly_day_of_week],
                    "month": month,
                }

        return _("Recurring holiday")

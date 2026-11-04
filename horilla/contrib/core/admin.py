"""
Admin configuration for core models.

This module registers core Horilla models with the Django admin
and customizes the admin interface for the Horilla User model.
"""

# Django imports
# Third-party imports (Django)
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError

# Horilla first-party imports
# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.auth_limits import (
    CredentialStoreUnavailable,
    clear_login_failures,
    login_blocked,
    record_login_failure,
    signin_unavailable_message,
)

# Local imports
from .models import (
    ActiveTab,
    BusinessHour,
    Company,
    CustomerRole,
    DatedConversionRate,
    Department,
    DetailFieldVisibility,
    ExportSchedule,
    FieldPermission,
    FiscalYear,
    FiscalYearInstance,
    Holiday,
    HorillaAttachment,
    HorillaContentType,
    ImportHistory,
    KanbanGroupBy,
    ListColumnVisibility,
    MultipleCurrency,
    PartnerRole,
    Period,
    PinnedView,
    Quarter,
    RecentlyViewed,
    RecycleBin,
    RecycleBinPolicy,
    Role,
    SavedFilterList,
    ShiftHour,
    TeamRole,
    TimelineSpanBy,
)


class HorillaAdminAuthenticationForm(AdminAuthenticationForm):
    """Admin login using the same failure limits as the main sign-in page."""

    def clean(self):
        username = self.cleaned_data.get("username") or ""
        try:
            blocked = login_blocked(self.request, username)
        except CredentialStoreUnavailable:
            raise ValidationError(signin_unavailable_message(), code="unavailable")
        if blocked:
            raise ValidationError(blocked, code="locked_out")
        try:
            cleaned = super().clean()
        except ValidationError:
            try:
                blocked = record_login_failure(self.request, username)
            except CredentialStoreUnavailable:
                raise ValidationError(signin_unavailable_message(), code="unavailable")
            if blocked:
                raise ValidationError(blocked, code="locked_out")
            raise
        return cleaned

    def confirm_login_allowed(self, user):
        clear_login_failures(self.request, user.get_username())
        super().confirm_login_allowed(user)


admin.site.login_form = HorillaAdminAuthenticationForm

admin.site.register(KanbanGroupBy)
admin.site.register(TimelineSpanBy)
admin.site.register(ListColumnVisibility)
admin.site.register(PinnedView)
admin.site.register(SavedFilterList)
admin.site.register(MultipleCurrency)
admin.site.register(ActiveTab)
admin.site.register(HorillaContentType)
admin.site.register(Company)
admin.site.register(FiscalYear)
admin.site.register(FiscalYearInstance)
admin.site.register(Quarter)
admin.site.register(Period)
admin.site.register(DatedConversionRate)
admin.site.register(Department)
admin.site.register(RecycleBin)
admin.site.register(PartnerRole)
admin.site.register(CustomerRole)
admin.site.register(TeamRole)
admin.site.register(RecycleBinPolicy)
admin.site.register(RecentlyViewed)
admin.site.register(ImportHistory)
admin.site.register(HorillaAttachment)
admin.site.register(ExportSchedule)
admin.site.register(FieldPermission)
admin.site.register(DetailFieldVisibility)


@admin.register(User)
class HorillaUserAdmin(UserAdmin):
    """
    Custom admin configuration for Horilla User model.
    """

    model = User
    list_display = ["username", "email", "is_active", "is_staff"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal Info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "profile",
                    "contact_number",
                    "city",
                    "state",
                    "country",
                    "zip_code",
                )
            },
        ),
        ("Work Info", {"fields": ("company", "department", "role")}),
        (
            "Preferences",
            {
                "fields": (
                    "language",
                    "time_zone",
                    "currency",
                    "time_format",
                    "date_format",
                    "number_format",
                    "date_time_format",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "email",
                    "city",
                    "state",
                    "country",
                    "zip_code",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    """Admin configuration for Role."""

    filter_horizontal = ("permissions",)


@admin.register(BusinessHour)
class BusinessHourAdmin(admin.ModelAdmin):
    """Admin configuration for BusinessHour."""

    filter_horizontal = ("holidays",)


@admin.register(ShiftHour)
class ShiftHourAdmin(admin.ModelAdmin):
    """Admin configuration for ShiftHour."""

    filter_horizontal = ("assigned_users",)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    """Admin configuration for Holiday."""

    filter_horizontal = ("specific_users",)

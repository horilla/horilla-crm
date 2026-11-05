"""
Forms for the horilla_booking app.
"""

# Django imports
from django import forms

# Horilla imports
from horilla.contrib.generics.forms import HorillaModelForm
from horilla.urls import reverse_lazy
from horilla.utils.html import format_html
from horilla.utils.text import slugify
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import BookingPage


class ColorPickerWidget(forms.TextInput):
    """Full-width color bar input, styled to match other form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs["type"] = "color"  # ensures HorillaModelForm skips class injection

    def render(self, name, value, attrs=None, renderer=None):
        """Render a native color input styled to match Horilla form fields."""
        final_attrs = self.build_attrs(self.attrs, attrs or {})
        input_id = final_attrs.get("id", f"id_{name}")

        return format_html(
            '<input type="color" id="{id}" name="{name}" value="{value}"'
            ' data-saved="{value}"'
            ' class="w-full h-10 mt-1 rounded-md border border-dark-50 cursor-pointer p-1"'
            ' style="min-height:2.5rem">',
            id=input_id,
            name=name,
            value=value or "",
        )


class BookingPageForm(HorillaModelForm):
    """
    Zoho-style multi-section form for creating and editing BookingPage instances.
    Requires a BusinessHour to exist for the company before a page can be created.
    """

    class Meta:
        """Meta options for BookingPageForm."""

        model = BookingPage
        fields = [
            # ── Section 1: Booking Form Information ──────────────────────────
            "business_hour",  # hidden — auto-assigned from company
            "shift_hour",
            "title",
            "description",
            "duration",
            "is_online",
            "meeting_provider",
            "location",
            "participants",
            # ── Section 2: Meeting Scheduling Settings ────────────────────────
            "advance_notice",
            "booking_window",
            "buffer_before",
            "buffer_after",
            "reminder_hours",
            "allow_reschedule",
            "reschedule_cutoff_days",
            "allow_cancel",
            "cancel_cutoff_days",
            # ── Section 3: Email Templates ────────────────────────────────────
            "confirmation_mail_template",
            "cancellation_mail_template",
            "reschedule_mail_template",
            # ── Other ─────────────────────────────────────────────────────────
            "max_per_day",
            "is_active",
            "primary_color",
            "slug",
            "host",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "title": forms.TextInput(
                attrs={"placeholder": _("e.g. 30-Minute Intro Call")}
            ),
            "primary_color": ColorPickerWidget(),
        }

    def _field_bool_value(self, field_name):
        """Return current boolean value — from instance, initial data, or model default."""
        if self.instance.pk:
            return bool(getattr(self.instance, field_name))
        if field_name in self.initial:
            return bool(self.initial[field_name])
        return bool(BookingPage._meta.get_field(field_name).default)

    @staticmethod
    def _meeting_provider_choices(user):
        """Return meeting provider choices the user has actually connected."""
        choices = [("", "---------")]
        if not user:
            return choices
        try:
            from horilla.contrib.calendar.models import GoogleCalendarConfig
            from horilla.contrib.meeting.models import (
                MeetingIntegrationSetting,
                MicrosoftTeamsOAuthConfig,
                UserMeetingConfig,
                ZoomOAuthConfig,
            )

            company = getattr(user, "company", None)
            if not company or not MeetingIntegrationSetting.user_can_access(
                user, company
            ):
                return choices
            if ZoomOAuthConfig.objects.filter(
                user=user, token__has_key="access_token"
            ).exists():
                choices.append(("zoom", "Zoom"))
            gcal = GoogleCalendarConfig.objects.filter(user=user).first()
            meet_enabled = UserMeetingConfig.objects.filter(
                user=user, provider="google_meet"
            ).exists()
            if gcal and gcal.is_connected() and meet_enabled:
                choices.append(("google_meet", "Google Meet"))
            if MicrosoftTeamsOAuthConfig.objects.filter(
                user=user, token__has_key="access_token"
            ).exists():
                choices.append(("ms_teams", "Microsoft Teams"))
        except Exception:
            pass
        return choices

    def _wire_toggle(self, toggle_field, dependent_field, url, hide_when_true, include):
        """Hide dependent container on load and wire hx-post on the toggle checkbox."""
        current = self._field_bool_value(toggle_field)
        should_hide = current if hide_when_true else not current
        if should_hide:
            self.fields[dependent_field].widget.attrs[
                "container_style"
            ] = "display:none"
        self.fields[toggle_field].widget.attrs.update(
            {
                "hx-post": str(url),
                "hx-target": f"#{dependent_field}_container",
                "hx-swap": "outerHTML",
                "hx-trigger": "change",
                "hx-include": include,
            }
        )

    # Sections config — consumed by the template to render fieldsets
    SECTIONS = [
        {
            "title": _("Booking Form Information"),
            "description": "",
            "fields": [
                "shift_hour",
                "title",
                "description",
                "duration",
                "is_online",
                "meeting_provider",
                "location",
                "participants",
                "primary_color",
            ],
        },
        {
            "title": _("Meeting Scheduling Settings"),
            "description": _(
                "Meeting details that are not collected from the user but required for scheduling."
            ),
            "fields": [
                "advance_notice",
                "booking_window",
                "buffer_before",
                "buffer_after",
                "reminder_hours",
                "allow_reschedule",
                "reschedule_cutoff_days",
                "allow_cancel",
                "cancel_cutoff_days",
                "max_per_day",
                "is_active",
            ],
        },
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Leave blank on new pages so the page's global color-input script
        # can fill it with the live accent color instead of the model's
        # static field default.
        if not self.instance.pk:
            self.initial["primary_color"] = ""
        self.fields["max_per_day"].required = False
        self.fields["meeting_provider"].required = False
        self.fields["location"].required = False
        self.fields["host"].required = False
        self.fields["host"].widget = forms.HiddenInput()
        self.fields["slug"].required = False
        self.fields["slug"].widget = forms.HiddenInput()
        self.fields["reminder_hours"].required = False
        self.fields["description"].required = False

        # Auto-assign the company's BusinessHour — hidden from user
        self.fields["business_hour"].required = False
        self.fields["business_hour"].widget = forms.HiddenInput()

        # ShiftHour — optional, company-filtered
        self.fields["shift_hour"].required = False
        self.fields["participants"].required = False
        try:
            from horilla.auth.models import User
            from horilla.contrib.core.models import ShiftHour
            from horilla.contrib.core.models.business_hours import BusinessHour
            from horilla.contrib.utils.middlewares import _thread_local

            request = getattr(_thread_local, "request", None)
            company = getattr(request, "active_company", None) if request else None
            user = getattr(request, "user", None) if request else None
            bh = (
                BusinessHour.objects.filter(company=company).first()
                if company
                else BusinessHour.objects.first()
            )
            if bh:
                if not self.instance.pk:
                    self.initial["business_hour"] = bh.pk
                elif not self.instance.business_hour_id:
                    self.initial["business_hour"] = bh.pk
            if company:
                self.fields["shift_hour"].queryset = ShiftHour.objects.filter(
                    company=company
                )
                self.fields["participants"].queryset = User.objects.filter(
                    company=company
                )
            else:
                self.fields["shift_hour"].queryset = ShiftHour.objects.all()
                self.fields["participants"].queryset = User.objects.all()
        except Exception:
            pass

        # Meeting provider choices are limited to providers the requesting
        # user has actually connected (and only when the company's Meeting
        # Integration setting grants them access) — mirrors the same
        # provider-choice logic used in horilla.contrib.activity.forms.
        provider_choices = self._meeting_provider_choices(user)
        self.fields["meeting_provider"].choices = provider_choices
        self._has_meeting_access = len(provider_choices) > 1

        # Wire HTMX conditional visibility for toggle fields
        self._wire_toggle(
            toggle_field="is_online",
            dependent_field="location",
            url=reverse_lazy("booking:toggle_location_field"),
            hide_when_true=True,
            include="[name='location'],[name='meeting_provider']",
        )
        if not self._field_bool_value("is_online"):
            self.fields["meeting_provider"].widget.attrs[
                "container_style"
            ] = "display:none"
        self._wire_toggle(
            toggle_field="allow_reschedule",
            dependent_field="reschedule_cutoff_days",
            url=reverse_lazy("booking:toggle_reschedule_cutoff"),
            hide_when_true=False,
            include="[name='reschedule_cutoff_days']",
        )
        self._wire_toggle(
            toggle_field="allow_cancel",
            dependent_field="cancel_cutoff_days",
            url=reverse_lazy("booking:toggle_cancel_cutoff"),
            hide_when_true=False,
            include="[name='cancel_cutoff_days']",
        )

        self.fields["advance_notice"].help_text = _(
            "Minimum minutes before a slot can be booked"
        )
        self.fields["booking_window"].help_text = _(
            "How many days ahead visitors can book"
        )
        self.fields["buffer_before"].help_text = _("Minutes before each meeting")
        self.fields["buffer_after"].help_text = _("Minutes after each meeting")
        self.fields["reminder_hours"].help_text = _(
            "Send reminder email X hours before the meeting. Leave blank to disable."
        )

        # Limit mail template choices to booking or general templates; mark all optional
        for field_name in (
            "confirmation_mail_template",
            "cancellation_mail_template",
            "reschedule_mail_template",
        ):
            self.fields[field_name].required = False
        try:
            from horilla.contrib.core.models import HorillaContentType
            from horilla.contrib.mail.models import HorillaMailTemplate
            from horilla.db.models import Q

            booking_ct = HorillaContentType.objects.filter(
                app_label="booking", model="bookingpage"
            ).first()
            qs = (
                HorillaMailTemplate.objects.filter(
                    Q(content_type=booking_ct) | Q(content_type__isnull=True)
                )
                if booking_ct
                else HorillaMailTemplate.objects.filter(content_type__isnull=True)
            )
            for field_name in (
                "confirmation_mail_template",
                "cancellation_mail_template",
                "reschedule_mail_template",
            ):
                self.fields[field_name].queryset = qs
        except Exception:
            pass

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get("title")
        is_online = cleaned_data.get("is_online")
        meeting_provider = cleaned_data.get("meeting_provider")

        # Auto-generate slug from title
        current_slug = cleaned_data.get("slug") or (
            self.instance.slug if self.instance.pk else ""
        )
        if title and not current_slug:
            base_slug = slugify(title)
            candidate = base_slug
            counter = 1
            qs = BookingPage.all_objects.filter(slug=candidate)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            while qs.exists():
                candidate = f"{base_slug}-{counter}"
                counter += 1
                qs = BookingPage.all_objects.filter(slug=candidate)
                if self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
            cleaned_data["slug"] = candidate
        elif self.instance.pk and self.instance.slug:
            cleaned_data["slug"] = self.instance.slug

        if (
            is_online
            and not meeting_provider
            and getattr(self, "_has_meeting_access", True)
        ):
            self.add_error(
                "meeting_provider",
                _("Meeting provider is required for online meetings."),
            )

        return cleaned_data


class PublicBookingForm(forms.Form):
    """Form filled out by external visitors on the public booking page."""

    booker_name = forms.CharField(
        max_length=200,
        label=_("Your Name"),
        widget=forms.TextInput(attrs={"placeholder": _("Full Name")}),
    )
    booker_email = forms.EmailField(
        label=_("Your Email"),
        widget=forms.EmailInput(attrs={"placeholder": _("email@example.com")}),
    )
    notes = forms.CharField(
        required=False,
        label=_("Notes"),
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": _("Any Additional Information...")}
        ),
    )

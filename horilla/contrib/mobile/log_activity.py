"""
Activity forms on the phone: log a call, add a task, a meeting or an event
(on a record, or from the Agenda without one), add a note, and edit them
again from their details sheet.

The forms are the desktop ones (``LogCallForm``, ``TaskForm``,
``MeetingsForm``, ``EventForm``, ``HorillaAttachmentForm``), validated and
saved the way the desktop saves them; only the template is the phone's. A
meeting is saved by the desktop meeting view itself, which also creates the
online meeting link and sends the invitations.
"""

# Standard library imports
import json
from datetime import datetime, time, timedelta

# Third-party imports (Django)
from django import forms
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.activity.forms import (
    EventForm,
    LogCallForm,
    MeetingsForm,
    TaskForm,
)
from horilla.contrib.activity.models import Activity
from horilla.contrib.activity.views import MeetingsCreateForm
from horilla.contrib.core.models import HorillaAttachment, HorillaContentType
from horilla.contrib.generics.forms.generics import HorillaAttachmentForm
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import redirect, render
from horilla.urls import reverse
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.translation import pgettext_lazy
from horilla.views.generic import FormView
from horilla.web import safe_url

# Local imports
from .access import (
    can_add_activity,
    can_edit_activity,
    can_edit_note,
    can_log_activity,
    can_open,
    scope_queryset,
)
from .dates import parse_day
from .navigation import agenda_url, get_nav_items
from .records import record_url
from .registry import get_mobile_config
from .utils import user_display_name
from .views import MobilePageMixin

# What each kind of activity shows on the phone, in this order, besides the
# fields its form requires. The related record and the owner are filled in,
# not shown. ``dates`` are pre-filled for a day picked on the Agenda.
ACTIVITY_KINDS = {
    "call": {
        "form_class": LogCallForm,
        "activity_type": "log_call",
        "fields": ["subject", "call_type", "call_purpose", "status", "notes"],
        "title": _("Log a call"),
        "edit_title": _("Edit call"),
        "dates": (),
    },
    "task": {
        "form_class": TaskForm,
        "activity_type": "task",
        "fields": ["subject", "due_datetime", "task_priority", "status", "description"],
        "title": _("New task"),
        "edit_title": _("Edit task"),
        "dates": ("due_datetime",),
    },
    "meeting": {
        "form_class": MeetingsForm,
        "activity_type": "meeting",
        "fields": [
            "subject",
            "start_datetime",
            "end_datetime",
            "is_all_day",
            "is_online",
            "location",
            "meeting_provider",
            "participants",
            "reminder",
            "status",
        ],
        "title": _("New meeting"),
        "edit_title": _("Edit meeting"),
        "dates": ("start_datetime", "end_datetime"),
        "status": "scheduled",
    },
    "event": {
        "form_class": EventForm,
        "activity_type": "event",
        "fields": [
            "subject",
            "start_datetime",
            "end_datetime",
            "is_all_day",
            "location",
            "status",
        ],
        "title": _("New event"),
        "edit_title": _("Edit event"),
        "dates": ("start_datetime", "end_datetime"),
        "status": "scheduled",
    },
}

# The kind of each activity type; every type can be edited on the phone.
KINDS_BY_TYPE = {kind["activity_type"]: key for key, kind in ACTIVITY_KINDS.items()}
EDITABLE_TYPES = {kind["activity_type"]: kind for kind in ACTIVITY_KINDS.values()}

# Kinds the Agenda creates (a logged call belongs to a record).
AGENDA_KINDS = ("meeting", "event", "task")

# Fields that tie the activity to the record: taken from the URL, never from
# the posted form.
RECORD_FIELDS = ("object_id", "content_type", "activity_type")

# Checkboxes that change which fields the form shows; ticking one posts the
# form back with TOGGLE_PARAM to re-render it, without saving.
TOGGLE_FIELDS = ("is_all_day", "is_online")
TOGGLE_PARAM = "mobile_toggle"
CHECKED_VALUES = ("on", "true", "True", "1", True)

# Between the names a people picker shows.
LIST_SEPARATOR = pgettext_lazy("list separator", ", ")

# Length of a new meeting or event.
DEFAULT_DURATION = timedelta(hours=1)
# Start of a new activity on a later day (today: the next full hour).
DEFAULT_START = time(9, 0)


def unavailable_page(request, message, status):
    """Phone-layout page saying why the form can't be shown."""
    return render(
        request,
        "mobile/unavailable.html",
        {
            "message": message,
            "mobile_nav_items": get_nav_items(request),
            "back_url": reverse("mobile:records"),
        },
        status=status,
    )


def record_context(record):
    """The record a form belongs to, and the way back to it."""
    config = None
    if record is not None:
        meta = record._meta
        config = get_mobile_config(meta.app_label, meta.model_name)
    return {
        "record": record,
        "config": config,
        "record_url": record_url(record) if config else reverse("mobile:records"),
    }


def mobile_next(request):
    """The posted or requested ``next`` page when it is a safe phone page, else ""."""
    value = request.POST.get("next") or request.GET.get("next") or ""
    url = safe_url(request, value, fallback="")
    return url if url.startswith(reverse("mobile:home")) else ""


def edit_context(request, record):
    """
    Like ``record_context``, but an edit opened from another page (My work,
    Agenda) returns there.
    """
    context = record_context(record)
    next_url = mobile_next(request)
    if next_url:
        context.update({"record_url": next_url, "next_url": next_url})
    return context


def is_checked(form, name):
    """Whether checkbox ``name`` is on, as the form sees it."""
    if form.is_bound:
        value = form.data.get(name)
    else:
        value = form.initial.get(name, getattr(form.instance, name, False))
    return value in CHECKED_VALUES


def posted_initial(data):
    """
    Posted values as the initial values of an unbound form, so a re-render
    after a toggle keeps what was typed without showing errors yet.
    """
    initial = {}
    for key in data:
        values = data.getlist(key)
        initial[key] = values if len(values) > 1 else values[0]
    for name in TOGGLE_FIELDS:
        initial[name] = data.get(name) in CHECKED_VALUES
    return initial


def default_dates(kind, day):
    """
    Values of the kind's date fields for a new activity on ``day``: the next
    full hour today, else ``DEFAULT_START``; meetings and events last
    ``DEFAULT_DURATION``.
    """
    if not kind["dates"] or day is None:
        return {}
    now = timezone.localtime()
    if day == now.date():
        start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    else:
        start = datetime.combine(day, DEFAULT_START, tzinfo=now.tzinfo)
    values = [start, start + DEFAULT_DURATION]
    return {
        name: value.strftime("%Y-%m-%dT%H:%M")
        for name, value in zip(kind["dates"], values)
    }


def note_form(form):
    """
    The desktop notes form without the file field (uploads come later) and
    with a plain text box: the desktop rich-text editor isn't loaded on the
    phone.
    """
    form.fields.pop("file", None)
    description = form.fields["description"]
    description.widget = forms.Textarea(attrs={"rows": 6})
    # Its help text describes a file's notes; here it is the note itself.
    description.help_text = ""
    return form


class ActivityFormMixin:
    """
    The phone side of a desktop activity form view: the kind's form and
    fields, the checkboxes that re-render the form (all day, online), people
    pickers, and the way back. Subclasses set ``kind``, ``record`` and
    ``editing`` before the form is built.
    """

    model = Activity
    template_name = "mobile/log_activity.html"
    hidden_fields = [*RECORD_FIELDS, "owner"]
    save_and_new = False
    editing = False
    toggled_initial = None

    def has_permission(self):
        """Access is decided before the form (record, activity or Agenda checks)."""
        return True

    def get_form_class(self):
        """The desktop form for this kind of activity, with its extensions."""
        self.form_class = self.kind["form_class"]
        return super().get_form_class()

    # ----- the record and the defaults of a new activity ------------------

    def record_values(self):
        """Values tying a new activity to its record (none from the Agenda)."""
        values = {"activity_type": self.kind["activity_type"]}
        if self.record is None:
            values.update({"object_id": "", "content_type": ""})
        else:
            content_type = HorillaContentType.objects.get_for_model(self.record)
            values.update(
                {"object_id": str(self.record.pk), "content_type": str(content_type.pk)}
            )
        return values

    def default_day(self):
        """Day a new activity is pre-filled for, or None."""
        return None

    def get_initial(self):
        """Pre-fill a new activity's record, type, owner, status and dates."""
        initial = super().get_initial()
        if not self.editing:
            initial.update(self.record_values())
            initial["owner"] = self.request.user.pk
            if self.kind.get("status"):
                initial["status"] = self.kind["status"]
            initial.update(default_dates(self.kind, self.default_day()))
        return initial

    def get_form_kwargs(self):
        """
        A new activity's posted data always carries its record and type,
        whatever the hidden inputs say. After a toggle, the posted values
        become initial values of an unbound form.
        """
        kwargs = super().get_form_kwargs()
        if self.toggled_initial is not None:
            kwargs.pop("data", None)
            kwargs.pop("files", None)
            kwargs["initial"] = {**kwargs.get("initial", {}), **self.toggled_initial}
        elif "data" in kwargs and not self.editing:
            data = kwargs["data"].copy()
            data.update(self.record_values())
            if not data.get("owner"):
                data["owner"] = str(self.request.user.pk)
            kwargs["data"] = data
        return kwargs

    # ----- which fields show, and how --------------------------------------

    def shown_names(self, form):
        """
        The kind's fields in its order, then any other field the form
        requires; never a hidden one. The meeting link provider shows for an
        online meeting when the user connected one.
        """
        names = [name for name in self.kind["fields"] if name in form.fields]
        names += [
            name
            for name, field in form.fields.items()
            if field.required and name not in names
        ]
        shown = []
        for name in names:
            field = form.fields[name]
            if name in self.hidden_fields or field.widget.is_hidden:
                continue
            if name == "meeting_provider" and not (
                is_checked(form, "is_online") and len(field.choices) > 1
            ):
                continue
            shown.append(name)
        return shown

    def get_form(self, form_class=None):
        """
        The desktop form for the phone: its HTMX hooks (which post to the
        desktop modal) are dropped, the all-day and online boxes re-render
        this form instead, people fields become a checklist, and when
        editing, fields the phone doesn't show are disabled so they keep
        their saved values.
        """
        form = super().get_form(form_class)
        for field in form.fields.values():
            attrs = field.widget.attrs
            for key in [key for key in attrs if key.startswith("hx-")]:
                del attrs[key]
            attrs.pop("onchange", None)
            if getattr(field.widget, "input_type", "") == "checkbox":
                # The desktop draws a switch next to a hidden box; the phone
                # shows the box itself.
                attrs.pop("class", None)
        if "owner" in form.fields:
            form.fields["owner"].widget = forms.HiddenInput()
        shown = self.shown_names(form)
        for name in shown:
            field = form.fields[name]
            if name in TOGGLE_FIELDS:
                field.widget.attrs.update(
                    {
                        "hx-post": self.request.get_full_path(),
                        "hx-trigger": "change",
                        "hx-vals": json.dumps({TOGGLE_PARAM: "1"}),
                        "hx-target": "#activity-form",
                        "hx-select": "#activity-form",
                        "hx-swap": "outerHTML",
                    }
                )
            elif isinstance(field, forms.ModelMultipleChoiceField):
                if field.queryset.model is User:
                    # Users without a full name would show as blank.
                    field.label_from_instance = user_display_name
                widget = forms.CheckboxSelectMultiple()
                widget.choices = field.choices
                field.widget = widget
        if self.editing:
            for name, field in form.fields.items():
                if name not in shown:
                    field.disabled = True
        return form

    def get_context_data(self, **kwargs):
        """The fields to show, the people pickers and the page title."""
        context = super().get_context_data(**kwargs)
        form = context["form"]
        shown = [form[name] for name in self.shown_names(form)]
        pickers = {}
        for bound in shown:
            if isinstance(bound.field.widget, forms.CheckboxSelectMultiple):
                selected = {str(value) for value in (bound.value() or [])}
                pickers[bound.name] = str(LIST_SEPARATOR).join(
                    str(label)
                    for value, label in bound.field.choices
                    if str(value) in selected
                )
        context.update(
            {
                "shown_fields": shown,
                "pickers": pickers,
                "list_separator": LIST_SEPARATOR,
                "page_title": self.kind["edit_title" if self.editing else "title"],
                "is_meeting": self.kind["activity_type"] == "meeting",
            }
        )
        if self.toggled_initial is not None:
            context["ext_email_string"] = self.request.POST.get(
                "external_participants_email", ""
            )
        return context

    # ----- toggles and saving -----------------------------------------------

    def post(self, request, *args, **kwargs):
        """A toggle re-renders the form with what was typed; anything else saves."""
        if request.POST.get(TOGGLE_PARAM):
            if not hasattr(self, "object"):
                self.object = None
            self.toggled_initial = posted_initial(request.POST)
            return self.render_to_response(self.get_context_data(form=self.get_form()))
        return super().post(request, *args, **kwargs)

    def success_url_for(self, activity):
        """Where saving returns to."""
        raise NotImplementedError

    def form_valid(self, form):
        """Save through the desktop form view, then go back where the form came from."""
        response = super().form_valid(form)
        if form.errors or not getattr(form.instance, "pk", None):
            return self.form_invalid(form) if form.errors else response
        return redirect(self.success_url_for(form.instance))


class DesktopMeetingSave(MeetingsCreateForm):
    """
    The desktop meeting view, used for its save: besides saving the form it
    creates the online meeting link and sends the invitations. Its HTMX-only
    dispatch and the desktop modal's GET checks are skipped; the phone views
    check access themselves before the form.
    """

    def dispatch(self, request, *args, **kwargs):
        """Signed-in users only, then the generic form view."""
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return HorillaSingleFormView.dispatch(self, request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Show the form."""
        return HorillaSingleFormView.get(self, request, *args, **kwargs)


class RecordActionMixin:
    """
    Resolve the record from ``app_label`` / ``model_name`` / ``record_pk``,
    and answer with the phone's "unavailable" page when the user can't add
    to it.
    """

    def dispatch(self, request, *args, **kwargs):
        """Check the record before any form handling."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        config = get_mobile_config(kwargs["app_label"], kwargs["model_name"])
        record = None
        if config is not None:
            record = config.model.objects.filter(pk=kwargs["record_pk"]).first()
        if record is None:
            return self.unavailable(_("This record doesn't exist or was deleted."), 404)
        if not can_open(request.user, record) or not can_log_activity(
            request.user, record
        ):
            return self.unavailable(
                _("You don't have permission to add activities to this record."), 403
            )
        self.config = config
        self.record = record
        return super().dispatch(request, *args, **kwargs)

    def unavailable(self, message, status):
        """Phone-layout page saying why the form can't be shown."""
        return unavailable_page(self.request, message, status)

    def get_context_data(self, **kwargs):
        """The record the activity belongs to, and the way back to it."""
        context = super().get_context_data(**kwargs)
        context.update(record_context(self.record))
        return context


class RecordActivityMixin(RecordActionMixin, ActivityFormMixin):
    """A new call, task, meeting or event on a record."""

    def setup(self, request, *args, **kwargs):
        """Pick the kind from the URL."""
        super().setup(request, *args, **kwargs)
        self.kind = ACTIVITY_KINDS.get(kwargs.get("kind"))

    def dispatch(self, request, *args, **kwargs):
        """Unknown kinds are not found."""
        if self.kind is None:
            return self.unavailable(_("This page doesn't exist."), 404)
        return super().dispatch(request, *args, **kwargs)

    def default_day(self):
        """Meetings and events start today; a task keeps its own due date."""
        if self.kind["activity_type"] in ("meeting", "event"):
            return timezone.localdate()
        return None

    def success_url_for(self, activity):
        """Back to the record."""
        return record_url(self.record)


class MobileLogActivityView(
    RecordActivityMixin, MobilePageMixin, HorillaSingleFormView
):
    """Log a call, or add a task or an event, to a record."""


class MobileLogMeetingView(RecordActivityMixin, MobilePageMixin, DesktopMeetingSave):
    """Add a meeting to a record."""


class AgendaActivityMixin(ActivityFormMixin):
    """
    A new task, meeting or event from the Agenda, on the day picked there and
    tied to no record. Needs the desktop's permission to add activities.
    """

    record = None

    def setup(self, request, *args, **kwargs):
        """Pick the kind from the URL and the day from ``?date=``."""
        super().setup(request, *args, **kwargs)
        key = kwargs.get("kind")
        self.kind = ACTIVITY_KINDS.get(key) if key in AGENDA_KINDS else None
        self.day = parse_day(request.user, request.GET.get("date"))

    def dispatch(self, request, *args, **kwargs):
        """Unknown kinds are not found; adding needs the add permission."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if self.kind is None:
            return unavailable_page(request, _("This page doesn't exist."), 404)
        if not can_add_activity(request.user):
            return unavailable_page(
                request, _("You don't have permission to add activities."), 403
            )
        return super().dispatch(request, *args, **kwargs)

    def default_day(self):
        """The day picked on the Agenda."""
        return self.day

    def get_context_data(self, **kwargs):
        """No record; back to the Agenda's day."""
        context = super().get_context_data(**kwargs)
        context.update(
            {"record": None, "config": None, "record_url": agenda_url(self.day)}
        )
        return context

    def success_url_for(self, activity):
        """Back to the Agenda, on the activity's own day."""
        when = activity.due_datetime or activity.start_datetime
        day = timezone.localtime(when).date() if when else self.day
        return agenda_url(day)


class MobileAgendaActivityView(
    AgendaActivityMixin, MobilePageMixin, HorillaSingleFormView
):
    """Add a task or an event from the Agenda."""


class MobileAgendaMeetingView(AgendaActivityMixin, MobilePageMixin, DesktopMeetingSave):
    """Add a meeting from the Agenda."""


class EditActivityMixin(ActivityFormMixin):
    """
    Edit a saved activity with the form it was added with. The phone shows
    the same fields as when adding it; every other field keeps its value.
    """

    editing = True

    def dispatch(self, request, *args, **kwargs):
        """Check the activity before any form handling."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        queryset = Activity.objects.filter(pk=kwargs["pk"])
        activity = scope_queryset(request.user, queryset).first()
        self.kind = (
            ACTIVITY_KINDS.get(KINDS_BY_TYPE.get(activity.activity_type))
            if activity
            else None
        )
        if self.kind is None:
            return unavailable_page(
                request, _("This item doesn't exist or you can't view it."), 404
            )
        if not can_edit_activity(request.user, activity):
            return unavailable_page(
                request, _("You don't have permission to edit this item."), 403
            )
        self.record = activity.related_object
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """The way back: where the edit was opened, else the record."""
        context = super().get_context_data(**kwargs)
        context.update(edit_context(self.request, self.record))
        return context

    def success_url_for(self, activity):
        """Back where the edit was opened, else to the record."""
        return edit_context(self.request, self.record)["record_url"]


class MobileEditActivityView(EditActivityMixin, MobilePageMixin, HorillaSingleFormView):
    """Edit a logged call, a task or an event."""


class MobileEditMeetingView(EditActivityMixin, MobilePageMixin, DesktopMeetingSave):
    """Edit a meeting; the desktop meeting view sends the invitations again."""


_LOG_ACTIVITY = MobileLogActivityView.as_view()
_LOG_MEETING = MobileLogMeetingView.as_view()
_AGENDA_ACTIVITY = MobileAgendaActivityView.as_view()
_AGENDA_MEETING = MobileAgendaMeetingView.as_view()
_EDIT_ACTIVITY = MobileEditActivityView.as_view()
_EDIT_MEETING = MobileEditMeetingView.as_view()


def log_activity(request, *args, **kwargs):
    """New activity on a record: meetings go through the desktop meeting view."""
    view = _LOG_MEETING if kwargs.get("kind") == "meeting" else _LOG_ACTIVITY
    return view(request, *args, **kwargs)


def agenda_activity(request, *args, **kwargs):
    """New activity from the Agenda: meetings go through the desktop meeting view."""
    view = _AGENDA_MEETING if kwargs.get("kind") == "meeting" else _AGENDA_ACTIVITY
    return view(request, *args, **kwargs)


def edit_activity(request, *args, **kwargs):
    """Edit an activity: meetings go through the desktop meeting view."""
    activity_type = (
        Activity.objects.filter(pk=kwargs.get("pk"))
        .values_list("activity_type", flat=True)
        .first()
    )
    view = _EDIT_MEETING if activity_type == "meeting" else _EDIT_ACTIVITY
    return view(request, *args, **kwargs)


class MobileNoteView(RecordActionMixin, MobilePageMixin, FormView):
    """Add a short text note to a record, saved like the desktop notes."""

    template_name = "mobile/log_activity.html"
    form_class = HorillaAttachmentForm

    def get_form(self, form_class=None):
        """The desktop notes form, trimmed for the phone."""
        return note_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        """Show every field of the trimmed notes form."""
        context = super().get_context_data(**kwargs)
        context["shown_fields"] = list(context["form"])
        context["page_title"] = _("New note")
        return context

    def form_valid(self, form):
        """Attach the note to the record, as the desktop notes view does."""
        note = form.save(commit=False)
        note.created_by = self.request.user
        note.content_type = HorillaContentType.objects.get_for_model(self.record)
        note.object_id = self.record.pk
        note.company = get_active_company(self.request)
        note.save()
        messages.success(
            self.request,
            _("%(title)s created successfully.") % {"title": note.title},
        )
        return redirect(record_url(self.record))


class MobileEditNoteView(MobilePageMixin, FormView):
    """Edit a note's title and text with the desktop notes form."""

    template_name = "mobile/log_activity.html"
    form_class = HorillaAttachmentForm

    def dispatch(self, request, *args, **kwargs):
        """Check the note and its record before any form handling."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        note = HorillaAttachment.objects.filter(pk=kwargs["pk"]).first()
        record = note.related_object if note is not None else None
        if record is None or not can_open(request.user, record):
            return unavailable_page(
                request, _("This item doesn't exist or you can't view it."), 404
            )
        if not can_edit_note(request.user, note, record):
            return unavailable_page(
                request, _("You don't have permission to edit this item."), 403
            )
        self.note = note
        self.record = record
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Bind the saved note."""
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.note
        return kwargs

    def get_form(self, form_class=None):
        """The desktop notes form, trimmed for the phone; the file is kept."""
        return note_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        """Show every field of the trimmed notes form."""
        context = super().get_context_data(**kwargs)
        context.update(edit_context(self.request, self.record))
        context["shown_fields"] = list(context["form"])
        context["page_title"] = _("Edit note")
        return context

    def form_valid(self, form):
        """Save the note and go back to its record."""
        note = form.save()
        messages.success(
            self.request,
            _("%(title)s updated successfully.") % {"title": note.title},
        )
        return redirect(edit_context(self.request, self.record)["record_url"])

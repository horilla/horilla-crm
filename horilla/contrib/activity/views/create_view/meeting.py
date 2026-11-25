"""
Meeting create/update form view.
"""

# Third-party imports (Django)
from django.contrib import messages

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.shortcuts import get_object_or_404
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.functional import cached_property  # type: ignore

# First-party imports (Horilla)
from horilla.web import Http404, ScriptResponse

# Local imports (Horilla)
from ...forms import MeetingsForm
from ...models import Activity
from .meeting_helpers import generate_meeting_url, send_meeting_invites
from .mixins import ActivityOwnerPermissionMixin


@method_decorator(htmx_required, name="dispatch")
class MeetingsCreateForm(
    ActivityOwnerPermissionMixin, LoginRequiredMixin, HorillaSingleFormView
):
    """Form view for meeting activity."""

    model = Activity
    form_class = MeetingsForm
    template_name = "meeting_create_form.html"
    save_and_new = False

    @cached_property
    def form_url(self):
        """Return the create or update URL depending on whether a pk is present."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("activity:meeting_update_form", kwargs={"pk": pk})
        return reverse_lazy("activity:meeting_create_form")

    def get_initial(self):
        """Set initial meeting form values including all-day/online toggles and related record."""
        initial = super().get_initial()
        if self.request.method == "POST":
            initial["is_all_day"] = self.request.POST.get("is_all_day") == "on"
            initial["is_online"] = self.request.POST.get("is_online") == "on"
        else:
            object_id = self.request.GET.get("object_id")
            model_name = self.request.GET.get("model_name")
            all_day = self.request.GET.get("is_all_day")
            toggle_is_all_day = self.request.GET.get("toggle_is_all_day")
            toggle_is_online = self.request.GET.get("toggle_is_online")

            content_type_for_initial = None
            if object_id and not model_name:
                ct_param = self.request.GET.get("content_type")
                if ct_param:
                    try:
                        content_type_for_initial = HorillaContentType.objects.get(
                            pk=int(ct_param)
                        )
                        model_name = content_type_for_initial.model
                    except (HorillaContentType.DoesNotExist, ValueError, TypeError):
                        pass

            if toggle_is_all_day == "true" and self.kwargs.get("pk"):
                initial["is_all_day"] = False
            elif all_day is not None:
                initial["is_all_day"] = all_day == "on"
            elif hasattr(self, "object") and self.object:
                initial["is_all_day"] = self.object.is_all_day

            if toggle_is_online == "true" and self.kwargs.get("pk"):
                initial["is_online"] = False
            elif self.request.GET.get("is_online") is not None:
                initial["is_online"] = self.request.GET.get("is_online") == "on"
            elif hasattr(self, "object") and self.object:
                initial["is_online"] = self.object.is_online

            if object_id and model_name:
                initial["object_id"] = object_id
                if content_type_for_initial is not None:
                    initial["content_type"] = content_type_for_initial.id
                else:
                    ct_row = HorillaContentType.objects.get(model=model_name.lower())
                    initial["content_type"] = ct_row.id
                initial["activity_type"] = "meeting"
                initial["owner"] = self.request.user

        return initial

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        object_id = request.GET.get("object_id")
        model_name = request.GET.get("model_name")
        app_label = request.GET.get("app_label")

        if object_id and not model_name:
            ct_param = request.GET.get("content_type")
            if ct_param:
                try:
                    ct = HorillaContentType.objects.get(pk=int(ct_param))
                    model_name = ct.model
                    app_label = app_label or ct.app_label
                except (HorillaContentType.DoesNotExist, ValueError, TypeError):
                    pass

        if pk:
            try:
                activity = get_object_or_404(Activity, pk=pk)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name} not found or no longer exists.",
                )
                return ScriptResponse(
                    reload=True,
                    close=True,
                )
            object_id = object_id or activity.object_id
            model_name = model_name or activity.content_type.model
            app_label = app_label or activity.content_type.app_label

        denied = self._check_owner_permission(
            request, object_id, model_name, app_label, pk
        )
        if denied is not None:
            return denied
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        instance = getattr(self, "object", None)
        existing = (
            instance.external_participants if instance and instance.pk else None
        ) or []
        if not isinstance(existing, list):
            existing = []
        context["ext_email_list"] = existing
        context["ext_email_string"] = ",".join(existing)
        return context

    def post(self, request, *args, **kwargs):
        """Re-render the form when the is_online toggle is changed via HTMX."""
        if request.POST.get("_toggle_field") == "is_online":
            self.object = None
            pk = self.kwargs.get("pk")
            if pk:
                try:
                    self.object = get_object_or_404(Activity, pk=pk)
                except Http404:
                    pass
            form = self.get_form()
            context = self.get_context_data(form=form)
            return self.render_to_response(context)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        provider = form.cleaned_data.get("meeting_provider") or ""
        is_online = form.cleaned_data.get("is_online", False)
        start_dt = form.cleaned_data.get("start_datetime")
        end_dt = form.cleaned_data.get("end_datetime")

        generated_url = ""
        if is_online and provider:
            activity = form.save(commit=False)
            activity.start_datetime = start_dt
            activity.end_datetime = end_dt
            host = activity.meeting_host or self.request.user
            generated_url = generate_meeting_url(self, provider, host, activity) or ""
            if generated_url:
                form.instance.meeting_url = generated_url

        external_emails = form.cleaned_data.get("external_participants") or []
        form.instance.external_participants = external_emails

        super().form_valid(form)

        if generated_url and form.instance.pk:
            Activity.objects.filter(pk=form.instance.pk).update(
                meeting_url=generated_url
            )
            form.instance.meeting_url = generated_url

        participant_emails = list(
            form.instance.participants.exclude(email="").values_list("email", flat=True)
        )
        host_email = getattr(form.instance.meeting_host, "email", "") or ""
        all_recipients = list(
            dict.fromkeys(
                ([host_email] if host_email else [])
                + participant_emails
                + external_emails
            )
        )
        if all_recipients:
            form.instance.start_datetime = form.instance.start_datetime or start_dt
            form.instance.end_datetime = form.instance.end_datetime or end_dt
            send_meeting_invites(self, form.instance, all_recipients)

        return ScriptResponse(extra="htmx.trigger('#MeetingsTab','click');", close=True)

    # Keep these as instance methods so ActivityCreateView can call them via bridge
    def _generate_url(self, provider, host, activity):
        return generate_meeting_url(self, provider, host, activity)

    def _send_invites(self, activity, emails):
        send_meeting_invites(self, activity, emails)

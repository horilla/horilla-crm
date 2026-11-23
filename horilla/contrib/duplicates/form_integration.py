"""
Integration module to inject duplicate checking into Horilla form views.
This module patches HorillaSingleFormView and HorillaMultiStepFormView
to check for duplicates before saving.
Also injects Potential Duplicates tab into detail views.
"""

# Standard library imports
import logging
import uuid
from functools import wraps

# Third-party imports (Django)
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import get_active_company
from horilla.urls import reverse
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse, QueryDict

from .duplicate_checker import check_duplicates

# Local imports
from .models import DuplicateRule


def create_form_valid_with_duplicate_check(original_form_valid, is_multi_step=False):
    """
    Create a wrapped form_valid method that checks for duplicates before saving.

    Args:
        original_form_valid: The original form_valid method
        is_multi_step: Whether this is for multi-step form view
    """

    @wraps(original_form_valid)
    def form_valid_with_duplicate_check(self, form):
        # Skip duplicate checking if this is not the final step (for multi-step)
        if is_multi_step:
            # Get current step from POST data or view attribute
            step = int(self.request.POST.get("step", getattr(self, "current_step", 1)))
            total_steps = getattr(self, "total_steps", 1)
            if step < total_steps:
                # Not final step, proceed normally
                return original_form_valid(self, form)

        # Check if we should skip duplicate checking (e.g., if bypass flag is set)
        skip_check = (
            self.request.GET.get("skip_duplicate_check", "false").lower() == "true"
        )
        skip_check = (
            skip_check
            or self.request.POST.get("skip_duplicate_check", "false").lower() == "true"
        )
        if skip_check:
            # Set flag on request so we don't check again
            self.request.skip_duplicate_check = True
            return original_form_valid(self, form)

        # Only check duplicates if model is registered for duplicate checking
        if not hasattr(self, "model") or not self.model:
            return original_form_valid(self, form)

        # Check if model is registered for duplicate checking
        try:
            from horilla.registry.feature import FEATURE_REGISTRY

            duplicate_models = FEATURE_REGISTRY.get("duplicate_models", [])
            if self.model not in duplicate_models:
                return original_form_valid(self, form)
        except Exception:
            # If registry check fails, continue anyway
            pass

        # Skip duplicate check when the form only changes owner fields
        owner_fields = set(getattr(self.model, "OWNER_FIELDS", []))
        if owner_fields:
            form_fields = set(form.fields.keys())
            if form_fields and form_fields.issubset(owner_fields):
                return original_form_valid(self, form)

        # Create instance from form (before saving)
        instance = form.save(commit=False)

        try:
            company = get_active_company(self.request)
            if company:
                instance.company = company
        except Exception:
            pass

        is_edit = bool(
            getattr(self, "object", None) and getattr(self.object, "pk", None)
        )
        if not is_edit:
            is_edit = bool(self.kwargs.get("pk"))
        if getattr(self, "duplicate_mode", False):
            is_edit = False
        try:
            duplicate_result = check_duplicates(instance, is_edit=is_edit)

            if duplicate_result.get("has_duplicates"):
                return get_duplicate_warning_response(
                    self.request,
                    duplicate_result,
                    form,
                    self,
                    original_form_valid,
                    is_multi_step,
                )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning("Duplicate check failed: %s", e)

        return original_form_valid(self, form)

    return form_valid_with_duplicate_check


def get_duplicate_warning_response(
    request, duplicate_result, form, view, original_form_valid, is_multi_step
):
    """
    Generate HTMX response that opens horillaModal with duplicate warning.
    Returns the form HTML with script appended so the form stays visible.

    Args:
        request: HttpRequest
        duplicate_result: dict from check_duplicates()
        form: Form instance
        view: View instance
        original_form_valid: Original form_valid method to call after user confirms
        is_multi_step: Whether this is a multi-step form
    """
    # Serialize form data for re-submission
    form_data = {}
    for field_name in form.fields:
        if field_name in form.cleaned_data:
            value = form.cleaned_data[field_name]
            # Handle various field types
            if hasattr(value, "pk"):  # ForeignKey
                form_data[field_name] = value.pk
            elif hasattr(value, "__iter__") and not isinstance(
                value, str
            ):  # ManyToMany
                form_data[field_name] = [v.pk if hasattr(v, "pk") else v for v in value]
            else:
                form_data[field_name] = value

    # Also include POST data for file fields and other fields not in cleaned_data
    for key, value in request.POST.items():
        if key not in form_data and key != "csrfmiddlewaretoken":
            if key in request.POST.getlist(key):
                form_data[key] = request.POST.getlist(key)
            else:
                form_data[key] = value

    # Get form URL for continue button
    form_url = request.path
    query_params = request.GET.copy()
    query_params["skip_duplicate_check"] = "true"
    if query_params:
        form_url += "?" + query_params.urlencode()

    # Preserve save_and_new button value if it was clicked
    save_and_new_value = request.POST.get("save_and_new", "")

    # Store modal context in session for the view to retrieve
    session_key = f"duplicate_modal_{uuid.uuid4().hex[:16]}"
    request.session[session_key] = {
        "alert_title": duplicate_result.get(
            "alert_title", "Potential Duplicate Detected"
        ),
        "alert_message": duplicate_result.get(
            "alert_message", "Similar records were found. Do you want to proceed?"
        ),
        "duplicate_records": [
            (r.pk, str(r)) for r in duplicate_result.get("duplicate_records", [])[:10]
        ],
        "show_duplicate_records": duplicate_result.get("show_duplicate_records", True),
        "form_url": form_url,
        "model_name": (
            view.model._meta.model_name
            if hasattr(view, "model") and view.model
            else None
        ),
        "action": duplicate_result.get("action", "allow"),  # 'allow' or 'block'
        "save_and_new": save_and_new_value,  # Preserve save_and_new button value
    }
    request.session.modified = True

    modal_url = reverse(
        "duplicates:duplicate_warning_modal",
        kwargs={"session_key": session_key},
    )

    try:
        context = view.get_context_data(form=form)
        if is_multi_step:
            template_name = "form_view.html"
        else:
            template_name = view.template_name or "single_form_view.html"

        form_html = render_to_string(template_name, context, request=request)

        # Append HTMX div to form HTML to open duplicate modal
        htmx_content = f"""
        <div hx-get="{modal_url}"
             hx-target="#dynamicCreateModalBox"
             hx-trigger="load"
             hx-swap="innerHTML"
             hx-on::load="openDynamicModal();">
        </div>
        """

        return HttpResponse(form_html + htmx_content)
    except Exception as e:
        # Fallback to HTMX-only response if rendering fails
        logger = logging.getLogger(__name__)
        logger.warning("Error rendering form for duplicate warning: %s", str(e))
        htmx_content = f"""
        <div hx-get="{modal_url}"
             hx-target="#dynamicCreateModalBox"
             hx-trigger="load"
             hx-swap="innerHTML"
             hx-on::load="openDynamicModal();">
        </div>
        """
        return HttpResponse(htmx_content)


def create_prepare_tabs_with_duplicate_tab(original_prepare_tabs):
    """
    Create a wrapped _prepare_detail_tabs method that adds Potential Duplicates tab.

    Args:
        original_prepare_tabs: The original _prepare_detail_tabs method
    """

    @wraps(original_prepare_tabs)
    def _prepare_detail_tabs_with_duplicate_tab(self):
        # Call original _prepare_detail_tabs first; this sets self.object_id
        # and builds self.tabs with all standard tabs.
        original_prepare_tabs(self)

        # Check if we have an object_id (required for tabs)
        if not self.object_id:
            return
        try:
            # Get model from self if available
            model = None
            if hasattr(self, "model") and self.model:
                model = self.model
            else:
                duplicate_rule_content_types = DuplicateRule.objects.values_list(
                    "content_type", flat=True
                ).distinct()

                # Try each content type to see if object_id exists in that model
                for horilla_ct_id in duplicate_rule_content_types:
                    try:
                        horilla_ct = HorillaContentType.objects.get(pk=horilla_ct_id)
                        model_name = horilla_ct.model

                        # Find the model class
                        Model = None
                        for app_config in apps.get_app_configs():
                            try:
                                Model = apps.get_model(
                                    app_config.label, model_name.lower()
                                )
                                if Model:
                                    break
                            except (LookupError, ValueError):
                                continue

                        if Model:
                            # Check if object with this pk exists in this model
                            if Model.objects.filter(pk=self.object_id).exists():
                                model = Model
                                break
                    except Exception:
                        continue

            if not model:
                return

            # Check if model has duplicate rules and matching rules
            try:
                model_name = model._meta.model_name.lower()
                content_type = HorillaContentType.objects.filter(
                    model=model_name
                ).first()

                if not content_type:
                    return

                # Check if there are duplicate rules for this content type
                duplicate_rules = DuplicateRule.objects.filter(
                    content_type=content_type
                )
                if not duplicate_rules.exists():
                    return

                # Check if at least one duplicate rule has a matching rule
                has_matching_rule = False
                for dup_rule in duplicate_rules:
                    if dup_rule.matching_rule:
                        has_matching_rule = True
                        break

                if not has_matching_rule:
                    return

                django_content_type = HorillaContentType.objects.get_for_model(model)
                content_type_id = django_content_type.pk

                duplicates_url = reverse(
                    "duplicates:potential_duplicates_tab", kwargs={}
                )
                # Use QueryDict to properly construct URL with parameters
                params = QueryDict(mutable=True)
                params["object_id"] = self.object_id
                params["content_type_id"] = content_type_id
                duplicates_url = f"{duplicates_url}?{params.urlencode()}"

                # Add the tab to self.tabs
                if not hasattr(self, "tabs"):
                    self.tabs = []

                # Check if tab already exists
                tab_exists = any(
                    tab.get("id") == "potential-duplicates" for tab in self.tabs
                )
                if not tab_exists:
                    tab_data = {
                        "title": _("Potential Duplicates"),
                        "url": duplicates_url,
                        "target": "tab-potential-duplicates-content",
                        "id": "potential-duplicates",
                    }
                    self.tabs.append(tab_data)
            except Exception as e:
                # If any error occurs, just skip adding the tab
                logger = logging.getLogger(__name__)
                logger.debug(
                    "Could not add Potential Duplicates tab: %s", e, exc_info=True
                )
        except Exception:
            pass

    return _prepare_detail_tabs_with_duplicate_tab


def _bulk_edit_tab_refresh(model, pk):
    """Return an HTMX div that reloads the Potential Duplicates tab content."""
    try:
        django_content_type = HorillaContentType.objects.get_for_model(model)
        params = QueryDict(mutable=True)
        params["object_id"] = pk
        params["content_type_id"] = django_content_type.pk
        tab_url = reverse("duplicates:potential_duplicates_tab")
        return (
            f'<div hx-get="{tab_url}?{params.urlencode()}"'
            f' hx-trigger="load"'
            f' hx-target="#inner-tab-potential-duplicates-content"'
            f' hx-swap="innerHTML"'
            f' style="display:none;"></div>'
        )
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "Could not build tab refresh for bulk inline edit: %s", exc
        )
        return ""


def _bulk_edit_duplicate_modal(request, duplicate_result, model, pk, rule_action):
    """
    Store duplicate warning data in session and return the HTMX modal-trigger snippet.
    rule_action is used verbatim: "allow" → Continue+Cancel, "block" → Cancel only.
    """
    session_key = f"duplicate_modal_{uuid.uuid4().hex[:16]}"
    request.session[session_key] = {
        "alert_title": duplicate_result.get(
            "alert_title", "Potential Duplicate Detected"
        ),
        "alert_message": str(
            duplicate_result.get(
                "alert_message",
                _("Similar records were found. Do you want to proceed?"),
            )
        ),
        "duplicate_records": [
            (r.pk, str(r)) for r in duplicate_result.get("duplicate_records", [])[:10]
        ],
        "show_duplicate_records": duplicate_result.get("show_duplicate_records", True),
        "model_name": model._meta.model_name,
        "action": rule_action,
        "save_and_new": "",
    }
    request.session.modified = True

    modal_url = reverse(
        "duplicates:duplicate_warning_modal",
        kwargs={"session_key": session_key},
    )
    return (
        f'<div hx-get="{modal_url}"'
        f' hx-target="#dynamicCreateModalBox"'
        f' hx-trigger="load"'
        f' hx-swap="innerHTML"'
        f' hx-on::load="openDynamicModal();"'
        f' style="display:none;"></div>'
    )


def create_bulk_update_check_before_save(original_check_before_save):
    """
    Wrap ``UpdateAllFieldsView.check_before_save`` to run a duplicate check
    against the fully in-memory-updated record before it's persisted.

    ``UpdateAllFieldsView.post`` applies every submitted field to the object
    in-memory first (without saving), then calls this hook once with the
    combined result and the list of field names actually changed in this
    submission. Returning ``None`` lets the save proceed; returning an
    ``HttpResponse`` short-circuits ``post`` with that response instead —
    used here to keep the bulk-edit form open with a duplicate-warning modal.

    Flow:
    - skip_duplicate_check=true in POST → let the save proceed, refresh tab
    - Model/rule guards fail → let the save proceed (no duplicate rules
      configured, or none of the changed fields matter to any rule)
    - Duplicates found, action=allow → keep the bulk-edit form open + modal
      (Continue re-submits with skip_duplicate_check=true; the modal locates
      the on-page form generically, so this works unchanged for the
      bulk-edit form)
    - Duplicates found, action=block → same, but Cancel only
    - No duplicates → let the save proceed, refresh tab
    """

    @wraps(original_check_before_save)
    def check_before_save_with_duplicate_check(self, request, obj, changed_fields):
        model = obj.__class__
        pk = obj.pk

        # User confirmed via "Continue" — proceed straight to save.
        if request.POST.get("skip_duplicate_check", "false").lower() == "true":
            return original_check_before_save(self, request, obj, changed_fields)

        # Guard: only process models registered for duplicate checking
        try:
            from horilla.registry.feature import FEATURE_REGISTRY

            duplicate_models = FEATURE_REGISTRY.get("duplicate_models", [])
            if model not in duplicate_models:
                return original_check_before_save(self, request, obj, changed_fields)
        except Exception:
            return original_check_before_save(self, request, obj, changed_fields)

        # Guard: skip duplicate check when every changed field is an owner field
        owner_fields = set(getattr(model, "OWNER_FIELDS", []))
        if owner_fields and set(changed_fields).issubset(owner_fields):
            return original_check_before_save(self, request, obj, changed_fields)

        # Guard: only process if model has active duplicate rules with matching
        # rules, AND at least one changed field is in a matching rule's criteria.
        try:
            ct = HorillaContentType.objects.filter(
                model=model._meta.model_name.lower()
            ).first()
            if not ct:
                return original_check_before_save(self, request, obj, changed_fields)
            rules = DuplicateRule.objects.filter(
                content_type=ct, matching_rule__isnull=False
            ).select_related("matching_rule")
            if not rules.exists():
                return original_check_before_save(self, request, obj, changed_fields)
            field_in_criteria = rules.filter(
                matching_rule__criteria__field_name__in=changed_fields
            ).exists()
            if not field_in_criteria:
                return original_check_before_save(self, request, obj, changed_fields)
        except Exception:
            return original_check_before_save(self, request, obj, changed_fields)

        try:
            duplicate_result = check_duplicates(obj, is_edit=True)

            if not duplicate_result.get("has_duplicates"):
                return original_check_before_save(self, request, obj, changed_fields)

            # Duplicates found — keep the bulk-edit form open, show modal
            from horilla.contrib.generics.views.helpers.edit_field import (
                build_edit_all_fields_context,
            )

            rule_action = duplicate_result.get("action", "allow")
            context = build_edit_all_fields_context(
                request,
                obj,
                model._meta.app_label,
                model._meta.model_name,
                pipeline_field=request.POST.get("pipeline_field"),
                cancel_url=request.POST.get("return_url", ""),
            )
            form_html = render_to_string(
                "partials/edit_all_fields.html", context, request=request
            )
            modal_html = _bulk_edit_duplicate_modal(
                request, duplicate_result, model, pk, rule_action
            )
            request._duplicate_check_blocked_save = True
            return HttpResponse(form_html + modal_html)

        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Bulk inline edit duplicate check failed: %s", exc
            )
            return original_check_before_save(self, request, obj, changed_fields)

    return check_before_save_with_duplicate_check


def append_bulk_edit_tab_refresh(request, response, app_label, model_name, pk):
    """
    Append a Potential Duplicates tab-refresh snippet to a successful bulk
    save response.

    Skipped when ``check_before_save`` blocked the save (flagged via
    ``request._duplicate_check_blocked_save`` — that response already is the
    re-opened bulk-edit form plus the warning modal, not a save result) or
    when the response isn't a plain 200 (e.g. a permission-denied
    ``ScriptResponse``).
    """
    if getattr(request, "_duplicate_check_blocked_save", False):
        return response
    if response.status_code != 200:
        return response
    try:
        model = apps.get_model(app_label, model_name)
    except Exception:
        return response
    refresh_html = _bulk_edit_tab_refresh(model, pk)
    if not refresh_html:
        return response
    response.content = response.content + refresh_html.encode("utf-8")
    return response

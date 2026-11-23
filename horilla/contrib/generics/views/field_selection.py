"""Generic "Insert Fields" modal view shared by mail and notification templates."""

# Standard library imports
import logging

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.methods import get_template_reverse_models
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.utils.middlewares import get_active_company
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import TemplateView

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "mail.view_horillamail",
            "mail.view_own_horillamail",
            "notifications.change_notificationtemplate",
            "notifications.view_notificationtemplate",
        ]
    ),
    name="dispatch",
)
class HorillaFieldSelectionView(LoginRequiredMixin, TemplateView):
    """
    Shared "Insert Fields" modal: lists the fields of a model (instance), the
    current user, the company and the request, as template variables. Used by the
    mail form, mail templates and notification templates.
    """

    template_name = "field_selection_modal.html"

    def get_context_data(self, **kwargs):
        """Build context with model/instance fields for template variable insertion."""
        context = super().get_context_data(**kwargs)

        model_name = self.request.GET.get("model_name")
        object_id = self.request.GET.get("object_id")
        content_type_id = self.request.GET.get("content_type")

        if model_name or content_type_id:
            tab_type = self.request.GET.get(
                "tab_type", "instance"
            )  # Default to instance if model exists
        else:
            tab_type = self.request.GET.get(
                "tab_type", "user"
            )  # Default to user if no model

        excluded_fields = {
            "is_active",
            "additional_info",
            "history",
            "password",
            "user_permissions",
            "groups",
            "last_login",
            "date_joined",
            "is_staff",
            "is_superuser",
            "recycle_bin_policy",
        }

        try:
            if tab_type == "instance" and model_name or content_type_id:
                if model_name:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                else:
                    content_type = HorillaContentType.objects.get(id=content_type_id)
                    # Use content_type.model (e.g. 'employee') for URLs, not verbose_name,
                    # so tab links send a value that HorillaContentType.objects.get(model=...) can find
                    model_name = content_type.model
                model_class = apps.get_model(
                    app_label=content_type.app_label, model_name=content_type.model
                )
                related_object = None
                if object_id and object_id != "None":
                    related_object = model_class.objects.get(pk=object_id)

                model_fields = []

                # Get regular fields (skip editable=False)
                for field in model_class._meta.get_fields():
                    if field.name in excluded_fields:
                        continue
                    if not getattr(field, "editable", True):
                        continue

                    if not field.many_to_many and not field.one_to_many:
                        field_info = {
                            "name": field.name,
                            "verbose_name": getattr(field, "verbose_name", field.name),
                            "field_type": field.__class__.__name__,
                            "template_syntax": f"{{{{ instance.{field.name} }}}}",
                            "is_foreign_key": (
                                field.many_to_one
                                if hasattr(field, "many_to_one")
                                else False
                            ),
                            "is_relation": hasattr(field, "related_model"),
                        }

                        model_fields.append(field_info)

                foreign_key_fields = []
                for field in model_class._meta.get_fields():
                    # Skip excluded fields
                    if field.name in excluded_fields:
                        continue
                    if not getattr(field, "editable", True):
                        continue

                    if field.many_to_one and hasattr(field, "related_model"):
                        # Get fields from the related model without needing object instance
                        for related_field in field.related_model._meta.get_fields():
                            # Skip excluded fields in related model too
                            if related_field.name in excluded_fields:
                                continue
                            if not getattr(related_field, "editable", True):
                                continue

                            if (
                                not related_field.many_to_many
                                and not related_field.one_to_many
                            ):
                                fk_field_info = {
                                    "name": (f"{field.name}.{related_field.name}"),
                                    "verbose_name": (
                                        getattr(
                                            related_field,
                                            "verbose_name",
                                            related_field.name,
                                        )
                                    ),
                                    "header": field.verbose_name,
                                    "field_type": (
                                        f"{field.__class__.__name__} -> "
                                        f"{related_field.__class__.__name__}"
                                    ),
                                    "template_syntax": (
                                        f"{{{{ instance.{field.name}."
                                        f"{related_field.name} }}}}"
                                    ),
                                    "parent_field": field.name,
                                    "is_foreign_key": True,
                                }

                                foreign_key_fields.append(fk_field_info)

                reverse_relation_fields = []

                # Models allowed as reverse relations in Insert field (feature registry)
                allowed_reverse_models = get_template_reverse_models()

                # Models already shown in Related Fields (forward FKs) - don't show again in Reverse
                related_models_in_forward = set()
                for f in model_class._meta.get_fields():
                    if (
                        f.many_to_one
                        and hasattr(f, "related_model")
                        and f.related_model
                    ):
                        related_models_in_forward.add(f.related_model)

                # Get all reverse relations
                for field in model_class._meta.get_fields():
                    if field.one_to_many or field.many_to_many:
                        # Skip fields that don't have get_accessor_name method
                        # (e.g., AuditlogHistoryField)
                        if not hasattr(field, "get_accessor_name"):
                            continue
                        try:
                            # Get the accessor name (like 'employee_set' or custom related_name)
                            accessor_name = field.get_accessor_name()

                            related_model = field.related_model

                            # Skip reverse relation if this model is already in Related Fields
                            if (
                                related_model
                                and related_model in related_models_in_forward
                            ):
                                continue

                            # Include only models in template_reverse registry when feature is registered
                            if (
                                allowed_reverse_models is not None
                                and related_model not in allowed_reverse_models
                            ):
                                continue

                            if related_model:
                                for reverse_field in related_model._meta.get_fields():
                                    if (
                                        reverse_field.name in excluded_fields
                                        or reverse_field.many_to_many
                                        or reverse_field.one_to_many
                                    ):
                                        continue
                                    if not getattr(reverse_field, "editable", True):
                                        continue

                                    if (
                                        hasattr(reverse_field, "related_model")
                                        and reverse_field.related_model == model_class
                                    ):
                                        continue

                                    reverse_field_info = {
                                        "name": (
                                            f"{accessor_name}.first."
                                            f"{reverse_field.name}"
                                        ),
                                        "verbose_name": (
                                            getattr(
                                                reverse_field,
                                                "verbose_name",
                                                reverse_field.name,
                                            )
                                        ),
                                        "header": field.related_model._meta.verbose_name,
                                        "field_type": (
                                            f"Reverse {field.__class__.__name__} -> "
                                            f"{reverse_field.__class__.__name__}"
                                        ),
                                        "template_syntax": (
                                            f"{{{{ instance.{accessor_name}|join_attr:"
                                            f"'{reverse_field.name}' }}}}"
                                        ),
                                        "parent_field": accessor_name,
                                        "is_reverse_relation": True,
                                    }

                                    reverse_relation_fields.append(reverse_field_info)
                        except Exception as e:
                            logger.error(
                                "Error processing reverse relation splits: %s",
                                e,
                            )
                            continue

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = foreign_key_fields
                context["reverse_relation_fields"] = reverse_relation_fields
                context["related_object"] = related_object

            elif tab_type == "user":
                user = self.request.user
                model_fields = []

                for field in user._meta.get_fields():
                    if field.name in excluded_fields:
                        continue
                    if not getattr(field, "editable", True):
                        continue

                    if not field.many_to_many and not field.one_to_many:
                        field_info = {
                            "name": field.name,
                            "verbose_name": getattr(field, "verbose_name", field.name),
                            "field_type": field.__class__.__name__,
                            "template_syntax": f"{{{{ request.user.{field.name} }}}}",
                            "is_foreign_key": (
                                field.many_to_one
                                if hasattr(field, "many_to_one")
                                else False
                            ),
                            "is_relation": hasattr(field, "related_model"),
                        }

                        model_fields.append(field_info)

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = []
                context["reverse_relation_fields"] = []
                context["related_object"] = user

            elif tab_type == "company":
                # Get current active company fields
                company = get_active_company(self.request)

                if company:
                    model_fields = []

                    for field in company._meta.get_fields():
                        if field.name in excluded_fields:
                            continue
                        if not getattr(field, "editable", True):
                            continue

                        if not field.many_to_many and not field.one_to_many:
                            field_info = {
                                "name": field.name,
                                "verbose_name": getattr(
                                    field, "verbose_name", field.name
                                ),
                                "field_type": field.__class__.__name__,
                                "template_syntax": f"{{{{ get_active_company(request).{field.name} }}}}",
                                "is_foreign_key": (
                                    field.many_to_one
                                    if hasattr(field, "many_to_one")
                                    else False
                                ),
                                "is_relation": hasattr(field, "related_model"),
                            }

                            model_fields.append(field_info)

                    context["model_fields"] = model_fields
                    context["foreign_key_fields"] = []
                    context["reverse_relation_fields"] = []
                    context["related_object"] = company
                else:
                    context["error"] = "No active company found"

            elif tab_type == "request":
                # Get request object fields (commonly used request attributes)
                request_fields = [
                    {
                        "name": "get_host",
                        "verbose_name": "Host",
                        "template_syntax": "{{ request.get_host }}",
                    },
                    {
                        "name": "scheme",
                        "verbose_name": "Scheme",
                        "template_syntax": "{{ request.scheme }}",
                    },
                ]

                model_fields = []
                for field_data in request_fields:
                    field_info = {
                        "name": field_data["name"],
                        "verbose_name": field_data["verbose_name"],
                        "field_type": "RequestAttribute",
                        "template_syntax": field_data["template_syntax"],
                        "is_foreign_key": False,
                        "is_relation": False,
                    }

                    model_fields.append(field_info)

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = []
                context["reverse_relation_fields"] = []
                context["related_object"] = self.request

            context["has_model_name"] = bool(model_name) or bool(content_type_id)
            context["model_name"] = model_name
            context["object_id"] = object_id
            context["tab_type"] = tab_type

        except Exception as e:
            context["error"] = f"Error loading fields: {str(e)}"
        return context

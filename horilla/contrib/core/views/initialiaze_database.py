"""
Views for initial database setup and onboarding workflow.

This module handles the step-by-step initialization process required
when Horilla is first installed. It includes:

- Checking whether database initialization is required
- Secured database initialization using a setup password
- Superuser creation and authentication
- Company creation and assignment
- Initial role creation and hierarchy setup
- Progress tracking across initialization steps
- HTMX-based partial rendering and navigation

These views are intended to run only during the first-time setup
and are protected using custom initialization guards and decorators.
"""

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.template import Context, Template

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.views import HorillaSingleFormView
from horilla.shortcuts import redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import db_initialization, htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import safe_url

# Local imports
from ..forms import CompanyFormClass, UserFormClassSingle
from ..models import Company, Role
from ..progress import ProgressStepsMixin
from ..signals import initialize_database_go_home


class InitializeDatabaseConditionView(View):
    """
    checks whether the database needs initialization.
    """

    def get_initialize_condition(self):
        """Check if the database needs initialization."""
        initialize_database = not User.objects.exists()
        return initialize_database


class InitializeDatabase(View, ProgressStepsMixin):
    """
    View to handle the initial database setup process.
    """

    current_step = 1

    def get(self, request, *args, **kwargs):
        """Handle GET requests for database initialization."""
        condition_view = InitializeDatabaseConditionView()
        initialize_database = condition_view.get_initialize_condition()
        next_url = safe_url(request, request.GET.get("next", "/"))
        if initialize_database:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
            }
            return render(request, "initialize_database/db_password.html", context)
        return redirect(next_url)


class InitializeDatabaseUser(View, ProgressStepsMixin):
    """
    View to handle user creation during database initialization.
    """

    current_step = 2

    def get(self, request, *args, **kwargs):
        """Handle GET requests for user creation during database initialization."""
        condition_view = InitializeDatabaseConditionView()
        initialize_database = condition_view.get_initialize_condition()
        next_url = safe_url(request, request.GET.get("next", "/"))
        if (
            request.session.get("db_password") == settings.DB_INIT_PASSWORD
            and initialize_database
        ):
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
            }
            return render(request, "initialize_database/sign_up.html", context)
        return redirect(next_url)

    def post(self, request, *args, **kwargs):
        """Handle POST requests for user creation during database initialization."""
        password = self.request.POST.get("db_password")

        if settings.DB_INIT_PASSWORD == password:
            request.session["db_password"] = password
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
            }
            return render(request, "initialize_database/sign_up.html", context)

        return render(
            request,
            "initialize_database/db_password.html",
            {"error": "Invalid password, please try again.", "password": password},
        )


class InitializeDatabaseCompany(LoginRequiredMixin, View, ProgressStepsMixin):
    """
    View to handle company creation during database initialization.
    """

    current_step = 3

    def get(self, request, *args, **kwargs):
        """Handle GET requests for company creation during database initialization."""
        next_url = safe_url(request, request.GET.get("next", "/"))
        if request.session.get("db_password") == settings.DB_INIT_PASSWORD:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
            }
            return render(
                request, "initialize_database/company_initialize.html", context
            )
        return redirect(next_url)


@method_decorator(db_initialization(model=User), name="dispatch")
@method_decorator(htmx_required(login=False), name="dispatch")
class SignUpFormView(HorillaSingleFormView, ProgressStepsMixin):
    """View to handle user sign-up during database initialization."""

    model = User
    view_id = "user-form-view"
    form_url = reverse_lazy("core:sign_up_user")
    form_class = UserFormClassSingle
    header = False
    modal_height = False
    current_step = 3
    skip_permission_check = True
    html = """{% load i18n static %}
        <div class="flex justify-end pt-5">
            <button class="border-[1px] border-[solid] border-[#e54f38] hover:border-[#9b210f] hover:bg-secondary-600 rounded-[5px] px-[15px] py-[8px] text-[#e54f38] flex gap-3 btn-with-icon border-[#e54f38] [transition:.3s] hover:text-white">
                <span id="single-form-save-spinner" class="htmx-indicator htmx-indicator-inline">
                    <img src="{% static '/assets/icons/spinner.svg' %}" alt="{% trans 'Loading...' %}" width="25" />
                </span>
                {% trans "Next" %}
                <img src="{% static 'assets/icons/ar3.svg' %}" alt="{% trans 'Next' %}" />
            </button>
        </div>
    """

    def get_button_html(self):
        """
        Render and return the HTML template for the form button.

        Returns:
            str: Rendered HTML string for the button element.
        """
        t = Template(self.html)
        return t.render(Context({}))

    def form_valid(self, form):
        instance = form.save(commit=False)

        instance.is_staff = True
        instance.is_superuser = True
        instance.save()
        raw_password = form.cleaned_data.get("password")
        user = authenticate(
            self.request, username=instance.username, password=raw_password
        )

        if user:
            login(self.request, user)
        context = {
            "progress_steps": self.get_progress_steps(),
            "current_step": self.current_step,
        }
        response = render(
            self.request, "initialize_database/company_initialize.html", context
        )
        response["HX-Retarget"] = "#initialize-user"
        response["HX-Reselect"] = "#initialize-company"
        response["HX-Push-Url"] = str(reverse_lazy("core:initialize_database_company"))
        return response


@method_decorator(db_initialization(model=Company), name="dispatch")
@method_decorator(htmx_required(), name="dispatch")
class InitializeCompanyFormView(
    LoginRequiredMixin, HorillaSingleFormView, ProgressStepsMixin
):
    """View to handle company creation during database initialization."""

    model = Company
    view_id = "user-form-view"
    form_url = reverse_lazy("core:initialize_company_form")
    form_class = CompanyFormClass
    current_step = 4
    header = False
    modal_height = False
    skip_permission_check = True
    html = """{% load i18n static %}
        <div class="flex justify-end pt-5">
            <button class="border-[1px] border-[solid] border-[#e54f38] hover:border-[#9b210f] hover:bg-secondary-600 rounded-[5px] px-[15px] py-[8px] text-[#e54f38] flex gap-3 btn-with-icon border-[#e54f38] [transition:.3s] hover:text-white">
                <span id="single-form-save-spinner" class="htmx-indicator htmx-indicator-inline">
                    <img src="{% static '/assets/icons/spinner.svg' %}" alt="{% trans 'Loading...' %}" width="25" />
                </span>
                {% trans "Next" %}
                <img src="{% static 'assets/icons/ar3.svg' %}" alt="{% trans 'Next' %}" />
            </button>
        </div>
    """

    def get_button_html(self):
        """
        Render and return the HTML template for the form button.

        Returns:
            str: Rendered HTML string for the button element.
        """
        t = Template(self.html)
        return t.render(Context({}))

    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.save()
        user = User.objects.filter(is_superuser=True).first()
        user.company = instance
        user.save(update_fields=["company"])
        self.request.session["company_id"] = instance.id
        context = {
            "progress_steps": self.get_progress_steps(),
            "current_step": self.current_step,
            "company_id": instance.id,
            "is_last": self.is_last_step(),
        }
        response = render(
            self.request, "initialize_database/initialize_role.html", context
        )
        response["HX-Retarget"] = "#initialize-company"
        response["HX-Reselect"] = "#initialize-role"
        response["HX-Push-Url"] = str(reverse_lazy("core:initialize_database_role"))
        return response


class InitializeRoleView(LoginRequiredMixin, View, ProgressStepsMixin):
    """
    View to handle the initial role setup process.
    """

    template_name = "initialize_database/initialize_role.html"
    current_step = 4
    response_template = None
    push_url = None
    select_id = None

    def get(self, request, *args, **kwargs):
        """Handle GET requests for role creation during database initialization."""
        next_url = safe_url(request, request.GET.get("next", "/"))
        company_id = request.GET.get("company_id") or request.session.get("company_id")
        edit_role_id = request.GET.get("edit_role")
        roles = Role.objects.all()

        edit_role = None
        if edit_role_id:
            edit_role = Role.objects.filter(id=edit_role_id).first()

        if request.session.get("db_password") == settings.DB_INIT_PASSWORD:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
                "roles": roles,
                "company_id": company_id,
                "edit_role": edit_role,
                "is_last": self.is_last_step(),
                "push_url": (
                    self.push_url if self.push_url else reverse_lazy("core:login")
                ),
                "select_id": self.select_id if self.select_id else "sec1",
            }
            return render(request, self.template_name, context)
        return redirect(next_url)

    def post(self, request, *args, **kwargs):
        """Handle POST requests for role creation during database initialization."""
        next_step = request.POST.get("next_step")
        company_id = request.POST.get("company_id") or request.session.get("company_id")
        role_name = request.POST.get("role_name")
        description = request.POST.get("description")
        parent_role_id = request.POST.get("parent_role")
        next_url = safe_url(request, request.POST.get("next", "/"))
        delete_role_id = request.POST.get("delete_role")
        edit_role_id = request.POST.get("edit_role_id")

        if delete_role_id:
            role_to_delete = Role.objects.filter(id=delete_role_id).first()
            if role_to_delete:
                role_to_delete.delete()

        elif role_name and description:
            parent_role = (
                Role.objects.filter(id=parent_role_id).first()
                if parent_role_id
                else None
            )
            if edit_role_id:
                role = Role.objects.filter(id=edit_role_id).first()
                if role:
                    role.role_name = role_name
                    role.description = description
                    role.parent_role = parent_role
                    role.save()
            else:
                Role.objects.create(
                    role_name=role_name,
                    description=description,
                    parent_role=parent_role,
                    company=request.active_company,
                )

        if next_step == "true":
            if self.is_last_step():
                request.session.flush()
            else:
                self.current_step = 5
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
                "company_id": company_id,
            }
            if self.response_template:
                return render(request, self.response_template, context)

            return redirect(next_url)

        roles = Role.objects.all()
        context = {
            "progress_steps": self.get_progress_steps(),
            "current_step": self.current_step,
            "roles": roles,
            "company_id": company_id,
            "is_last": self.is_last_step(),
            "push_url": (
                self.push_url if self.push_url else reverse_lazy("core:login")
            ),
            "select_id": self.select_id if self.select_id else "sec1",
        }
        return render(request, self.template_name, context)


class InitializeDatabaseGoHomeView(LoginRequiredMixin, View):
    """
    Exit remaining Initialize Database steps and go to the home page.
    """

    def get(self, request, *args, **kwargs):
        """Clear init session keys and redirect to the default home page."""
        if not User.objects.exists() or not Company.objects.exists():
            messages.error(
                request,
                _("Complete user sign-up and company setup before going to home."),
            )
            if not User.objects.exists():
                return redirect(reverse_lazy("core:initialize_database_user"))
            return redirect(reverse_lazy("core:initialize_database_company"))

        company_id = getattr(request.user, "company_id", None) or request.session.get(
            "company_id"
        )
        company = Company.objects.filter(pk=company_id).first()
        if company is None and getattr(request.user, "company_id", None):
            company = request.user.company

        if company:
            initialize_database_go_home.send(
                sender=self.__class__,
                company=company,
                request=request,
            )

        request.session.pop("db_password", None)
        request.session.pop("company_id", None)
        return redirect(settings.DEFAULT_HOME_REDIRECT)

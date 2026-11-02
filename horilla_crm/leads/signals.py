"""
Signal handlers for leads in Horilla CRM.
Handles automatic updates when company-related events occur, e.g., currency change.
"""

# Standard library imports
import logging
import threading

# Third-party imports (Django)
from django.dispatch import Signal, receiver

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.signals import (
    company_created,
    company_currency_changed,
    initialize_database_go_home,
)
from horilla.contrib.generics.forms.condition_fields import (
    get_condition_field_extension,
    get_condition_field_value,
    get_extension_condition_result,
)
from horilla.contrib.keys.models import ShortcutKey
from horilla.contrib.keys.utils import resolve_page_url
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import FieldDoesNotExist
from horilla.db import transaction
from horilla.db.models.signals import post_save, pre_save
from horilla.urls import reverse, reverse_lazy
from horilla.utils import timezone
from horilla.web.response import ScriptResponse
from horilla_crm.leads.assignment.evaluation import compare
from horilla_crm.leads.assignment.notify import (
    deliver_assignment_notifications,
    notify_assignment,
)
from horilla_crm.leads.assignment.pool import (
    OWNER_FIELD,
    VIA_AUTO,
    build_assignment_info,
    condition_users,
    pick_least_loaded,
)

# Local imports
from horilla_crm.leads.models import (
    DEFAULT_LEAD_INIT_STAGES,
    Lead,
    LeadAssignmentCondition,
    LeadAssignmentRule,
    LeadStatus,
)
from horilla_crm.scoring_rules.utils import compute_score

logger = logging.getLogger(__name__)


lead_stage_created = Signal()


@receiver(initialize_database_go_home)
def ensure_default_lead_stages_on_go_home(sender, company, request, **kwargs):
    """Create default lead stages when init wizard exits early to home."""
    if LeadStatus.objects.filter(company=company).exists():
        return

    user = request.user if request.user.is_authenticated else User.objects.first()
    for stage in DEFAULT_LEAD_INIT_STAGES:
        LeadStatus.objects.create(
            company=company,
            created_by=user,
            name=stage["name"],
            order=stage["order"],
            probability=stage["probability"],
            is_final=stage["is_final"],
        )


@receiver(company_created)
def handle_company_created(sender, instance, request, view, is_new, **kwargs):
    """Inject lead stages loading after company creation"""
    if is_new:  # Only for new companies
        request.session["newly_created_company_id"] = instance.id
        url = reverse("leads:load_lead_stages", kwargs={"company_id": instance.id})
        response = ScriptResponse.reload_close_and_load_content_modal(url)
        response["X-Debug"] = "Modal transition in progress"
        return response
    return None


@receiver(company_currency_changed)
def update_crm_on_currency_change(sender, **kwargs):
    """
    Updates Lead amounts when a company's currency changes.
    """
    company = kwargs.get("company")
    conversion_rate = kwargs.get("conversion_rate")

    leads_to_update = []
    leads = (
        Lead.objects.filter(company=company)
        .select_related()
        .only("id", "annual_revenue")
    )

    for lead in leads:
        if lead.annual_revenue is not None:
            lead.annual_revenue = lead.annual_revenue * conversion_rate
            leads_to_update.append(lead)

    if leads_to_update:
        Lead.objects.bulk_update(leads_to_update, ["annual_revenue"], batch_size=1000)


@receiver(post_save, sender=User)
def create_leads_shortcuts(sender, instance, created, **kwargs):
    """Create default keyboard shortcuts for leads when a user is created."""
    page = resolve_page_url("leads:leads_view")
    if not page:
        return

    predefined = [
        {"page": page, "key": "E", "command": "alt"},
    ]

    for item in predefined:
        ShortcutKey.all_objects.get_or_create(
            user=instance,
            key=item["key"],
            command=item["command"],
            defaults={
                "page": item["page"],
                "company": instance.company,
            },
        )


_CRM_SHORTKEY_URL_MIGRATIONS = {
    "/leads/leads-view/": "/crm/leads/leads-view/",
    "/accounts/accounts-view/": "/crm/accounts/accounts-view/",
    "/contacts/contacts-view/": "/crm/contacts/contacts-view/",
    "/opportunities/opportunities-view/": "/crm/opportunities/opportunities-view/",
    "/campaigns/campaign-view/": "/crm/campaigns/campaign-view/",
    "/forecast/forecast-view/": "/crm/forecast/forecast-view/",
    "crm/leads/leads-view/": "/crm/leads/leads-view/",
    "crm/accounts/accounts-view/": "/crm/accounts/accounts-view/",
    "crm/contacts/contacts-view/": "/crm/contacts/contacts-view/",
    "crm/opportunities/opportunities-view/": "/crm/opportunities/opportunities-view/",
    "crm/campaigns/campaign-view/": "/crm/campaigns/campaign-view/",
    "crm/forecast/forecast-view/": "/crm/forecast/forecast-view/",
}


# Disabled in v1.10.1: this one-time URL migration was only needed for the v1.10.0
# upgrade. Keeping the function in place for v1.10.1 release; remove entirely in the
# next version.
# @receiver(post_migrate, dispatch_uid="migrate_crm_shortkey_urls")
def migrate_crm_shortkey_urls(sender, **kwargs):
    """Prefix existing CRM shortkey URLs with crm/ after the URL restructure."""
    if sender.name != "horilla_crm.leads":
        return
    try:
        for old_url, new_url in _CRM_SHORTKEY_URL_MIGRATIONS.items():
            updated = ShortcutKey.all_objects.filter(page=old_url).update(page=new_url)
            print(f"Migrated {updated} shortkey(s): '{old_url}' → '{new_url}'")
            if updated:
                logger.info(
                    "Migrated %d shortkey(s): '%s' → '%s'", updated, old_url, new_url
                )
    except Exception as exc:
        logger.warning("Could not migrate CRM shortkey URLs: %s", exc)


@receiver(pre_save, sender=Lead)
def update_lead_score(sender, instance, **kwargs):
    """Signal to update lead score before saving a Lead instance."""

    instance.lead_score = compute_score(instance)


@receiver(pre_save, sender=Lead)
def flag_lead_conversion_transition(sender, instance, **kwargs):
    """
    Detect is_convert flipping False -> True on this save and stash that on
    the instance for handle_lead_conversion (post_save) to act on once the
    row is actually committed.
    """
    instance._just_converted = False
    if not instance.pk or not instance.is_convert:
        return
    was_converted = (
        Lead.objects.filter(pk=instance.pk).values_list("is_convert", flat=True).first()
    )
    instance._just_converted = not was_converted


@receiver(post_save, sender=Lead)
def handle_lead_conversion(sender, instance, created, **kwargs):
    """
    Run the same Account/Contact/Opportunity conversion the manual Convert
    button performs whenever is_convert flips to True from any code path
    (not just LeadConversionView), e.g. a WhatsApp Bot Rule's update_record
    node. Deferred to on_commit so the flip is durable before creating
    related records.
    """
    if created or not getattr(instance, "_just_converted", False):
        return
    if getattr(instance, "_skip_conversion_signal", False):
        # LeadConversionView already ran the conversion manually.
        return

    def _run():
        from horilla_crm.leads.methods import convert_lead

        try:
            lead = Lead.objects.get(pk=instance.pk)
            _account, contact, opportunity = convert_lead(lead, lead.company)
            # update() so the lead's post_save handlers do not fire again.
            Lead.objects.filter(pk=lead.pk).update(
                converted_contact=contact,
                converted_opportunity=opportunity,
                converted_at=timezone.now(),
            )
        except Lead.DoesNotExist:
            pass
        except Exception as exc:
            logger.error("handle_lead_conversion error (pk=%s): %s", instance.pk, exc)

    transaction.on_commit(_run)


def _eval_single_criterion(criteria, lead):
    """
    Evaluate one LeadAssignmentMatchCriteria row against a lead instance.
    Returns True if the criterion matches, False otherwise.
    """
    field = criteria.field
    operator = criteria.operator
    value = criteria.value or ""

    if get_condition_field_extension(field) is not None:
        extension_result = get_extension_condition_result(field, lead, operator, value)
        if extension_result is not None:
            return extension_result
        field_val = get_condition_field_value(field, lead)
        if field_val is None:
            return False
    else:
        try:
            meta_field = Lead._meta.get_field(field)
        except FieldDoesNotExist:
            logger.warning("Assignment rule: field '%s' does not exist on Lead", field)
            return False

        try:
            raw = getattr(lead, field, None)

            # FK → compare by PK string
            if (
                hasattr(meta_field, "related_model")
                and meta_field.related_model is not None
            ):
                field_val = str(raw.pk) if raw is not None else ""
            else:
                field_val = "" if raw is None else str(raw)
        except Exception as exc:
            logger.error(
                "Assignment rule criterion eval error (field=%s): %s", field, exc
            )
            return False

    return compare(operator, field_val, value, field=field)


def _eval_condition_criteria(condition, lead):
    """
    Evaluate all match-criteria rows of a condition using their AND/OR logic.
    Returns True if the condition as a whole matches the lead.
    No criteria means "always match".
    """
    criteria_qs = condition.criteria.all().order_by("created_at")
    if not criteria_qs.exists():
        return True

    result = None
    for criteria in criteria_qs:
        row_result = _eval_single_criterion(criteria, lead)
        if result is None:
            result = row_result
        elif criteria.logical_operator == "or":
            result = result or row_result
        else:
            result = result and row_result

    return bool(result)


def _resolve_target_users(condition):
    """
    Return a queryset of candidate User objects for the condition:
    - 'user' type → the explicitly selected users
    - 'role' type → all users whose role FK matches one of the selected roles
    """
    return condition_users(condition)


def _pick_least_loaded_user(users_qs):
    """
    From a queryset of users, return the one currently owning the fewest active leads.
    Ties broken by PK (lowest first) for determinism.
    """
    return pick_least_loaded(users_qs)


def apply_assignment_rules(lead):
    """
    Main assignment engine: evaluate active rules in order and apply the first matching condition.

    Steps:
    1. Iterate active LeadAssignmentRules ordered by creation date.
    2. For each rule, iterate its conditions (ordered by creation date).
    3. Evaluate criteria for each condition against the lead.
    4. On first match: pick the user with fewest leads (round-robin), update the lead's owner,
       then send email / notification / both per the condition's notify_method.
    5. Stop after the first matching condition across all rules.
    """
    try:
        rules = LeadAssignmentRule.objects.filter(is_active=True).order_by("created_at")
        for rule in rules:
            conditions = LeadAssignmentCondition.objects.filter(rule=rule).order_by(
                "created_at"
            )

            for condition in conditions:
                if not _eval_condition_criteria(condition, lead):
                    continue

                # Condition matched — resolve target users
                users_qs = _resolve_target_users(condition)
                assigned_user = _pick_least_loaded_user(users_qs)
                if not assigned_user:
                    logger.warning(
                        "Assignment rule '%s' condition #%s matched lead %s "
                        "but no eligible users found.",
                        rule.name,
                        condition.pk,
                        lead.pk,
                    )
                    continue

                # Assign via direct UPDATE to avoid re-triggering post_save.
                # The record of how the owner was chosen goes in the same UPDATE.
                additional_info = build_assignment_info(
                    lead.additional_info, condition, assigned_user, VIA_AUTO
                )
                Lead.objects.filter(pk=lead.pk).update(
                    **{OWNER_FIELD: assigned_user}, additional_info=additional_info
                )
                # keep in-memory object consistent
                setattr(lead, OWNER_FIELD, assigned_user)
                lead.additional_info = additional_info
                logger.info(
                    "Lead %s assigned to %s via rule '%s'.",
                    lead.pk,
                    assigned_user.username,
                    rule.name,
                )

                # Deliver notifications / email
                deliver_assignment_notifications(condition, lead, assigned_user)

                return  # first matching condition wins

    except Exception as exc:
        logger.error(
            "apply_assignment_rules error for lead %s: %s", lead.pk, exc, exc_info=True
        )


@receiver(post_save, sender=Lead)
def handle_lead_assignment(sender, instance, created, **kwargs):
    """
    Trigger assignment rules after a lead is created.
    Deferred to on_commit to guarantee the row exists before querying.

    A lead saved from a lead form with "Assign using rules" ticked already
    has its owner chosen from the rule's people, so the engine does not pick
    again; only the condition's notifications are sent. Every other creation
    path (import, API, web-to-lead, booking, form without the option) runs the
    engine as before.
    """
    if not created:
        return

    # Web-to-lead form with "Apply assignment rule" unticked: keep the owner
    # selected in the form.
    if getattr(instance, "_skip_assignment_rule", False):
        return

    condition_id = getattr(instance, "_assignment_condition_id", None)
    if condition_id:
        transaction.on_commit(lambda: notify_assignment(condition_id, instance.pk))
        return

    def _run():
        try:
            lead = Lead.objects.get(pk=instance.pk)
            apply_assignment_rules(lead)
        except Lead.DoesNotExist:
            pass
        except Exception as exc:
            logger.error("handle_lead_assignment error (pk=%s): %s", instance.pk, exc)

    transaction.on_commit(_run)


# ─── Booking Integration ──────────────────────────────────────────────────────
# booking fires booking_submitted; we own Lead/Contact/Activity creation.
# Import is deferred inside the handler to avoid issues if booking is
# not installed.


def _send_booking_confirmation(booking, company):
    """Send a meeting-invitation-style confirmation email to the booker."""
    from django.conf import settings as _settings

    booking_pk = booking.pk

    site_url = getattr(_settings, "SITE_URL", "").rstrip("/")
    if not site_url:
        request = getattr(_thread_local, "request", None)
        if request:
            site_url = request.build_absolute_uri("/").rstrip("/")

    def _send():
        try:
            from booking.models import Booking as _Booking
            from booking.tasks import send_booking_confirmation_email

            booking_obj = _Booking.all_objects.select_related(
                "booking_page__host", "booking_page"
            ).get(pk=booking_pk)

            cancel_url = f"{site_url}{reverse_lazy('booking:booking_cancel', kwargs={'token': booking_obj.cancellation_token})}"
            reschedule_url = f"{site_url}{reverse_lazy('booking:booking_reschedule', kwargs={'token': booking_obj.cancellation_token})}"

            send_booking_confirmation_email(
                booking_obj,
                cancel_url=cancel_url,
                reschedule_url=reschedule_url,
            )
        except Exception:
            logger.exception(
                "Booking confirmation email failed for booking pk=%s", booking_pk
            )

    threading.Thread(target=_send, daemon=True).start()


try:
    from booking.signals import booking_submitted as _booking_submitted

    @receiver(_booking_submitted)
    def create_or_link_crm_record(
        sender, booker_name, booker_email, booking_instance, company, **kwargs
    ):
        """
        When a public booking is submitted:
        1. Find existing Lead or Contact by email (company-scoped).
        2. If none found, create a new Lead.
        3. Create a Meeting Activity linked to the Lead/Contact.
        4. Update the Booking with the CRM links.
        5. Send a confirmation email (non-blocking thread).
        """
        try:
            from horilla.contrib.activity.models import Activity
            from horilla.contrib.core.models import HorillaContentType
            from horilla_crm.contacts.models import Contact

            lead = None
            contact = None

            lead = Lead.all_objects.filter(email=booker_email, company=company).first()
            if not lead:
                contact = Contact.all_objects.filter(
                    email=booker_email, company=company
                ).first()
                if not contact:
                    name_parts = booker_name.strip().split(None, 1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else "-"
                    default_status = (
                        LeadStatus.all_objects.filter(company=company).first()
                        or LeadStatus.all_objects.first()
                    )
                    lead = Lead.objects.create(
                        email=booker_email,
                        first_name=first_name,
                        last_name=last_name,
                        lead_source="website",
                        lead_owner=booking_instance.booking_page.host,
                        lead_status=default_status,
                        lead_company="",
                        industry="other",
                        country="",
                        company=company,
                    )

            crm_obj = lead or contact
            page = booking_instance.booking_page
            content_type = HorillaContentType.objects.get_for_model(crm_obj)
            subject = f"{page.title}"[:100]
            activity = Activity.objects.create(
                activity_type="meeting",
                subject=subject,
                title=subject,
                status="scheduled",
                start_datetime=booking_instance.start_datetime,
                end_datetime=booking_instance.end_datetime,
                is_online=page.is_online,
                meeting_provider=page.meeting_provider if page.is_online else "",
                meeting_url=booking_instance.meeting_url or "",
                location=page.location or "",
                owner=page.host,
                meeting_host=page.host,
                external_participants=[booker_email],
                company=company,
                content_type=content_type,
                object_id=crm_obj.pk,
            )
            page_participants = list(page.participants.all())
            if page_participants:
                activity.participants.set(page_participants)

            booking_instance.activity = activity
            info = booking_instance.additional_info or {}
            if lead:
                info["crm_lead_id"] = lead.pk
            elif contact:
                info["crm_contact_id"] = contact.pk
            booking_instance.additional_info = info
            booking_instance.save(update_fields=["activity", "additional_info"])

            _send_booking_confirmation(booking_instance, company)

        except Exception:
            logger.exception(
                "create_or_link_crm_record failed for booking pk=%s",
                booking_instance.pk,
            )

except ImportError:
    pass

"""
Signal handlers for leads in Horilla CRM.
Handles automatic updates when company-related events occur, e.g., currency change.
"""

# Standard library imports
import logging
import threading

# Third-party imports (Django)
from django.dispatch import Signal, receiver
from django.template import engines

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.signals import (
    company_created,
    company_currency_changed,
    initialize_database_go_home,
)
from horilla.contrib.keys.models import ShortcutKey
from horilla.contrib.keys.utils import resolve_page_url
from horilla.contrib.notifications.methods import create_notification
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import FieldDoesNotExist
from horilla.db import transaction
from horilla.db.models import Count
from horilla.db.models.signals import post_save, pre_save
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils import timezone
from horilla.web.response import ScriptResponse

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
            convert_lead(lead, lead.company)
        except Lead.DoesNotExist:
            pass
        except Exception as exc:
            logger.error("handle_lead_conversion error (pk=%s): %s", instance.pk, exc)

    transaction.on_commit(_run)


def _get_custom_field_value_for_lead(field, lead):
    """
    Resolve a 'cf_<id>' condition field to its string value for this lead.
    Returns None if the field definition can't be resolved (caller treats
    that as "no match"), or "" when the lead simply has no value stored.
    """
    try:
        from custom_fields.models import CustomFieldDefinition, CustomFieldValue
        from horilla.contrib.core.models import HorillaContentType

        cfd = CustomFieldDefinition.objects.filter(pk=field[len("cf_") :]).first()
        if not cfd:
            logger.warning(
                "Assignment rule: custom field '%s' no longer exists", field
            )
            return None
        content_type = HorillaContentType.objects.get(app_label="leads", model="lead")
        cfv = CustomFieldValue.objects.filter(
            field_definition=cfd, content_type=content_type, object_id=lead.pk
        ).first()
        if not cfv:
            return ""
        value = cfv.get_value()
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return "" if value is None else str(value)
    except Exception as exc:
        logger.error(
            "Assignment rule custom field eval error (field=%s): %s", field, exc
        )
        return None


def _eval_single_criterion(criteria, lead):
    """
    Evaluate one LeadAssignmentMatchCriteria row against a lead instance.
    Returns True if the criterion matches, False otherwise.
    """
    field = criteria.field
    operator = criteria.operator
    value = criteria.value or ""

    if field.startswith("cf_"):
        field_val = _get_custom_field_value_for_lead(field, lead)
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

    try:
        if operator == "exact":
            return field_val == value
        if operator == "ne":
            return field_val != value
        if operator == "icontains":
            return value.lower() in field_val.lower()
        if operator == "not_contains":
            return value.lower() not in field_val.lower()
        if operator == "istartswith":
            return field_val.lower().startswith(value.lower())
        if operator == "iendswith":
            return field_val.lower().endswith(value.lower())
        if operator == "isnull":
            return not field_val.strip()
        if operator == "isnotnull":
            return bool(field_val.strip())
        if operator in ("gt", "gte", "lt", "lte"):
            try:
                fv, rv = float(field_val), float(value)
                return {"gt": fv > rv, "gte": fv >= rv, "lt": fv < rv, "lte": fv <= rv}[
                    operator
                ]
            except (ValueError, TypeError):
                return False
        if operator == "between":
            parts = [p.strip() for p in value.split(",") if p.strip()]
            if len(parts) == 2:
                try:
                    fv = float(field_val)
                    return float(parts[0]) <= fv <= float(parts[1])
                except (ValueError, TypeError):
                    return False
    except Exception as exc:
        logger.error("Assignment rule criterion eval error (field=%s): %s", field, exc)

    return False


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
    if condition.assign_to_type == "role":
        roles = condition.assign_to_roles.all()
        return User.objects.filter(role__in=roles, is_active=True)
    return condition.assign_to_users.filter(is_active=True)


def _pick_round_robin(users_qs):
    """
    From a queryset of users, return the one currently owning the fewest active leads.
    Ties broken by PK (lowest first) for determinism.
    """
    if not users_qs.exists():
        return None
    return (
        users_qs.annotate(lead_count=Count("lead")).order_by("lead_count", "pk").first()
    )


def _send_assignment_email(condition, lead, assigned_user):
    """Send assignment email to the assigned user using the condition's mail template."""
    try:
        from horilla.contrib.core.models import HorillaContentType
        from horilla.contrib.mail.models import HorillaMail, HorillaMailConfiguration
        from horilla.contrib.mail.services import HorillaMailManager

        tmpl = condition.mail_template
        if not tmpl or not assigned_user.email:
            return

        company = getattr(lead, "company", None)
        sender = None
        if company:
            sender = (
                HorillaMailConfiguration.objects.filter(
                    company=company, mail_channel="outgoing", is_primary=True
                ).first()
                or HorillaMailConfiguration.objects.filter(
                    company=company, mail_channel="outgoing"
                ).first()
            )

        content_type = HorillaContentType.objects.get_for_model(lead)
        mail = HorillaMail.objects.create(
            sender=sender,
            to=assigned_user.email,
            subject=tmpl.subject or "",
            body=tmpl.body or "",
            content_type=content_type,
            object_id=lead.pk,
            mail_status="draft",
            company=company,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        context = {"instance": lead, "user": assigned_user, "lead": lead}

        def _send():
            try:
                if sender:
                    setattr(_thread_local, "from_mail_id", sender.pk)
                HorillaMailManager.send_mail(mail, context=context)
            except Exception as exc:
                logger.error(
                    "Assignment rule email send error (lead=%s): %s", lead.pk, exc
                )
            finally:
                if hasattr(_thread_local, "from_mail_id"):
                    delattr(_thread_local, "from_mail_id")

        threading.Thread(target=_send, daemon=True).start()

    except Exception as exc:
        logger.error("Assignment rule email setup error (lead=%s): %s", lead.pk, exc)


def _send_assignment_notification(condition, lead, assigned_user):
    """Send in-app notification to the assigned user using the condition's notification template."""
    try:
        tmpl = condition.notification_template
        if not tmpl:
            return

        context = {"instance": lead, "lead": lead}
        django_engine = engines["django"]
        msg_src = (
            ("{% load horilla_tags %}\n" + tmpl.message).strip() if tmpl.message else ""
        )
        message = (
            django_engine.from_string(msg_src).render(context)[:500]
            if msg_src
            else f"New lead assigned: {lead}"
        )

        lead_url = (
            str(lead.get_detail_url()) if hasattr(lead, "get_detail_url") else None
        )
        create_notification(
            user=assigned_user,
            message=message,
            sender=None,
            url=lead_url,
            instance=lead,
            read=False,
        )
    except Exception as exc:
        logger.error("Assignment rule notification error (lead=%s): %s", lead.pk, exc)


def apply_assignment_rules(lead):
    """
    Main assignment engine: evaluate active rules in order and apply the first matching condition.

    Steps:
    1. Iterate active LeadAssignmentRules ordered by creation date.
    2. For each rule, iterate its conditions (ordered by `order`).
    3. Evaluate criteria for each condition against the lead.
    4. On first match: pick the user with fewest leads (round-robin), update lead_owner,
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
                assigned_user = _pick_round_robin(users_qs)
                if not assigned_user:
                    logger.warning(
                        "Assignment rule '%s' condition #%s matched lead %s "
                        "but no eligible users found.",
                        rule.name,
                        condition.order,
                        lead.pk,
                    )
                    continue

                # Assign via direct UPDATE to avoid re-triggering post_save
                Lead.objects.filter(pk=lead.pk).update(lead_owner=assigned_user)
                lead.lead_owner = assigned_user  # keep in-memory object consistent
                logger.info(
                    "Lead %s assigned to %s via rule '%s'.",
                    lead.pk,
                    assigned_user.username,
                    rule.name,
                )

                # Deliver notifications / email
                method = condition.notify_method
                if method in ("email", "both"):
                    _send_assignment_email(condition, lead, assigned_user)
                if method in ("notification", "both"):
                    _send_assignment_notification(condition, lead, assigned_user)

                return  # first matching condition wins

    except Exception as exc:
        logger.error(
            "apply_assignment_rules error for lead %s: %s", lead.pk, exc, exc_info=True
        )


@receiver(post_save, sender=Lead)
def handle_lead_assignment(sender, instance, created, **kwargs):
    """
    Trigger assignment rules after a lead is created or updated.
    Deferred to on_commit to guarantee the row exists before querying.
    """

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
                meeting_url="",
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

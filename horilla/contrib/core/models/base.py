"""
This module defines the core models for the Horilla platform
"""

# Third-party imports
# Standard library imports
import logging

from auditlog.models import AuditlogHistoryField, LogEntry

# Django imports
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

# Third-party imports (Django)
from django_countries.fields import CountryField
from djmoney.settings import CURRENCY_CHOICES

from horilla.apps import apps
from horilla.contrib.utils.middlewares import _thread_local
from horilla.db import models
from horilla.extension import ExtensionModelBase
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.choices import (
    DATE_FORMAT_CHOICES,
    DATETIME_FORMAT_CHOICES,
    TIME_FORMAT_CHOICES,
    TIMEZONE_CHOICES,
)
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.upload import upload_path

logger = logging.getLogger(__name__)

# Models that may point at a parent via GenericForeignKey or string GFK
# (related_model_name + related_object_id). Built once; used by full_histories.
_HISTORY_GFK_MODELS = None


def get_history_gfk_models():
    """
    Return models that can link to an arbitrary parent via GFK / string GFK.

    Cached after first call so history tabs do not re-scan apps.get_models().
    ContentTypes are NOT resolved here — that happens only when related rows exist.
    """
    global _HISTORY_GFK_MODELS
    if _HISTORY_GFK_MODELS is not None:
        return _HISTORY_GFK_MODELS

    candidates = []
    for model in apps.get_models():
        has_gfk = any(
            isinstance(field, GenericForeignKey) for field in model._meta.private_fields
        )
        field_names = {
            field.name for field in model._meta.get_fields() if hasattr(field, "name")
        }
        has_string_gfk = (
            "related_model_name" in field_names and "related_object_id" in field_names
        )
        if has_gfk or has_string_gfk:
            candidates.append(model)

    _HISTORY_GFK_MODELS = candidates
    return _HISTORY_GFK_MODELS


@permission_exempt_model
class HorillaContentType(ContentType):
    """Proxy model for Django's ContentType with custom verbose names."""

    class Meta:
        """Meta options for the HorillaContentType model."""

        proxy = True
        verbose_name = _("Model")
        verbose_name_plural = _("Models")

    def __str__(self):
        model_cls = self.model_class()
        if model_cls:
            return str(model_cls._meta.verbose_name)
        return self.model.replace("_", " ").title()


class Company(models.Model):
    """
    Company model representing business entities in the system.
    """

    name = models.CharField(max_length=255, verbose_name=_("Company Name"))
    email = models.EmailField(max_length=255, verbose_name=_("Email Address"))
    website = models.URLField(max_length=255, blank=True, verbose_name=_("Website"))
    icon = models.ImageField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Company Icon"),
    )
    contact_number = models.CharField(
        max_length=20, blank=True, null=True, verbose_name=_("Contact Number")
    )
    fax = models.CharField(
        max_length=20, blank=True, null=True, verbose_name=_("Fax Number")
    )
    annual_revenue = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Annual Revenue"),
    )
    no_of_employees = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Number of Employees")
    )
    hq = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Head Quarter")
    )
    country = CountryField(verbose_name=_("Country"))
    state = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("State/Province")
    )
    city = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("City")
    )
    zip_code = models.CharField(
        max_length=20, blank=True, null=True, verbose_name=_("ZIP/Postal Code")
    )
    language = models.CharField(
        max_length=50,
        choices=settings.LANGUAGES,
        blank=True,
        null=True,
        verbose_name=_(
            "Language",
        ),
    )
    time_zone = models.CharField(
        max_length=100,
        choices=TIMEZONE_CHOICES,
        default="UTC",
        verbose_name=_("Time Zone"),
    )
    currency = models.CharField(
        max_length=20,
        choices=CURRENCY_CHOICES,
        default="USD",
        help_text=_("Select your preferred currency"),
        verbose_name=_("Currency"),
    )
    time_format = models.CharField(
        max_length=20,
        choices=TIME_FORMAT_CHOICES,
        default="%I:%M:%S %p",
        help_text=_("Select your preferred time format."),
        verbose_name=_("Time Format"),
    )
    date_format = models.CharField(
        max_length=20,
        choices=DATE_FORMAT_CHOICES,
        default="%Y-%m-%d",
        help_text=_("Select your preferred date format."),
        verbose_name=_("Date Format"),
    )
    date_time_format = models.CharField(
        max_length=100,
        choices=DATETIME_FORMAT_CHOICES,
        default="%Y-%m-%d %H:%M:%S",
        help_text=_("Select your preferred date time format."),
        verbose_name=_("Date Time Format"),
    )
    activate_multiple_currencies = models.BooleanField(
        default=False, verbose_name=_("Multiple Currencies")
    )
    all_objects = models.Manager()
    objects = models.Manager()

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_created",
        verbose_name=_("Created By"),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_updated",
        verbose_name=_("Updated By"),
    )

    class Meta:
        """
        Meta options for the Company model.
        """

        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")
        ordering = ["name"]

    SORT_FIELD_MAPPING = {"get_avatar_with_name": "name"}

    def __str__(self):
        return f"{self.name}"

    def get_detail_view_url(self):
        """
        This method to get detail view url
        """
        return reverse_lazy("core:branch_detail_view", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("core:edit_company", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("core:branch_delete", kwargs={"pk": self.pk})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_currency = self.currency

    def save(self, *args, **kwargs):
        """
        Fixed save method to prevent recursion and handle currency changes.
        """
        if hasattr(self, "_saving"):
            super().save(*args, **kwargs)
            return None

        self._saving = True
        try:
            if not Company.objects.exclude(pk=self.pk).filter(hq=True).exists():
                self.hq = True
            elif self.hq:
                Company.objects.exclude(pk=self.pk).filter(hq=True).update(hq=False)

            super().save(*args, **kwargs)

            self._original_currency = self.currency

            return None

        except Exception as e:
            logger.error("Error saving company %s: %s", self.pk, e)
            raise
        finally:
            del self._saving

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.name}&background=random"
        return url

    def get_avatar_with_name(self):
        """
        Returns HTML to render profile image and full name (first + last name).
        """
        image_url = self.icon.url if self.icon else self.get_avatar()
        name = self.name
        return format_html(
            """
            <div class="flex items-center space-x-2">
                <img src="{}" alt="{}" class="w-8 h-8 rounded-full object-cover" />
                <span class="text-sm font-medium text-gray-900 hover:text-primary-600">{}</span>
            </div>
            """,
            image_url,
            name,
            name,
        )


class CompanyFilteredManager(models.Manager):
    """Manager that filters queryset by active company in request."""

    def get_queryset(self):
        """Get queryset filtered by active company."""
        queryset = super().get_queryset()
        try:
            request = getattr(_thread_local, "request", None)
            if request is None:
                return queryset
            # Check if request has session attribute before accessing it
            if hasattr(request, "session") and request.session.get(
                "show_all_companies", False
            ):
                return queryset

            company = getattr(request, "active_company", None)
            if not company:
                # ActiveCompanyMiddleware runs before DRF resolves request.user
                # for non-session auth (JWT/Basic), so active_company can still
                # be unset here even though the request is now authenticated.
                user = getattr(request, "user", None)
                if user is not None and user.is_authenticated:
                    company = getattr(user, "company", None)
            if company:
                queryset = queryset.filter(company=company)
        except Exception as e:
            logger.error("Error in CompanyFilteredManager.get_queryset: %s", e)
        return queryset


class HorillaCoreModel(models.Model, metaclass=ExtensionModelBase):
    """
    Core Base model.

    Supports _inherit_model extensions: subclass with
    _inherit_model = "app_label.ModelName" to inject fields onto an existing
    model without creating a new table.
    """

    is_active = models.BooleanField(
        default=True, db_index=True, verbose_name=_("Is Active")
    )
    additional_info = models.JSONField(
        blank=True, null=True, verbose_name=_("Additional Info")
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Company"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name=_("Created At")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_created",
        verbose_name=_("Created By"),
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="%(class)s_updated",
        verbose_name=_("Updated By"),
    )
    history = AuditlogHistoryField()
    objects = CompanyFilteredManager()
    all_objects = models.Manager()

    field_permissions_exclude = [
        "is_active",
        "additional_info",
        "company",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    ]

    class Meta:
        """
        Meta options for the HorillaCoreModel."""

        abstract = True

    # Bookkeeping fields that change on every save regardless of whether any
    # "real" field changed — never enough on their own to justify a write.
    _NOOP_SAVE_IGNORE_FIELDS = frozenset({"updated_at", "updated_by"})

    def _has_real_changes(self):
        """
        Return whether any concrete field (other than bookkeeping ones) differs
        from what's currently stored in the database for this pk.

        Used by :meth:`save` to skip a write (and therefore every signal,
        including auditlog's) when a full-object save would otherwise be a
        pure no-op — e.g. a detail-tab or edit-form "Save" with nothing
        actually changed. Only called when ``self.pk`` is set and no
        ``update_fields`` was passed, so partial/explicit saves are never
        affected by this check.
        """
        concrete_fields = [
            f
            for f in self._meta.concrete_fields
            if f.name not in self._NOOP_SAVE_IGNORE_FIELDS
        ]
        field_names = [f.name for f in concrete_fields]
        db_obj = type(self).all_objects.filter(pk=self.pk).values(*field_names).first()
        if db_obj is None:
            return True
        for field in concrete_fields:
            current = field.pre_save(self, add=False)
            if current != db_obj[field.name]:
                return True
        return False

    def save(self, *args, force=False, **kwargs):
        """
        Override save to automatically set created_by, updated_by, created_at,
        updated_at, and company fields.

        ``force=True`` skips the no-op check below and always writes/bumps
        updated_at/updated_by — use it when the caller knows a related
        change happened that ``_has_real_changes`` can't see on its own
        (e.g. a many-to-many field, which lives on a separate table and
        isn't part of ``_meta.concrete_fields``).
        """
        user = None

        request = getattr(_thread_local, "request", None)
        if request:
            user = getattr(request, "user", None)
        now = timezone.now()
        if not self.pk:
            if user and not isinstance(user, AnonymousUser):
                self.created_by = user
                self.updated_by = user
            self.created_at = now
            self.updated_at = now

        else:
            if (
                not force
                and kwargs.get("update_fields") is None
                and not self._state.adding
            ):
                if not self._has_real_changes():
                    return
            if user and not isinstance(user, AnonymousUser):
                self.updated_by = user
            self.updated_at = now
        super().save(*args, **kwargs)

    @property
    def histories(self):
        """
        Returns sorted auditlog history entries for this object.
        Usage: instance.histories
        """
        return self.history.all().order_by("-timestamp")

    @property
    def full_histories(self):
        """
        Returns auditlog history for this object + any related models (FK or GFK)
        with optimized status field retrieval.

        Avoids one ``django_content_type`` lookup per installed model: ContentTypes
        are resolved only for models that actually have related rows (via
        ``get_for_models`` in one query).
        """
        own_history = list(self.history.all())

        current_model = self.__class__._meta.concrete_model
        content_type = HorillaContentType.objects.get_for_model(current_model)
        related_by_model = {}
        # How each related model reaches this object, used below to pick the
        # log entries that record it being linked / unlinked.
        fk_link_fields = {}
        gfk_linked_models = set()

        def _add_related(model, pks):
            if not pks:
                return
            related_by_model.setdefault(model, set()).update(pks)

        # Reverse FKs / OneToOne pointing at this model (no all-models scan).
        skipped = getattr(current_model, "FULL_HISTORY_EXCLUDE", ())
        for rel in current_model._meta.related_objects:
            if rel.many_to_many or rel.get_accessor_name() in skipped:
                continue
            model = rel.related_model
            if getattr(model, "HISTORY_EXCLUDE_FROM_RELATED", False):
                continue
            field_name = rel.field.name
            fk_link_fields.setdefault(model, set()).add(field_name)
            _add_related(
                model,
                model.objects.filter(**{field_name: self}).values_list("pk", flat=True),
            )

        # GFK + string-GFK candidates only (cached list; CT deferred).
        for model in get_history_gfk_models():
            if getattr(model, "HISTORY_EXCLUDE_FROM_RELATED", False):
                continue
            opts = model._meta
            related_pks = set()

            for gfk in opts.private_fields:
                if not isinstance(gfk, GenericForeignKey):
                    continue
                related_pks.update(
                    model.objects.filter(
                        **{gfk.ct_field: content_type, gfk.fk_field: self.pk}
                    ).values_list("pk", flat=True)
                )

            field_names = {
                field.name for field in opts.get_fields() if hasattr(field, "name")
            }
            if (
                "related_model_name" in field_names
                and "related_object_id" in field_names
            ):
                manager = getattr(model, "all_objects", model.objects)
                related_pks.update(
                    manager.filter(
                        related_model_name__iexact=current_model._meta.model_name,
                        related_object_id=self.pk,
                    ).values_list("pk", flat=True)
                )

            if related_pks:
                gfk_linked_models.add(model)
            _add_related(model, related_pks)

        # Only the moments a related record was linked to / unlinked from this
        # object belong in its history. Anything else that happens to that
        # record (edits, or its creation when it was made before being linked
        # here) is its own history and is not repeated here.
        self_pk = str(self.pk)

        def _is_link_event(entry, model):
            if model in gfk_linked_models and entry.action in (
                LogEntry.Action.CREATE,
                LogEntry.Action.DELETE,
            ):
                return True
            changes = entry.changes_dict or {}
            if model in gfk_linked_models and entry.action == LogEntry.Action.UPDATE:
                # A model can opt specific fields in (e.g. a mail's status
                # moving from draft to sent) so its lifecycle reads in the
                # parent's history; every other edit stays out.
                tracked = getattr(model, "HISTORY_LINKED_UPDATE_FIELDS", ())
                tracked_changes = {f: changes[f] for f in tracked if f in changes}
                if tracked_changes:
                    # In-memory only, the log row is never saved.
                    entry.changes = tracked_changes
                    return True
            link_changes = {}
            for field_name in fk_link_fields.get(model, ()):
                change = changes.get(field_name)
                if (
                    isinstance(change, (list, tuple))
                    and len(change) == 2
                    and self_pk in (str(change[0]), str(change[1]))
                ):
                    link_changes[field_name] = change
            if not link_changes:
                return False
            if entry.action == LogEntry.Action.UPDATE:
                # An edit that also touched other fields of the related record
                # (e.g. probability alongside the campaign) shows only the link
                # itself here; the rest stays in that record's own history.
                # In-memory only, the log row is never saved.
                entry.changes = link_changes
            return True

        related_history = []
        if related_by_model:
            model_ct_map = HorillaContentType.objects.get_for_models(
                *related_by_model.keys(), for_concrete_models=True
            )
            for model, related_pks in related_by_model.items():
                model_ct = model_ct_map[model]
                object_pks = [str(pk) for pk in related_pks]
                entries = [
                    entry
                    for entry in LogEntry.objects.filter(
                        content_type=model_ct,
                        object_pk__in=object_pks,
                    )
                    if _is_link_event(entry, model)
                ]
                if hasattr(model, "status"):
                    status_map = {
                        str(obj.pk): obj.status
                        for obj in model.objects.filter(pk__in=related_pks).only(
                            "pk", "status"
                        )
                    }
                    for entry in entries:
                        entry.status = status_map.get(entry.object_pk)
                # A record that is created in a placeholder state and then
                # moved on (a mail is saved as a draft the moment the compose
                # window opens, then sent) should read as its outcome only,
                # not as "Draft created" followed by the outcome.
                transient = getattr(model, "HISTORY_TRANSIENT_CREATE", None)
                if transient:
                    field_name, placeholder = transient
                    moved_on = set()
                    for entry in entries:
                        change = (entry.changes_dict or {}).get(field_name)
                        if (
                            entry.action == LogEntry.Action.UPDATE
                            and isinstance(change, (list, tuple))
                            and len(change) == 2
                            and str(change[0]) == placeholder
                        ):
                            moved_on.add(entry.object_pk)
                    entries = [
                        entry
                        for entry in entries
                        if not (
                            entry.action == LogEntry.Action.CREATE
                            and entry.object_pk in moved_on
                            and str(
                                (entry.changes_dict or {}).get(
                                    field_name, [None, None]
                                )[1]
                            )
                            == placeholder
                        )
                    ]
                related_history.extend(entries)

        return sorted(
            own_history + related_history, key=lambda x: x.timestamp, reverse=True
        )

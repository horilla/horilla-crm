"""Dashboard utilities for leads module."""

# Standard library imports
from datetime import timedelta

# Third-party imports (Django)
from django.utils.http import urlencode

from horilla.contrib.dashboard.utils import DefaultDashboardGenerator, filtered_list_url
from horilla.contrib.utils.methods import get_section_info_for_model

# First party imports (Horilla)
from horilla.db.models import Count, Sum
from horilla.utils import timezone
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Lead


def create_lead_source_charts(self, queryset, model_info):
    """
    Lead-specific charts moved out of horilla.contrib.dashboard.
    """
    try:
        # ---- lead source chart ----
        if hasattr(queryset.model, "lead_source") or hasattr(queryset.model, "source"):
            field = (
                "lead_source" if hasattr(queryset.model, "lead_source") else "source"
            )

            data = queryset.values(field).annotate(count=Count("id")).order_by("-count")

            if data.exists():
                labels = [item[field] or _("Unknown") for item in data]
                values = [item["count"] for item in data]

                section = get_section_info_for_model(queryset.model)
                urls = []

                for item in data:
                    value = item[field] or "Unknown"
                    query = urlencode(
                        {
                            "section": section["section"],
                            "apply_filter": "true",
                            "field": field,
                            "operator": "exact",
                            "value": value,
                        }
                    )
                    urls.append(f"{section['url']}?{query}")

                return {
                    "title": _("Leads by Source"),
                    "type": "donut",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "urls": urls,
                        "labelField": _("Lead Source"),
                    },
                }

        # ---- conversion status chart ----
        if hasattr(queryset.model, "is_converted") or hasattr(
            queryset.model, "converted"
        ):
            field = (
                "is_converted"
                if hasattr(queryset.model, "is_converted")
                else "converted"
            )

            data = queryset.values(field).annotate(count=Count("id"))

            if data.exists():
                labels = [
                    _("Converted") if row[field] else _("Not Converted") for row in data
                ]
                values = [row["count"] for row in data]

                return {
                    "title": _("Lead Conversion Status"),
                    "type": "column",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "labelField": _("Status"),
                    },
                }

        # ---- status chart ----
        if hasattr(queryset.model, "status"):
            data = (
                queryset.values("status").annotate(count=Count("id")).order_by("-count")
            )

            if data.exists():
                labels = [row["status"] or _("No Status") for row in data]
                values = [row["count"] for row in data]

                return {
                    "title": _("Leads by Status"),
                    "type": "funnel",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "labelField": _("Status"),
                    },
                }

    except Exception as e:
        print("Lead chart error:", e)

    return None


def create_lead_charts_by_stage(self, queryset, model_info):
    """Chart: lead counts grouped by pipeline stage (second dashboard chart slot)."""
    try:
        if not hasattr(queryset.model, "lead_status"):
            return None

        data = (
            queryset.values("lead_status_id", "lead_status__name")
            .annotate(count=Count("id"))
            .order_by("lead_status__order", "lead_status_id")
        )

        if not data.exists():
            return None

        labels = [row["lead_status__name"] or _("No stage") for row in data]
        values = [row["count"] for row in data]

        section = get_section_info_for_model(queryset.model)
        urls = []
        for row in data:
            pk = row["lead_status_id"]
            query = urlencode(
                {
                    "section": section["section"],
                    "apply_filter": "true",
                    "field": "lead_status",
                    "operator": "exact",
                    "value": str(pk) if pk is not None else "",
                }
            )
            urls.append(f"{section['url']}?{query}")

        return {
            "title": _("Leads by Stage"),
            "type": "funnel",
            "data": {
                "labels": labels,
                "data": values,
                "urls": urls,
                "labelField": _("Lead Stage"),
            },
        }
    except Exception as e:
        print("Lead stage chart error:", e)

    return None


def lead_kpi_cards(generator, model_info):
    """
    KPI values come from any queryset logic: filters, aggregates, annotations, etc.
    Display style (integer vs decimals vs text) is inferred from each ``value``;
    set ``type`` only if you need to override formatting.
    """
    model_class = model_info["model"]
    qs = generator.get_queryset(model_class)
    section_info = get_section_info_for_model(model_class)
    open_qs = qs.filter(is_convert=False) if hasattr(model_class, "is_convert") else qs
    open_count = open_qs.count()

    return [
        {
            "title": _("New Leads (7 Days)"),
            "value": open_qs.filter(
                created_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
            "icon": "fa-user-plus",
            "color": "green",
            "url": filtered_list_url(
                model_class,
                [
                    (
                        "created_at",
                        "between",
                        (timezone.localdate() - timedelta(days=7)).isoformat(),
                        timezone.localdate().isoformat(),
                    ),
                ],
            ),
            "section": section_info["section"],
        },
    ]


def lead_table_fields(model_class):
    """Return list of {name, verbose_name} for lead table columns."""

    priority = ["first_name", "last_name", "email", "company", "lead_source"]
    fields = []
    for name in priority:
        try:
            f = model_class._meta.get_field(name)
            fields.append(
                {
                    "name": name,
                    "verbose_name": f.verbose_name or name.replace("_", " ").title(),
                }
            )
        except Exception:
            continue
    if len(fields) < 4:
        for f in model_class._meta.fields:
            if len(fields) >= 4:
                break
            if (
                f.name not in [x["name"] for x in fields]
                and f.get_internal_type() in TABLE_FALLBACK_FIELD_TYPES
            ):
                fields.append(
                    {
                        "name": f.name,
                        "verbose_name": f.verbose_name
                        or f.name.replace("_", " ").title(),
                    }
                )
    return fields


def lead_hot_table_func(generator, model_info):
    """Open leads with the biggest annual revenue - the ones worth calling first."""
    return generator.build_table_context(
        model_info=model_info,
        title=_("Hot Leads"),
        description=_("Highest-revenue open leads that are still in play"),
        filter_kwargs={"is_convert": False, "lead_status__probability__gt": 0},
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg=_("No open leads found."),
        view_id="leads_dashboard_open_list",
        order_by=["-annual_revenue"],
        table_fields=[
            {"name": "lead_company", "verbose_name": _("Company")},
            {"name": "annual_revenue", "verbose_name": _("Annual Revenue")},
            {"name": "lead_source", "verbose_name": _("Source")},
            {"name": "lead_status", "verbose_name": _("Status")},
            {"name": "lead_owner", "verbose_name": _("Owner")},
        ],
    )


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Lead,
        "name": _("Leads"),
        "order": 3,
        "kpi_func": lead_kpi_cards,
        "chart_descriptions": [
            _("Where your leads are coming from"),
            _("How leads are spread across the pipeline"),
        ],
        "chart_func": [create_lead_source_charts, create_lead_charts_by_stage],
        "chart_titles": [_("Leads by Source"), _("Leads by Stage")],
        "table_func": lead_hot_table_func,
        "table_fields_func": lead_table_fields,
    }
)

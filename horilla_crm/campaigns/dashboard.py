"""Dashboard utilities for campaigns module."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.utils.http import urlencode

from horilla.contrib.dashboard.utils import (
    DefaultDashboardGenerator,
    build_grouped_chart,
)
from horilla.contrib.utils.methods import get_section_info_for_model

# First party imports (Horilla)
from horilla.db.models import Count, Sum
from horilla.utils import timezone
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Campaign

logger = logging.getLogger(__name__)


def campaign_table_fields(model_class):
    """Return list of {name, verbose_name} for campaign table columns."""

    priority = ["campaign_name", "campaign_type", "status", "expected_revenue"]
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


def create_campaign_charts(self, queryset, model_info):
    """Create campaign-specific charts"""
    try:
        if hasattr(queryset.model, "campaign_type") or hasattr(queryset.model, "type"):
            type_field = (
                "campaign_type" if hasattr(queryset.model, "campaign_type") else "type"
            )
            type_data = (
                queryset.values(type_field)
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            if type_data.exists():
                labels = [item[type_field] or "Unknown" for item in type_data]
                data = [item["count"] for item in type_data]

                section_info = get_section_info_for_model(queryset.model)
                urls = []
                for item in type_data:
                    value = item[type_field] or "Unknown"
                    query = urlencode(
                        {
                            "section": section_info["section"],
                            "apply_filter": "true",
                            "field": type_field,
                            "operator": "exact",
                            "value": value,
                        }
                    )
                    urls.append(f"{section_info['url']}?{query}")

                return {
                    "title": _("Campaigns by Type"),
                    "type": "donut",
                    "data": {
                        "labels": labels,
                        "data": data,
                        "urls": urls,
                        "labelField": "Campaign Type",
                    },
                }

        if hasattr(queryset.model, "status"):
            status_data = (
                queryset.values("status").annotate(count=Count("id")).order_by("-count")
            )

            if status_data.exists():
                labels = [item["status"] or "No Status" for item in status_data]
                data = [item["count"] for item in status_data]

                return {
                    "title": _("Campaigns by Status"),
                    "type": "column",
                    "data": {
                        "labels": labels,
                        "data": data,
                        "labelField": "Status",
                    },
                }

        if hasattr(queryset.model, "is_active"):
            active_data = queryset.values("is_active").annotate(count=Count("id"))

            if active_data.exists():
                labels = []
                data = []
                for item in active_data:
                    status = "Active" if item["is_active"] else "Inactive"
                    labels.append(status)
                    data.append(item["count"])

                return {
                    "title": _("Campaign Activity Status"),
                    "type": "column",
                    "data": {
                        "labels": labels,
                        "data": data,
                        "labelField": "Activity",
                    },
                }

    except Exception as e:
        logger.warning("Error creating campaign chart: %s", e)

    return None


def create_campaign_actual_return_chart(self, queryset, model_info):
    """Revenue actually won per unit spent, for each campaign channel.

    Won revenue is the amount of won opportunities whose source campaign is
    one of the channel's campaigns; spend is the campaigns' actual cost.
    """
    # Lazy import: the opportunities app imports campaigns.
    from horilla_crm.opportunities.models import Opportunity

    won = {
        row["primary_campaign_source__campaign_type"]: float(row["won"] or 0)
        for row in Opportunity.objects.filter(
            primary_campaign_source__in=queryset, stage__stage_type="won"
        )
        .values("primary_campaign_source__campaign_type")
        .annotate(won=Sum("amount"))
    }
    spend = {
        row["campaign_type"]: float(row["spend"])
        for row in queryset.filter(actual_cost__gt=0)
        .values("campaign_type")
        .annotate(spend=Sum("actual_cost"))
    }
    results = sorted(
        ((name, round(won.get(name, 0) / cost, 2)) for name, cost in spend.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not results or not any(value for _name, value in results):
        return None
    section = get_section_info_for_model(queryset.model)
    type_labels = dict(queryset.model._meta.get_field("campaign_type").choices)
    return {
        "title": _("Actual Return by Campaign Type"),
        "type": "column",
        "data": {
            "labels": [str(type_labels.get(name, name)) for name, _value in results],
            "data": [value for _name, value in results],
            "urls": [
                f"{section['url']}?"
                + urlencode(
                    {
                        "section": section["section"],
                        "apply_filter": "true",
                        "field": "campaign_type",
                        "operator": "exact",
                        "value": name,
                    }
                )
                for name, _value in results
            ],
            "labelField": _("Return (won revenue ÷ spend)"),
        },
    }


def campaign_kpi_cards(generator, model_info):
    """Running campaigns plus spend and expected return."""
    model_class = model_info["model"]
    qs = generator.get_queryset(model_class)
    section_info = get_section_info_for_model(model_class)
    base = {"url": section_info["url"], "section": section_info["section"]}
    return [
        {
            "title": _("Running Campaigns"),
            "value": qs.filter(status="in_progress").count(),
            "icon": "fa-bullhorn",
            "color": "orange",
            **base,
        },
        {
            "title": _("Campaign Spend"),
            "value": qs.aggregate(total=Sum("actual_cost"))["total"] or 0,
            "icon": "fa-wallet",
            "color": "red",
            **base,
        },
        {
            "title": _("Expected Campaign Revenue"),
            "value": qs.exclude(status="aborted").aggregate(
                total=Sum("expected_revenue")
            )["total"]
            or 0,
            "icon": "fa-chart-line",
            "color": "green",
            **base,
        },
    ]


def campaign_table_func(generator, model_info):
    """Campaigns currently running, the ones ending soonest first."""
    return generator.build_table_context(
        model_info=model_info,
        title=_("Running Campaigns"),
        filter_kwargs={"status": "in_progress"},
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg=_("No campaigns are running."),
        view_id="campaigns_dashboard_list",
        order_by=["end_date"],
        table_fields=[
            {"name": "campaign_name", "verbose_name": _("Campaign")},
            {"name": "campaign_type", "verbose_name": _("Type")},
            {"name": "end_date", "verbose_name": _("Ends On")},
            {"name": "budget_cost", "verbose_name": _("Budget")},
            {"name": "actual_cost", "verbose_name": _("Spent")},
        ],
    )


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Campaign,
        "name": _("Campaigns"),
        "icon": "fa-bullhorn",
        "color": "orange",
        "order": 4,
        "chart_titles": [_("Actual Return by Campaign Type")],
        "chart_descriptions": [
            _("Revenue actually won divided by money spent, for each channel"),
        ],
        "chart_func": create_campaign_actual_return_chart,
        "table_fields_func": campaign_table_fields,
    }
)

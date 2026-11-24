"""Dashboard utilities for opportunities module."""

# Standard library imports
import logging
from datetime import timedelta

# First party imports (Horilla)
from django.db.models.functions import TruncMonth

# Third-party imports (Django)
from django.utils.http import urlencode

from horilla.contrib.dashboard.utils import (
    DefaultDashboardGenerator,
    build_grouped_chart,
    filtered_list_url,
    format_compact_number,
)
from horilla.contrib.utils.methods import get_section_info_for_model
from horilla.db.models import Count, Min, Sum
from horilla.utils import timezone
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import Opportunity

logger = logging.getLogger(__name__)


def create_opportunity_charts(self, queryset, model_info):
    """Create opportunity-specific charts"""
    try:
        if hasattr(queryset.model, "lead_source") or hasattr(queryset.model, "source"):
            source_field = (
                "lead_source" if hasattr(queryset.model, "lead_source") else "source"
            )
            source_data = (
                queryset.values(source_field)
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            if source_data.exists():
                labels = [item[source_field] or _("Unknown") for item in source_data]
                data = [item["count"] for item in source_data]

                section_info = get_section_info_for_model(queryset.model)
                urls = []
                for item in source_data:
                    value = item[source_field] or "Unknown"
                    query = urlencode(
                        {
                            "section": section_info["section"],
                            "apply_filter": "true",
                            "field": source_field,
                            "operator": "exact",
                            "value": value,
                        }
                    )
                    urls.append(f"{section_info['url']}?{query}")

                return {
                    "title": _("Opportunities by Lead Source"),
                    "type": "column",
                    "data": {
                        "labels": labels,
                        "urls": urls,
                        "data": data,
                        "labelField": _("Lead Source"),
                    },
                }

        stage_field = None
        if hasattr(queryset.model, "stage"):
            stage_field = "stage"
        elif hasattr(queryset.model, "status"):
            stage_field = "status"
        elif hasattr(queryset.model, "opportunity_stage"):
            stage_field = "opportunity_stage"

        if stage_field:
            stage_data = (
                queryset.values(stage_field)
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            if stage_data.exists():
                labels = [item[stage_field] or _("Unknown") for item in stage_data]
                data = [item["count"] for item in stage_data]

                return {
                    "title": _("Opportunities by Stage"),
                    "type": "funnel",
                    "data": {"labels": labels, "data": data, "labelField": _("Stage")},
                }

        if hasattr(queryset.model, "is_won"):
            won_data = queryset.values("is_won").annotate(count=Count("id"))

            if won_data.exists():
                labels = []
                data = []
                for item in won_data:
                    status = _("Won") if item["is_won"] else _("In Progress/Lost")
                    labels.append(status)
                    data.append(item["count"])

                return {
                    "title": _("Opportunity Win Rate"),
                    "type": "pie",
                    "data": {
                        "labels": labels,
                        "data": data,
                        "labelField": _("Status"),
                    },
                }

        if hasattr(queryset.model, "amount") or hasattr(queryset.model, "value"):
            amount_field = "amount" if hasattr(queryset.model, "amount") else "value"

            opportunities = list(
                queryset.values("id", amount_field).exclude(
                    **{f"{amount_field}__isnull": True}
                )
            )
            if opportunities:
                ranges = [_("<10K"), _("10K-50K"), _("50K-100K"), _("100K+")]
                range_counts = [0, 0, 0, 0]

                for opp in opportunities:
                    amount = float(opp[amount_field] or 0)
                    if amount < 10000:
                        range_counts[0] += 1
                    elif amount < 50000:
                        range_counts[1] += 1
                    elif amount < 100000:
                        range_counts[2] += 1
                    else:
                        range_counts[3] += 1

                return {
                    "title": _("Opportunities by Value Range"),
                    "type": "column",
                    "data": {
                        "labels": ranges,
                        "data": range_counts,
                        "labelField": _("Value Range"),
                    },
                }

    except Exception as e:
        logger.warning("Error creating opportunity chart: %s", e)

    return None


def opportuntiy_table_fields(model_class):
    """Return list of {name, verbose_name} for opportuntiy table columns."""

    priority = ["name", "title", "account", "amount", "stage"]
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


def _open_stage_filter():
    return {"stage__stage_type": "open"}


def create_pipeline_by_stage_chart(self, queryset, model_info):
    """Deal value at every stage, in stage order, ending with closed won and lost."""
    rows = [
        row
        for row in queryset.values("stage", "stage__name")
        .annotate(total=Sum("amount"), stage_order=Min("stage__order"))
        .order_by("stage_order", "stage")
        if row["total"]
    ]
    if not rows:
        return None
    section = get_section_info_for_model(queryset.model)
    return {
        "title": _("Deals by Stage"),
        "type": "funnel",
        "data": {
            "labels": [row["stage__name"] or _("No stage") for row in rows],
            "data": [float(row["total"]) for row in rows],
            "urls": [
                f"{section['url']}?"
                + urlencode(
                    {
                        "section": section["section"],
                        "apply_filter": "true",
                        "field": "stage",
                        "operator": "exact",
                        "value": row["stage"] or "",
                    }
                )
                for row in rows
            ],
            "labelField": _("Stage"),
        },
    }


def create_won_revenue_trend_chart(self, queryset, model_info):
    """Won revenue per month over the last 6 months."""
    today = timezone.localdate()
    month_start = today.replace(day=1)
    start = month_start
    for _i in range(5):
        start = (start - timedelta(days=1)).replace(day=1)
    rows = {
        row["month"].date() if hasattr(row["month"], "date") else row["month"]: row[
            "total"
        ]
        for row in queryset.filter(stage__stage_type="won", close_date__gte=start)
        .annotate(month=TruncMonth("close_date"))
        .values("month")
        .annotate(total=Sum("amount"))
    }
    months = []
    cursor = start
    for _i in range(6):
        months.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    if not any(rows.get(m) for m in months):
        return None
    section = get_section_info_for_model(queryset.model)
    return {
        "title": _("Won Revenue by Month"),
        "type": "line",
        "data": {
            "labels": [m.strftime("%b %Y") for m in months],
            "data": [float(rows.get(m) or 0) for m in months],
            "urls": [section["url"]] * len(months),
            "labelField": _("Won Revenue"),
        },
    }


def _stage_ids(model_class, stage_type):
    """Comma-separated ids of the stages of one type, for a Stage filter.

    The list's filter form only knows the model's own fields, so a related path
    like ``stage__stage_type`` would not show up in the form; ``stage`` does.
    """
    stage_model = model_class._meta.get_field("stage").related_model
    ids = stage_model.objects.filter(stage_type=stage_type).values_list("pk", flat=True)
    return ",".join(str(pk) for pk in ids)


def opportunity_kpi_cards(generator, model_info):
    """Open pipeline, won revenue and deals about to close."""
    model_class = model_info["model"]
    qs = generator.get_queryset(model_class)
    section_info = get_section_info_for_model(model_class)
    open_qs = qs.filter(**_open_stage_filter())
    base = {"url": section_info["url"], "section": section_info["section"]}
    return [
        {
            "title": _("Open Pipeline"),
            "value": format_compact_number(
                open_qs.aggregate(total=Sum("amount"))["total"]
            ),
            "type": "text",
            "icon": "fa-filter-circle-dollar",
            "color": "purple",
            **base,
            "url": filtered_list_url(
                model_class, [("stage", "exact", _stage_ids(model_class, "open"))]
            ),
        },
        {
            "title": _("Won Revenue"),
            "value": format_compact_number(
                qs.filter(stage__stage_type="won").aggregate(total=Sum("amount"))[
                    "total"
                ]
            ),
            "type": "text",
            "icon": "fa-trophy",
            "color": "green",
            **base,
            "url": filtered_list_url(
                model_class, [("stage", "exact", _stage_ids(model_class, "won"))]
            ),
        },
    ]


def opportunity_table_func(generator, model_info):
    """Open deals expected to close within the next 30 days, soonest first."""
    today = timezone.localdate()
    return generator.build_table_context(
        model_info=model_info,
        title=_("Deals Closing in the Next 30 Days"),
        description=_("Open deals expected to close soon, earliest first"),
        filter_kwargs={
            **_open_stage_filter(),
            "close_date__gte": today,
            "close_date__lte": today + timedelta(days=30),
        },
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg=_("No deals closing in the next 30 days."),
        view_id="opportunities_dashboard_list",
        order_by=["close_date", "-amount"],
        table_fields=[
            {"name": "name", "verbose_name": _("Opportunity")},
            {"name": "account", "verbose_name": _("Account")},
            {"name": "amount", "verbose_name": _("Amount")},
            {"name": "stage", "verbose_name": _("Stage")},
            {"name": "close_date", "verbose_name": _("Close Date")},
        ],
    )


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Opportunity,
        "name": _("Opportunities"),
        "icon": "fa-handshake",
        "color": "purple",
        "order": 1,
        "chart_titles": [_("Deals by Stage"), _("Won Revenue by Month")],
        "kpi_func": opportunity_kpi_cards,
        "chart_descriptions": [
            _("Value of deals at each stage, including closed won and lost"),
            _("Closed-won revenue over the last 6 months"),
        ],
        "chart_func": [create_pipeline_by_stage_chart, create_won_revenue_trend_chart],
        "table_func": opportunity_table_func,
        "table_fields_func": opportuntiy_table_fields,
    }
)

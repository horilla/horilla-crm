# Shared empty-state partials (`templates/components/`)

Reusable markup for **prerequisite gates** and **no-data** screens (image + message + optional CTA). Introduced in v1.13.8 to replace duplicated `not-found.svg` / `activate-company.svg` blocks across settings and module templates.

`static`, `i18n`, and `horilla_tags` are **built in** — do not add `{% load static %}` or `{% load i18n %}`. See [settings `base.py` — Template builtins](../../horilla/settings/base.md#-template-builtins) and [coding_rule.md](../../coding_rule.md#django-templates--built-in-tag-libraries).

---

## Files

| Template | Role |
|----------|------|
| `components/empty_state.html` | Base partial — parameterized image, message, spacer, optional link button |
| `components/empty_states/activate_company.html` | Preset: “Please create or activate your company.” |

---

## `empty_state.html` parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `image` | `assets/img/not-found.svg` | Static path passed to `{% static %}` |
| `alt` | `""` | Image `alt` text |
| `message` | — | Body paragraph (omit to hide) |
| `spacer` | falsy | When true, renders top `h-20` spacer (settings pages) |
| `action_url` | — | Optional primary CTA link `href` |
| `action_label` | — | CTA link label (required when `action_url` set) |
| `feature_disabled` | falsy | When true, uses `assets/img/feature-disabled.svg` with a “Feature not enabled” alt (ignores `image` / `alt`) |
| `wrapper_class` | — | Extra CSS classes on root `.empty-state` div |

Optional action buttons that need permissions, HTMX, or `onclick` should stay **outside** the include (see forecast target “Go To Forecast Type” button).

---

## Preset: activate company

```django
{% if not has_company %}
    {% include "components/empty_states/activate_company.html" %}
{% else %}
    ...
{% endif %}
```

**Used in:**

- `horilla/contrib/core/templates/settings/company_information.html`
- `horilla/contrib/core/templates/settings/multiple_currency.html`
- `horilla_crm/forecast/templates/forecast_target/forecast_target_view.html` (`has_company` branch)
- `horilla_crm/forecast/templates/forecast_view.html` (no `request.active_company` branch)

Context: views set `has_company` from `request.active_company`, or templates test `request.active_company` directly.

---

## Custom message (generic partial)

```django
{% trans "No potential duplicates found." as empty_state_message %}
{% include "components/empty_state.html" with message=empty_state_message %}
```

**Examples in codebase (v1.13.8):**

| Area | Template |
|------|----------|
| Booking — business hours gate | `booking/templates/settings/booking_pages.html` (custom message + CTA to working hours) |
| Forecast target — no forecast type | `forecast_target/forecast_target_view.html` |
| Core — roles | `core/templates/role/role.html` |
| Duplicates | `matching_rule_accordion.html`, `potential_duplicates_list_view.html` |
| Theme | `theme/theme_cards.html` |
| CRM | `big_deal_alert_accordion.html`, `opportunity_split_view.html`, `scoring_rule_detail_view.html` |
| Generics | `history_tab.html` |

---

## List / kanban empty states (not migrated yet)

Generic layout views (`list_view.html`, `card_view.html`, `kanban_view.html`, …) still resolve messages inline using:

- `no_record_msg`
- `has_active_filters`
- `{% empty_add_message model_verbose_name %}` ([misc_tags.md](../../horilla/contrib/generics/templatetags/horilla_tags/misc_tags.md))

When touching those templates, prefer resolving `empty_state_message` with the same if/elif chain, then:

```django
{% include "components/empty_state.html" with message=empty_state_message image=no_found_img|default:"assets/img/not-found.svg" %}
```

---

## Related documentation

- [Settings list shell](../../horilla/contrib/core/settings_list_shell.md)
- [Forecast targets](../../horilla_crm/forecast/forecast_target.md)
- [Booking app](../../horilla/contrib/booking/booking.md)

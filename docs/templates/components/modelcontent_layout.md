# Modelcontent Layout Migration Guide

This guide documents the **current** shared layout contract and migration pattern for:

- `templates/components/modelcontent_layout.html`

## Goal

Avoid repeating shell markup in every page template:

- `<div class="flex modelcontent">`
- sidebar include
- `#mainContent` wrapper

Keep shell structure in one place and move page-specific content into blocks.

## Current Shared Layout Contract

Template:

- `templates/components/modelcontent_layout.html`

It provides:

- shared `modelcontent` wrapper
- shared sidebar include
- shared `#mainContent` container
- default messages include (overridable)

### All available blocks (current)

- `before_modelcontent`
- `before_sub_sidebar`
- `sub_sidebar` (override default sidebar include)
- `after_sub_sidebar`
- `main_content` (override entire `#mainContent` wrapper)
- `main_leftspace_class`
- `main_content_classes`
- `main_content_attrs`
- `messages`
- `navbar`
- `main`
- `after_modelcontent`

### `#mainContent` class composition

`#mainContent` class in the shared layout is:

```django
class="flex-[1_0] transition-all duration-300 ease-in-out pt-0 {% block main_leftspace_class %}leftspace{% endblock %} {% block main_content_classes %}{% endblock %}"
```

Use:

- `main_leftspace_class` to enable/disable/conditionalize `leftspace`
- `main_content_classes` for page-specific extras (`overflow-*`, height, custom-scroll, etc.)

## Standard Migration Steps

## 1) Update parent template

From:

```django
{% extends "index.html" %}
```

To:

```django
{% extends "components/modelcontent_layout.html" %}
```

## 2) Remove duplicated shell markup

Remove from child template:

- `flex modelcontent` wrapper
- direct sidebar include
- direct `#mainContent` wrapper

## 3) Map old sections to blocks

Common mapping:

- header/nav loader -> `navbar`
- page body -> `main`
- helper markup between sidebar and main -> `after_sub_sidebar`
- per-page `#mainContent` classes -> `main_leftspace_class` / `main_content_classes`

## 4) Handle messages explicitly

By default, layout renders:

```django
{% include "messages.html" %}
```

If old template did **not** render messages in this position:

```django
{% block messages %}{% endblock %}
```

If old template rendered messages in a custom location, disable default and include manually inside `main`.

## 5) Preserve HTMX contracts

Keep these unchanged unless intentional:

- `hx-target="#mainContent"`
- `hx-select="#mainContent"`
- `hx-swap="outerHTML"`
- `hx-push-url="true"`

## 6) Validate

- compile template through Django loader
- check lints for edited templates

## Migrated Templates (current)

### Calendar

- `horilla/contrib/calendar/templates/calendar.html`

### Dashboard

- `horilla/contrib/dashboard/templates/dashboard_list_view.html`
- `horilla/contrib/dashboard/templates/dashboard_detail_view.html`
- `horilla/contrib/dashboard/templates/favourite_dashboard.html`
- `horilla/contrib/dashboard/templates/dashboard_folder_detail.html`
- `horilla/contrib/dashboard/templates/favourite_folder.html`
- `horilla/contrib/dashboard/templates/home/default_home.html`

### Generics

- `horilla/contrib/generics/templates/base.html`
- `horilla/contrib/generics/templates/detail_view.html`
- `horilla/contrib/generics/templates/global_search.html`

### Reports

- `horilla/contrib/reports/templates/report_list_view.html`
- `horilla/contrib/reports/templates/report_detail.html`
- `horilla/contrib/reports/templates/report_folder_detail.html`
- `horilla/contrib/reports/templates/favourite_report_list_view.html`
- `horilla/contrib/reports/templates/favourite_folder_list.html`

### Process approvals

- `horilla/contrib/process/approvals/templates/approval_detail_page.html`

## Special Cases

- Pages with conditional sidebar/leftspace behavior should use:
  - `before_sub_sidebar`
  - `main_leftspace_class`
- Pages needing a custom `#sideMenuContainer` for OOB swaps should define that in `before_sub_sidebar` / `after_sub_sidebar`.
- Pages that previously had custom `#mainContent` classes should move them to `main_content_classes`.

## Quick Checklist

- [ ] extends changed to `components/modelcontent_layout.html`
- [ ] duplicated shell wrappers removed
- [ ] all sections mapped to blocks
- [ ] `messages` behavior preserved
- [ ] `#mainContent` HTMX behavior preserved
- [ ] template compile check passed

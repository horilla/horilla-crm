# Component template tags (`horilla_generics/templatetags/horilla_tags/components.py`)

## Purpose

`components.py` is the shared markup for buttons, badges, breadcrumbs, and HTMX anchors. Tags render templates under `horilla/contrib/generics/templates/components/`.

`horilla_tags` is a built-in library. Do not add `{% load horilla_tags %}`.

The rollout notes, including pills and buttons that are still pasted by hand, are in [Plan_INCLUSION_TAGS.md](../../../../../../plans&review/Plan_INCLUSION_TAGS.md).

---

## `HX_TAGS` and `html_attr_name`

A template keyword cannot contain a colon or a hyphen. `HX_TAGS` maps the keyword to the HTML attribute. `html_attr_name` reads that map. `{% reload_button %}`, `{% hx_anchor %}`, and `{% btn %}` all use it.

| Keyword | HTML attribute |
|---------|----------------|
| `hx_get`, `hx_post`, `hx_put`, `hx_patch`, `hx_delete` | the matching `hx-*` verb |
| `hx_target`, `hx_swap`, `hx_trigger`, `hx_select`, `hx_push_url`, `hx_indicator`, `hx_vals`, `hx_include`, `hx_sync` | the matching `hx-*` attribute |
| `hx_on_click` and `hx_on__click` | `hx-on:click` |
| `hx_on__after_request` | `hx-on::after-request` |

`__` stands in for a colon. An htmx lifecycle event keeps the second colon (`hx-on::after-request` runs on `htmx:afterRequest`). A name that is not in the map still turns underscores into hyphens, so `data_toggle` is `data-toggle`.

Add a DOM event to `HX_TAGS` before using it. `hx_on__keyup` is not listed, and the hyphen fallback would write `hx-on--keyup`, which htmx reads as `htmx:keyup`.

`True` is a bare attribute. `None`, `False`, and `""` leave the attribute off.

---

## `{% reload_button %}`

Renders `components/_reload_button.html`. The container selector is both `hx-target` and `hx-select`. The URL defaults to the current path plus the query string.

```django
{% reload_button "#mainContent" %}
{% reload_button "#report-content" url=report_detail_url %}
```

## `{% modal_header %}`

Renders `components/_modal_header.html`: title, optional count pill, close icon.

```django
{% modal_header _("Account Hierarchy") %}
{% modal_header _("Insert Fields") on_close="closeContentModal()" %}
```

## `{% spinner %}`

Renders `components/_spinner.html`. Sizes are `xs`, `sm`, `md`, and `lg` (the default). `centered=True` wraps the ring.

```django
{% spinner %}
{% spinner "sm" centered=True %}
```

## `{% status_badge %}`

Renders `components/_status_badge.html`. `variant` is `success`, `danger`, `warning`, `info`, or `neutral`. `icon` is `check`, `cross`, `dot`, or left off. An unknown variant or icon raises `ValueError`.

```django
{% status_badge _("Enabled") variant="success" icon="check" %}
{% status_badge _("Disabled") icon="cross" %}
```

Used on the calls, meeting, and Google Calendar integration settings, opportunity splits, team selling, and the Zoom pill in meeting user settings.

## `{% breadcrumb_nav %}`

Renders `components/_breadcrumbs.html`. The name is `breadcrumb_nav` so it does not hide the `breadcrumbs` variable the views already put in the context.

Each crumb has `name`, an optional `url`, and an optional `active`. The active crumb is the current page and is not a link. A crumb with a url replaces `#mainContent`. Anything else is plain text. A missing or empty list still renders the nav.

```django
{% breadcrumb_nav breadcrumbs %}
```

Call sites: `dashboard_folder_detail.html`, `favourite_folder.html`, `report_folder_detail.html`, and `favourite_folder_list.html`.

## `{% hx_anchor %}`

Renders `components/_hx_anchor.html`. The label is escaped. `href` defaults to `""`.

`variant="submenu"` is the sidebar link and the only variant that receives the default HTMX attributes: `hx-trigger="click"`, `hx-target="#mainContent"`, `hx-select="#mainContent"`, `hx-swap="outerHTML"`, `hx-push-url="true"`. `active=True` marks the current page (`text-primary-600`, `before:opacity-100`).

`variant="base"` is the dropdown item (`hover:text-primary-600 transition duration-300 text-sm px-3 py-1.5`). It does not receive those defaults. With no variant, pass `class`.

```django
{% hx_anchor _("All Folders") variant="submenu" active=True hx_get=url %}
{% hx_anchor _("Change Chart") variant="base" hx_get=url hx_target="#modalBox" hx_swap="innerHTML" hx_on_click="openModal();" %}
```

Do not put `{{ }}` or `{% url %}` inside the tag. Assign the URL, then append with [`concat`](url_filters.md) when the page loads `reports_tags`.

`partials/dashboard_sidebar.html` holds the four dashboard sidebar links. These pages include it:

| Page | `active` |
|------|----------|
| `dashboard_list_view.html` | `all_dashboards` |
| `dashboard_folder_detail.html` | `all_folders` |
| `favourite_folder.html` | `folders` |
| `favourite_dashboard.html` | `dashboards` |

`active|eq:"all_dashboards"` comes from [`eq`](misc_tags.md) and is what sets `active=True` on that one link.

`partials/report_sidebar.html` is the same menu for reports. These pages include it. They do not load `reports_tags`, so each link uses Django's `add` for `url|add:"?"|add:request.GET.urlencode`.

| Page | `active` |
|------|----------|
| `report_list_view.html` | `all_reports` |
| `report_folder_detail.html` | `all_folders` |
| `favourite_folder_list.html` | `folders` |
| `favourite_report_list_view.html` | `reports` |

`report_detail.html` does load `reports_tags`, so its chart menu uses `concat`. All four items are `variant="base"`:

| Item | How the tag is built |
|------|----------------------|
| Change Chart | `hx_get=change_chart_url\|concat:"?total="\|concat:total_groups_count`, then `hx_target="#modalBox"` and `hx_swap="innerHTML"` |
| Export as PDF | `{% with chart_id=report.pk\|stringformat:"s" %}`, then `hx_on_click` joins `chart-` and `report_` with that id |
| Export as PNG | Same `chart_id`, joined into `EChartsConfig.exportChart(...)` |
| Add to Dashboard | Rendered only when `total_groups_count > 0`. `hx_get` is `report_to_dashboard_url\|concat:"?report_id="\|concat:report.pk` and opens `#modalBox` |

## `{% btn %}`

Not an inclusion tag. `body` reads until `{% endbtn %}`. Colour tokens are `primary` and `outline`. Other keywords go through `HX_TAGS`.

```django
{% btn type="submit" %}
{% btn _("Add") type="button" hx_get=url hx_target="#modalBox" hx_swap="innerHTML" hx_on_click="openModal()" %}
{% btn _("Merge") type="submit" hx_post=url hx_on__after_request="closeModal();" %}
```

---

## Summary

| Tag | Role |
|-----|------|
| `HX_TAGS` / `html_attr_name` | Keyword to HTML attribute, including `hx-on:click` |
| `reload_button` | Hidden button that refreshes one container |
| `modal_header` | Title bar and close icon |
| `spinner` | Theme-coloured loading ring |
| `status_badge` | Enabled / disabled pill |
| `breadcrumb_nav` | Folder trail |
| `hx_anchor` | Sidebar link (`submenu`) or dropdown item (`base`) |
| `btn` | Primary or outline button, with optional `{% endbtn %}` |

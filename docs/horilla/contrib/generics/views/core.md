# Horilla Generic Core Views (`horilla_generics/views/core.py`)

## 🎯 Purpose

`core.py` provides foundational reusable views used throughout Horilla generics:

- page shell view (`HorillaView`)
- HTMX tab container view (`HorillaTabView`)
- object history section with filtering + pagination (`HorillaHistorySectionView`)
- dynamic related-object creation modal (`HorillaDynamicCreateView`)

These are base building blocks that higher-level app views subclass.

---

## 📦 Classes in this file

1. `HorillaView(TemplateView)`
2. `HorillaTabView(TemplateView)` *(HTMX required)*
3. `HorillaHistorySectionView(DetailView)` *(HTMX required)*
4. `HorillaDynamicCreateView(FormView)` *(HTMX required + login required)*

---

## 🔁 `HorillaView`

### Purpose

Simple base page view that passes common navigation/layout URLs to templates.

### Important class attributes

| Attribute | Default |
|---|---|
| `template_name` | `"base.html"` |
| `nav_url` | `""` |
| `list_url` | `""` |
| `kanban_url` | `""` |
| `group_by_url` | `""` |
| `card_url` | `""` |
| `timeline_url` | `""` |
| `split_view_url` | `""` |
| `chart_url` | `""` |
| `view_id` | `""` | Optional root element id for settings shells |
| `custom_layouts` | `{}` | Extra layout types beyond the built-ins above (see below) |
| `default_layout` | *(unset)* | Key of the layout to load when no `?layout=` param is present |

### `custom_layouts`: adding a new layout type

The built-in slots (`list`, `kanban`, `group_by`, `card`, `timeline`, `split_view`, `chart`) are a fixed set. To register an additional layout type without touching this base class, set `custom_layouts` on the subclass:

```python
custom_layouts = {
    "hierarchy": {
        "url": reverse_lazy("core:roles_hierarchy_view"),
        "icon": "assets/icons/hierarchy.svg",
        "label": _("Hierarchy"),
    },
}
```

Each key becomes a valid `?layout=<key>` value and a valid `default_layout` value. The paired `HorillaNavView` subclass should declare the *same* `custom_layouts` dict (same keys/urls) so the toggle icon and dropdown label agree with the content that loads — see `RolesView`/`RoleNavbar` in `horilla/contrib/core/views/roles.py` for the real example this pattern is based on.

### `get_layout_url()`

Returns the HTMX URL loaded into the main content area, resolved in this order:
1. `?layout=<key>` if `<key>` is a valid built-in or `custom_layouts` key with a non-empty URL.
2. `default_layout`, if set and it maps to a non-empty URL — this is what makes the *default* view (no `?layout=` in the URL) match what the navbar's toggle icon shows. Leads, Opportunities, and Campaigns set `default_layout = "kanban"` on both the page view and the navbar, so those pages open on Kanban.
3. Legacy fallback: `kanban_url` if `list_url` is empty, otherwise `list_url`.

### Settings list pages

For **admin Settings** modules:

```python
template_name = "settings/settings_list_shell.html"
view_id = "my-settings-view"
nav_url = reverse_lazy("app:nav_view")
list_url = reverse_lazy("app:list_view")
```

For **My Settings** list pages (sidebar profile area):

```python
template_name = "settings/my_settings_list_shell.html"
```

See [settings list shell](../../core/settings_list_shell.md).

### `get_context_data()` output

Adds:
- `filter_form` only when `HX-Trigger == "filter-form"`
- `nav_url`, `layout_url`, `view_id`, `custom_layouts`, and all layout URL attributes

### Example subclass

```python
from horilla.auth.mixins import LoginRequiredMixin
from horilla.urls import reverse_lazy
from horilla_generics.views.core import HorillaView


class LeadView(LoginRequiredMixin, HorillaView):
    template_name = "base.html"
    nav_url = reverse_lazy("leads:leads_nav")
    list_url = reverse_lazy("leads:leads_list")
    kanban_url = reverse_lazy("leads:leads_kanban")
    group_by_url = reverse_lazy("leads:leads_group_by")
    card_url = reverse_lazy("leads:leads_card")
    timeline_url = reverse_lazy("leads:leads_timeline")
    split_view_url = reverse_lazy("leads:leads_split_view")
    chart_url = reverse_lazy("leads:leads_chart")
```

Example subclass registering a page-specific layout type instead of one of the built-ins:

```python
class RolesView(LoginRequiredMixin, HorillaView):
    template_name = "settings/settings_list_shell.html"
    view_id = "role-view"
    default_layout = "hierarchy"
    nav_url = reverse_lazy("core:roles_nav_bar")
    list_url = reverse_lazy("core:role_list_view")
    custom_layouts = {
        "hierarchy": {
            "url": reverse_lazy("core:roles_hierarchy_view"),
            "icon": "assets/icons/hierarchy.svg",
            "label": _("Hierarchy"),
        },
    }
```

---

## 🧩 `HorillaTabView`

### Decorator

- `@htmx_required` on `dispatch`

### Purpose

Reusable HTMX tab renderer (`tab_view.html`) with persistent active tab support via `ActiveTab`.

### Important attributes

| Attribute | Default |
|---|---|
| `view_id` | `""` |
| `template_name` | `"tab_view.html"` |
| `tabs` | `[]` |
| `background_class` | `""` |
| `background_color` | `""` |
| `tab_class` | `""` |

### Behavior

- In `__init__`, it gets request from thread local (`_thread_local.request`) and sets `self.request`.
- `get_context_data()`:
  - loads saved active tab from `ActiveTab(created_by=user, path=request.path)`
  - sets `active_target` if found
  - passes tab style config + tabs list + view id

### Example `tabs` structure

```python
tabs = [
    {
        "title": "Overview",
        "url": "/leads/42/overview/",
        "target": "tab-overview-content",
        "id": "overview",
    },
    {
        "title": "Notes & Attachments",
        "url": "/leads/42/notes/",
        "target": "tab-notes-attachments-content",
        "id": "notes-attachments",
    },
]
```

---

## 🕘 `HorillaHistorySectionView`

### Decorator

- `@htmx_required` on `dispatch`

### Purpose

Render model history/audit timeline in `history_tab.html` with:
- grouping by date
- date-range filter (`HorillaHistoryForm`: `date_range` = `all`/`custom`/`7`/`30`/`60`/`90`, plus `date_from`/`date_to` for custom)
- pagination (`paginate_by = 10`)

### Core behavior

#### `dispatch()`

- resolves `self.object = self.get_object()`
- on failure:
  - adds error message
  - returns `RefreshResponse(request)` (**`horilla.web`** — HTMX refresh behavior)

#### `get_context_data()`

Adds:
- `model_name`
- `page_obj` (paginated grouped history)
- `actions` (action names from history entries)
- `filter_form`
- `filter_applied` (`filter_form.is_filtering()`)
- `date_range`, `date_from`, `date_to` (only when filtering) and `date_range_choices`

It builds `history_by_date` as:
- list of `(date, [entries])` sorted descending by date.

#### `get()`

- always renders the history tab; there is no filter modal or `show_filter` branch any more
- the date-range dropdown (`components/date_range_filter.html`) offers named presets (Today, Yesterday, This Week, This Month) and a custom range, and re-requests the tab with `date_range` params; `apply_filter(history_by_date, today)` keeps the days in range
- related records only contribute entries that link/unlink them to this object (FK set/cleared, generic link created/deleted)

### Example subclass

```python
from horilla.auth.mixins import LoginRequiredMixin
from horilla_generics.views.core import HorillaHistorySectionView
from horilla_crm.leads.models import Lead


class LeadHistoryView(LoginRequiredMixin, HorillaHistorySectionView):
    model = Lead
```

Date-range filter call example:

```text
/leads/history/42/?date_range=30
/leads/history/42/?date_range=custom&date_from=2026-10-01&date_to=2026-10-15
```

---

## ➕ `HorillaDynamicCreateView`

### Decorator / mixins

- `@htmx_required` on `dispatch`
- `LoginRequiredMixin`

### Purpose

Generic dynamic modal for creating related model records from another form (for example creating a new FK option without leaving the current page).

Template:
- `dynamic_form_view.html`

---

### Request contract

#### URL kwargs (required)

- `app_label`
- `model_name`

#### GET params (optional but commonly used)

| Param | Meaning | Example |
|---|---|---|
| `fields` | comma-separated fields to include | `name,code,is_active` |
| `permission` | comma-separated custom perms (overrides default add perm) | `leads.add_leadstatus` |
| `target_field` | target `<select name="...">` to receive new option | `lead_status` |
| `full_width_fields` | comma-separated fields that render full width | `description,notes` |
| `initial_<field>` | initial value injection | `initial_name=Hot Lead` |

---

### Main methods

#### `get_model_and_fields()`

- resolves target model via `apps.get_model(app_label, model_name)`
- parses `fields` param to list
- returns `(model, field_names)` or `(None, None)` with message on lookup failure

#### `dispatch()`

Validation sequence:
1. resolve model + fields
2. validate requested field names exist on model
3. compute required permissions:
   - custom from `permission` param OR default `"{app}.add_{model}"`
4. deny:
   - invalid model/fields -> script response closing dynamic modal + reload messages
   - missing permission -> render `403.html` with modal style

#### `get_form_class()`

Builds dynamic `HorillaModelForm` subclass:
- `model = target_model`
- `fields = selected fields or "__all__"`
- excludes system fields:
  - `created_at`, `updated_at`, `created_by`, `updated_by`, `additional_info`
- applies date input widgets for `DateField`
- fields named in the `rich_text_fields` GET param (comma-separated) use `HorillaSummernoteWidget` (preset from the model's `dynamic_create_rich_text_presets`, default `"full"`)

#### `get_context_data()`

Adds:
- `form_title` (`Create <Verbose Name>`, title-cased)
- `target_field`
- `form_url` (same path + query string)
- `full_width_fields`
- `field_permissions` from `get_field_permissions_for_model(user, model)`
- `field_tools`: from the target model's `dynamic_create_field_tools` (`get_field_tools()`), per-field toolbar entries rendered by `components/field_tools/toolbar.html` (e.g. `"insert_field"`)

#### `get_form_kwargs()`

Passes to form:
- `full_width_fields`
- `field_permissions`
- `initial` values from `initial_...` query params

#### `form_valid()`

Creates instance and sets:
- `created_by`, `updated_by` = request user
- `company` = form `company` or `request.active_company` or `request.user.company`

Then returns JS that:
- finds `select[name="<target_field>"]`
- appends new `<option>` (`pk`, escaped string label)
- triggers Select2 change if applicable
- closes dynamic modal

#### `form_invalid()`

- sets error message
- re-renders form with validation errors.

---

## 🧪 End-to-end example

### Use-case

From a Lead form, allow creating a new `LeadStatus` in a dynamic modal and auto-selecting it.

### Example request URL

```text
/generics/dynamic-create/leads/leadstatus/?fields=name,color&target_field=lead_status&full_width_fields=name&initial_name=New%20Status
```

### What happens

1. `HorillaDynamicCreateView` resolves model `leads.LeadStatus`.
2. Builds form with `name,color`.
3. On submit success, JS injects option into:
   - `select[name="lead_status"]`
4. Modal closes; parent form keeps user in place.

---

## 📌 Summary

- `HorillaView`: base context wiring for nav/layout endpoints.
- `HorillaTabView`: HTMX tabs + persisted active tab target.
- `HorillaHistorySectionView`: object history timeline with filtering + pagination.
- `HorillaDynamicCreateView`: safe dynamic creation modal with model/field validation, permission checks, and JS select-option injection.

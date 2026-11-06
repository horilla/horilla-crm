# Horilla detail views (`horilla_generics/views/details.py`)

## Purpose

This module provides:

1. **`HorillaDetailView`** — Full-page (and split-panel) **object detail** with header/body fields, **pipeline** (choices or FK stages), **badges**, **breadcrumbs**, **prev/next** from list session, **field permissions**, **`DetailFieldVisibility`**, and **HTMX pipeline updates**.
2. **`HorillaModalDetailView`** — **Modal-style** detail (`single_detail_view.html`) with **session-backed ID lists** for **previous/next** navigation within a filtered set.

### Extension resolution (`_inherit_detail`)

`HorillaDetailView.as_view()` wraps the class so each request calls `resolve_detail_view_class()`. Target apps register URLs in `AppLauncher.ready()` before extension apps import `details.py`; `bootstrap_extensions()` composes registered specs after `apps.ready`. See [../../../extension/inherit.md](../../../extension/inherit.md). Platform integration tests extend `horilla.contrib.core.views.users.UserDetailView`.

---

## `HorillaDetailView`

Django **`DetailView`** subclass. Template: **`detail_view.html`** (or **`detail_view_split_fragment.html`** when `layout=split`).

### Edit Details (bulk field edit)

The details tab (`details_tab.html`) exposes **Edit Details**, which HTMX-loads
`generics:edit_all_fields` and saves via `generics:update_all_fields`. See
[edit_field.md](helpers/edit_field.md) for `EditAllFieldsView`,
`UpdateAllFieldsView`, and extension seams (`check_before_save`,
`ExtraFieldsProvider`, Jalali `FieldInfoResolver`).

### Edit Details (one record)

`HorillaInlineEditMixin` and `HorillaInlineEditNavMixin`
(`horilla/contrib/generics/views/inline_edit.py`, re-exported from
`horilla.contrib.generics.views`) edit a single record in place. The page is a
`TemplateView` that names `model` and a `HorillaModelForm` with `fieldsets`.
The sections render read-only until `?edit=true` (or `as_view(edit=True)`),
then the same page shows the form. The navbar mixin supplies Edit Details,
Cancel and Save. File fields stay on the form and are left out of the
read-only sections. `can_change` checks `change_<model>` unless `change_perm`
is set.

Core uses this for the company Details tab, the branch detail page, the user
detail Details tab and My Profile. Those pages reload after a save so the
navbar name and avatar refresh. This is separate from the bulk Edit Details
flow above.

### Automatic registration (`__init_subclass__`)

Subclasses that set **`model`** are stored in **`HorillaDetailView._view_registry[model] = cls`**. Used when handling **`POST`** pipeline updates so the correct subclass (with its `pipeline_field`, etc.) can be instantiated.

### Class attributes (configuration)

| Attribute | Default | Role |
|-----------|---------|------|
| `template_name` | `"detail_view.html"` | Overridden by `get_template_names()` for split fragment. |
| `context_object_name` | `"obj"` | Main instance in templates. |
| `body` | `[]` | List of field specs `(verbose_name, name)` or bare names; feeds **grid** via `get_body()` / visibility. |
| `fieldsets` | `()` | Optional sectioned layout: `(name, {"fields": (...), "icon": optional})`. Feeds **`get_fieldsets()`** / context `fieldsets` (e.g. user settings detail). |
| `header_fields` | `[]` | Fields for **header**; if empty, first field from normalized `body` is used. |
| `base_excluded_fields` | `id`, `created_at`, `additional_info`, … | Base exclude list for field lists. |
| `excluded_fields` | `[]` | Extra excludes (merged in `get_excluded_fields()`). |
| `split_excluded_fields` | `[]` | Extra excludes **only** when `layout=split` (`get_detail_section_body()`). |
| `pipeline_field` | `""` | Field name driving **pipeline UI** (choices or FK to ordered related model). |
| `breadcrumbs` | `[]` | Default/initial; often overridden by dynamic logic in `get_context_data`. |
| `actions` | `[]` | Action buttons for toolbar (dicts with `action`, `src`, `attrs`, etc.). |
| `tab_url` | `""` | If set, enables **“change visible fields”** URL and sync with tab details URL. |
| `final_stage_action` | `{}` | Shown in pipeline context; may be a **callable** (called in `get_context_data`). |
| `badge` | `[]` | List of `{"condition": callable(obj)->bool, "label", "class", optional icon keys}`. |

### `dispatch`

1. Unauthenticated → **`login_redirect(request)`** (`horilla.auth.mixins`; 302, or 204 + `HX-Redirect` for HTMX).
2. Optionally **`model`** from **`GET`/`POST`** `app_label` + `model_name` via **`apps.get_model`**.
3. **`get_object()`** — failures: HTMX → **`RefreshResponse`** + message; else **`HttpNotFound`** (both from **`horilla.web`**).
4. Permission: **`view_{model}`** **or** (**owner** per **`OWNER_FIELDS`** and **`view_own_{model}`**) **or** granted access. Owner detection supports **FK** (`== user`) and **M2M** (`user in field.all()`). Granted access is a per-model opt-in beyond `OWNER_FIELDS`: if the model defines an instance method `has_granted_access(user, action)`, `user_has_granted_access(obj, user, action)` (in `helpers/queryset_utils.py`) calls it and grants access on a truthy result — used e.g. for `Opportunity` team members (`OpportunityTeamMember`) who aren't the record owner but should still see/act on it. The same hook (as a classmethod `granted_access_filter(cls, user, action)` returning a `Q`) is used at the queryset level by list/kanban/global-search views.
5. Denied → **`403.html`**.

### `get` / templates

- Unauthenticated → `login_redirect(request)` (see above).
- **`get_template_names()`**: if **`layout=split`** (GET) → **`["detail_view_split_fragment.html"]`**.

### Field lists

| Method | Role |
|--------|------|
| `get_excluded_fields()` | `base_excluded_fields` + `excluded_fields`. |
| `_normalize_field_list(field_list, exclude_set)` | Builds `(verbose_name, field_name)`; skips **hidden** field perms; resolves **`verbose_name`** from model for i18n. |
| `get_header_fields()` | From `header_fields` or first normalized **`body`** row. |
| `get_detail_section_body()` | Split layout: all model fields minus excludes + `split_excluded_fields` + effective **pipeline** field; optional **`include_fields`** if defined on class. |
| `get_body()` | If **`DetailFieldVisibility`** exists for **`resolve(request.path).url_name`** and has **`header_fields`**, uses that list (same storage key name as core model — **not** only “header” in practice). Else normalized **`body`**; if `header_fields` not set, returns **full** `body` so index 0 can act as title and rest as grid. |
| `get_fieldsets()` | When **`fieldsets`** is set: list of `{name, fields, description, icon}` with normalized `(verbose_name, field_name)` lists (permissions / excludes applied). When empty: single untitled group from `get_body()` (skips title row when `header_fields` empty). Extensions use **`fieldsets_insert`**. |

### Pipeline

| Method | Role |
|--------|------|
| `_get_effective_pipeline_field()` | Returns `pipeline_field` only if not filtered out as hidden for user (**`filter_hidden_fields`**). |
| `_make_pipeline_choice(...)` | Builds one **dict** pill: `label`, `value`, `is_completed`, `is_current`, `related_obj`, `use_custom_colors`. Domain-only keys (e.g. `is_final`) are **not** set here. |
| `get_pipeline_choices()` | List of those dicts for **choices** or **FK** (orders by related `order` if present; can filter related queryset by **`company`** when both sides have it). For FK stages, **`related_obj`** is the loaded related instance so subclasses can read attrs without re-querying. |
| `check_update_permission()` | **`change_{model}`** or (**owner** + **`change_own_{model}`**), with M2M/FK owner logic. |

#### `related_obj` vs domain `is_final`

Same pattern as [kanban](kanban.md#related_obj-generic-contract):

- **`HorillaDetailView`** only attaches **`related_obj`** (or `None` for choice fields).
- **`is_final`**, convert/closed actions, and similar CRM rules live on **Lead** / **Opportunity** detail subclasses (and their stage models).
- Template `partials/pipeline_choices.html` uses named keys (`choice.label`, `choice.value`, `choice.is_final`, …). `choice.is_final` is only present when a CRM subclass annotates it; otherwise the check is falsy.

| Subclass | How `is_final` is set |
|----------|------------------------|
| `LeadDetailView` | After `super().get_pipeline_choices()`, from `related_obj.is_final` on `LeadStatus` |
| `OpportunityDetailView` | Local `_pipeline_choice(..., is_final=...)` — synthetic **Closed** / closed won-lost need an explicit flag because Closed Lost may not have `model.is_final=True` |

`final_stage_action` (class attr / `cached_property`) still drives HTMX for those final pills when `choice.is_final` is true.

### Badges — `get_badges()`

Evaluates **`self.badge`** entries: **`condition(obj)`** optional; if missing, badge always shows. Supports **`label`**, **`class`**, optional **`icon`**, **`icon_class`**, **`icon_bg_class`**.

### Tab URL — `_get_details_section_url_for_fields(object_id)`

When **`tab_url`** is set, resolves the tab view class and temporarily sets **`_thread_local.request`** to read **`urls["details"]`** from a minimal fake request (for **field selector** modal alignment with Details tab). Returns URL **name** string or `None`.

### `get_context_data` (high level)

Always adds (among others): **`header_fields`**, **`body`** (from `get_body()` or `get_detail_section_body()` if split), **`fieldsets`** (from `get_fieldsets()`), **`pipeline_choices`**, **`tab_url`**, **`badges`**, **`field_permissions`**, **`can_update`**, **`final_stage_action`** (callable resolved), optional **`pipeline_custom_*`** from **`get_pipeline_custom_colors()`** if present.

**Split layout** (`GET` or **`POST` `layout=split`**): **`body`** = `get_detail_section_body()`, **`split_detail_url`** from **`obj.get_detail_url()`** if defined; may append **“View full detail”** to **`actions`**.

**Prev/next**: Uses session **`list_view_queryset_ids_{model_name}`**; if empty, builds IDs from **`HorillaListView`** queryset and stores **`list_view_queryset_ids`** (note: different session key than the primary one — see source). Sets **`has_previous`**, **`has_next`**, **`previous_id`**, **`next_id`**.

**Field selector**: If **`tab_url`**, sets **`change_fields_url`** to **`horilla_generics:detail_field_selector`** with query params; may append **`details_section_url`** from `_get_details_section_url_for_fields`.

**Breadcrumbs**: Combines **HX-Current-URL**, **HTTP_REFERER**, session keys per object, **`referrer_*`** GET params, **`session_url`** preservation, and stores **`detail_view_breadcrumbs_{model}_{id}`**. Early return when **HX reload** path matches current path restores **stored breadcrumbs**.

**Pipeline in context**: **`pipeline_field`** / **`pipeline_field_verbose_name`** when effective pipeline field exists.

### `post` / `update_pipeline`

- **`POST`** with **`pipeline_update`**: resolves **`model`** from POST, finds **`view_class`** from **`_view_registry`** or uses current class, sets **`pipeline_field`**, delegates to **`update_pipeline`**.
- **`update_pipeline`**: Requires **`pipeline_value`**; checks **change** / **change_own** (and superuser); updates choice or FK field; **`save()`**; success message.
  - If **`layout=split`**: re-renders **`detail_view_split_fragment.html`** with updated context (fixes **`url_name`** / **`app_label`** from **`get_detail_url()`** when possible).
  - Else: returns HTML fragment from **`partials/pipeline_choices.html`** with **`pipeline_update`** flag in context.

---

## `HorillaModalDetailView`

For **modal** or **lightweight** detail pages using **`template_name = "single_detail_view.html"`**.

### Class attributes

| Attribute | Default | Role |
|-----------|---------|------|
| `title` | `"Detailed View"` | Context **`title`**. |
| `header` | dict with title/subtitle/avatar | Branding block. |
| `body` | `[]` | Field rows; normalized by `get_body_fields()` (see below). |
| `action_method` | `[]` | Extra action metadata. |
| `actions` | `[]` | Toolbar actions. |
| `cols` | `{}` | Layout columns config. |
| `empty_template` | `None` | If **`get_object`** yields nothing, optional alternate render. |
| `ids_key` | `"instance_ids"` | GET param for passing ID list into session (with `get`). |

### Session keys

- **`ordered_ids_{modelname_lower}`** — list of PKs for ordering and filter (set from GET **`ids_key`** in **`get`** when needed).
- **`get_queryset()`** filters to **`pk__in`** session list when present.

### Flow

- **`__init__`**: sets **`ordered_ids_key`**, attaches **`request`** from **`_thread_local`** if available.
- **`get`**: initializes empty session list if no **`ids_key`** in GET and no session data; if no **`instance`** and **`empty_template`**, renders it; if no instance, error + reload script.
- **`get_context_data`**: **`instance`**, **`title`**, **`header`**, **`body`** (from **`get_body_fields()`**), **`actions`**, **`action_method`**, **`cols`**; if **`instance_ids`** in session, **`closest_numbers`** for prev/next **`reverse_lazy`** URLs, **`extra_query`** (GET without **`ids_key`**).

### `get_body_fields()` — label normalization

Each entry in **`self.body`** is normalized into `(label, field_name)`:

- tuple/list `(label, field_name)` -> if `label` is a plain string that itself
  names a real model field, resolved to that field's verbose name (e.g.
  `("is_active", "is_active_col")` displays the `is_active` field's verbose
  name); otherwise `label` is used as-is
- string field name -> resolves the model field's verbose name
- string `get_<field>_display` -> resolves the verbose name of `<field>`
- string naming a method/property with a `short_description` attribute
  (Django admin convention) -> uses that as the label
- fallback -> title-cased string label

---

## Related history and read-only records

`horilla/contrib/generics/history.py` lets one record list another record's
activities, notes, attachments and emails, and lets a record lock itself.
Nothing in that module imports an app model.

| Hook on the model | Effect |
|-------------------|--------|
| `get_history_sources()` | Records whose related rows also show on this one. `history_sources()` keeps only those the user may view. `history_q()` matches rows on this record or on those sources. |
| `is_record_locked` | Truthy while the record is read-only. `is_record_locked()` reads the property. Detail, list actions and edits honour it. |

Rows that come from a history source are labelled and their row actions are
disabled, not hidden (`guard_foreign_row_action`). A locked record disables
actions on every row.

CRM uses both hooks for converted leads:

- `Lead.is_record_locked` is true when `is_convert` is set, so a converted lead stays readable and cannot be edited.
- Contact, Account and Opportunity implement `get_history_sources()` so the converted lead's activities, notes and emails show on the record it became. Account walks the contacts and opportunities created from the lead. Those reverse relations are listed in `FULL_HISTORY_EXCLUDE` so the History tab does not also merge them as ordinary related rows.

A detail modal whose record no longer exists closes instead of rendering an empty page.

---

## Examples

### 1. Subclass `HorillaDetailView` (from the Leads app)

This mirrors how **`LeadDetailView`** is wired: **`model`** registers the view for pipeline POST routing; **`body`** lists field names (normalized to verbose names); **`pipeline_field`** drives the stage UI; **`tab_url`** enables the field-visibility modal to align with the tab strip.

```python
from horilla.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from horilla.urls import reverse_lazy
from horilla.utils.decorators import permission_required_or_denied
from horilla.contrib.generics.views import HorillaDetailView
from horilla_crm.leads.models import Lead


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadDetailView(LoginRequiredMixin, HorillaDetailView):
    model = Lead
    body = [
        "title",
        "first_name",
        "last_name",
        "email",
        "lead_source",
        "industry",
        "lead_owner",
    ]
    excluded_fields = ["is_convert", "message_id"]
    pipeline_field = "lead_status"
    tab_url = reverse_lazy("leads:lead_detail_view_tabs")

    def get_pipeline_choices(self):
        """Annotate is_final from LeadStatus (CRM-only; not in HorillaDetailView)."""
        pipeline = super().get_pipeline_choices()
        if not isinstance(pipeline, list):
            return pipeline
        for choice in pipeline:
            related = choice.get("related_obj")
            choice["is_final"] = bool(
                related is not None and getattr(related, "is_final", False)
            )
        return pipeline
```

See [lead stages — kanban & detail](../../../../horilla_crm/leads/lead_stages.md#kanban--detail-pipeline).

**URL** (typical):

```python
# horilla_crm/leads/urls.py
path("leads-detail/<int:pk>/", views.LeadDetailView.as_view(), name="leads_detail"),
```

Open split fragment (e.g. from a list split pane):

```text
GET /leads/leads-detail/42/?layout=split
```

---

### 2. Pipeline update (HTMX `POST`)

The template posts to the same detail view class that owns **`pipeline_field`**. Required fields include **`pipeline_update`**, **`pipeline_value`**, **`pipeline_field`**, **`model_name`**, **`app_label`**.

Conceptual **`hx-vals`** / form body:

```text
pipeline_update=1
pipeline_field=lead_status
pipeline_value=<choice_or_fk_pk>
model_name=lead
app_label=leads
```

Optional: **`layout=split`** so the response re-renders **`detail_view_split_fragment.html`** instead of **`partials/pipeline_choices.html`**.

---

### 3. Dynamic model via query string (generic helper URL)

`dispatch` can set **`self.model`** from **`GET`/`POST`** when **`app_label`** and **`model_name`** are present. That pattern is used by shared routes (e.g. **`horilla_generics`** helpers) so one endpoint can target different models—permissions still use **`view_*` / `view_own_*`** on the resolved model.

---

### 4. `HorillaModalDetailView` — prev/next over a list of IDs

Session key **`ordered_ids_{modelname_lower}`** must contain the ordered PK list. **`HorillaListView`** (and some section views, e.g. attachments) **write this key** before you open a row’s modal; then **`HorillaModalDetailView`** can compute **`next_url`** / **`previous_url`** via **`closest_numbers`**.

```python
from horilla_generics.views.details import HorillaModalDetailView
from myapp.models import Ticket


class TicketModalDetailView(HorillaModalDetailView):
    model = Ticket
    title = "Ticket"
    body = [("Subject", "subject"), ("Status", "status")]
```

**Upstream** (conceptual—often in list or parent view):

```python
request.session[f"ordered_ids_{Ticket.__name__.lower()}"] = [3, 5, 7, 12]
```

**User request** to the modal (path depends on your `urls.py`):

```text
GET /tickets/modal/5/
```

Optional GET param **`instance_ids`** (see **`ids_key`**) is only used when your flow copies IDs into session; match patterns already used in **`horilla_generics.views.list`** or **`HorillaNotesAttachementDetailView`** in this repo.

### 4. Sectioned detail with `fieldsets` (`BranchDetailView`)

Use **`fieldsets`** when the detail page has named sections (icons optional). Template: **`{% include "detail_fieldset.html" %}`** with context `fieldsets` from `get_fieldsets()`.

```python
from horilla.contrib.generics.views import HorillaDetailView
from horilla.contrib.core.models import Company

class BranchDetailView(LoginRequiredMixin, HorillaDetailView):
    template_name = "branches/branch_detail_view.html"
    model = Company
    fieldsets = (
        (_("Branch Information"), {
            "fields": ("name", "email", "website", "contact_number", ...),
            "icon": "fas fa-building",
        }),
        (_("Address"), {"fields": ("city", "state", "country", "zip_code"), ...}),
        (_("Localization"), {"fields": ("time_zone", "language", "currency"), ...}),
    )
```

Extensions can inject fields with **`fieldsets_insert`** on `_inherit_detail` targets. See [extension detail inherit](../../../extension/detail/inherit.md#fieldsets-layout).

### 5. Flat grid from view-declared `body` (`CompanyDetailsTab`)

For tab partials that are not full `HorillaDetailView` pages, declare **`body`** as `(field_name, icon_class)` and build rows in `get_context_data()`:

```python
class CompanyDetailsTab(LoginRequiredMixin, TemplateView):
    template_name = "settings/company_details_tab.html"
    body = (("name", "fa-solid fa-building"), ("email", "fa-solid fa-envelope"), ...)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = request.active_company or request.user.company
        context["obj"] = obj
        context["detail_fields"] = [
            (obj._meta.get_field(name).verbose_name, name, icon)
            for name, icon in self.body
        ]
        return context
```

Template loops `detail_fields` and uses **`{% display_field_value obj field %}`** so labels stay aligned with model metadata.

---

## Related docs

| Topic | See |
|-------|-----|
| Details **tab** section (HTMX, `details_tab.html`) | `detail_tabs.md` |
| Tab strip (`HorillaDetailTabView`) | `detail_tabs.md` |
| Core tab / history | `core.md` |
| Kanban `related_obj` / bulk column counts | `kanban.md` |
| Lead `is_final` on kanban & detail | [lead_stages.md](../../../../horilla_crm/leads/lead_stages.md#kanban--detail-pipeline) |
| Opportunity closed pipeline pills | [opportunity_stages.md](../../../../horilla_crm/opportunities/opportunity_stages.md#detail-pipeline) |

---

## Summary

| Class | When to use |
|-------|-------------|
| `HorillaDetailView` | Standard **record detail** with pipeline, breadcrumbs, list navigation, permissions, and optional **split** fragment. |
| `HorillaModalDetailView` | **Modal** detail with **session-based** prev/next over a list of IDs. |

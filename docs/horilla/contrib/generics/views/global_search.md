# Global search (`horilla_generics/views/global_search.py`)

## Purpose

`GlobalSearchView` is a **login-required** cross-model search UI. It:

- reads **which models** participate from the **feature registry** (`global_search_models`);
- builds **per-model search field lists** and **display columns** from the model's **`global_search` feature options** (falling back to the first five **CharField** / **TextField** fields);
- applies **`view_*` / `view_own_*`** filtering with **`OWNER_FIELDS`** (or common ownership heuristics);
- renders **`global_search.html`** with **tabs** (by model) and **result tables** via **`HorillaListView`** + **`list_view.html`**;
- supports **HTMX** for **tab switching** and **empty-query redirect** back to the previous page;
- offers **live suggestions** in the header search box (**`GlobalSearchSuggestView`**) and **quick filters**.

URL names (under the generics URL config):

| Name | Path | View |
|------|------|------|
| `generics:global_search` | `search/` | `GlobalSearchView` — full results page |
| `generics:global_search_suggest` | `search/suggest/` | `GlobalSearchSuggestView` — dropdown fragment |

---

## Registration: which models appear

Models are **not** hard-coded in this file. They come from:

```python
FEATURE_REGISTRY.get("global_search_models", [])
```

Populated at runtime via **`horilla.registry.feature`** (e.g. **`register_model_for_feature(..., features=["global_search"])`** or **`register_models_for_feature(..., features=["global_search"])`**). Apps often do this in **`registration.py`** loaded from **`AppConfig.ready()`**.

**Important:** `get_include_models()` **must** read the registry **at request time** (as implemented). Caching model lists on the class at **import** time would stay **empty**, because registration runs **after** imports during **`AppConfig.ready()`**.

---

## Class: `GlobalSearchView`

- **Base:** `LoginRequiredMixin`, Django **`View`** (not `TemplateView`).
- **Template:** `template_name = "global_search.html"`.

### Class-level defaults

| Name | Role |
|------|------|
| `exclude_standard_fields` | Field names skipped for search and column picking (`id`, `company`, audit fields, etc.). |
| `default_icons` | Default Tailwind / Font Awesome keys for tab UI (`bg_color`, `text_color`, `icon`). |

---

## Choosing search fields — `global_search` options

Each app decides what its models search and show, from its own `registration.py`, with no change to this file. Options are stored by the [feature registry](../../../registry/feature.md#feature-options):

```python
register_model_for_feature(
    app_label="reports",
    model_name="Report",
    features=["global_search"],
    options={
        "global_search": {
            "search_fields": ["name", ("Module", "module__model"), "folder__name"],
            "columns": ["name", "module", "folder", ("Chart Type", "chart_type")],
        }
    },
)
```

| Option | Format | Default |
|--------|--------|---------|
| `search_fields` | Lookups searched with `icontains` and OR'd: `"name"`, a path through a relation such as `"owner__first_name"`, or `("Label", "lookup")` | First 5 `CharField` / `TextField` fields not in `exclude_standard_fields` |
| `columns` | Columns of the results table: `"field"` or `("Label", "field")`; **direct fields only** | The direct fields of `search_fields` (up to 5) |

Options can also be set with `set_feature_options("global_search", {...}, model_class=...)` (used for models registered as a group, e.g. in `core/registration.py`) or as `FEATURE_OPTIONS = {"global_search": {...}}` on the model.

Names that are not fields of the model are **logged and skipped**, so a typo cannot break search. Do not list credentials or serialised settings (for example API keys, JSON columns) as search fields.

### Labels

`get_configured_fields(model)` returns `(search_fields, columns, labels)`. A label is the field's **verbose name** (for a relation path, the verbose name of the final field). When two search fields would get the same label, the relation's name is added (`name` / `parent__name` become "Folder Name" / "Parent Folder Name"). Use `("Label", "lookup")` only when the verbose name reads badly. Labels are used by the dropdown's field rows.

---

## Dynamic model configuration — `get_dynamic_model_config()`

For each **installed** model whose **`model_name`** (capitalized class name, e.g. `Lead`) matches an entry from `get_include_models()` (matched by **lowercase** `model_name`):

1. Resolve **`search_fields`**, **`columns`** and **`field_labels`** with `get_configured_fields(model)` (options above).
2. Skip the model if **`search_fields`** or **`columns`** ends up empty.

Each entry in the returned dict is keyed by **`model_name`** (e.g. `"Lead"`) with:

| Key | Meaning |
|-----|---------|
| `app_name` | `app_label` |
| `search_fields` | Lookups to search |
| `field_labels` | `{lookup: label}` for the dropdown |
| `icons`, `verbose_name`, `columns` | As above |

`build_search_q(config, query, field=None)` builds the OR query; when `field` is one of the model's search fields only that field is searched.

---

## Permission filtering — `filter_viewable_queryset(user, model, base_queryset)`

Lives in `helpers/queryset_utils.py` (not on `GlobalSearchView`), because the Select2 endpoint (the filter panel's value dropdowns) and the User Picker apply the same rule to the lists they return, so all three stay in step.

- **`view_{model_name}`** → return **full** `base_queryset`.
- Else **`view_own_{model_name}`**:
  - for the **user model** itself, **the user's own record and the users under them** (`get_allowed_user_ids`), since a user record is owned by that user and not by whoever created it. Without this a normal user got an empty Lead Owner dropdown in the filter panel;
  - for other models, restrict using **`OWNER_FIELDS`**:
    - **ForeignKey** / **ManyToMany** to **user** / **employee** / **`auth.user`**: filter with `Q(...)` combined with **OR** across fields.
    - Non-relation fields: `Q(field_name=user)` when applicable.
    - **`get_granted_access_filter(model, user, "view")`** (see [list.md — Granted access](list.md#granted-access-per-model-opt-in-beyond-owner_fields)) is called and, if it returns a `Q`, **OR'd** into the same combined query — so a model opting into granted access (e.g. `Opportunity` team members) surfaces matching records in search results even without an `OWNER_FIELDS` match.
- If **`OWNER_FIELDS`** is missing or yields no queries, falls back to trying common names: **`created_by`**, **`user`**, **`owner`**, **`employee_id`** (same FK/M2M rules).
- If user has **neither** permission → **empty** queryset.

---

## Tab / table HTML — `get_tab_content(request, model_name, query)`

1. Resolves **`model_config[model_name]`**; otherwise returns a small “Model not found” HTML fragment.
2. Builds the query with **`build_search_q`** (all **`search_fields`**, or only the **`field`** GET parameter), applies **`filter_viewable_queryset`**, then **`apply_quick_filter`**.
3. Configures a **`HorillaListView`** instance: **`queryset`**, **`columns`**, **`paginate_by=100`**, **`search_url`** → **`generics:global_search`**, **`view_id`** `global-search-{model}`, etc.
4. If the model defines **`get_detail_url`** or **`get_detail_view_url`**, sets **`col_attrs`** on the **first column** with **`get_col_attrs_for_model`** (HTMX navigation into main content). Models without either are listed without a link.

Returns **`render_to_string("list_view.html", ...)`**.

---

## HTMX column navigation — `get_col_attrs_for_model(model_name, request, detail_attr)`

Builds **`hx-*`** attrs for the first column so clicking a row loads the object’s detail:

- **`hx-get`**: `{<detail_attr>}` placeholder (`get_detail_url` or `get_detail_view_url`) plus **`q`**, **`filter`**, and **`section`**. The section always comes from **`get_section_info_for_model(model_name)`** (when the model's app has one), so the detail page loads its side menu even if the search was started without a section.
- **`hx-target`**: `#mainContent`, **`hx-push-url`**, **`hx-select`**, **`hx-select-oob`** for `#sideMenuContainer`.
- Clears header search on click: **`hx-on:click`**: `$('#header-search').val('')`.

The template/list layer substitutes the placeholder per row with each instance’s detail URL.

---

## GET handler — `get(request)`

### Query parameters

| GET | Role |
|-----|------|
| `q` | Search string (trimmed). **Empty** → see below. |
| `filter` | `all` (default) or a model name (e.g. `lead`; capitalised internally) to show **only** that model’s tab/results. |
| `prev_url` | Where to go when **`q`** is empty; **sanitized** with **`safe_url`** from **`horilla.web`**, `section` may be stripped from query, and nested global-search URLs fall back to **`session["pre_search_url"]`**. |
| `section` | Passed through when redirecting; used in close button and tab links. |
| `tab_model` | With **HTMX** + non-empty **`q`** (or a quick filter), returns **only** `get_tab_content(...)` HTML for that model (tab switch). |
| `field` | Search only this field of the model(s); an unknown name is ignored (all fields are searched). Set from the dropdown's "Search <field> for" rows. |
| `qf` | Quick filter, works **without** `q` (see below). An unknown value behaves like no filter. |

### Quick filters (`qf`)

`apply_quick_filter(model, queryset, request)` narrows results after the permission filter. Labels are in `quick_filter_labels`:

| `qf` | Label | Rule |
|------|-------|------|
| `mine` | My Records | Owner field(s) (`OWNER_FIELDS`, else `created_by`) equal the current user |
| `today` | Created Today | `created_at` date is today |
| `yesterday` | Created Yesterday | `created_at` date is yesterday |
| `week` | Created This Week | `created_at` in the last 7 days |
| `month` | Created This Month | `created_at` on or after the 1st of this month |

A model that cannot satisfy a filter (no owner field, no `created_at`) returns nothing and drops out. With a quick filter and no `q`, the page is shown (heading and chip name the filter) instead of redirecting.

### Empty query (`q` missing/blank, and no `qf`)

- Optionally appends **`section`** to **`previous_url`**.
- If **`HX-Request`**: **`HttpResponse`** with **`HX-Redirect`** → **`previous_url`**.
- Else: **`redirect(previous_url)`**.

### Full page (non-tab HTMX)

Builds **`model_config`**, runs search per model, counts results, **sorts** models by **result count** descending, pre-renders **`first_tab_content`** for the **first** model with hits (respecting **`filter`**).

Renders **`global_search.html`** with:

- `query`, `quick_filter`, `quick_filter_label`, `total_results`, `model_config`, `search_results`, `first_tab_content`, `previous_url`.

---

## Live suggestions — `GlobalSearchSuggestView`

Subclass of `GlobalSearchView` (same model config and permission filtering). `GET search/suggest/?q=...` returns an HTML fragment (`global_search_suggest.html`) for the header dropdown:

- nothing when **`q`** is shorter than 2 characters;
- a **Search All for: q** row with the total, then one row per model with matches and its count (sorted by count), each linking to the full results page filtered to that model (`filter=<model>`);
- with **`expand=<Model>`**, that model also lists one row per search field with its count (`field=<lookup>`); fields with no match are hidden;
- **`prev_url`** is passed through to the links.

Counts use the same permission filtering as the results page, so users only see counts for records they can open.

### Header behaviour (`templates/components/header.html`)

- Typing (after 250 ms, 2+ characters) loads the suggestions into `#global-search-dd`; **Enter** opens the full results page; **Esc** or a click outside closes the dropdown.
- With fewer than 2 characters, the dropdown shows **Recent Searches** (last 5, kept in the browser's `localStorage`, with a Clear link) and **Quick Filters** (links with `qf=`).
- On the results page the search box keeps the query. The clear (×) control is a normal link back to the previous page.

---

## Integration points

| Piece | Location |
|-------|----------|
| Header search box | `templates/components/header.html` — suggestions via **`global_search_suggest`**, Enter opens **`global_search`**, both with **`prev_url`**. |
| Templates | `global_search.html` — tabs, `first_tab_content`, clear link; `global_search_suggest.html` — dropdown fragment. |
| URLs | `generics/urls.py` — `search/` (`global_search`) and `search/suggest/` (`global_search_suggest`). |
| Feature registry | `horilla/registry/feature.py` — **`FEATURE_CONFIG["global_search"]`** → **`global_search_models`**; per-model settings via `get_feature_options("global_search", model)`. |

---

## Example: register a model for global search

In your app’s **`registration.py`** (loaded from **`AppConfig`**):

```python
from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="myapp",
    model_name="Ticket",
    features=["global_search"],
)
```

Or bulk:

```python
from horilla.registry.feature import register_models_for_feature

register_models_for_feature(
    models=[("myapp", "Ticket"), ("myapp", "Tag")],
    features=["global_search"],
)
```

Without options the model searches its first five **CharField** / **TextField** fields; it needs at least one that is not in **`exclude_standard_fields`**, or it is skipped by **`get_dynamic_model_config()`**. To choose the fields, add `options` as shown in [Choosing search fields](#choosing-search-fields--global_search-options):

```python
register_model_for_feature(
    app_label="myapp",
    model_name="Ticket",
    features=["global_search"],
    options={"global_search": {
        "search_fields": ["subject", "reporter__email"],
        "columns": ["subject", ("Reporter", "reporter"), "status"],
    }},
)
```

For a clickable first column, give the model **`get_detail_url`** or **`get_detail_view_url`**.

---

## Summary

| Topic | Behavior |
|-------|----------|
| **Scope** | Only models in **`FEATURE_REGISTRY["global_search_models"]`**. |
| **Search** | OR of **`__icontains`** on the model's configured `search_fields` (default: first five text fields). |
| **Security** | **`view_*` / `view_own_*`** + ownership filters. |
| **UI** | Header dropdown with live suggestions; full page + HTMX tabs; list rows open detail via **`get_detail_url`** / **`get_detail_view_url`**. |

For registry API details, see **`horilla/registry/feature.md`**.

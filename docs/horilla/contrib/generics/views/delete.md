# Horilla single delete (`horilla_generics/views/delete.py`)

## Purpose

`HorillaSingleDeleteView` is the generic **single-record delete** flow with **dependency checks**, **reassign / set-null / delete related** options, **bulk reassign**, and **hard vs soft** delete modes.

It combines Django’s `DeleteView` with mixins from `horilla_generics.views.toolkit.delete_mixins`:

- `DeleteDependencyMixin`
- `DeleteReassignMixin`

Actual dependency scanning and helpers live in those mixins; this file wires them into HTTP GET/POST and templates under `partials/single_delete/`.

### Imports (`delete.py`)

| Symbol | Import |
|--------|--------|
| `transaction` | `from horilla.db import transaction` under `# First party imports (Horilla)` |
| `DeleteView`, `messages` | `django.*` under `# Third-party imports (Django)` |

Do not place `horilla.db` imports in the Django block. See [coding_rule.md](../../../../coding_rule.md#import-order-and-section-comments).

---

## Class: `HorillaSingleDeleteView`

```python
class HorillaSingleDeleteView(DeleteDependencyMixin, DeleteReassignMixin, DeleteView):
    ...
```

### Class attributes (configuration)

| Attribute | Default | Role |
|-----------|---------|------|
| `template_name` | `None` | Not used as a single full-page template; responses render named partials. |
| `success_url` | `None` | If set, `get_post_delete_response()` redirects here after successful delete. |
| `success_message` | `"The record was deleted successfully."` | Used by `get_success_message()` / flash messages. |
| `reassign_all_visibility` | `True` | UI/feature flags for bulk reassign (used in dependency context). |
| `reassign_individual_visibility` | `True` | UI/feature flags for per-row actions. |
| `check_delete_permission` | `True` | If `True`, `get_object()` enforces `delete_*` / `delete_own_*` and `OWNER_FIELDS`. |
| `hx_target` | `None` | Passed into `delete_all_confirm` partial as `hx_target`. |
| `excluded_dependency_model_labels` | list of model names | Models ignored when walking dependencies; defaults to `DEFAULT_EXCLUDED_DEPENDENCY_MODEL_LABELS` (`toolkit/delete_mixins.py`) plus models apps register for the core `delete_dependency` feature. |

### Resolving the model / queryset

`get_queryset()`:

1. If `self.model` is not already set (`getattr(self, "model", None)`), read URL kwargs `app_label` + `model_name`, call `apps.get_model(...)`, and assign `self.model`.
   - Missing `app_label` or `model_name` → `ImproperlyConfigured`.
   - `LookupError` → render `403.html` with `{"modal": True}`.
2. Return one queryset for the resolved model: `model.all_objects.all()` when `all_objects` exists, else `objects.all()`.

Reassign targets (`available_targets`) are built from `model.objects` (company-filtered manager), not `all_objects`, so only the active company's records are offered.

Model resolution happens **before** the queryset is built so `self.model` is always set for downstream `get_object()` / dependency checks.

**Subclass pattern:** set `model = MyModel` on the view; **or** use URL kwargs `app_label` / `model_name`.

---

## GET flow (`get`)

### Authentication

If not authenticated → `login_redirect(request)` (`horilla.auth.mixins`): a 302 to login for normal requests, or a 204 with `HX-Redirect` for HTMX requests; `next` is the page the user was on.

### Query parameters (common)

| GET param | Meaning | Example |
|-----------|---------|---------|
| `action` | Sub-flow / partial to return | `load_more_dependencies` |
| `delete_mode` | `hard` / soft context for templates | `hard` (default in code when reading) |
| `view_id` | Stable id for HTMX targets | `delete_42` |
| `related_name` | For paginated dependency rows | `lead_set` |
| `page`, `per_page` | Pagination for partials | `page=2&per_page=8` |
| `check_dependencies` | Often passed from HTMX as POST; GET path uses dependency checks internally | — |

### `action` branches

| `action` | Template / behavior |
|----------|---------------------|
| `load_more_dependencies` | `partials/single_delete/delete_dependency_partial.html` |
| `load_more_individual_records` | `partials/single_delete/individual_reassign_partial.html` |
| `show_bulk_reassign` | `partials/single_delete/bulk_reassign_form.html` |
| `show_individual_reassign` | Loads **all** dependents (`get_all=True`), sets `dependent_records`, `selected_ids_json` → `individual_reassign_form.html` |
| `show_delete_confirmation` | `delete_all_confirm.html` with related model names |
| *(no `delete_mode` in GET)* | `delete_mode_modal.html` (pick mode first) |
| *(with `delete_mode`)* | `delete_dependency_modal.html` (main dependency UI) |

### Errors

On unexpected exceptions → `raise HttpNotFound(e) from e` (**`horilla.web`** — Horilla custom 404 path). Chaining preserves the underlying lookup/permission error in logs while returning the standard 404 UX.

---

## `get_object()` — delete permissions

When `check_delete_permission` is `True`:

- `delete_perm` = `{app_label}.delete_{model_name}`
- `delete_own_perm` = `{app_label}.delete_own_{model_name}`

Rules:

- User with `delete_perm` → can delete any instance.
- User with `delete_own_perm` → can delete only if **any** `OWNER_FIELDS` on the model equals `request.user` (FK equality only in this check).
- User with `delete_own_perm` but no `OWNER_FIELDS` match → falls back to the per-instance **granted access** hook, `user_has_granted_access(obj, user, "delete")` (see [list.md — Granted access](list.md#granted-access-per-model-opt-in-beyond-owner_fields)); if that returns `True`, the object may still be deleted.
- Otherwise → `PermissionDenied`.

Set `check_delete_permission = False` only if you enforce permissions elsewhere.

---

## POST flow (`post` → `delete`)

`post` loads `self.object` via `get_object()`; on failure returns a small script to reload messages and close delete modals.

`delete()` is the main state machine. Important POST fields:

| POST field | Role |
|------------|------|
| `delete_mode` | Required for most paths (`hard` / soft, etc.) |
| `action` | Which sub-operation to run |
| `check_dependencies` | `"true"` / `"false"` — skip dependency UI when `"false"` and `delete_mode` set |

### High-level branches

1. **No `delete_mode` and** `action != "check_dependencies_with_mode"`
   → render `delete_mode_modal.html` (force mode selection).

2. **`check_dependencies == "false"` and `delete_mode` set**
   → `transaction.atomic()` → `_delete_main_object(delete_mode, user)` → success message → `get_post_delete_response()`.
   (`transaction` is imported via `from horilla.db import transaction` in `delete.py`.)
   On failure (e.g. company context) → message + reload script.

3. **`action == "check_dependencies_with_mode"`**
   → re-run `_check_dependencies`, build context → `delete_dependency_modal.html`.

4. **`action == "bulk_reassign"`** with `new_target_id`
   → bulk reassign dependents, then delete main object.

5. **`action == "individual_action"`**
   → JSON `selected_ids`, per-row or bulk `action_*` / `new_target_*`, then `_perform_individual_action`; if no blocking deps left, delete main.

6. **`action == "soft_delete_record"`** / **`delete_single_record`**
   → operate on one related row (RecycleBin for soft).

7. **`action == "bulk_delete"`**
   → `_bulk_delete_related()` then delete main.

8. **`action == "simple_delete"`**
   → delete main only (inside transaction).

9. **`action == "set_null_action"`**
   → null FK on a related row when nullable, refresh dependency UI.

10. Default path: if `_check_dependencies` says no blockers → render `delete_dependency_modal.html` with empty deps; else error script.

---

## After delete: `get_post_delete_response()`

1. If `success_url` or `get_success_url()` resolves → **redirect**.
2. Else → `HttpResponse` with script:

```javascript
htmx.trigger('#reloadButton','click'); closeDeleteModeModal();
```

Override `get_post_delete_response()` in subclasses for custom HTMX behavior (see `HorillaNotesAttachmentDeleteView`).

---

## Templates (under `partials/single_delete/`)

Referenced by this view:

- `delete_mode_modal.html`
- `_delete_notice.html` — included by the mode modal and the dependency modal. Renders `object.get_delete_notice()` when the model defines it and the return value is not empty. `ForecastTarget.get_delete_notice()` is the shipped example: it says what a role total will add up to after that target is deleted.
- `delete_dependency_modal.html`
- `delete_dependency_partial.html`
- `bulk_reassign_form.html`
- `individual_reassign_form.html`
- `individual_reassign_partial.html`
- `delete_all_confirm.html`

---

## Example: subclass for an app model

```python
from horilla.urls import reverse_lazy
from horilla.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from horilla.utils.decorators import (
    htmx_required,
    permission_required_or_denied,
)
from horilla_generics.views.delete import HorillaSingleDeleteView
from horilla_crm.leads.models import Lead


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.delete_lead", modal=True),
    name="dispatch",
)
class LeadDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    model = Lead
    success_url = reverse_lazy("leads:leads_view")
    success_message = "Lead deleted successfully."
    hx_target = "#mainContent"  # optional, for delete_all_confirm context
```

### Example HTMX open (conceptual)

List row or detail might open the delete modal with:

```html
hx-post="{% url 'leads:lead_delete' object.pk %}"
hx-vals='{"check_dependencies": "true"}'
hx-target="#deleteModeBox"
hx-swap="innerHTML"
```

First GET to the same URL (or POST with `check_dependencies`) drives which partial is returned; exact URLs depend on your `urls.py`.

---

## Summary

| Concern | Where |
|---------|--------|
| Model resolution | `get_queryset()` |
| Delete permission | `get_object()` |
| Dependency UI | `get()` + `build_dependency_context` |
| Delete / reassign / bulk | `delete()` POST branches |
| Success navigation | `get_post_delete_response()` |

For deeper dependency rules, see `horilla_generics/views/toolkit/delete_mixins.py` (`DeleteDependencyMixin`, `DeleteReassignMixin`).

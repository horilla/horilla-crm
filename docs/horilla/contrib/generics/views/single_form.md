# Single form view (`horilla_generics/views/single_form.py`)

## Purpose

`HorillaSingleFormView` is the generic **single-step create/update/duplicate** form view used across Horilla apps.

It supports:

- dynamic form generation when no `form_class` is provided,
- create, edit, and duplicate mode in one view,
- field-level permission enforcement (hidden/readonly/readwrite),
- dynamic-create controls for FK/M2M fields,
- condition-row builders (for rule/criteria style UIs),
- single-object save and multi-instance creation patterns,
- file field clear handling,
- success workflows (`save_and_new`, optional detail redirect),
- consistent permission/object checks via `FormViewCommonMixin`.

Template: `single_form_view.html`

`{% block form_fields %}` and `{% block condition_section %}` are the two override points. A subclass template (for example `forecast_target_form.html`) replaces the generated fields or the condition rows and keeps the shell: form tag, CSRF, header, errors, scroll area, and save button.

When the form has field errors, `partials/form_error_summary.html` lists them as **Please check this field** or **Please check these fields**, with a link that scrolls to that field. The field area scrolls (`max-h-[620px]` when `modal_height` is set, otherwise `modal_height_class`).

---

## Class: `HorillaSingleFormView`

```python
class HorillaSingleFormView(FormViewCommonMixin, FormView):
```

### Key class attributes

| Attribute | Default | Role |
|-----------|---------|------|
| `model` | `None` | Target model. |
| `form_class` | `None` | If missing, dynamic form class is generated. |
| `fields` / `exclude` | `None` | Used by dynamic form builder (`single_form_builder`). |
| `form_url` | `None` | Explicit form submission URL; falls back to current path. |
| `full_width_fields` | `None` | Fields rendered full width. |
| `dynamic_create_fields` | `None` | FK/M2M fields that support inline dynamic create. |
| `hidden_fields` | `[]` | Hard-hidden form fields. |
| `condition_fields` | `None` | Enables condition-row UI (rule builder style). |
| `condition_model` | `None` | Related condition model for condition-row persistence. |
| `condition_field_choices` | `None` | Optional predefined choices for condition fields. |
| `condition_related_name` | `None` | Relation name from main model to condition model. |
| `condition_related_name_candidates` | `[]` | Fallback relation names to try. |
| `condition_hx_include` | `None` | HTMX include selector for dynamic condition widgets. |
| `condition_order_by` | `["created_at"]` | Existing condition ordering in edit mode. |
| `content_type_field` | `None` | Enables auto model-name extraction from content type. |
| `form_mode` | `[]` | Mode switcher entries (see [form_mixin.md](toolkit/form_mixin.md)); empty → Default Form fallback. |
| `detail_url_name` | `None` | On create success, optional HX redirect target. |
| `duplicate_mode` | `False` | Duplicate behavior flag (`?duplicate=true` in edit path). |
| `save_and_new` | `True` | Create-mode save-and-open-new workflow. |
| `permission_required` | `None` | Explicit permissions; otherwise auto add/change logic. |
| `skip_permission_check` | `False` | Bypass mixin permission checks. |
| `return_response` | `""` | Optional custom response override on success. |

---

## Request lifecycle

### `dispatch`

1. If `pk` present, checks `duplicate=true` query param and sets `duplicate_mode`.
2. Runs permission checks through `FormViewCommonMixin.has_permission()`.
3. If HTMX + `add_condition_row` in query, delegates to `single_form_builder.add_condition_row(...)`.
4. Resolves edit object (`pk`) via `get_object_or_error_response`.
5. Sets `self.object` and proceeds.

### `get`

In edit mode:

- clears transient session keys (e.g. `condition_row_count`),
- calculates existing condition count and stores it to session for UI row tracking.

Then delegates to parent `FormView` get flow.

### `post`

Handled by FormView submit flow -> `form_valid` / `form_invalid`.

---

## Form class resolution (`get_form_class`)

When `form_class` is set (e.g. `UserFormSingle`), the view returns the **composed** subclass from `resolve_form_class()` when extension apps registered `_inherit_form` against that path (e.g. `UserFormSingleExtended`). Dynamic forms skip composition.

## Dynamic form generation

If `form_class` is not provided and `model` exists:

- delegates to `single_form_builder.get_dynamic_form_class(self)`.

That builder uses:

- `model`, `fields`, `exclude`,
- `full_width_fields`, `dynamic_create_fields`,
- `condition_fields`, `condition_model`, `condition_field_choices`,
- `hidden_fields`,
- field permissions (`hidden` / `readonly` / `readwrite`),
- duplicate/create/update mode rules.

Important behavior from builder:

- hidden readonly fields may be removed in create/duplicate mode when non-mandatory,
- readonly fields are protected during clean (changes are reverted + validation error),
- owner-aware queryset filtering is inherited from `OwnerQuerysetMixin`.

---

## Form kwargs (`get_form_kwargs`)

Adds a rich kwargs set to the form:

- `full_width_fields`
- filtered `dynamic_create_fields`
- condition metadata (`condition_fields`, model, choices, relation names)
- `hidden_fields`
- `condition_hx_include`
- `field_permissions`
- `duplicate_mode`
- `request`

### Edit vs duplicate handling

- edit normal (`pk`, `duplicate_mode=False`): passes `instance=self.object`.
- duplicate mode (`pk`, `duplicate_mode=True`):
  - does **not** bind instance,
  - builds `initial` from existing object fields,
  - appends `" (Copy)"` to text-like fields (except email/url/slug/choice),
  - preloads many-to-many initial values.

### Content type support

If `content_type_field` is configured, extracts model name and injects into form initial.

---

## Context payload (`get_context_data`)

Main keys:

- `form_title` (Create/Update/Duplicate auto title unless overridden),
- `duplicate_mode`, `save_and_new`,
- `full_width_fields`,
- condition UI keys:
  - `condition_fields`,
  - `condition_fields_tiltle` (source typo retained),
  - `condition_model_str`,
  - `add_condition_url`,
  - `submitted_condition_data`,
- dynamic create config:
  - `dynamic_create_fields`,
  - `dynamic_create_field_mapping`,
  - `related_models_info`,
- `form_url`,
- modal settings (`modal_height`, `modal_height_class`, `header`),
- `view_id`,
- model identity (`model_name`, `app_label`),
- `hx_attrs` (default hx-post/target/swap/enctype merged with custom `self.hx_attrs`),
- `form_mode` (resolved mode switcher list from `resolve_form_mode()`),
- `field_permissions`.

Condition-specific context is enriched via:

- `single_form_builder.build_condition_context(self, context)`

---

## Condition-row feature

This view supports two condition patterns:

### Pattern A: main object + separate condition model

- configure both `condition_fields` and `condition_model`
- main object saved first
- condition rows saved via `save_conditions(...)`

### Pattern B: multiple main instances directly

- configure `condition_fields`
- keep `condition_model = None`
- `form_valid` calls `save_multiple_main_instances(...)`
- each non-empty condition row creates one main-model instance

`save_multiple_main_instances` extension hooks:

- `validate_form_for_multiple_instances(form)`
- `process_row_data_before_create(row_data, row_id, form)`
- `check_duplicate_instance(row_data, unique_check_cache, form)`
- `modify_create_kwargs(create_kwargs, row_data, row_id, form)`
- `update_unique_check_cache(row_data, unique_check_cache, instance)`
- `get_duplicate_error_message(row_data, db_error)`

These hooks are how domain views implement custom row semantics.

---

## Save flow (`form_valid`)

### Step 1: auth guard

Rejects unauthenticated submit with error.

### Step 2: multi-instance branch (optional)

If `condition_fields` and no `condition_model`:

- tries `save_multiple_main_instances`
- returns:
  - success script with created count,
  - form invalid with row-level errors,
  - generic row-required error when no instances produced.

### Step 3: standard single-object save

1. `self.object = form.save(commit=False)`
2. clears file fields flagged as `<field>_clear=true`
3. sets audit fields:
   - edit -> `updated_by`
   - create/duplicate -> `created_by` + `updated_by`
4. sets company from form or active company fallback
5. `save()` + `save_m2m()`
6. optional condition save (`condition_model` pattern)
7. resets `condition_row_count` session
8. success messaging (`created` / `updated` / `duplicated`)

### Step 4: response variants

- `save_and_new` (create only): reload list + auto-open create form
- `detail_url_name` (create only): returns `HX-Redirect` (preserves `section` query param)
- `return_response` if custom response provided
- default: close modal + reload

---

## Error handling

### IntegrityError (duplicate keys)

Parses `"UNIQUE constraint failed"` and tries to:

- identify involved fields,
- attach field-level friendly error (`already exists`),
- fallback to generic duplicate message.

### Other exceptions

- logs with stack,
- adds generic form non-field error,
- returns `form_invalid`.

`form_invalid` re-renders template with errors (currently includes debug `print(form.errors)` in source).

---

## Permission behavior

Provided by `FormViewCommonMixin`:

- superuser bypass,
- auto create permissions: `add_<model>` or `add_own_<model>`,
- auto edit permissions: `change_<model>` or `change_own_<model>` + object ownership,
- override with `permission_required`,
- deny response via `permission_denied_template` (`403.html` modal by default).

---

## Examples

## Example 1: Standard single create/update form

```python
from horilla.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from horilla.utils.decorators import htmx_required, permission_required_or_denied
from horilla.urls import reverse_lazy
from horilla_generics.views.single_form import HorillaSingleFormView
from myapp.forms import TicketSingleForm
from myapp.models import Ticket


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["myapp.view_ticket", "myapp.view_own_ticket"]),
    name="dispatch",
)
class TicketSingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    model = Ticket
    form_class = TicketSingleForm
    full_width_fields = ["description"]
    form_title = "Ticket"
    save_and_new = True
    detail_url_name = "myapp:ticket_detail"
    form_mode = [
        {
            "title": _("Single-Step Form"),
            "url_name": {
                "create": "myapp:ticket_create_single",
                "edit": "myapp:ticket_edit_single",
            },
            "active": True,
        },
        {
            "title": _("Multi-Step Form"),
            "url_name": {
                "create": "myapp:ticket_create",
                "edit": "myapp:ticket_edit",
            },
            "active": False,
        },
    ]
    view_id = "ticket-single-form"
```

Route:

```python
path("ticket/create-single/", views.TicketSingleFormView.as_view(), name="ticket_create_single")
path("ticket/edit-single/<int:pk>/", views.TicketSingleFormView.as_view(), name="ticket_edit_single")
```

Duplicate URL usage:

```text
/ticket/edit-single/42/?duplicate=true
```

---

## Example 2: Condition model pattern (rule builder)

```python
class AutomationRuleFormView(LoginRequiredMixin, HorillaSingleFormView):
    model = AutomationRule
    form_class = AutomationRuleForm
    condition_fields = ["field", "operator", "value", "logical_operator"]
    condition_model = AutomationCondition
    condition_related_name = "conditions"
    condition_field_title = "Conditions"
    condition_hx_include = "#rule-form"
```

Behavior:

- main `AutomationRule` saved once,
- existing conditions replaced with submitted rows via `save_conditions`.

---

## Example 3: Multi-instance row creation (no condition model)

```python
class OpportunityTeamMemberCreateView(LoginRequiredMixin, HorillaSingleFormView):
    model = OpportunityTeamMember
    form_class = OpportunityTeamMemberForm
    condition_fields = ["user", "team_role", "opportunity_access_level"]
    condition_model = None

    def check_duplicate_instance(self, row_data, cache, form):
        key = (row_data.get("user"), row_data.get("team_role"))
        if key in cache:
            return "Duplicate team member row."
        return None

    def update_unique_check_cache(self, row_data, cache, instance):
        cache.add((row_data.get("user"), row_data.get("team_role")))
```

Behavior:

- one submitted condition row -> one main model instance,
- useful for "add multiple members in one submit" workflows.

---

## Example 4: HTMX open and submit

```html
<button
  hx-get="{% url 'myapp:ticket_create_single' %}"
  hx-target="#modalBox"
  hx-swap="innerHTML"
  onclick="openModal()">
  Add Ticket
</button>
```

Form submission uses `hx_attrs` generated by context:

- `hx-post=<form_url + current query>`
- `hx-target=#<view_id>-container`
- `hx-swap=outerHTML`
- multipart enabled for file upload.

---

---

## Example 5: `@cached_property` form_url (create vs. update routing)

Used in activity views (`CallCreateForm`, `EventCreateForm`, `MeetingsCreateForm`) to avoid a conditional on every request:

```python
from functools import cached_property
from horilla.urls import reverse_lazy

class CallCreateForm(ActivityOwnerPermissionMixin, LoginRequiredMixin, HorillaSingleFormView):
    model = Activity
    form_class = LogCallForm

    @cached_property
    def form_url(self):
        if self.kwargs.get("pk"):
            return reverse_lazy("activity:call_update_form", kwargs={"pk": self.kwargs["pk"]})
        return reverse_lazy("activity:call_create_form")
```

The property is computed once per request cycle and cached — safe because `self.kwargs` is set before any attribute access during dispatch.

---

## Example 6: Conditional field toggle via dedicated POST endpoint

`MeetingsCreateForm` re-renders the form in-place when `is_online` is toggled, without saving:

```python
class MeetingsCreateForm(ActivityOwnerPermissionMixin, LoginRequiredMixin, HorillaSingleFormView):
    model = Activity
    form_class = MeetingsForm
    _toggle_field = "is_online"

    def post(self, request, *args, **kwargs):
        if request.POST.get("_toggle_field") == self._toggle_field:
            # Re-render form with toggled state — does NOT save
            form = self.get_form()
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)
```

Template wires the toggle as a standard HTMX form submit with the hidden `_toggle_field` input.

---

## Example 7: Feature-flag mixin blocking access

`TeamSellingRequiredMixin` (in `opportunity_team.py`) gates entire view trees behind a feature flag:

```python
class TeamSellingRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not team_selling_is_enabled():
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("opportunities:team_selling_setup")
                return response
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)
```

HTMX requests get a 204 + `HX-Redirect` header so the browser navigates without a full reload. Non-HTMX requests receive a 403.

---

## Example 8: Multi-instance creation with duplicate check

`OpportunityTeamMemberCreateView` uses condition rows to create multiple members in one submit:

```python
class OpportunityTeamMemberCreateView(LoginRequiredMixin, HorillaSingleFormView):
    model = OpportunityTeamMember
    form_class = OpportunityTeamMemberForm
    condition_fields = ["user", "team_role", "opportunity_access_level"]
    condition_model = None  # each row → one new instance

    def check_duplicate_instance(self, row_data, unique_check_cache, form):
        key = (row_data.get("user"), row_data.get("team"))
        if key in unique_check_cache:
            return _("This user is already a member of the team.")
        return None

    def update_unique_check_cache(self, row_data, unique_check_cache, instance):
        unique_check_cache.add((row_data.get("user"), row_data.get("team")))
```

Each non-empty condition row produces one `OpportunityTeamMember` instance; duplicates within the same submit are caught by `check_duplicate_instance`.

---

## Related files

| File | Role |
|------|------|
| `horilla_generics/views/toolkit/form_mixin.py` | permission/object/dynamic-create shared logic |
| `horilla_generics/views/toolkit/single_form_builder.py` | dynamic form generation + condition helpers |
| `horilla_generics/templates/single_form_view.html` | rendering template |
| `horilla_generics/views/multi_form.py` | wizard alternative using same mixin patterns |

---

## Summary

`HorillaSingleFormView` is the generic high-flexibility form endpoint for modal and inline create/update flows. It handles not just ordinary model saves but also duplicate mode, condition-row builders, multi-instance creation, and HTMX-specific success routing with minimal subclass code.

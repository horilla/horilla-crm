# Lead Assignment Rules (`horilla_crm.leads.views.assignment_rule`)

## What this module does

Defines class-based views for managing **lead assignment rules** — configurable rules that automatically assign incoming leads to users or roles based on matching conditions.

Only one rule of a company is active at a time. `LeadAssignmentRule.save()` deactivates the company's other active rules when the saved rule is active (`update()`, so those rules do not save again). Turning a rule on from the list does the same.

---

## View inventory

| View | Base | Purpose |
|------|------|---------|
| `LeadsAssignmentView` | `HorillaView` | Main shell — [settings list shell](../../horilla/contrib/core/settings_list_shell.md) |
| `LeadAssignmentNavbar` | `HorillaNavView` | Navigation bar with "Create Rule" action button |
| `LeadAssignmentListView` | `HorillaListView` | Rule list with edit/delete column actions |
| `LeadAssignmentActivateView` | `View` | HTMX POST — toggles `is_active` on a rule |
| `LeadAssignmentForm` | `HorillaSingleFormView` | Create/update a single assignment rule |
| `LeadAssignmentDelete` | `HorillaSingleDeleteView` | Delete an assignment rule |
| `AssignmentRuleDetailView` | `DetailView` | Detail page showing rule + its conditions list |
| `AssignmentRuleDetailNavbar` | `HorillaNavView` | Navbar for the detail page |
| `AssignmentConditionFormView` | `HorillaSingleFormView` | Create/update a single condition row tied to a rule |
| `ToggleAssignToFieldView` | `TemplateView` | HTMX partial — swaps between `assign_to_users` and `assign_to_roles` widgets |
| `ToggleNotifyMethodFieldView` | `TemplateView` | HTMX partial — swaps between mail template and notification template widgets |
| `AssignmentConditionDeleteView` | `HorillaSingleDeleteView` | Delete one condition; triggers HTMX refresh on the detail page |

---

## Key patterns

### Conditional field toggling

`ToggleAssignToFieldView` and `ToggleNotifyMethodFieldView` are lightweight `TemplateView` endpoints that return only a field partial. The form calls them via HTMX when the user changes the assignment type or notification method, swapping the visible field without re-rendering the full modal.

### Assignment method

When a condition can assign to several people (a role with many users, or several selected users), its **Assignment Method** decides who gets the lead:

| Method | Value | Who gets the lead |
|--------|-------|-------------------|
| Least Lead Count (default) | `least_leads` | the person who owns the fewest leads; ties go to the lowest user id |
| Round Robin | `round_robin` | each person in turn, in user id order, wrapping back to the first |

- Stored on `LeadAssignmentCondition.assignment_method`. Each condition has its own rotation, kept in `last_assigned_user` (the person who got its last lead; not editable in the form). The pointer is a user id, so people joining, leaving or being deactivated never break the rotation; if the pointer user is deleted the rotation restarts from the lowest id.
- Conditions that existed before the option was added keep `least_leads`, so nothing changes for them.
- **Engine** (`apply_assignment_rules`): `pick_for_condition(..., advance=True)` takes the next turn under a row lock, so leads created at the same time get different people.
- **Form** ("Assign using rules"): the owner box only *previews* the next person; the turn is taken after the lead is saved (`advance_rotation`), for the person actually chosen, so choosing someone else means the rotation continues from them.
- On the lead form, ticking "Assign using rules" always pre-selects the person the condition's method suggests (the next in turn, or the one with the fewest leads), even when the form arrives with an owner (for example Duplicate, which copies the source lead's owner). The suggestion is re-selected on each preview, and the user can still pick anyone from the list before saving.
- Round robin ignores how many leads someone already owns; use Least Lead Count to balance workload.
- After updating, run `python manage.py makemigrations leads` and `python manage.py migrate` (adds the two columns; existing rows get the default).

### Mail configuration popup

`ToggleNotifyMethodFieldView` also checks the mail setup. When **Notify as Email** or **Both** is picked and no active outgoing mail configuration exists (`HorillaMailConfiguration`, `mail_channel="outgoing"`, `is_active=True`), the partial returned to the form carries `lead_assignment_rule/mail_config_popup.html`, the same "Mail Configuration Required" popup the cadence email follow-up uses, with a **Configure** button to the mail server page. Email is not kept: the select goes back to empty (or to *Notify as Notification* when *Both* was picked) and the mail template field stays hidden. Saving is still checked by `LeadAssignmentCondition.clean()`.

### Rule pre-fill in condition form

`AssignmentConditionFormView` reads `rule_pk` from GET params and pre-fills the `rule` FK in the form's initial data. This allows opening the condition form directly from the rule detail page without manual input.

### Dynamic `model_name` initialisation

The condition form resolves field choices based on the parent rule's target model. `AssignmentConditionFormView.get_initial()` extracts `model_name` from the rule instance and injects it into form initial so field selector widgets load the correct column list.

### Missing object handling

- **HTMX requests** on a missing object → **`RefreshResponse`** (`horilla.web`) — HTMX-aware partial refresh.
- **Non-HTMX requests** on a missing object → **`HttpNotFound`** (`horilla.web`) — standard 404 page.

### Condition delete refresh

`AssignmentConditionDeleteView.delete()` returns an HTMX response that triggers a reload of the conditions list partial, keeping the detail page reactive.

### Matching against Lead custom fields

A `LeadAssignmentMatchCriteria.field` isn't limited to real `Lead` model columns — it can also be a synthetic `cf_<id>` field for a user-defined custom field (the `custom_fields` app). This is not special-cased here or in `horilla_crm.leads.models.assignment_rules`/`horilla_crm.leads.signals`; all three go through the generic **condition-field extension registry** in [`condition_fields.py`](../../horilla/contrib/generics/forms/condition_fields.md#condition-field-extension-registry), so this app never imports `custom_fields` directly:

- **Field dropdown** — `get_model_field_choices()` (used to build `condition_field_choices["field"]`) appends any `cf_<id>` choices contributed by a registered extension.
- **Value widget/operators** — `condition_widget.py` renders the appropriate input (e.g. a `select` for a Choice-type custom field) via `get_condition_field_widget_info()`; see [condition_widget.md](../../horilla/contrib/generics/views/helpers/condition_widget.md#synthetic-non-model-fields).
- **Display** — `LeadAssignmentMatchCriteria.get_field_label()` uses `get_condition_field_label()` for the "Field" column instead of `Lead._meta.get_field(...).verbose_name`.
- **Evaluation** — `horilla_crm.leads.signals._eval_single_criterion()` uses `get_condition_field_value(field, lead)` instead of `getattr(lead, field)` whenever `get_condition_field_extension(field)` returns an owner; `None` means "can't resolve, treat as no match", matching how an unknown real field is handled. The operator semantics themselves (`exact`, `icontains`, `between`, …) live in `horilla_crm.leads.assignment.evaluation.compare()`, which this function and the lead forms both call.

> `_eval_single_criterion` must stay a module-level function of `horilla_crm.leads.signals`: `custom_fields` wraps it by that dotted path (`CustomFieldDateLeadAssignmentExtension`) to evaluate custom Date / Date and Time criteria by value.

### Create vs edit: custom fields and `post_save` timing

Assignment rules run from Lead's `post_save` signal (for newly created leads only) via `transaction.on_commit()`. Custom field values are written by `form.save_m2m()`, which the create/edit views call **after** `instance.save()`.

Outside an atomic block, Django runs `on_commit` callbacks immediately, so a rule keyed on a custom field used to evaluate against an empty value on **create** (before `save_m2m`). On **edit**, the prior save's custom field row already existed, so the same rule appeared to work only on edit.

`LeadFormView` and `LeadsSingleFormView` (`horilla_crm/leads/views/lead_actions.py`) decorate `form_valid` with `transaction.atomic` so the signal's `on_commit` callback is deferred until after `save_m2m()` completes — create and edit then see the same custom field values.

### "Assign using rules" on the lead create forms

When at least one **active** rule has a condition, the lead **create** forms (single-step `LeadSingleForm`, multi-step `LeadFormClass`, and Custom Layout, which renders the single-step form) show an **Assign using rules** checkbox directly below the **Owner** field. It is never shown on edit.

| Checkbox | Owner field | On save |
|--------|-------------|---------|
| unticked | normal (ajax select) | the owner picked in the form is saved, then the post-save engine runs as it always did and may re-assign by rule |
| ticked, a condition matches | limited to the people that condition can assign to (role members *or* the selected users), the person the condition's **Assignment Method** picks pre-selected | the chosen person owns the lead; the engine does **not** pick again, only the condition's notifications are sent |
| ticked, no condition matches | normal field plus a notice | rejected with *"The lead does not satisfy any active assignment rule (…). Change the values or untick "Assign using rules"."* |

Pieces (all inside the leads app; nothing under `horilla/` is changed and no form/view extension is used):

| Piece | Role |
|-------|------|
| `horilla_crm/leads/assignment/evaluation.py` | `compare`/`normalise` (shared operator semantics) and a three-valued (`YES`/`NO`/`UNKNOWN`) evaluation of conditions against a plain dict such as `cleaned_data` |
| `horilla_crm/leads/assignment/pool.py` | `active_conditions`, `condition_users`, `pick_least_loaded`, `pick_round_robin`, `pick_for_condition`, `advance_rotation` (the same functions the engine uses) and `resolve_for_data` ("first matching condition with someone to assign to wins") |
| `horilla_crm/leads/assignment/notify.py` | the email / in-app notification senders, plus `notify_assignment` for the form path |
| `horilla_crm/leads/form_mixins.py` | `LeadAssignmentRuleFormMixin`, the **outermost** base of both lead forms (it must come after `OwnerQuerysetMixin.__init__` has set the owner queryset) |
| `horilla_crm/leads/views/assignment_rule_form.py` | `LeadAssignmentOwnerView` (`leads:assignment_rule_owner`): redraws the Owner box (field and checkbox) when the checkbox is toggled, or a field the rules look at changes while it is ticked |

How it works:

- **Checking** happens in the form's `clean()` and is authoritative. While the form is bound with the checkbox ticked, the owner queryset is the union of every condition's people (so the generic owner check passes); `clean()` then resolves the real condition from `cleaned_data`, requires the owner to be in its pool and records the decision. `lead_owner` is added to `_unrestricted_fields` only in this mode, because the people of a rule can be assigned whatever the user's own owner permissions are.
- **Pool widget**: a static `<select>` listing the people (each once, no group headings). The ajax select the owner normally uses is not used here: it would reload every user and ignore the restriction.
- **Checkbox**: it is drawn by the Owner widget (so it is always under the owner, also in Form Layout); the `apply_assignment_rule` form field only reads its value (a hidden-type widget that renders nothing), which lets the wizard keep it between steps.
- **Swap**: the checkbox carries `hx-get`, `hx-include` (the owner plus the fields the rules use), `hx-trigger` and `hx-target="div:has(> #id_lead_owner)"` with `innerHTML` swap, so the old select2 container is replaced together with its select. The endpoint takes the form class from a whitelist (`mode=single|multi`), never from the request.
- **Unknown values**: in the preview, and on intermediate wizard steps, a value that is not entered yet is `UNKNOWN`, never "no". A condition is only ruled out when a known value contradicts it, so the wizard can show the "does not satisfy" message early; the final step judges the whole lead.
- **Multi-step**: the checkbox is drawn under Owner on step 1 and is deliberately **not** listed in `step_fields` (the wizard's `clean()` looks every listed name up on the model). The wizard only resets *model* checkboxes when they are missing from a POST, so `LeadFormView.get_form_kwargs` stores `False` when step 1 is posted without the checkbox.
- **Signal**: `handle_lead_assignment` only runs for newly created leads. The form sets `_assignment_condition_id` on the instance when the decision was made in the form; the handler then skips the engine and calls `notify_assignment`. Every other creation path (import, API, web-to-lead, booking, email-to-lead) runs the engine as before.
- **Audit trail**: how the owner was chosen is stored in the existing `Lead.additional_info` JSON field (no model change):

```json
{"assignment": {"rule_id": 3, "rule_name": "Website leads", "condition_id": 5,
                "assigned_user_id": 12, "via": "form", "assigned_at": "2026-05-01T09:30:00+00:00"}}
```

  `via` is `"form"` (checkbox ticked) or `"auto"` (engine). Only the latest assignment is kept. Query with `Lead.objects.filter(additional_info__assignment__rule_id=3)`. A lead whose owner was picked by hand has no `assignment` key.

Limitations:

- Sub-roles of a role target are not expanded (same as the engine).
- Custom Date / Date and Time criteria that use `gt`/`lt`/`between` or the relative operators are evaluated by value by `custom_fields` for the engine, which needs a saved lead. The form compares the submitted values as text, so such a criterion may report "does not satisfy" on the form; untick the checkbox and the engine assigns as before.
- "Least Lead Count" counts every lead the person owns, including converted ones (parity with the engine).
- **Assign To** users and roles on a condition are limited to the active company. `AssignmentRuleConditionForm` uses `OwnerQuerysetMixin`, the same scoping as the other CRM user and role fields, including the filter next to those fields.

---

## Tests

Lead tests live in the package `horilla_crm/leads/tests/` (empty `__init__.py`; Django discovers `test*.py` modules — do not re-export them from `__init__`):

| Module | Covers |
|--------|--------|
| `tests/tests.py` | Web-to-lead parsing/RTL, feature registration, field requirements |
| `tests/test_form_layouts.py` | Form-layout opt-in and Lead create/edit/duplicate (skips if app missing) |
| `tests/test_history_rtl.py` | History tab RTL / Shamsi overlays |
| `tests/test_assignment_rule_timing.py` | Custom-field assignment on create: `TransactionTestCase` POST that asserts owner assignment when the rule matches a custom field (uses real commits so `on_commit` runs inside the request, unlike `TestCase`) |
| `tests/test_assignment_on_forms.py` | "Assign using rules": operator table, three-valued evaluation, pools and least-loaded pick, single-step and multi-step forms, the owner preview endpoint, saving through the views (checkbox ticked/unticked, engine, notifications, audit trail) and Form Layout |

```bash
python manage.py test horilla_crm.leads.tests
python manage.py test horilla_crm.leads.tests.test_assignment_rule_timing
python manage.py test horilla_crm.leads.tests.test_assignment_on_forms
```

---

## URL names (reference)

All URLs are namespaced under `leads:`.

| Name | Pattern | View |
|------|---------|------|
| `leads:assignment_rule_owner` | `lead-assignment-owner/` | `LeadAssignmentOwnerView` (Owner box redraw for the lead create forms) |
| `leads:assignment_rule_view` | `assignment-rules/` | `LeadsAssignmentView` |
| `leads:assignment_rule_list` | `assignment-rules/list/` | `LeadAssignmentListView` |
| `leads:assignment_rule_form` | `assignment-rules/form/` | `LeadAssignmentForm` |
| `leads:assignment_rule_form` | `assignment-rules/form/<int:pk>/` | `LeadAssignmentForm` (update) |
| `leads:assignment_rule_delete` | `assignment-rules/delete/<int:pk>/` | `LeadAssignmentDelete` |
| `leads:assignment_rule_detail` | `assignment-rules/detail/<int:pk>/` | `AssignmentRuleDetailView` |
| `leads:assignment_condition_form` | `assignment-conditions/form/` | `AssignmentConditionFormView` |
| `leads:assignment_condition_delete` | `assignment-conditions/delete/<int:pk>/` | `AssignmentConditionDeleteView` |

---

## Related documentation

- [Lead stages](lead_stages.md)
- Lead create/edit views (`LeadFormView` / `LeadsSingleFormView`): `horilla_crm/leads/views/lead_actions.py`
- `HorillaSingleFormView`: [../../horilla/contrib/generics/views/single_form.md](../../horilla/contrib/generics/views/single_form.md)
- `HorillaMultiStepFormView`: [../../horilla/contrib/generics/views/multi_form.md](../../horilla/contrib/generics/views/multi_form.md)
- `HorillaListView`: [../../horilla/contrib/generics/views/list.md](../../horilla/contrib/generics/views/list.md)
- Permission model (four layers): [../../horilla/contrib/generics/mixins.md](../../horilla/contrib/generics/mixins.md)
- Condition-field extension registry (custom-field matching): [../../horilla/contrib/generics/forms/condition_fields.md](../../horilla/contrib/generics/forms/condition_fields.md#condition-field-extension-registry)
- Condition value widgets: [../../horilla/contrib/generics/views/helpers/condition_widget.md](../../horilla/contrib/generics/views/helpers/condition_widget.md)

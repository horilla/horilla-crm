# Forecast Targets (`horilla_crm.forecast.views.forecast_target`)

## What this module does

Manages **ForecastTarget** records — per-user, per-period targets against a forecast type (e.g. revenue, deal count). The form asks **Set Target For** once: **User**, **Role**, or **Role Hierarchy**. A role target is one total split among the people in that role. The older "same" checkboxes and the role switch stay in the form as hidden state; the page does not show them.

---

## View inventory

| View | Base | Purpose |
|------|------|---------|
| `ForecastTargetView` | `HorillaView` | Main shell; validates `forecast_type` and `period` query params, redirects on invalid values |
| `ForecastTargetFiltersView` | `TemplateView` | HTMX partial — returns dynamic filter dropdowns for forecast type and period |
| `ForecastTargetNavbar` | `HorillaNavView` | Navigation bar with "Set Target" action |
| `ForecastTargetListView` | `HorillaListView` | Filtered and sortable target list |
| `ForecastTargetFormView` | `HorillaSingleFormView` | Create/update. **Set Target For** chooses user rows or a role split. Overrides `form_fields` in `forecast_target_form.html` |
| `ToggleRoleBasedView` | `View` | HTMX partial — filters user dropdown by selected role |
| `ToggleConditionFieldsView` | `View` | HTMX partial — shows or hides conditional fields based on checkbox state |
| `UpdateTargetHelpTextView` | `View` | HTMX partial — returns updated help text for target field based on `forecast_type` |
| `UpdateForecastTarget` | `HorillaSingleFormView` | Inline quick-update of a single target value |
| `ForecastTargetDeleteView` | `HorillaSingleDeleteView` | Delete a forecast target |

---

## Key patterns

### Parameter validation in main view

`ForecastTargetView.get()` validates `forecast_type` and `period` query params against allowed choices. Invalid values result in a redirect to the default forecast target URL rather than a 400 or an empty page.

### Set Target For

The visible control is one `<select name="set_for">`:

| Value | What it saves |
|-------|----------------|
| `user` | One row per user. **+ Add More** adds a row. |
| `role` | One total, divided across the users in the selected role (`is_whole_role`). |
| `below` | The same total, divided across that role and the roles under it (`include_below`). |

`forecastSetFor()` writes the hidden checkboxes (`is_role_based`, `is_whole_role`, `include_below`, and the "same" flags) and lets the form redraw. A manager can assign targets only to people in roles below their own, and can split only a role below them. Their own target comes from the manager above.

`save_whole_role()` writes one `ForecastTarget` per person in the split. Deleting one of those rows calls `ForecastTarget.get_delete_notice()`, and the generic delete modal shows how the role total will add up afterwards.

### "Same" checkbox column collapsing

The three checkboxes `is_period_same`, `is_target_same`, and `is_forecast_type_same` are still read on save. For a user target they are set together from **Set Target For** (period and type shared, amount per row). When one is on, that column is hidden and `process_row_data_before_create()` copies row 0 onto the other rows.

`ForecastTargetForm` (`Meta.exclude`) omits **`currency`** and **`current_amount`** — those values are derived from the forecast type / runtime totals rather than edited on the target form.

```
is_period_same=True  → all rows get the same period value from row 0
is_target_same=True  → all rows get the same target value from row 0
is_forecast_type_same=True → all rows get the same forecast type from row 0
```

### Role-based user filtering

`ToggleRoleBasedView` filters the `assigned_to` queryset to users belonging to a selected role. Called via HTMX when the role dropdown changes; returns a replacement `<select>` widget for the user field.

`ToggleConditionFieldsView` does the same for a condition row's user column when working inside the bulk-create condition rows.

### Duplicate check

`ForecastTargetFormView.check_duplicate_instance()` blocks creation of a second target with the same `(assigned_to, period, forecast_type)` triple. Caught both within the same submit (via cache) and against the database.

### Session-based condition row count

The number of open condition rows is tracked in `request.session["condition_row_count"]`. `ForecastTargetView` and `ForecastTargetFormView` read and write this key so the form can expand with the right number of rows on re-render.

### Dynamic help text

`UpdateTargetHelpTextView` returns an HTML snippet with context-sensitive help for the target value field (e.g. currency symbol, unit label) based on the selected `forecast_type`. Called via HTMX when the forecast type dropdown changes.

### Empty states (`forecast_target_view.html`)

The main template uses shared [empty-state partials](../../../templates/components/empty_state.md):

| Condition | Partial |
|-----------|---------|
| `not has_company` | `components/empty_states/activate_company.html` |
| No forecast type configured | `components/empty_state.html` with message “No Forecast Type set. Set it from settings.” (CTA button rendered outside the include when permissions allow) |

The forecast dashboard shell (`forecast_view.html`) uses the same `activate_company.html` preset when `request.active_company` is missing.

---

## Bulk creation flow

1. User opens **Set Target**. `ForecastTargetFormView` renders **Set Target For** and, for a user target, one condition row.
2. **User** — add rows with **+ Add More**. Period and forecast type are shared; each row has its own user and amount.
3. **Role** or **Role Hierarchy** — `build_whole_role_context()` lists the people and the share of the total. **+ Add More** stays hidden. Submit calls `save_whole_role()`.
4. A role change still goes through `ToggleRoleBasedView`, which narrows the user list.
5. `check_duplicate_instance()` rejects a second target with the same `(assigned_to, period, forecast_type)`.

On the Forecast page, an expanded period shows a row per role (`build_period_role_rows` in `views/core/helpers.py`, template `forecast_role_row.html`). A role row opens the roles under it and the people in that role. A manager sees their own role and the roles below it, not peers or the roles above. A single role in scope gets no role rows.

---

## Forecast type conditions on fields that aren't model columns

`ForecastCalculator.build_single_condition_query` (`forecast/utils.py`) asks `get_extension_condition_q(Opportunity, field, operator, value)` first; when an extension owns the field (e.g. an Opportunity custom field) the returned `Q` is used, otherwise the operator map filters the model column. The forecast type form lists extension fields through the generic condition builders ([condition_fields.md](../../horilla/contrib/generics/forms/condition_fields.md#conditionfieldprovider-extension-seam)).

---

## Related documentation

- Forecast type tab (period table, trends, charts): [forecast_type_tab.md](forecast_type_tab.md)
- Shared empty-state partials: [../../templates/components/empty_state.md](../../templates/components/empty_state.md)
- `HorillaSingleFormView` multi-instance pattern: [../../horilla/contrib/generics/views/single_form.md](../../horilla/contrib/generics/views/single_form.md)
- `HorillaListView`: [../../horilla/contrib/generics/views/list.md](../../horilla/contrib/generics/views/list.md)

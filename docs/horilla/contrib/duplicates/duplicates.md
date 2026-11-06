# Horilla Clone Management (Duplicates) — deep dive (`horilla.contrib.duplicates`)

## What this app does

- **MatchingRule** / **MatchingRuleCriteria** — declarative “how to compare two records” (fields, fuzzy options) for duplicate detection.
- **DuplicateRule** / **DuplicateRuleCondition** — when to run detection, thresholds, and which models merge together.
- **`view_extensions.py`** registers `ViewExtension`s (`_inherit_view`) on shared generics base classes so duplicate checks run on **create/update** flows and a **Potential Duplicates** tab appears on **detail** views; **UpdateAllFieldsView** (bulk Edit Details) also warns via `check_before_save` before commit.

---

## App startup (`apps.py`)

`DuplicatesConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `duplicates/` |
| `url_module` | `horilla.contrib.duplicates.urls` |
| `auto_import_modules` | `menu`, `registration`, **`view_extensions`** |

`app_name` in `urls.py` is **`duplicates`**. App config does not set `url_namespace` explicitly; URL reversing uses `duplicates:` from `urls.py`.

---

## Menu (`menu.py`)

Registers settings or admin entries for **Matching rules** and **Duplicate rules** list views (`matching_rule_view`, `duplicate_rule_view`, etc.). Icons and permissions are defined alongside each item.

---

## Feature registration (`registration.py`)

```text
register_feature("duplicate_data", "duplicate_models", auto_register_all=False)
```

Models registered under **`duplicate_models`** participate in duplicate detection and merge UIs.

---

## Cross-app integration (`view_extensions.py`)

Registered at import when **`view_extensions`** is auto-imported. Each is a real `ViewExtension` (`_inherit_view` — see [extension index](../../extension/inherit.md)), not a monkey-patch: `HorillaSingleFormView`, `HorillaMultiStepFormView`, and `HorillaDetailTabView` are shared base classes every concrete view across every app inherits, so a registration on the base applies to every concrete subclass automatically via `resolve_view_class()`'s base-class MRO fallback (see [extension index — Targeting a shared base class](../../extension/inherit.md#targeting-a-shared-base-class)).

| Extension | Target | Effect |
|-----------|--------|--------|
| `DuplicateCheckSingleFormExtension` | `HorillaSingleFormView` (base) | Overrides `form_valid` to run duplicate detection before redirect. |
| `DuplicateCheckMultiStepFormExtension` | `HorillaMultiStepFormView` (base) | Same, for the final step of a wizard form. |
| `DuplicateTabExtension` | `HorillaDetailTabView` (base) | Overrides `_prepare_detail_tabs` to append the **Potential Duplicates** tab. |
| `DuplicateCheckBulkEditExtension` | `UpdateAllFieldsView` (concrete) | Overrides `check_before_save` to block commit and re-render Edit Details / refresh the duplicates tab when matches are found. |

Each override calls a real zero-arg `super()` to reach "the rest of the chain" (the next-highest-priority extension on the same base, or the real target method) — the actual duplicate-checking logic is unchanged, in `form_integration.py`'s `create_*_with_duplicate_check` factory functions. `DuplicateTabExtension` and `horilla.contrib.cadences`'s `CadenceTabExtension` both target `HorillaDetailTabView` and compose together correctly.

---

## Models — roles

### `MatchingRule` / `MatchingRuleCriteria`

- Defines **similarity** logic (exact, fuzzy, concatenated fields).
- Criteria rows are ordered; evaluation code lives in duplicate engine modules (see `methods.py` / services next to views).

### `DuplicateRule` / `DuplicateRuleCondition`

- Business rules: which model, auto-merge vs suggest, minimum score, etc.
- Conditions narrow **when** the rule runs (same pattern as automations/cadences).

All extend **`HorillaCoreModel`** — company-scoped.

---

## Forms (`forms.py`)

Both rule forms use **`HorillaModelForm`** with **`fields = "__all__"`** and explicit **`field_order`** (model has no extra columns beyond those lists). Criteria rows use **`condition_fields`** on the views, not extra model fields on these forms.

### `MatchingRuleForm`

- **`field_order`**: `name`, `content_type`, `description`
- **Conditions**: `MatchingRuleCriteria` — `field_name`, `matching_method`, `match_blank_fields` (dynamic choices in **`__init__`**)
- **`clean()`**: requires at least one valid criterion row; no duplicate `field_name` across rows

### `DuplicateRuleForm`

- **`field_order`**: `name`, `content_type`, `description`, `matching_rule`, `action_on_create`, `action_on_edit`, `alert_title`, `alert_message`, `show_duplicate_records`
- **`__init__`**: HTMX on `content_type` filters `matching_rule` queryset; **`clean()`** enforces matching rule / content type alignment

---

## Typical flows

1. Admin defines a **matching rule** for Lead email + phone.
2. User creates a lead via **HorillaSingleFormView** → `DuplicateCheckSingleFormExtension.form_valid` runs → modal warns if high-confidence duplicate exists.
3. User opens lead detail → **Potential Duplicates** tab lists side-by-side candidates → merge action uses rule configuration.

---

## Empty states (v1.13.8)

Matching rules accordion and potential-duplicates list use [empty_state.html](../../../templates/components/empty_state.md) instead of inline SVG blocks:

| Template | Message |
|----------|---------|
| `matching_rule_accordion.html` | “Nothing to show yet. Please add your Matching Rules.” |
| `potential_duplicates_list_view.html` | “No potential duplicates found.” |

---

## Rule conditions on fields that aren't model columns

`duplicate_checker.evaluate_rule_conditions` reads a condition's value from the field's owning extension (`get_condition_field_extension` / `get_condition_field_value` in [condition_fields.md](../generics/forms/condition_fields.md#conditionfieldprovider-extension-seam)) when one owns the field, and from the instance attribute otherwise. A path such as `owner__department` uses the shared related-field registry (the user's department, role and company) and is compared on the related record.

---

## Related documentation

- Generics forms and detail tabs: [../generics/views/single_form.md](../generics/views/single_form.md), [../generics/views/detail_tabs.md](../generics/views/detail_tabs.md)
- Core content types: [../core/models.md](../core/models.md)
- Empty-state partials: [../../../templates/components/empty_state.md](../../../templates/components/empty_state.md)

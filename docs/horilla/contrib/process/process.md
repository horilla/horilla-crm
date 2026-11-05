# Horilla Process apps — deep dive (`horilla.contrib.process.*`)

Parent package **`horilla.contrib.process`** bundles two independent Django apps that share no single `AppLauncher`—each has its own `apps.py`, migrations, and URL namespace.

---

## Approvals (`horilla.contrib.process.approvals`)

### Purpose

Generic **multi-step approval** engine: rules bind to any model registered under the **`approval_models`** feature, with steps, approvers, conditions, running **instances**, and immutable **decisions**.

### `ApprovalsConfig`

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.process.approvals` |
| `label` | `approvals` |
| `url_prefix` | `approvals/` |
| `url_namespace` | `approvals` |
| `auto_import_modules` | `registration`, `signals`, `menu` |

### Feature registration (`registration.py`)

```text
register_feature("approvals", "approval_models", auto_register_all=False)
```

`auto_register_all=False` means **opt-in only**—each business app must register eligible models; nothing is auto-approved globally.

### Model stack (summary)

| Model | Role |
|-------|------|
| `ApprovalRule` | Template: which `ContentType`, trigger events, active flag. |
| `ApprovalProcessRule` | Links rules into ordered processes. |
| `ApprovalStep` | Approver role/user, ordering, SLA hints. |
| `ApprovalCondition` | Field-level gating before a step fires. |
| `ApprovalInstance` | Live state machine row for one target object. |
| `ApprovalDecision` | Who approved/rejected, timestamps, comments. |

### UX integration

- Detail views may embed approval status via generics tabs or partials (`templates/` under approvals).
- Menu entries open approval job queues for managers.
- Approval job and history details open through **`approval_detail_page.html`**, which loads the detail fragment over HTMX on direct page loads.
- List views that hide rows with a pending approval instance cast object ids consistently when excluding pending PKs (avoids type-mismatch misses between `str`/`int` id sets).
- **`ApprovalListVisibilityExtension`** (`MixinExtension` on list views) replaces earlier monkey patches for pending-approval row visibility; **`ApprovalGuardBulkEditExtension`** (`_inherit_view` on `UpdateAllFieldsView`) blocks bulk Edit Details when an approval guard raises.
- **`ApprovalDetailVisibilityExtension`** (`MixinExtension` on `HorillaDetailView.dispatch`) blocks the detail view while a record has an active **pending** approval. The user is sent back to the list with a message. The pending approver is not exempt from that block; they act from the Approvals screen, and can use Edit Details without the change permission. Rejected records stay hidden from lists and are not blocked on the detail view by this extension.
- Approval and review details show condition values with `get_condition_value_display`.

---

## Review Process (`horilla.contrib.process.reviews`)

### Purpose

Structured **review cycles** (360 / performance-style) with configurable rules, participants, and **jobs** tracking progress.

### `ReviewProcessConfig`

| Setting | Value |
|---------|--------|
| `name` | `horilla.contrib.process.reviews` |
| `label` | `reviews` |
| `url_prefix` | `review-process/` |
| `url_namespace` | `reviews` |
| `auto_import_modules` | `registration`, `signals`, `menu` |

### Model stack (summary)

| Model | Role |
|-------|------|
| `ReviewProcess` | Definition: frequency, anonymity, rating scales. |
| `ReviewCondition` / `ReviewRule` / `ReviewRuleCondition` | Eligibility and scoring matrix. |
| `ReviewJob` | Concrete assignment batch per employee/period. |

### Global `post_save` handler (`signals.py`)

`reviews_post_save_handler` is connected once at import time. It checks `FEATURE_REGISTRY` at **dispatch** time (not at `ready()`), because target apps register review-enabled models after the reviews app starts. Per-model connections at startup would miss late-registered models.

### List visibility

**`ReviewListVisibilityExtension`** (`MixinExtension`) replaces earlier monkey patches that hid or filtered review-related list rows.

---

## Cross-cutting concerns

- Both apps rely on **`HorillaContentType`** for polymorphic links—see [../core/models.md](../core/models.md).
- Permissions follow standard `AppLauncher` + `register_model_for_feature` patterns in each app’s `registration.py` (read files for exact model lists).

---

## Conditions on fields that aren't model columns

`approvals.utils.evaluate_condition` and `reviews.utils.evaluate_condition` call `evaluate_extension_condition` first: when an extension owns the condition's field (e.g. a user-defined custom field) the value is compared as text with the engine's own `_compare_string_operator`; otherwise the model field is read as before. Paths such as `owner__department` are read on the related record. The review-process condition dropdown (`single_form_builder`) and the approval rule dropdown use the extension field choices and the shared related-field list (department, role, company) plus audit fields, from [condition_fields.md](../generics/forms/condition_fields.md#related-user-fields-audit-fields-and-row-values).

---

## Related documentation

- Generics detail tabs embedding process widgets: [../generics/views/detail_tabs.md](../generics/views/detail_tabs.md)
- Permission registry concepts: [../core/Registry/permission_registry.md](../core/Registry/permission_registry.md)

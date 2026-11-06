# Horilla Workflow app — deep dive (`horilla.contrib.workflow`)

## What this app does

- **`WorkflowRule`** — module (`HorillaContentType`), name, description, triggers on create/edit, active flag.
- **`WorkflowCondition`** — criteria rows (field / operator / value / logical operator).
- **`WorkflowAction`** / **`WorkflowTimeTriggerAction`** — actions on match (update field, task, email, notification, or a registered delivery channel such as SMS) with JSON **`action_config`** built from hidden compose fields. See [Actions and delivery channels](#actions-and-delivery-channels).
- Runs on record create/edit for models registered under the workflow feature registry (core models such as users, departments, and holidays, plus any app that calls `register_model_for_feature` with workflow enabled).

**Owner resolution for `assign_task` actions** tries common owner FK names in order: `owner`, `assigned_to`, `created_by`, then `lead_owner` for legacy CRM models.

---

## Actions and delivery channels

`action_type` on `WorkflowAction` and `WorkflowTimeTriggerAction` is a plain `CharField` (`max_length=50`, the longest delivery channel key) with no fixed `choices` (migration `0005`; stored values are unchanged). It holds **one key**:

| `action_type` | Run by | `action_config` |
|---------------|--------|-----------------|
| `update_field` | `_execute_update_field` | `{field, value}` |
| `assign_task` | `_execute_assign_task` | `{title, due_basis, due_in_days, status, priority, description}` |
| `email` | `_execute_email` | `{template_id, to, also_send_to}` |
| `notification` | `_execute_notification` | `{template_id, to, also_notify_to, custom_message}` |
| any other key, e.g. `sms` | the channel registered under that key in [`horilla.registry.delivery`](../automations/automations.md#delivery-channels-horillaregistrydelivery) | `{template_id, to, also_send_to}` |

`action_types.py` builds the list: `get_action_type_choices(company)` is the four built-ins, then `get_delivery_channels(company)` in registry order. The `mail` and `notification` channels are left out because the `email` and `notification` built-ins already send them, so nothing is listed twice. `get_action_channel(key)` returns the channel for a channel key (and `None` for a built-in or a key no app registers); `WorkflowAction.get_action_type_display()` shows the built-in's or the channel's label, or the key itself when the channel's app is gone.

**One action, one channel.** `action_type` is a single channel key, never a generic `"channel"` value or a comma-separated list. A workflow that must mail and then send an SMS has two actions, `email` then `sms`, in `order`. Mail and notifications still do not define combinations.

**Execution.** `execute_workflow_rule()` and the Celery task `execute_workflow_time_trigger()` both call `methods.execute_action(action, instance, user)`. A built-in runs its executor from `BUILTIN_EXECUTORS`; any other key is looked up with `get_action_channel()` and sent by `_execute_channel()`, so a new provider needs no new `elif`:

1. `template_id` is a `NotificationTemplate` when the channel's `shows_notification_fields()` is true, else a `HorillaMailTemplate` when `shows_mail_fields()` is true, else not used. Only a template of the action's company (or of no company) is used; a channel that needs a template and has none is logged and skipped.
2. `channel.resolve_recipients(to, instance, user)` reads `to` (`self`, `instance.<field>`, or a typed address) for the channel's own address kind, then `channel.add_also_sent_to(...)` adds the users whose PKs are in `also_send_to`. No recipient: logged and skipped.
3. `channel.send(message, instance, recipients, context, user)`, with the same `context` Automations uses (`instance`, `user`, `self`, `active_company`, `request`). Channels are written against `HorillaAutomation`, so `message` is a `ChannelActionMessage` with the attributes they read: `title` (the rule name), `pk` (the action), `company`, `mail_template`, `notification_template`, `mail_server` (`None`: the mail channel picks the company's outgoing server), `mail_to` (`to`), `created_by` / `updated_by` (the rule's), plus `action` and `rule`.

An `action_type` that is neither a built-in nor registered (the channel's app was removed) is logged and skipped by `execute_workflow_rule()`, and the other actions still run; a time trigger with such a key is marked **failed** with that reason and is not retried. An error raised by one action does not stop the next.

**Forms and views.** `ActionConfigMixin` adds the hidden fields `channel_template_id`, `channel_to` and `channel_also_send_to` and stores them as `{template_id, to, also_send_to}` for a channel action. `clean()` refuses a key that is not a built-in or not available to the rule's company (`is_available(company)`), and a channel action without its template. The action and time-trigger modals list `action_type_choices` from the registry; `WorkflowActionFieldsView` returns the channel block for an offered channel (template list by template kind, **To** from `channel.get_recipient_choices(model)`, **Also send to** users) and nothing for any other key. Editing an action whose channel is no longer offered keeps its key in the picker so it is not changed silently.

**Adding a channel** is the same as for Automations: a `DeliveryChannel` registered from another app's `registration.py`. It appears in Workflow's action list with no change here and no migration.

---

## Forms (`forms.py`)

### `WorkflowRuleForm` (`HorillaModelForm`)

Uses the Horilla 1.10 layout pattern (see [single-step form base](../generics/forms/single_step.md)).

| Setting | Value |
|---------|--------|
| **`field_order`** | `name`, `model`, `description`, `trigger_on_create`, `trigger_on_edit`, `is_active` |
| **`Meta.fields`** | `"__all__"` |
| **`keep_on_form`** | `("is_active",)` |
| **`Meta.exclude`** | None — the model only exposes the fields above plus core audit columns (auto-excluded except `is_active` via `keep_on_form`) |

### Action / condition forms (unchanged layout)

These remain plain **`forms.ModelForm`** + **`ActionConfigMixin`** (not `fields = "__all__"`):

| Class | Model fields on form | Notes |
|-------|----------------------|--------|
| **`WorkflowConditionForm`** | `rule`, `field`, `operator`, `value`, `logical_operator`, `order` | Dynamic `field` choices in **`__init__`** |
| **`WorkflowActionForm`** | `rule`, `action_type`, `order` + hidden action-config fields | Injected in **`__init__`**; `action_type` checked against the built-ins and the delivery channel registry. An `email` action adds a non-field error when no outgoing mail configuration exists, because the template field is hidden and would not show the error |
| **`WorkflowTimeTriggerActionForm`** | delay fields + `action_type`, `order` + hidden config | Date-field choices from view |

---

## Conditions on fields that aren't model columns

`evaluate_workflow_condition` calls `evaluate_extension_condition` first (see [condition_fields.md](../generics/forms/condition_fields.md#conditionfieldprovider-extension-seam)); when an extension owns the field its value is compared as text with the workflow's `_compare_string_operator`, otherwise the model field is read as before. The condition field dropdown comes from the generic condition builders, which include extension fields. Rule detail pages show those values with `get_condition_value_display`.

---

## Related documentation

- Automations (similar condition/action patterns): [../automations/automations.md](../automations/automations.md)
- Form extension API: [../../extension/form_extension.md](../../extension/form_extension.md)
- Generics single-step forms: [../generics/forms/single_step.md](../generics/forms/single_step.md)

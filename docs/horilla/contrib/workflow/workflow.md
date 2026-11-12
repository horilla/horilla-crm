# Horilla Workflow app — deep dive (`horilla.contrib.workflow`)

## What this app does

- **`WorkflowRule`** — module (`HorillaContentType`), name, description, triggers on create/edit (an edit runs the rule only when the record enters its criteria, see [Edits run a rule when the record enters its criteria](#edits-run-a-rule-when-the-record-enters-its-criteria)), active flag.
- **`WorkflowCondition`** — criteria rows (field / operator / value / logical operator).
- **`WorkflowAction`** / **`WorkflowTimeTriggerAction`** — actions on match (update field, task, email, notification, or a registered delivery channel such as SMS) with JSON **`action_config`** built from hidden compose fields. See [Actions and delivery channels](#actions-and-delivery-channels). A time trigger can repeat, see [Repeating time triggers](#repeating-time-triggers).
- Runs on record create/edit for models registered under the workflow feature registry (core models such as users, departments, and holidays, plus any app that calls `register_model_for_feature` with workflow enabled).

**Owner resolution for `assign_task` actions** tries common owner FK names in order: `owner`, `assigned_to`, `created_by`, then `lead_owner` for legacy CRM models.

**Due date of `assign_task` actions** is `due_in_days` after the `due_basis` chosen in the action form, for immediate and time-trigger actions alike (`TASK_DUE_BASIS_FIELDS` in `methods.py`):

| `due_basis` | Counts from |
|-------------|-------------|
| `record_submission_date` (**Record submission date**, the form's default) | the record's `created_at` |
| `record_update_date` (**Record update date**) | the record's `updated_at` |
| `rule_trigger_date`, or no `due_basis` (configs saved before the form had this select) | the moment the action runs |

A record without that field, or with no value in it, counts from the moment the action runs. A plain `date` is taken as midnight of that day.

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

**Time triggers at fire time.** When a rule matches, `_schedule_time_triggers()` stores a `ScheduledWorkflowExecution` (status **pending**) for each active time trigger; `process_scheduled_workflow_executions()` queues the due ones for `execute_workflow_time_trigger()`. Before running the action, that task asks `methods.time_trigger_skip_reason(time_trigger, instance)`, which returns why it must not run or `""`: the rule is inactive, the time trigger is inactive, or the record no longer meets the rule's criteria (`evaluate_workflow_conditions()`, the rule's conditions are its only queries). A skipped execution is marked **skipped** (migration `0006`) with that reason in `error_message` and `executed_at` set, and is not run again even if the record meets the criteria later. A record that no longer exists is still marked **failed**. The time-trigger history modal (`WorkflowTimeTriggerHistoryView`) shows the status and a **Details** column with `error_message`.

**Forms and views.** `ActionConfigMixin` adds the hidden fields `channel_template_id`, `channel_to` and `channel_also_send_to` and stores them as `{template_id, to, also_send_to}` for a channel action. `clean()` refuses a key that is not a built-in or not available to the rule's company (`is_available(company)`), and a channel action without its template. The action and time-trigger modals list `action_type_choices` from the registry; `WorkflowActionFieldsView` returns the channel block for an offered channel (template list by template kind, **To** from `channel.get_recipient_choices(model)`, **Also send to** users) and nothing for any other key. Editing an action whose channel is no longer offered keeps its key in the picker so it is not changed silently.

**Adding a channel** is the same as for Automations: a `DeliveryChannel` registered from another app's `registration.py`. It appears in Workflow's action list with no change here and no migration.

---

## Repeating time triggers

A time trigger can repeat: **Repeat (optional)** in the time-trigger modal sets **Every** `repeat_every_value` `repeat_every_unit` (minutes, hours or days, migration `0007`). Empty, the default and the value of every time trigger saved before, runs once. For example, "1 day after the rule trigger date, create a task for the owner, repeat every 1 day" on a rule with the criteria "Stage is Proposal" creates the task each day while the opportunity stays in that stage.

- **Next run.** When a run of a repeating time trigger completes, `execute_workflow_time_trigger()` calls `methods.schedule_next_repeat(execution)`, which adds the next `ScheduledWorkflowExecution` (status **pending**) one interval after the run's own `scheduled_at`. A worker that runs late does not shift the times. A run that is late by more than one interval (the worker was down) goes to the next time still ahead, so the missed runs are not sent in a burst. The rule page shows "Repeats every …" under the time trigger, and each run is a row of the time-trigger history.
- **A run that fails** (the action raised, for example a provider error) still schedules the next one, so one error does not end the repeat. A run whose action type is no longer a built-in or a registered channel, or whose record no longer exists, schedules nothing.
- **The repeat ends by itself** when a run is skipped (see [Time triggers at fire time](#actions-and-delivery-channels)): the record no longer meets the rule's criteria, or the rule or the time trigger is inactive. A skipped run schedules nothing. With **When Record Is Edited**, an edit that takes the record out of the criteria marks the pending run **skipped** at once (see below), and an edit back into them starts a new repeat from the new entry. Turning the rule or the time trigger back on does not restart a repeat that was skipped; the record must enter the criteria again.
- **One repeat per record.** A record has at most one pending run of a repeating time trigger: when the rule fires again while one is waiting (for example a rule without criteria, run on every edit), `_schedule_time_triggers()` adds no second chain, and `schedule_next_repeat()` adds nothing either.
- **A rule without criteria** repeats while the rule and the time trigger are active.
- Clearing **Every** on a time trigger with a pending run lets that run happen and schedules no more.

**Query cost.** A repeating run adds one `exists()` and one `INSERT` after it completes. Scheduling a repeating time trigger when the rule fires adds one `exists()`. Time triggers that do not repeat add nothing.

---

## Edits run a rule when the record enters its criteria

**When Record Is Edited** runs a rule only when the edit takes the record **into** its entry criteria: the record did not meet them before the save and meets them after it. Before, it ran on every edit whose saved values met the criteria, so a record that stayed in, for example, stage X got the rule's actions and time triggers again each time any field was edited.

| Save | Before | Now |
|------|--------|-----|
| Create, criteria met | runs (if **When Record Is Created**) | runs (if **When Record Is Created**) |
| Edit into the criteria | runs | runs |
| Edit that keeps the record matching | runs | does not run |
| Edit out of the criteria | does not run; pending time triggers still ran when due | does not run; the rule's pending time triggers for the record are marked **skipped** at once |
| Edit back into the criteria | runs | runs again |
| Edit, rule without criteria | runs | runs (unchanged) |

**Behavior change on upgrade.** An existing rule with **When Record Is Edited** and criteria no longer runs on edits that keep the record matching. A rule that must act on every edit can have no criteria: a record cannot enter criteria that do not exist, so such a rule still runs on every edit. No field or migration was added; the rule form is unchanged.

Immediate actions and time-trigger scheduling (`_schedule_time_triggers`) sit behind the same check. An edit that takes the record out of the criteria calls `methods.skip_pending_time_triggers(rule, instance, reason)` (one `UPDATE`), so a record that leaves and comes back before a delay is due gets one run, counted from its new entry, instead of two. Each rule is decided on its own criteria, and criteria still met through another `or` condition are not left.

**How it works.** `signals.remember_workflow_criteria_before_save` (`pre_save`, models in `FEATURE_REGISTRY["workflow_models"]`, not on create, not on `raw` loads, not for saves made by a workflow action) calls `methods.criteria_met_before_save(instance)`. It lists the active rules of the record's model and company (`active_workflow_rules`, the same filter `trigger_workflow_rules` uses) that have **When Record Is Edited** and at least one condition, reads the stored row with `_base_manager`, and returns `{rule pk: criteria met}`. `trigger_workflow_rules_on_save` (`post_save`) passes that to `trigger_workflow_rules(..., met_before=...)` → `execute_workflow_rule(..., met_before=...)`, which returns without running on an update whose rule criteria were already met. A rule missing from `met_before` (no criteria, a stored row that is gone, or a rule turned on between the two signals) counts as not met before, so it runs on a matching edit.

**Query cost.** Each edit of a registered model adds two queries: the table check of `is_running_migrations()` (post-save already runs it) and the rule list. The save guard (`signals._is_workflow_save`) checks the model registry and the re-entrancy set before that table check, so saves of models workflow does not watch, and saves made by a workflow action, query nothing. Only when an edit rule with criteria exists for that model and company are the stored row read (one query) and its criteria evaluated (the same condition queries as the post-save evaluation, per such rule). An edit out of a rule's criteria adds the one `UPDATE` of its pending executions. Saves that change nothing are skipped by `HorillaCoreModel.save` and send no signal. `QuerySet.update()` and bulk operations send no signals and never run workflow rules.

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

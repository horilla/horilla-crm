# `horilla.contrib.workflow` — technical reference

Catalog of every Python module. Each file lists its module variables, functions, and classes. Class sections list attributes and methods.

Inherited `HorillaCoreModel` columns on every concrete model: `id`, `is_active`, `company`, `additional_info`, `created_at`, `updated_at`, `created_by`, `updated_by`.

---

## `__init__.py`

No variables, functions, or classes.

## `templatetags/__init__.py`

No variables, functions, or classes.

---

## `__version__.py`

### Variables

| Name | Value |
| --- | --- |
| `__version__` | `"1.11.9"` |
| `__module_name__` | `_("Workflow")` |
| `__release_date__` | `""` |
| `__description__` | Lazy string: record-triggered rules, conditions, immediate actions, time triggers. |
| `__icon__` | `"assets/icons/automation.svg"` |
| `__1_11_9__` … `__1_10_0__` | Lazy changelog strings, one per release. |

No functions. No classes.

---

## `apps.py`

### Class `WorkflowConfig(AppLauncher)`

App config. `default = True`.

| Attribute | Value |
| --- | --- |
| `default_auto_field` | `"django.db.models.BigAutoField"` |
| `name` | `"horilla.contrib.workflow"` |
| `label` | `"workflow"` |
| `verbose_name` | `_("Workflow")` |
| `url_prefix` | `"workflow/"` |
| `url_module` | `"horilla.contrib.workflow.urls"` |
| `url_namespace` | `"workflow"` |
| `celery_schedule_module` | `"celery_schedules"` |
| `auto_import_modules` | `["registration", "signals", "menu"]` |

No module variables. No module functions.

---

## `registration.py`

No variables, functions, or classes.

Import-time calls:

- `register_feature("workflow", "workflow_models", auto_register_all=True)`
- `register_models_for_feature(models=[("workflow", "ScheduledWorkflowExecution")], features=["delete_dependency"])`

---

## `menu.py`

### Variables

`automation` — alias of `horilla.contrib.automations.menu.AutomationSettings`. One item is appended:

| Key | Value |
| --- | --- |
| `label` | `_("Workflow Rules")` |
| `url` | `reverse_lazy("workflow:workflow_rule_view")` |
| `hx-target` | `"#settings-content"` |
| `hx-push-url` | `"true"` |
| `hx-select` | `"#workflow-rule-view"` |
| `hx-select-oob` | `"#settings-sidebar"` |
| `perm` | `"workflow.view_workflowrule"` |
| `order` | `3` |

No functions. No classes.

---

## `celery_schedules.py`

### Variables

`HORILLA_BEAT_SCHEDULE`

| Key | `task` | `schedule` |
| --- | --- | --- |
| `"process-scheduled-workflow-executions"` | `"horilla.contrib.workflow.tasks.process_scheduled_workflow_executions"` | `timedelta(seconds=60)` |

No functions. No classes.

---

## `action_types.py`

### Variables

| Name | Value |
| --- | --- |
| `BUILTIN_ACTION_TYPES` | `(("update_field", _("Edit Field")), ("assign_task", _("Assign Task")), ("email", _("Mail")), ("notification", _("Notification")))` |
| `BUILTIN_CHANNEL_KEYS` | `frozenset({"mail", "notification"})` |
| `ACTION_TYPE_MAX_LENGTH` | `50` |
| `TEMPLATE_MAIL` | `"mail"` |
| `TEMPLATE_NOTIFICATION` | `"notification"` |
| `_BUILTIN_KEYS` | `frozenset` of the four built-in keys |

### Functions

| Function | Returns |
| --- | --- |
| `is_builtin_action_type(action_type)` | `action_type in _BUILTIN_KEYS` |
| `get_action_channel(action_type)` | `None` for empty, built-in, or `BUILTIN_CHANNEL_KEYS`. Otherwise `get_delivery_channel(action_type)`. |
| `get_action_type_choices(company=None)` | List of `(key, label)`. Built-ins, then `get_delivery_channels(company)` excluding `BUILTIN_CHANNEL_KEYS` and built-in keys. |
| `get_action_type_label(action_type)` | Built-in label, else channel label, else the raw key, else `""`. |
| `get_channel_template_kind(channel)` | `None` if `channel` is `None`. `"notification"` when `shows_notification_fields()`. Else `"mail"` when `shows_mail_fields()`. Else `None`. |

No classes.

---

## `models.py`

### Class `WorkflowRule(HorillaCoreModel)`

| Attribute | Definition |
| --- | --- |
| `name` | `CharField(max_length=255)`, verbose name Rule Name |
| `model` | `ForeignKey(HorillaContentType, on_delete=CASCADE, limit_choices_to=limit_content_types("workflow_models"), related_name="workflow_rules")` |
| `description` | `TextField(blank=True)` |
| `trigger_on_create` | `BooleanField(default=True)` |
| `trigger_on_edit` | `BooleanField(default=False)` |

`Meta`: `verbose_name` Workflow Rule, `verbose_name_plural` Workflow Rules, `ordering = ["-created_at"]`.

| Method | Behavior |
| --- | --- |
| `__str__(self)` | `str(self.name)` |
| `is_active_col(self)` | Renders `components/toggle_active_col.html`. Toggle URL `workflow:workflow_rule_activate_toggle_view`. Confirm text depends on current `is_active`. |
| `get_execute_display(self) -> str` | Both flags: "Create and Edit". Create only: "Create only". Edit only: "Edit only". Else "Not set". |
| `get_detail_url(self)` | `workflow:workflow_rule_detail_view` |
| `get_edit_url(self)` | `workflow:workflow_rule_update_view` |
| `get_delete_url(self)` | `workflow:workflow_rule_delete_view` |

### Class `WorkflowCondition(HorillaCoreModel)`

Decorated `@permission_exempt_model`.

| Attribute | Definition |
| --- | --- |
| `rule` | `ForeignKey(WorkflowRule, CASCADE, related_name="conditions")` |
| `field` | `CharField(max_length=100)` |
| `operator` | `CharField(max_length=50, choices=OPERATOR_CHOICES)` |
| `value` | `CharField(max_length=255, blank=True)` |
| `logical_operator` | `CharField(max_length=3, choices=[("and", "AND"), ("or", "OR")], default="and")` |
| `order` | `PositiveIntegerField(default=0)` |

`Meta`: ordering `["order", "created_at"]`.

`__str__(self)` → `"{rule.name}: {field} {operator} {value}"`.

### Class `WorkflowAction(HorillaCoreModel)`

| Attribute | Definition |
| --- | --- |
| `rule` | `ForeignKey(WorkflowRule, CASCADE, related_name="actions")` |
| `action_type` | `CharField(max_length=ACTION_TYPE_MAX_LENGTH)`. No `choices`. |
| `action_config` | `JSONField(default=dict, blank=True)`. Shapes: `update_field` `{field, value}`; `assign_task` `{title, due_basis, due_in_days, status, priority, description}`; `email` `{template_id, to, also_send_to}`; `notification` `{template_id, to, also_notify_to, custom_message}`; channel `{template_id, to, also_send_to}`. |
| `order` | `PositiveIntegerField(default=0)` |

`Meta`: ordering `["order", "created_at"]`.

| Method | Behavior |
| --- | --- |
| `get_action_type_display(self)` | `get_action_type_label(self.action_type)` |
| `__str__(self)` | `"{rule.name} — {get_action_type_display()}"` |

### Class `WorkflowTimeTriggerAction(HorillaCoreModel)`

Decorated `@permission_exempt_model`.

| Attribute | Definition |
| --- | --- |
| `DELAY_UNIT_CHOICES` | `("minutes", "Minutes")`, `("hours", "Hours")`, `("days", "Days")` |
| `DELAY_DIRECTION_CHOICES` | `("after", "After")`, `("before", "Before")` |
| `rule` | `ForeignKey(WorkflowRule, CASCADE, related_name="time_trigger_actions")` |
| `delay_value` | `PositiveIntegerField(default=1)` |
| `delay_unit` | `CharField(max_length=10, choices=DELAY_UNIT_CHOICES, default="days")` |
| `delay_direction` | `CharField(max_length=10, choices=DELAY_DIRECTION_CHOICES, default="after")` |
| `trigger_date_field` | `CharField(max_length=100)`. Sentinel `rule_trigger_date`, or a date field name on the target model. |
| `action_type` | `CharField(max_length=ACTION_TYPE_MAX_LENGTH)`. No `choices`. |
| `action_config` | `JSONField(default=dict, blank=True)` |
| `order` | `PositiveIntegerField(default=0)` |

| Method | Behavior |
| --- | --- |
| `get_action_type_display(self)` | `get_action_type_label(self.action_type)` |
| `__str__(self)` | Rule name, action label, delay value, unit, and direction. |

### Class `ScheduledWorkflowExecution(HorillaCoreModel)`

| Attribute | Definition |
| --- | --- |
| `STATUS_PENDING` | `"pending"` |
| `STATUS_COMPLETED` | `"completed"` |
| `STATUS_FAILED` | `"failed"` |
| `STATUS_CHOICES` | Those three values with translated labels |
| `time_trigger` | `ForeignKey(WorkflowTimeTriggerAction, CASCADE, related_name="scheduled_executions")` |
| `object_id` | `PositiveIntegerField` |
| `scheduled_at` | `DateTimeField(db_index=True)` |
| `status` | `CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)` |
| `executed_at` | `DateTimeField(null=True, blank=True)` |
| `error_message` | `TextField(blank=True)` |

`Meta` index name pattern `workflow_sc_status_*` on `(status, scheduled_at)`.

| Method | Behavior |
| --- | --- |
| `get_record_name(self)` | `str(model.objects.get(pk=object_id))`. On failure, `"Record #<object_id>"`. |
| `__str__(self)` | Time trigger, arrow, record name. |

No module variables. No module functions.

---

## `filters.py`

### Class `WorkflowRuleFilter(HorillaFilterSet)`

`Meta.model = WorkflowRule`. `fields = "__all__"`. `exclude = ["additional_info", "process_config"]`. `search_fields = ["name"]`.

### Class `ScheduledWorkflowExecutionFilter(HorillaFilterSet)`

`Meta.model = ScheduledWorkflowExecution`. `fields = "__all__"`. `exclude = ["additional_info", "time_trigger", "error_message"]`. `search_fields = ["object_id"]`.

No module variables. No module functions.

---

## `forms.py`

### Variables

| Name | Role |
| --- | --- |
| `_INPUT_CLASS` | CSS class string for text and number inputs. |
| `_SELECT_CLASS` | CSS class string for Select2 selects (`js-example-basic-single headselect`). |
| `_ACTION_CONFIG_FIELD_NAMES` | Hidden `CharField` names injected into action forms. |

`_ACTION_CONFIG_FIELD_NAMES`: `update_field`, `update_value`, `task_title`, `task_due_basis`, `task_due_in_days`, `task_status`, `task_priority`, `task_description`, `email_template_id`, `email_to`, `email_also_send_to`, `notification_template_id`, `notification_to`, `notification_also_notify_to`, `notification_custom_message`, `channel_template_id`, `channel_to`, `channel_also_send_to`.

### Functions

`action_config_initials(action_type, config, default_due_basis) -> dict`

Maps a stored `action_config` back onto hidden field names.

| `action_type` | Keys returned |
| --- | --- |
| `"update_field"` | `update_field`, `update_value` |
| `"assign_task"` | `task_title`, `task_due_basis` (fallback `default_due_basis`), `task_due_in_days` (default `"1"`), `task_status` (default `"not_started"`), `task_priority` (default `"low"`), `task_description` |
| `"email"` | `email_template_id`, `email_to`, `email_also_send_to` |
| `"notification"` | `notification_template_id`, `notification_to`, `notification_also_notify_to`, `notification_custom_message` |
| any other non-empty key | `channel_template_id`, `channel_to`, `channel_also_send_to` |
| empty | `{}` |

### Class `WorkflowRuleForm(HorillaModelForm)`

| Attribute | Value |
| --- | --- |
| `field_order` | `name`, `model`, `description`, `trigger_on_create`, `trigger_on_edit`, `is_active` |
| `Meta.model` | `WorkflowRule` |
| `Meta.fields` | `"__all__"` |
| `Meta.keep_on_form` | `("is_active",)` |

### Class `ActionConfigMixin`

| Method | Behavior |
| --- | --- |
| `_inject_action_config_fields(self)` | Adds each `_ACTION_CONFIG_FIELD_NAMES` entry as `CharField(required=False, widget=HiddenInput)`. |
| `_seed_action_config_initials(self)` | If `instance.pk`, sets hidden initials from `action_config_initials(..., default_due_basis="")`. |
| `_build_action_config(self, cleaned_data) -> dict` | Inverse of `action_config_initials`. Channel branch runs only when `get_action_channel(action_type)` is not `None`. Assign-task `due_basis` default is `"record_submission_date"`. Unknown type returns `{}`. |
| `_clean_action_type(self, cleaned_data)` | Built-in or empty: return. Else require `get_action_channel` and `channel.is_available(company)`. Company is `instance.company` or `cleaned_data["rule"].company`. Failure is a non-field error `"%(action_type)s is not an available action."`. If `get_channel_template_kind(channel)` is set and `channel_template_id` is empty, non-field error `"Select a template."`. |
| `clean(self)` | Calls `_clean_action_type`, sets `cleaned_data["action_config"]`. For `action_type == "email"`, if no `HorillaMailConfiguration` with `mail_channel="outgoing"` exists, error on `email_template_id`. |
| `save(self, commit=True)` | `super().save(commit=False)`, assigns `action_config` from `cleaned_data`, saves when `commit`. |

### Class `WorkflowActionForm(ActionConfigMixin, forms.ModelForm)`

`Meta.model = WorkflowAction`. `Meta.fields = ["rule", "action_type", "order"]`. All three widgets are `HiddenInput`.

`__init__(self, *args, **kwargs)` calls `_inject_action_config_fields` and `_seed_action_config_initials`.

### Class `WorkflowTimeTriggerActionForm(ActionConfigMixin, forms.ModelForm)`

`Meta.fields`: `rule`, `delay_value`, `delay_unit`, `delay_direction`, `trigger_date_field`, `action_type`, `order`.

Widgets: `rule`, `order`, `action_type` hidden. `delay_value` is `NumberInput` (`id="tt-delay-value"`, `min="1"`, class `_INPUT_CLASS`). `delay_unit` id `tt-delay-unit`. `delay_direction` id `tt-delay-direction`. `trigger_date_field` id `tt-trigger-date-field`.

`__init__(self, *args, date_field_choices=None, **kwargs)` injects hidden fields, sets `trigger_date_field` choices to `[("rule_trigger_date", _("Rule Trigger Date"))]` plus `date_field_choices`, then seeds initials.

---

## `methods.py`

### Variables

| Name | Value |
| --- | --- |
| `logger` | `logging.getLogger(__name__)` |
| `_UNHANDLED` | Sentinel object. A compare helper returns it when the operator is not its job. |
| `BUILTIN_EXECUTORS` | `{"update_field": _execute_update_field, "assign_task": _execute_assign_task, "email": _execute_email, "notification": _execute_notification}` |

### Functions

| Function | Contract |
| --- | --- |
| `is_running_migrations()` | `True` while Django migrations are executing. |
| `_compare_date_between(field_value, value)` | Date/datetime `between`. |
| `_compare_date_operator(op, field_value, value)` | Date operators `isnull`, `isnotnull`, `exact`, `gt`, `lt`, `between`. Returns `_UNHANDLED` for other operators. |
| `_compare_numeric_exact(op, field_value, value)` | Numeric `exact` / `ne`. Falls through on bad input. |
| `_compare_string_relational(op, field_value, value)` | `gt`, `gte`, `lt`, `lte` by numeric read of strings. |
| `_compare_string_between(field_value, value)` | String `between` as a numeric range. |
| `_compare_string_operator(op, field_value, value)` | String operators `exact`, `ne`, `icontains`, `gt`, `between`, `isnull`, `isnotnull`. Default handler returns `False`. |
| `evaluate_workflow_condition(condition, instance) -> bool` | Calls `evaluate_extension_condition` first. If that handles the field, returns its result. Otherwise reads `getattr(instance, condition.field, None)` and runs the compare helpers. Any exception is logged and returns `False`. |
| `evaluate_workflow_conditions(rule, instance) -> bool` | `rule.conditions` ordered by `order`, `created_at`. No rows: `True`. First row sets the result. Later rows combine with the previous row's `logical_operator` (`or` or else `and`). |
| `_resolve_email_recipients(to_value, also_send_to, instance, user) -> list` | Comma-separated specs. `"self"` → `user.email`. `"instance.<dotted path>"` → string containing `@`, or an object with `.email`. Integer → `User` pk. Otherwise a raw address. |
| `_resolve_notification_users(to_value, also_notify_to, instance, user) -> list` | Same spec language, resolved to `User` instances. |
| `_execute_update_field(action, instance, user)` | `action_config["field"]` and `["value"]`. Missing field name or unknown field: warning and return. Coerces int, float, and boolean internal types, then `setattr` and `save`. |
| `_execute_email(action, instance, user)` | Sends with `action_config` `template_id`, `to`, `also_send_to` via `_resolve_email_recipients`. |
| `_execute_assign_task(action, instance, user)` | Creates an `Activity` from `title`, `due_basis`, `due_in_days`, `status`, `priority`, `description`. |
| `_execute_notification(action, instance, user)` | Sends an in-app notification from `template_id`, `to`, `also_notify_to`, `custom_message` via `_resolve_notification_users`. |
| `_get_channel_template(action, channel, company) -> tuple` | `(template, ok)`. Kind from `get_channel_template_kind`. `ok` is `True` when the channel needs no template. Otherwise the id must be an int and the row must be that company or `company__isnull=True`. |
| `_also_send_to_users(raw) -> list` | Comma-separated user primary keys → `User` queryset results. |
| `_execute_channel(action, channel, instance, user)` | Loads the template. Resolves `action_config["to"]` with `channel.resolve_recipients`, adds `_also_send_to_users`. Builds `ChannelActionMessage` and calls `channel.send(message, instance, recipients, context, user)`. Empty template or recipients: warning, no send. |
| `execute_action(action, instance, user) -> bool` | Built-in: run `BUILTIN_EXECUTORS[action_type]`, return `True`. Else `get_action_channel`. `None`: log error, return `False`. Else `_execute_channel`, return `True`. |
| `execute_workflow_rule(rule, instance, user, trigger_type)` | Returns immediately when `trigger_type` is `"on_create"` and `trigger_on_create` is false, or `"on_update"` and `trigger_on_edit` is false. Returns when `evaluate_workflow_conditions` is false. Runs `rule.actions.filter(is_active=True)` ordered by `order`, `created_at`. One action exception is logged; the loop continues. Then `_schedule_time_triggers`. |
| `_schedule_time_triggers(rule, instance)` | Active `time_trigger_actions`. Base datetime is `timezone.now()` when `trigger_date_field == "rule_trigger_date"`, else `getattr(instance, trigger_date_field)`. `None` base skips that trigger. A `date` is combined with `datetime.min.time()` and made aware. Delta is `timedelta(**{delay_unit: delay_value})`, added or subtracted by `delay_direction`. Inserts `ScheduledWorkflowExecution(time_trigger, object_id=instance.pk, scheduled_at=fire_at, company=instance.company)`. A past `fire_at` is still inserted. |
| `trigger_workflow_rules(instance, trigger_type="on_create", user=None)` | Content type of `instance`. Company is `instance.company`, else `request.active_company` from thread-local. Filters `WorkflowRule` by content type, `is_active=True`, and company when known. Prefetches `conditions` and `actions`. Calls `execute_workflow_rule` per rule. Exceptions are logged per rule and around the whole function. |

### Class `ChannelActionMessage`

Adapter passed to `DeliveryChannel.send` as the automation-shaped object.

`__init__(self, action, channel, template=None)` sets:

| Attribute | Source |
| --- | --- |
| `action` | argument |
| `rule` | `action.rule` |
| `pk` | `action.pk` |
| `title` | `rule.name`, or `str(action)` |
| `company` | `action.company` or `rule.company` |
| `mail_template` | `template` when kind is `TEMPLATE_MAIL`, else `None` |
| `notification_template` | `template` when kind is `TEMPLATE_NOTIFICATION`, else `None` |
| `mail_server` | `None` |
| `mail_to` | `action_config["to"]` or `""` |
| `created_by` | `rule.created_by` |
| `updated_by` | `rule.updated_by` |

`__str__(self)` returns `str(self.title)`.

---

## `signals.py`

### Variables

`logger = logging.getLogger(__name__)`.

### Functions

`trigger_workflow_rules_on_save(sender, instance, created, **kwargs)`

`@receiver(post_save)`.

1. Return if `is_running_migrations()`.
2. Return if `sender` is not in `FEATURE_REGISTRY["workflow_models"]`.
3. Return if `(sender, instance.pk)` is in `_thread_local._workflow_executing`.
4. Return if no active `WorkflowRule` exists for `HorillaContentType` of `instance`.
5. `trigger_type` is `"on_create"` when `created`, else `"on_update"`.
6. `user` is `thread_local.request.user` when a request exists.
7. Add the instance key to `_workflow_executing`, call `trigger_workflow_rules(instance, trigger_type, user)`, discard the key in `finally`.
8. Any exception is logged with `exc_info=True`.

No classes.

---

## `tasks.py`

### Variables

`logger = logging.getLogger(__name__)`.

### Functions

`process_scheduled_workflow_executions()`

`@shared_task`. Query `ScheduledWorkflowExecution` with `status=STATUS_PENDING` and `scheduled_at__lte=timezone.now()`. Calls `execute_workflow_time_trigger.delay(execution.pk)` for each. Returns `"Queued {count} workflow time-trigger executions"`.

`execute_workflow_time_trigger(self, execution_id)`

`@shared_task(bind=True, max_retries=3)`.

1. `select_related("time_trigger__rule").get(pk=execution_id)`. `DoesNotExist`: log and return.
2. Return if `status != STATUS_PENDING`.
3. `rule.model.model_class().objects.get(pk=execution.object_id)`. Failure: `STATUS_FAILED`, `error_message=str(exc)`, `executed_at=now`, save, return.
4. `user = rule.updated_by or rule.created_by`.
5. `execute_action(time_trigger, instance, user)` is `False`: `STATUS_FAILED`, message `Action type {action_type!r} is not a built-in or a registered delivery channel.`, save, return. No `self.retry`.
6. Else `STATUS_COMPLETED`, `executed_at=now`.
7. Other exceptions: `STATUS_FAILED`, `error_message=str(exc)`, then `self.retry(exc=exc, countdown=300)`.

No classes.

---

## `admin.py`

No variables, functions, or classes.

`admin.site.register` on `WorkflowRule`, `WorkflowCondition`, `WorkflowAction`, `WorkflowTimeTriggerAction`, `ScheduledWorkflowExecution`.

---

## `urls.py`

### Variables

`app_name = "workflow"`.

`urlpatterns` — `path(route, view, name=)`:

| Route | View | `name` |
| --- | --- | --- |
| `workflow-rule-view/` | `WorkflowRuleView` | `workflow_rule_view` |
| `workflow-rule-navbar-view/` | `WorkflowRuleNavbar` | `workflow_rule_nav_view` |
| `workflow-rule-list-view/` | `WorkflowRuleListView` | `workflow_rule_list_view` |
| `workfow-activate-toggle/<int:pk>/` | `WorkflowActiveToggleView` | `workflow_rule_activate_toggle_view` |
| `workflow-rule-create-view/` | `WorkflowCreateUpdateView` | `workflow_rule_create_view` |
| `workflow-rule-update-view/<int:pk>/` | `WorkflowCreateUpdateView` | `workflow_rule_update_view` |
| `workflow-rule-delete-view/<int:pk>/` | `WorkflowDeleteView` | `workflow_rule_delete_view` |
| `workflow-rule-detail-view/<int:pk>/` | `WorkflowRuleDetailView` | `workflow_rule_detail_view` |
| `workflow-rule-detail-navbar/` | `WorkflowRuleDetailNavbar` | `workflow_rule_detail_navbar` |
| `workflow-action-fields/` | `WorkflowActionFieldsView` | `workflow_action_fields_view` |
| `workflow-action-value-widget/` | `WorkflowActionValueWidgetView` | `workflow_action_value_widget_view` |
| `workflow-action-add/<int:rule_pk>/` | `WorkflowActionSaveView` | `workflow_action_add_view` |
| `workflow-action-edit/<int:pk>/` | `WorkflowActionSaveView` | `workflow_action_edit_view` |
| `workflow-action-delete/<int:pk>/` | `WorkflowActionDeleteView` | `workflow_action_delete_view` |
| `workflow-time-trigger-add/<int:rule_pk>/` | `WorkflowTimeTriggerSaveView` | `workflow_time_trigger_add_view` |
| `workflow-time-trigger-edit/<int:pk>/` | `WorkflowTimeTriggerSaveView` | `workflow_time_trigger_edit_view` |
| `workflow-time-trigger-delete/<int:pk>/` | `WorkflowTimeTriggerDeleteView` | `workflow_time_trigger_delete_view` |
| `workflow-time-trigger-history/<int:rule_pk>/` | `WorkflowTimeTriggerHistoryView` | `workflow_time_trigger_history_view` |

No functions. No classes.

---

## `views/__init__.py`

### Variables

`__all__` exports:

`WorkflowRuleView`, `WorkflowRuleNavbar`, `WorkflowRuleListView`, `WorkflowRuleDetailNavbar`, `WorkflowRuleDetailView`, `WorkflowTimeTriggerHistoryView`, `WorkflowActiveToggleView`, `WorkflowCreateUpdateView`, `WorkflowDeleteView`, `WorkflowActionDeleteView`, `WorkflowTimeTriggerDeleteView`, `_get_model_fields`, `_build_field_meta`, `_get_date_field_choices`, `_action_form_context`, `WorkflowActionFieldsView`, `WorkflowActionValueWidgetView`, `WorkflowActionSaveView`, `WorkflowTimeTriggerSaveView`.

No functions. No classes.

---

## `views/core.py`

### Variables

`logger = logging.getLogger(__name__)`.

### Class `WorkflowRuleView(LoginRequiredMixin, HorillaView)`

Dispatch decorator: `permission_required_or_denied("workflow.view_workflowrule", wrapper_id="workflow-rule-view")`.

| Attribute | Value |
| --- | --- |
| `template_name` | `"settings/settings_list_shell.html"` |
| `view_id` | `"workflow-rule-view"` |
| `nav_url` | `workflow:workflow_rule_nav_view` |
| `list_url` | `workflow:workflow_rule_list_view` |

### Class `WorkflowRuleNavbar(LoginRequiredMixin, HorillaNavView)`

Decorators: `htmx_required`, `permission_required_or_denied(["workflow.view_workflowrule"])`.

| Attribute | Value |
| --- | --- |
| `nav_title` | `_("Workflow Rules")` |
| `nav_description` | `_("Automate actions when records meet the conditions you set.")` |
| `search_url` | `workflow:workflow_rule_list_view` |
| `main_url` | `workflow:workflow_rule_view` |
| `model_name` | `"WorkflowRule"` |
| `model_app_label` | `"workflow"` |
| `nav_width` | `False` |
| `all_view_types` | `False` |
| `filter_option` | `False` |
| `one_view_only` | `True` |
| `reload_option` | `False` |
| `border_enabled` | `False` |

`new_button` (`cached_property`): if `workflow.add_workflowrule`, `{"url": create view + "?new=true", "attrs": 'id="workflow-rule-create"'`. Else `None`.

### Class `WorkflowRuleListView(LoginRequiredMixin, HorillaListView)`

Same two decorators as the navbar.

| Attribute | Value |
| --- | --- |
| `model` | `WorkflowRule` |
| `view_id` | `"workflow-rule-list"` |
| `search_url` | `workflow:workflow_rule_list_view` |
| `main_url` | `workflow:workflow_rule_view` |
| `filterset_class` | `WorkflowRuleFilter` |
| `save_to_list_option` | `False` |
| `bulk_select_option` | `False` |
| `list_column_visibility` | `False` |
| `columns` | `"name"`, `"model"`, `"description"`, `(_("Execute on"), "get_execute_display")`, `("is_active", "is_active_col")` |

`actions`:

| `action` | `permission` | HTMX |
| --- | --- | --- |
| Edit | `workflow.change_workflowrule` | `hx-get="{get_edit_url}?new=true"` → `#modalBox`, `openModal()` |
| Delete | `approvals.delete_approvalrule` | `hx-post="{get_delete_url}"` → `#deleteModeBox`, `hx-vals` `check_dependencies=true`, `openDeleteModeModal()` |

| Method | Behavior |
| --- | --- |
| `col_attrs` (`cached_property`) | Name cell: pointer and `hover:text-primary-600`. With `workflow.view_workflowrule`, also `hx-get="{get_detail_url}"`, target `#workflow-rule-view`, `outerHTML`, `hx-push-url`, `hx-select` `#workflow-rule-view`. |
| `no_record_add_button(self)` | If `approvals.add_approvalrule`, create URL and `id="approval-process-create"`. Else `None`. |

### Class `WorkflowRuleDetailNavbar(LoginRequiredMixin, HorillaNavView)`

Decorators: `htmx_required`, `permission_required_or_denied("workflow.view_workflowrule")`.

| Attribute | Value |
| --- | --- |
| `search_url` | `workflow:workflow_rule_list_view` |
| `main_url` | `workflow:workflow_rule_view` |
| `filterset_class` | `WorkflowRuleFilter` |
| `one_view_only` | `True` |
| `all_view_types` | `False` |
| `filter_option` | `False` |
| `model_name` | `"WorkflowRule"` |
| `model_app_label` | `"Workflow"` |
| `nav_width` | `False` |
| `url_name` | `"workflow_rule_list_view"` |
| `search_option` | `False` |
| `border_enabled` | `False` |
| `navbar_indication` | `True` |
| `reload_option` | `False` |
| `navbar_indication_attrs` | `hx-get` rule view, target `#workflow-rule-view`, `outerHTML`, `hx-push-url`, `hx-select` `#workflow-rule-view` |

`get_context_data(self, **kwargs)`: reads `GET["obj"]`, strips a query suffix, casts to `int`, loads `WorkflowRule`, sets `nav_title` and `context["nav_title"]` to `obj.name`. `ValueError` is ignored.

`second_button`: edit control. `hx-get` the rule update URL, target `#modalBox`.

### Class `WorkflowRuleDetailView(DetailView)`

| Attribute | Value |
| --- | --- |
| `template_name` | `"workflow_rule_detail_view.html"` |
| `model` | `WorkflowRule` |
| `context_object_name` | `"workflow_rule"` |

| Method | Behavior |
| --- | --- |
| `_normalize_rule_config(config)` | Static. Copies a dict. For each character of the string `"record_modification"` used as a key, a string value that starts and ends with `{` / `}` is `json.loads`'d while it stays a string of that shape. A parsed dict replaces the value. |
| `_resolve_field_verbose_name(model, field_name)` | Static. Model field `verbose_name`, including custom fields. |
| `get_queryset(self)` | `WorkflowRule` queryset with conditions and actions prefetched. |
| `get_context_data(self, **kwargs)` | Super context plus readable conditions and `_enrich_actions` output. |
| `_enrich_actions(self, actions)` | Sets `action.display_config`. Resolves template and user primary keys in `action_config`. Nested `_resolve_users` maps comma-separated user pks to display names. |
| `dispatch(self, request, *args, **kwargs)` | Unauthenticated: `login_redirect(request)`. `get_object()` failure on `HX-Request: true`: error message and `RefreshResponse`. Otherwise `raise HttpNotFound(exc) from exc`. Then `super().dispatch`. |

### Class `WorkflowTimeTriggerHistoryView(LoginRequiredMixin, HorillaListView)`

| Attribute | Value |
| --- | --- |
| `model` | `ScheduledWorkflowExecution` |
| `template_name` | `"workflow_tt_history_modal.html"` |
| `view_id` | `"workflow-tt-history-list"` |
| `filterset_class` | `ScheduledWorkflowExecutionFilter` |
| `save_to_list_option` | `False` |
| `bulk_select_option` | `False` |
| `list_column_visibility` | `False` |
| `table_width` | `False` |
| `main_url` | `""` |
| `columns` | `(_("Record"), "get_record_name")`, `"scheduled_at"`, `"executed_at"`, `"status"` |

| Method | Behavior |
| --- | --- |
| `search_url(self)` | History URL including `rule_pk`. |
| `get_queryset(self)` | Executions whose `time_trigger.rule_id` is the URL rule. |

---

## `views/actions.py`

### Variables

`logger = logging.getLogger(__name__)`.

### Class `WorkflowActiveToggleView(LoginRequiredMixin, View)`

`post(self, request, pk)`: load `WorkflowRule`. Without `workflow.change_workflowrule`, `ScriptResponse(reload=True)`. Else flip `is_active`, `save(update_fields=["is_active"])`, success message, reload. Exception: error message, reload.

### Class `WorkflowCreateUpdateView(LoginRequiredMixin, HorillaSingleFormView)`

Decorator: `htmx_required`.

| Attribute | Value |
| --- | --- |
| `model` | `WorkflowRule` |
| `form_class` | `WorkflowRuleForm` |
| `template_name` | `"workflow_rule_create_update.html"` |
| `full_width_fields` | `["name", "model", "description"]` |
| `modal_height` | `False` |
| `save_and_new` | `False` |
| `condition_fields` | `["field", "operator", "value", "logical_operator"]` |
| `condition_model` | `WorkflowCondition` |
| `condition_related_name` | `"conditions"` |
| `condition_order_by` | `["order"]` |
| `condition_field_title` | `_("When should this rule apply?")` |
| `content_type_field` | `None` |

| Method | Behavior |
| --- | --- |
| `get_model_name_from_content_type(self, request=None)` | For an existing pk, `rule.model.model`. Else `None`. |
| `form_valid(self, form)` | If no submitted condition row has `field`, `add_error(None, "At least one condition is required.")` and `form_invalid`. Else `super().form_valid`. |
| `form_url` (`cached_property`) | Update URL when `kwargs["pk"]` or `GET["id"]`. Else create URL. |

### Class `WorkflowDeleteView(LoginRequiredMixin, HorillaSingleDeleteView)`

Decorators: `htmx_required`, `permission_required_or_denied("workflow.delete_workflowrule", modal=True)`.

`model = WorkflowRule`. `get_post_delete_response(self)` returns `HxTriggerResponse()`.

### Class `WorkflowActionDeleteView(LoginRequiredMixin, HorillaSingleDeleteView)`

Decorators: `htmx_required`, `permission_required_or_denied("workflow.change_workflowrule", modal=True)`.

`model = WorkflowAction`. `get_post_delete_response(self)` returns `ScriptResponse(reload=True)`.

### Class `WorkflowTimeTriggerDeleteView(LoginRequiredMixin, HorillaSingleDeleteView)`

Same decorators as the action delete view.

`model = WorkflowTimeTriggerAction`. `get_post_delete_response(self)` returns `ScriptResponse(reload=True)`.

---

## `views/fragments.py`

### Variables

`logger = logging.getLogger(__name__)`.

### Functions

| Function | Contract |
| --- | --- |
| `_get_model_fields(rule)` | `list[(name, label)]` of editable fields on the rule module. |
| `_build_field_meta(rule)` | Field metadata dicts for the action popup, plus email and notification recipient choice lists. |
| `_get_date_field_choices(rule)` | `(field_name, verbose_label)` for `DateField` and `DateTimeField` on the rule module. |
| `_rule_model_class(rule)` | `rule.model.model_class()`, with an `apps.get_model` fallback. `None` when the rule or model is missing. |
| `_is_offered_action_type(action_type, company) -> bool` | `action_type` is a key in `get_action_type_choices(company)`. |
| `_action_form_context(request, rule, action_type="", current_values=None) -> dict` | Keys: `rule`, `rule_pk`, `action_type_choices`, `field_meta`, `mail_templates`, `notification_templates`, `users`, `email_to_choices`, `notification_to_choices`, `channel`, `channel_template_kind`, `channel_to_choices`, `current_values`. Templates filtered by content type (or null content type) and by `request.active_company` or null company. Users filtered to that company and `is_active=True`. `channel_to_choices` is `channel.get_recipient_choices(model_class)` when `get_action_channel(action_type)` is set. |
| `_keep_saved_action_type(context, action_type)` | If `action_type` is absent from `context["action_type_choices"]`, append `(action_type, get_action_type_label(action_type))`. |
| `_posted_current_values(request) -> dict` | Posted compose fields, used to redisplay an invalid form. |

### Class `WorkflowActionFieldsView`

`get(self, request)`: renders `workflow_action_fields_fragment.html` from `_action_form_context`. An `action_type` that `_is_offered_action_type` rejects returns an empty fragment.

### Class `WorkflowActionValueWidgetView`

`get(self, request)`: renders `workflow_action_value_widget_fragment.html`, the value widget for the requested model field (`update_field`).

### Class `WorkflowActionSaveView`

| Method | Behavior |
| --- | --- |
| `_get_rule(self)` | `WorkflowRule` for the add `rule_pk`, or for the edited action's rule. |
| `get(self, request, rule_pk=None, pk=None)` | Renders `workflow_action_form.html`. Edit path calls `_keep_saved_action_type`. |
| `post(self, request, rule_pk=None, pk=None)` | `WorkflowActionForm`. Valid: save, HTMX refresh. Invalid: re-render with errors and `_posted_current_values`. |

### Class `WorkflowTimeTriggerSaveView`

| Method | Behavior |
| --- | --- |
| `_get_rule(self)` | Same lookup as the action save view, for a time trigger. |
| `get(self, request, rule_pk=None, pk=None)` | Renders `workflow_time_trigger_form.html`. Passes `_get_date_field_choices` into the form. |
| `post(self, request, rule_pk=None, pk=None)` | `WorkflowTimeTriggerActionForm`. Valid: save and refresh. Invalid: re-render. |

---

## `migrations/__init__.py`

No variables, functions, or classes.

## `migrations/0001_initial.py`

`Migration.dependencies`: workflow app initial.

`operations`: `CreateModel` for `WorkflowRule`, `WorkflowCondition`, `WorkflowAction`, `WorkflowTimeTriggerAction`, `ScheduledWorkflowExecution`, plus the status/scheduled_at index on `ScheduledWorkflowExecution`.

## `migrations/0002_alter_workflowaction_action_type_and_more.py`

`AlterField` `action_type` on `workflowaction` and `workflowtimetriggeraction`.

## `migrations/0003_alter_scheduledworkflowexecution_additional_info_and_more.py`

`AlterField` on `additional_info`, `created_at`, and `is_active` for all five models, and on `WorkflowRule.trigger_on_create` / `trigger_on_edit` verbose names.

## `migrations/0004_alter_workflowaction_action_config_and_more.py`

`AlterField` `workflowaction.action_config`. `AlterField` both `action_type` columns to `CharField(max_length=50)` with no `choices`.

---

## `tests.py`

### Variables

`BUILTIN_KEYS = ["update_field", "assign_task", "email", "notification"]`.

### Functions

| Function | Behavior |
| --- | --- |
| `only_builtin_channels(test)` | `mock.patch.dict(delivery_registry._channels, {mail, notification}, clear=True)`. `test.addCleanup(patcher.stop)`. |
| `register(test, channel)` | `register_delivery_channel(channel)`. `test.addCleanup(unregister_delivery_channel, channel.key)`. Returns `channel`. |

### Class `FakeSmsChannel(DeliveryChannel)`

| Attribute | Value |
| --- | --- |
| `key` | `"fake_sms"` |
| `label` | `"Send as Fake SMS"` |
| `address_kind` | `ADDRESS_PHONE` |

`__init__(self, available=True)` sets `self.available` and `self.sent = []`. `is_available(self, company=None)` returns `self.available`. `shows_notification_fields(self)` returns `True`. `send(self, automation, instance, recipients, context, user)` appends `(automation, instance, list(recipients), context, user)` to `self.sent`.

### Class `FakeMailerChannel(FakeSmsChannel)`

| Attribute | Value |
| --- | --- |
| `key` | `"fake_mailer"` |
| `label` | `"Send as Fake Mailer"` |
| `address_kind` | `"email"` |
| `order` | `110` |

`shows_notification_fields(self)` returns `False`. `shows_mail_fields(self)` returns `True`.

### Class `NotificationAgainChannel(NotificationChannel)`

`key = "notification_again"`. `label = "Send as Notification Again"`. Inherits `NotificationChannel.send`.

### Class `MailAgainChannel(MailChannel)`

`key = "mail_again"`. `label = "Send as Mail Again"`. Inherits `MailChannel.send`.

### Class `ActionTypeTests`

`setUp` calls `only_builtin_channels`. `keys(self)` returns keys from `get_action_type_choices`.

| Method | Asserts |
| --- | --- |
| `test_without_other_channels_the_list_is_the_builtins` | Choices are the four built-in keys. |
| `test_registered_channels_follow_the_builtins_in_registry_order` | Registered fakes follow built-ins in `order`. |
| `test_unavailable_channel_is_not_offered` | `is_available` false removes the key. |
| `test_action_channel` | `get_action_channel` is `None` for built-ins and `mail`, and the fake for `fake_sms`. |
| `test_labels` | `get_action_type_label` for built-ins, fakes, and a missing key. |
| `test_template_kind` | `get_channel_template_kind` for notification-kind and mail-kind fakes. |
| `test_action_type_has_no_fixed_choices` | `WorkflowAction.action_type` and `WorkflowTimeTriggerAction.action_type` have empty `choices`. |

### Class `WorkflowTestCase`

`setUp` builds company, user, content type, record, and rule under `only_builtin_channels`.

`action(self, **kwargs)` creates a `WorkflowAction`. `sms_action(self, **kwargs)` creates one with `action_type="fake_sms"` and a channel `action_config`.

### Class `ExecuteActionTests(WorkflowTestCase)`

| Method | Asserts |
| --- | --- |
| `test_builtins_run_their_executors` | Each built-in key dispatches to its executor. |
| `test_channel_action_sends_through_the_channel` | Fake `send` receives template, recipients, and also-send-to users. |
| `test_mail_kind_channel_gets_the_mail_template` | Mail-kind channel gets `mail_template`. |
| `test_missing_template_or_recipients_sends_nothing` | Missing template or unresolved recipients do not call `send`. |
| `test_unknown_action_type_is_logged_and_skipped` | `execute_action` returns `False` and logs. |
| `test_rule_runs_one_action_per_channel_in_order` | Two actions run in `order`. |
| `test_failing_channel_does_not_stop_the_next_action` | Exception in one action does not skip the next. |

### Class `RealChannelTests(WorkflowTestCase)`

| Method | Asserts |
| --- | --- |
| `test_notification_channel_send` | Real `NotificationChannel.send` creates a `Notification`. |
| `test_mail_channel_send` | Real `MailChannel.send` sends mail. |

### Class `TimeTriggerTests(WorkflowTestCase)`

`execution(self, **kwargs)` builds a `ScheduledWorkflowExecution` in `STATUS_PENDING`.

| Method | Asserts |
| --- | --- |
| `test_channel_time_trigger_sends_and_completes` | Worker sets `STATUS_COMPLETED` and the fake recorded a send. |
| `test_unregistered_channel_fails_without_retry` | Missing key sets `STATUS_FAILED` and does not call `retry`. |

### Class `FormTests(WorkflowTestCase)`

`form(self, **data)` returns a bound `WorkflowActionForm`.

| Method | Asserts |
| --- | --- |
| `test_channel_action_stores_template_to_and_also_send_to` | Saved `action_config` is `{template_id, to, also_send_to}`. |
| `test_channel_action_needs_its_template` | Empty `channel_template_id` is invalid. |
| `test_unknown_or_unavailable_action_type_is_refused` | Unknown key and `is_available` false are invalid. |
| `test_builtins_keep_their_config` | Email and notification configs stay on their own keys. |
| `test_edit_form_seeds_the_channel_fields` | Edit initials match stored `channel_*` values. |

### Class `ViewTests(WorkflowTestCase)`

`setUp` logs the client in. `get(self, url)` performs GET. `type_options(self, response)` parses `<option>` values from the action-type `<select>`.

| Method | Asserts |
| --- | --- |
| `test_add_modals_list_the_builtins_and_the_channels` | Add action and add time-trigger responses include built-ins and `fake_sms`. |
| `test_fields_fragment_for_a_channel` | Fragment contains channel template and recipient controls. |
| `test_fields_fragment_refuses_what_is_not_offered` | Unoffered key does not render channel fields. |
| `test_edit_modal_selects_the_channel_and_fills_its_fields` | Edit HTML selects the stored channel and fills config inputs. |
| `test_edit_modal_keeps_a_type_that_is_no_longer_offered` | Unregistered saved key remains an `<option>`. |
| `test_saving_a_channel_action` | POST persists `action_type` and `action_config`. |
| `test_invalid_post_shows_the_error_and_keeps_the_fields` | Invalid POST returns the error and the posted field values. |

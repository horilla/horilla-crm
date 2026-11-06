# Horilla Automations app — deep dive (`horilla.contrib.automations`)

## What this app does

- **`HorillaAutomation`** rules: when a registered model is created/updated/deleted (or on a **schedule**), evaluate **`AutomationCondition`** rows and send through one or more **delivery channels**: **email**, **in-app notification**, or a channel another app registers, in any combination (see [Delivery channels](#delivery-channels-horillaregistrydelivery)).
- Uses **`HorillaContentType`** so any model that opts into the **`automation_models`** feature can be a trigger target (no hard-coded model list in signals).
- Supports **Celery** execution (`execute_automation_task`) when async is enabled; otherwise runs synchronously from signal handlers.
- Ships **JSON seed automations** from `load_automation/automation.json` via `automation_files` on the app config.

---

## App startup (`apps.py`)

`AutomationsConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `automations/` |
| `url_namespace` | `automations` |
| `auto_import_modules` | `registration`, `menu`, `signals` |
| `celery_schedule_module` | `celery_schedules` |
| `automation_files` | `["load_automation/automation.json"]` |

`registration` runs first in practice because `menu` and `signals` depend on registry entries.

---

## Feature registration (`registration.py`)

```text
register_feature("automation", "automation_models")
```

Apps register models into **`automation_models`**. The universal **`post_save`** / **`pre_delete`** receivers in `signals.py` **only** continue if `sender` is in that registry list—this keeps automation overhead off unrelated tables.

---

## Menu (`menu.py`)

`AutomationSettings` (`@settings_menu.register`):

- Section title **Automations**, icon `/assets/icons/automation.svg`, `order = 4`.
- First item: **Mail & Notifications** → `automations:automation_view` with HTMX targeting `#settings-content`, OOB `#settings-sidebar`, fragment `#automation-view`.
- Permission gate: `automation.view_horillaautomation`.

---

## Models (`models.py`)

### `HorillaAutomation`

- **`title`** (unique), **`method_title`** (internal/slug-like, `editable=False`).
- **`model`** → `HorillaContentType`, `limit_choices_to=limit_content_types("automation_models")`.
- **`trigger`** — `on_create` | `on_update` | `on_create_or_update` | `on_delete` | `scheduled`.
- **`delivery_channel`** — the keys of the selected delivery channels, comma-separated in `get_delivery_channels()` order: `mail`, `notification`, `mail,notification`, later `mail,sms`. A plain `CharField` (`max_length=255`) with no fixed `choices`: `clean()` checks every key against the registry and stores them in that order, and `get_delivery_channel_display()` joins the channels' labels (a key whose app is gone shows as the key). Split the value with `split_delivery_channels()`; never search it with a substring (`sms` is also inside `sms_backup`).
- **Templates** — FK to **`HorillaMailTemplate`**, **`NotificationTemplate`** (validated in `clean()` per selected channel: the mail template and server when any selected channel shows the mail fields, the notification template when any shows the notification field).
- **"+ Add" for templates** — the form view sets `dynamic_create_fields` / `dynamic_create_field_mapping` so the Mail Template and Notification Template selects get an "+ Add" button that opens the generic dynamic-create popup (Summernote body/message via `rich_text_fields`, insert-field tools, module pre-filled from `TemplateFieldsView`'s `model_id`). It needs `mail.add_horillamailtemplate` / `notifications.add_notificationtemplate`; the new template is added to the select and chosen.
- **Owner fields** — `HorillaAutomationForm` uses `OwnerQuerysetMixin`, so owner querysets are restricted like other forms.
- **`mail_server`** — optional outgoing **`HorillaMailConfiguration`**.
- **`mail_to`** — rich text rules: literals, `self`, `instance.owner.email`, etc. (see field `help_text` in code).
- **`also_sent_to`** — extra users (M2M).
- **Scheduled-only fields** — `schedule_date_field`, offset amount/direction/unit, `schedule_run_time`; required combinations validated in `clean()`.
  - `schedule_run_time` is optional; when set, the scheduler task holds off running that automation until this time has passed. It's interpreted in the automation's own timezone — `created_by.time_zone`, falling back to `company.time_zone`, then UTC — not the raw server clock (see `tasks.py` below).
- **Edge trigger.** An `on_update` automation can set `additional_info["edge_trigger_only"] = True` so it fires only when a condition newly becomes true, not on later edits of a record that already matched. The model must expose a pre-save snapshot as `_old_<field>` (Opportunity amount does this in `horilla_crm/opportunities/signals.py` for Big Deal Alert). Automations that leave the flag unset are unchanged.
- **Recipient timezone.** Mail and notification templates render bare datetime variables (`{{ instance.due_datetime }}`) in each recipient's `time_zone` (else UTC). The send thread calls `timezone.activate` because a background thread has no active timezone; the stand-in request (`MockRequest` in `mail/tasks.py`, `_RenderRequest` in `notifications/delivery.py`) only backs filters such as `user_datetime_format`.

### `AutomationCondition`

- Links to an automation; stores **field**, **condition** operator (custom `CONDITIONS` list), **value**, ordering, and logical grouping for AND/OR evaluation in `methods.py`.

### `AutomationRunLog`

- Prevents duplicate scheduled sends and stores execution metadata (see model for fields used by scheduler).

`HorillaAutomation` is a normal **`HorillaCoreModel`** (company-scoped, audited). Related condition/runlog rows cascade with the automation.

---

## Delivery channels (`horilla.registry.delivery`)

Automations does not know how a message is delivered. Each channel is a `DeliveryChannel` subclass that its own app defines in `delivery.py` and registers from its `registration.py` (imported at startup through `auto_import_modules`, not from `AppConfig.ready()`):

| Key | Class | App | `send` does |
|-----|-------|-----|-------------|
| `mail` (`order` 10) | `MailChannel` | `horilla/contrib/mail/delivery.py` | Creates the `HorillaMail` draft and sends it in a background thread. |
| `notification` (`order` 20) | `NotificationChannel` | `horilla/contrib/notifications/delivery.py` | Renders the notification template per recipient and creates the notifications. |

The registry module (`horilla/registry/delivery.py`) imports no app: `register_delivery_channel(channel)`, `get_delivery_channel(key)`, `get_delivery_channels(company=None)`. Registering a key twice raises `ValueError`, and so does a key with a comma or a space; `mail` and `notification` are reserved for their apps, and `both` (the value Automations stored for mail and notification together) can never be registered.

**Several channels, one string.** The form is a multi-select of `get_delivery_channels(company)`. The selected keys are stored joined by a comma, in `get_delivery_channels()` order: each channel's `order` (mail 10, notification 20, 100 by default), then registration order. So `notification,mail` is saved and sent as `mail,notification`, like `both` today. Registration alone follows `INSTALLED_APPS`, where notifications comes before mail; `order` is what keeps mail first. There is no `both` choice: selecting mail and notification is that combination, and mail with an SMS channel is `mail,sms`. Migration `0006` rewrites rows stored as `both` to `mail,notification`; a row that still holds `both` runs as mail, then notification, and `clean()` rewrites it when it is saved. A channel key can therefore contain no comma and no space.

**`execute_automation()`**, for each stored key in order:

1. `get_delivery_channel(key)`; a key that is not registered (its app was removed) is logged and skipped, and the other selected channels still send. The save of the record never fails.
2. `channel.resolve_recipients(mail_to, instance, user)`, then `channel.add_also_sent_to(...)` with **Also Send To**. One `mail_to` value is shared; each channel reads it for its own address kind (mail takes email addresses, notification users, a phone channel numbers). An empty list skips only that channel.
3. `channel.send(automation, instance, recipients, context, user)`. An error in one channel is logged and does not stop the next.

**Form.** The recipient picker (`mail_to`) shows the union of the selected channels' `get_recipient_choices(model)` and is refreshed by `TemplateFieldsView` whenever the selection or the module changes. `TemplateFieldsView` reads every selected key (`request.GET.getlist("delivery_channel")`) and shows the mail template and mail server when any selected channel's `shows_mail_fields()` is true, the notification template when any `shows_notification_fields()` is true.

**Adding a channel** (an SMS gateway, a messenger) is a new app: no change in Automations and no migration anywhere. The channel is also offered as a Workflow action type (see [Workflow: actions and delivery channels](../workflow/workflow.md#actions-and-delivery-channels)), one channel per action, and as a Cadence follow-up type (see [Cadences: follow-ups through delivery channels](../cadences/cadences.md#follow-ups-through-delivery-channels)), one channel per follow-up.

```python
# myapp/delivery.py
from horilla.registry.delivery import ADDRESS_PHONE, DeliveryChannel


class SmsChannel(DeliveryChannel):
    key = "sms"
    label = _("Send as SMS")
    address_kind = ADDRESS_PHONE  # recipients are phone numbers

    def shows_notification_fields(self):
        return True  # the text comes from the notification template

    def send(self, automation, instance, recipients, context, user):
        ...  # queue the messages; must not block (runs inside post_save)


# myapp/registration.py
from horilla.registry.delivery import register_delivery_channel

from .delivery import SmsChannel

register_delivery_channel(SmsChannel())
```

The defaults follow `address_kind` (`"email"`, `"user"` or `"phone"`): recipient choices are `self`, the model's user foreign keys and its fields of that kind (`*email*` fields for email and user, `*phone*`, `*mobile*`, `contact_number` for phone); a target resolves to the raw value or the user's `email` / the user / `contact_number`, and a value the channel cannot use is skipped (mail skips a value without `@`, a phone channel one that is not written like a phone number, such as an email in the shared `mail_to`). A channel that leaves `order` at 100 is listed and sent after mail and notification. Override `get_recipient_choices`, `resolve_recipients` or `get_address` when a channel needs something else, and `is_available(company)` to offer it only to some companies. Credentials and provider calls stay in the channel's app.

Seed automations (`load_automation.py`) are normalized the same way (a seed `both` is written as `mail,notification`); a row with a key that is not registered is logged and skipped.

---

## Signals (`signals.py`)

- **`is_running_migrations()`** — skips handlers during `migrate` or before `auditlog_logentry` exists to avoid boot-time errors.
- **`post_save`** (`trigger_automations_on_save`) — if sender is in `FEATURE_REGISTRY["automation_models"]` and matching `HorillaAutomation` rows exist for that content type, computes `on_create` vs `on_update`, builds **`request_info`** from `_thread_local.request` (user, company, META), then dispatches to **`trigger_automations`** (sync or Celery).
- **`pre_delete`** — parallel path for **`on_delete`** triggers.

Thread-local request is populated by **`ThreadLocalMiddleware`** (`horilla.contrib.utils.middlewares`), registered in project settings.

---

## Typical flows

1. Admin enables automation for **Lead** by registering the model under **`automation_models`** (in that app’s `registration.py`).
2. Admin creates a **HorillaAutomation** row with trigger `on_create_or_update` and a mail or notification template. Those fields offer **+ Add**, which opens the generic dynamic-create popup (pre-filled with the automation's module, limited to models allowed for that template) and selects the new template.
3. User saves a lead → signal runs → conditions evaluated → each selected delivery channel sends, in stored order.
4. Scheduled automation: Celery beat hits `celery_schedules` → `run_scheduled_automations` resolves "today"/"current time" in the automation's own timezone (`created_by.time_zone` → `company.time_zone` → UTC) → honors `schedule_run_time` in that timezone → loads due rows using date field + offset (via a `__date` lookup for `DateTimeField` targets, exact match for `DateField` targets) → **`AutomationRunLog`** dedupes.

---

## Conditions and fields that aren't model columns

- **Field dropdown** — `AutomationFieldChoicesView` builds the condition field list after a module is chosen; `HorillaAutomationForm._get_model_field_choices` builds it on first render. The view exposes `get_extra_field_choices(model)` (default `[]`) for fields that aren't model columns, and the form method can be overridden by a `FormExtension`.
- **Evaluation** — `evaluate_condition(condition, instance)` first asks `evaluate_extension_condition` (see [condition_fields.md](../generics/forms/condition_fields.md#conditionfieldprovider-extension-seam)); when an extension owns the field the value is compared as text with `_compare_generic_operator`, otherwise the model field is read as before. Cadences reuse this function, so they get the same behaviour.

---

## Related documentation

- Mail templates and servers: [../mail/mail.md](../mail/mail.md)
- Notifications templates: [../notifications/notifications.md](../notifications/notifications.md)
- Feature registry: [../core/Registry/feature.md](../core/Registry/feature.md)
- Delivery channel registry: `horilla/registry/delivery.py` (see [Delivery channels](#delivery-channels-horillaregistrydelivery))

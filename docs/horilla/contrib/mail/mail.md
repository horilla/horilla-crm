# Horilla Mail app — deep dive (`horilla.contrib.mail`)

## What this app does

- **Outgoing mail configuration** per channel (SMTP, etc.) via **`HorillaMailConfiguration`**.
- **Message queue / history** via **`HorillaMail`** and **`HorillaMailAttachment`** (settings label: **Outbox**).
- **Incoming mail**: messages fetched from IMAP/Outlook mailboxes are persisted as **`IncomingMail`** rows and browsable in the **Inbox** screen, with pluggable "convert this email into a record" actions contributed by other apps (e.g. CRM's `leads`/`contacts`) — see [Incoming mail / Inbox](#incoming-mail--inbox-incomingmail-actionspy-fetch_hookspy) below.
- **Reusable HTML templates** via **`HorillaMailTemplate`** (seeded from `load_template/template.json` on install).
- **Celery** tasks in `tasks.py` for async send and for the incoming-mail fetch/prune jobs; **`scheduler`** module for periodic mail jobs.
- **REST API** at `mail/` for mobile/integrations.

**Architectural constraint**: this app never imports `horilla_crm` (or any other app that wants to act on incoming mail). Cross-app behavior is contributed *into* `mail` via two plain-list callback registries (`actions.py`, `fetch_hooks.py`), the same pattern `horilla/contrib/process/integration.py` uses elsewhere — `mail` only ever calls through the registered callables, it never imports the apps that register them.

---

## App startup (`apps.py`)

`MailConfig`:

| Setting | Value |
|---------|--------|
| `url_prefix` | `mail/` |
| `url_namespace` | `mail` |
| `auto_import_modules` | `registration`, `signals`, **`scheduler`**, `menu` |
| `celery_schedule_module` | `celery_schedules` |
| `template_files` | `["load_template/template.json"]` |
| API | `mail/` include → `horilla.contrib.mail.api.urls` |

---

## Feature registration (`registration.py`)

```text
register_feature("mail_template", "mail_template_models")
```

Models that expose themselves under **`mail_template_models`** can be selected when building mail templates with merge fields / loops (see mail template editor views).

---

## Models (`models.py`) — concepts

### `HorillaMailConfiguration`

- Stores host, port, username, **`EncryptedCharField`** for **password** and **Outlook client secret**, TLS, default from-address, **`mail_channel`** (`incoming` / `outgoing`) for limit choices on automations.
- Help text on host, port, from email, username, display name, TLS/SSL, fail silently, primary server, timeout, and the Outlook OAuth fields.

### `HorillaMail`

- One row per send attempt: headers, body snapshot, status, FK to template used, link to triggering user/company.
- **`rendered_subject`** / **`rendered_body`** — HTML/text snapshot of the template (or compose body) **persisted at send time**, so later preview of a sent message does not re-render against live template context (avoids stale or privileged context leaks).

### `HorillaMailAttachment`

- File rows bound to a parent mail message (`upload_path` pattern from `horilla.utils.upload`).
- Belongs to **exactly one** of an outgoing **`mail`** (FK → `HorillaMail`) or an incoming **`incoming_mail`** (FK → `IncomingMail`) — never both, never neither. Enforced twice: `clean()` raises a `ValidationError` (so forms/admin get a clear message), and a DB-level `CheckConstraint` (`mail_attachment_exactly_one_parent`, migration `0006`) rejects any row from a path that bypasses `save()`/`clean()` (raw SQL, `bulk_create()`).
- `is_inline` / `content_id`: derived at fetch time from the real `Content-Disposition` (IMAP) / `isInline` (Outlook Graph) flag — **not** from mere presence of a `Content-ID` header, since some senders stamp a `Content-ID` on ordinary (non-inline) file attachments too.

### `HorillaMailTemplate`

- Named template with HTML body; referenced by **Automations**, **Cadences**, and manual compose UIs.
- Supports the generic **"+ Add" dynamic create** popup (e.g. from the automation form). `dynamic_create_field_tools` adds **Insert Fields** (driven by `#id_content_type`) and a **Preview** button (`mail:mail_template_preview_view`, posting `#id_body, #id_subject`) beside `body`.

### `IncomingMail` and `DeletedIncomingMessageId`

See [Incoming mail / Inbox](#incoming-mail--inbox-incomingmail-actionspy-fetch_hookspy) below — kept separate since this pair of models carries its own non-obvious delete/dedup design.

---

## Forms (`forms.py`)

### `HorillaMailTemplateForm` (`forms.ModelForm`, not `HorillaModelForm`)

- **`field_order`**: `title`, `subject`, `content_type`, `body`, `company`
- **`Meta.fields = "__all__"`**
- **`Meta.exclude`**: `is_active`, `created_at`, `updated_at`, `created_by`, `updated_by`, `additional_info` — **`company` stays on the form** (manual exclude list, same effect as `keep_on_form` on `HorillaModelForm`)
- Used by **`MailTemplateCreateUpdateView`** (`FormView`, not `HorillaSingleFormView`)

### `SaveAsMailTemplateForm`

- Still uses explicit **`fields = ["title", "body", "company", "content_type"]`** (unchanged)

### Mail configuration (`HorillaModelForm`)

| Form | `keep_on_form` | `Meta.exclude` (high level) |
|------|----------------|----------------------------|
| **`HorillaMailConfigurationForm`** (outgoing SMTP) | `company` | Outlook/OAuth fields (`outlook_*`, `token`, `oauth_state`, `last_refreshed`) |
| **`IncomingHorillaMailConfigurationForm`** | `company` | Outgoing-only SMTP + Outlook/OAuth fields |
| **`OutlookMailConfigurationForm`** | `company` | SMTP fields (`host`, `port`, `from_email`, model `password`, TLS/SSL, …) + token/oauth |

Each configuration form declares a class-level **`password`** or **`outlook_client_secret`** `CharField` override. **`__init__`** required-field logic is unchanged.

**`HorillaMailConfigurationForm.clean`** rejects Use TLS and Use SSL both set to Yes. Display Name stays hidden while Dynamic Display Name is off. The outgoing backend (`HorillaDefaultMailBackend`) uses the triggering user's name as the sender only when Dynamic Display Name is off.

### Other

- **`DynamicMailTestForm`**, **`MailTemplateSelectForm`** — plain `forms.Form`; unchanged

---

## Signals (`signals.py`)

- `auto_delete_file_on_delete` (`post_delete`, `HorillaMailAttachment`) — removes the file from storage when an attachment row is deleted.
- `remember_deleted_message_id` (`pre_delete`, `IncomingMail`) — see [Deleting incoming mail](#deleting-incoming-mail-never-refetch-without-piling-up-rows) below.

---

## Incoming mail / Inbox (`IncomingMail`, `actions.py`, `fetch_hooks.py`)

### `IncomingMail` model

One row per message fetched from any `incoming`-channel `HorillaMailConfiguration` (IMAP or Outlook). Every message is persisted here regardless of whether any CRM auto-create pipeline is configured, so the Inbox screen always has something to list.

Key fields: `mail` (FK → `HorillaMailConfiguration`, `SET_NULL`), `sender_email`, `sender_name`, `subject`, `body`, `is_html_body` (drives preview rendering — HTML bodies render with `|safe` since they're sanitized; plain-text bodies render **without** `|safe`, relying on Django's default autoescaping — never mark a plain-text body safe), `cc`, `message_id` (unique, mirrors `Lead.message_id`'s role), `in_reply_to`, `references`, `received_at`.

- `clean()` / `save()`: sanitizes `subject` (`sanitize_plain_text`) always, and `body` (`sanitize_html`) only when `is_html_body` — a model-level backstop so any future write path (admin, shell, migration) gets the same protection even if it forgets to sanitize explicitly.
- `get_converted_actions()` / `mark_action_converted(key)`: read/write the inherited `additional_info["converted_actions"]` list — **no dedicated column** was added for this; it reuses `HorillaCoreModel`'s existing JSONField under a documented key.
- No FK from `Contact`/`Lead` back to `IncomingMail` (no `source_mail` field) — linking a converted record back to its source email is done the same way `Lead.message_id` already worked: `Contact`/`Lead` carry their own `message_id` field that matches the originating `IncomingMail.message_id`, looked up on demand.

### Action registry (`actions.py`) — "what can be done with this email"

`register_incoming_mail_action(key, label, handler, icon=None, permission=None, already_exists_check=None, warning_check=None)` lets another app (e.g. `leads`, `contacts`) contribute a row-action button to the Inbox list without `mail` importing it:

- `handler(incoming_mail, request)` — performs the create/dedup work; its return value is only used by the view to render a result, `mail` never inspects it.
- `already_exists_check(incoming_mail, request) -> bool` — lets the registering app report "this sender already has a record" even for a message that was itself never converted (e.g. a second email from an already-added Contact) — used to drive hide/disable logic on the Inbox action buttons.
- `warning_check(incoming_mail, request) -> str | None` — a non-blocking warning shown in the confirm step (e.g. "this sender already has a Contact, create a Lead anyway?"), mirroring how Salesforce/HubSpot/Zoho warn rather than block when creating a Lead for someone already a Contact.
- On success, the view stores `key` into `IncomingMail.additional_info["converted_actions"]` via `mark_action_converted`.

`get_incoming_mail_actions()` / `get_incoming_mail_action(key)` read the registry back. Today `leads` (`leads/registration.py`) registers `key="lead"` and `contacts` (`contacts/registration.py`) registers `key="contact"`, each pointing at its own `create_lead_from_email`/`create_contact_from_email` helper — but the Inbox view code itself has no hardcoded knowledge of either; if neither app were installed, the Inbox would simply show rows with no action buttons.

### Fetch hook registry (`fetch_hooks.py`) — "what to do while fetching"

Separate from the action registry: `register_incoming_mail_fetch_hook(get_config, get_allowed_senders, matches_filters, create_record, is_duplicate_message=None)` lets an app plug into the periodic fetch task itself (per-mailbox allow-list filtering + auto-create), consulted from `tasks.py`'s `fetch_emails_to_incoming_mail`:

- `resolve_fetch_hook_for_mailbox(mail_config)` returns the first registered hook whose `get_config()` claims that mailbox (non-`None`) — only one hook "owns" a given mailbox for filtering/auto-create, same semantics as the single `EmailToLeadConfig` per mailbox before this registry existed.
- `any_hook_reports_duplicate(message_ids)` is the exception — it's consulted across **every** registered hook regardless of which one owns the mailbox, since dedup-checking is cheap and additive (two CRM apps' dedup records should both count).
- `leads` registers here too (`EmailToLeadConfig.create_as` picks `"lead"` or `"contact"` — a simple either/or per mailbox config, not a combined mode) so the existing automatic pipeline and the new interactive Inbox buttons both end up calling the same underlying `create_lead_from_email`/`create_contact_from_email` helpers.

### Deleting incoming mail (never-refetch without piling up rows)

Deleting an `IncomingMail` row from the Inbox is a **genuine hard delete** — `InboxDeleteView` is a thin `HorillaSingleDeleteView` subclass (same generic confirm-modal flow as every other delete view in the codebase, e.g. `EmailToLeadConfigDeleteView`), and the row (plus its attachments, via cascade) is actually removed. Nothing is soft-deleted or left behind to accumulate indefinitely.

That raises an obvious problem: the periodic fetch task would just recreate the same message on its next poll. This is solved by a **separate, intentionally tiny** table instead of a `is_deleted` flag on `IncomingMail` itself:

- `DeletedIncomingMessageId` stores just `message_id` (unique) + `deleted_at`.
- `signals.py`'s `remember_deleted_message_id` (`pre_delete` on `IncomingMail`) writes a tombstone **before** the row is actually destroyed — this fires regardless of which code path deletes the row (this view, Django admin, a shell command), so "delete" stays permanent everywhere, not just from the Inbox UI.
- `tasks.py`'s duplicate check (`_is_duplicate_message`) consults `DeletedIncomingMessageId` first, before falling back to `any_hook_reports_duplicate`.

**Windowing, so neither table grows forever:**

- `TOMBSTONE_RELEVANCE_WINDOW = timedelta(days=7)` (defined in `models.py`, next to `DeletedIncomingMessageId`). The fetch task only ever searches a short recent window — a message older than this can never be seen again by a poll no matter what, so there's no point tombstoning it, and no point keeping an existing tombstone around past this point either.
- `remember_deleted_message_id` skips creating a tombstone at all if the deleted message's `received_at` is already older than the window — deleting an old message is simply a hard delete with nothing further needed, since it was never going to be re-fetched anyway.
- `tasks.py`'s `prune_expired_deleted_message_ids` (Celery task, scheduled daily at 03:00 via `celery_schedules.py`'s `prune-expired-deleted-message-ids-daily` entry) deletes any `DeletedIncomingMessageId` row whose `deleted_at` is older than the same window.

### Inbox views (`views/inbox.py`)

Mirrors the rest of the app's settings-screen conventions (same shape as `MailHistoryView`/`MailHistoryListView`):

- `InboxView` / `InboxNavbar` / `InboxListView` — settings shell, navbar, and list (`model = IncomingMail`, ordered `-received_at`). Row actions combine the dynamic CRM actions from `get_incoming_mail_actions()` with a static **Delete** action.
- Per-row action visibility: every registered action **always shows**, and is **disabled** (never hidden) once it is blocked — already converted on this row, or the registering app's `already_exists_check` says this sender already has a record. The tooltip names which conversion is unavailable. `_is_action_blocked` takes an optional `_cache` dict so the same (action, row) check runs once per page render.
- `InboxRunActionView` — single generic confirm/execute endpoint for any registered action, keyed by `pk` + action `key`; looks the action up via `get_incoming_mail_action(key)`, checks its `permission`, renders `warning_check`'s output (if any) on the confirm step, and calls `handler` on submit. Requires an HTMX request. The lead action is extended by `horilla_crm.leads.view_extensions.InboxAddAsLeadExtension`: the confirm step asks for an owner and whether to assign using rules, then `create_lead_from_email` uses that choice. See [mail to lead](../../../horilla_crm/leads/mail_to_lead.md).
- `InboxPreviewView` — full message detail modal. Splits attachments into inline-image vs. regular-file lists; `_was_embedded_in_body(attachment)` checks whether the attachment's actual file URL appears in the (already `cid:`-resolved) body, rather than trusting the stored `is_inline` flag alone — an attachment can be legitimately flagged inline by its `Content-Disposition` yet never actually be referenced in the body, in which case it should still show as a visible/downloadable attachment.
- `InboxDeleteView` — see [Deleting incoming mail](#deleting-incoming-mail-never-refetch-without-piling-up-rows) above.

Settings menu: **Mail** section now has **Outbox** (renamed from "Mail History" — it only ever showed outgoing `HorillaMail` rows; label-only change, URL/view unchanged) followed by **Inbox** (`mail.view_incomingmail` permission).

### Fetch task notes (`tasks.py`)

- `fetch_from_imap` / `fetch_from_outlook`: open the mailbox connection, list candidate messages, and isolate each message's processing in its own try/except so one malformed message can't abort the whole mailbox's run; IMAP connections are released via `try`/`finally` regardless of outcome.
- CC recipients are captured and stored (`IncomingMail.cc`); inline `cid:` image references in HTML bodies are rewritten post-save to the real attachment URLs (`_resolve_inline_cid_images`).
- Non-UTF-8 charsets are handled explicitly when decoding MIME parts (`_decode_part_payload`) rather than assuming UTF-8.
- `use_ssl`/`use_tls` are read from the mailbox's own `HorillaMailConfiguration` fields rather than hardcoded.

---

## Scheduler (`scheduler.py`)

Registers APScheduler / Celery beat entries for mailbox sync or retry queues (implementation-specific—read module).

---

## Open tracking (`services.py`, `views/core/track.py`)

Outbound HTML from **`HorillaMailManager.send_mail()`** appends a 1×1 tracking pixel when the body is HTML:

1. **`reverse("mail:track_open", kwargs={"uid": str(mail.tracking_uid)})`** — built via `horilla.urls.reverse` (not `django.urls`).
2. **`SITE_URL`** from settings, or the current request's absolute URI (honours `X-Forwarded-Host` / `X-Forwarded-Proto` for ngrok and reverse proxies).
3. An invisible `<img>` tag is appended to the HTML body before SMTP send.

**`TrackOpenView`** (`mail/track-open/<uuid:uid>/`, name `mail:track_open`):

- Public GET endpoint (no login).
- Looks up `HorillaMail` by `tracking_uid`.
- A direct visit (`Sec-Fetch-Dest` of `document`, `iframe` or `frame`) is a 404 and does not count as an open. The pixel is only meant to load as an image inside the message.
- A logged-in user who sent the mail (`send_by` or `created_by`) previewing it in Horilla is a self-open and does not set `opened_at`.
- On the first real open: sets `opened_at`, updates `mail_status` to `"opened"`, saves.
- Returns a transparent GIF via **`horilla.web.HttpResponse`** (`content_type="image/gif"`). The outgoing-server form requires add permission.

Model fields involved: `HorillaMail.tracking_uid` (UUID, set on create), `opened_at`, and `mail_status` choice `"opened"`.

---

## Mail templates list & preview

### `MailTemplateListView`

- Gated by **`mail.view_horillamailtemplate`**.
- Title column `col_attrs` load the detail modal only when the user has that view permission (pointer/HX attrs omitted otherwise).
- Row actions use the correct permission codenames (`change_horillamailtemplate`, `delete_horillamailtemplate`).

### Preview (`views/core/preview_draft.py`)

- Preview renders **`rendered_subject` / `rendered_body`** when present, otherwise a fresh render; HTML is passed through **`sanitize_html`** before display.
- Access checks ensure the user can only preview drafts/messages they are allowed to see (IDOR guard on the mail row).
- Template-error / XSS false positives surface via `mail_preview_error.html` rather than treating safe content as blocked.

---

## Typical flows

1. Admin configures **outgoing** server → the mail backend selects a configuration
   scoped to the **active company** with `mail_channel="outgoing"` (preferring the
   primary), not an unrelated or first-global row.
2. **HorillaAutomation** with `delivery_channel=mail` renders **`HorillaMailTemplate`** with context from triggering instance → `HorillaMail` row created → Celery sends SMTP (pixel injected when HTML).
3. User composes one-off mail from record detail → same models, different view.
4. Recipient opens the message → browser loads the pixel → `TrackOpenView` records the first open.
5. Admin configures an **incoming** mailbox → `fetch_emails_to_incoming_mail` (Celery, every minute) persists each new message as `IncomingMail`; any registered fetch hook (e.g. `leads`' `EmailToLeadConfig`) additionally applies its own filters and auto-creates a Lead or Contact per its `create_as` setting.
6. A user opens **Inbox**, reviews a fetched message, and clicks **Add as Contact** / **Add as Lead** on a row — same underlying create/dedup helpers as the automatic pipeline, just triggered interactively via `InboxRunActionView`.
7. A user deletes a message from the Inbox → hard-deleted immediately; a small `DeletedIncomingMessageId` tombstone (pruned after `TOMBSTONE_RELEVANCE_WINDOW`) stops it from being silently refetched on the next poll.

---

## Delivery channel

`registration.py` registers `MailChannel` (`delivery.py`, key `mail`, label "Send as Mail") with `horilla.registry.delivery`. Automations call `MailChannel.send` through that registry. Mail history navbar text uses the product name from the branding module.

---

## Insert Fields modal

`HorillaFieldSelectionView` (`horilla/contrib/generics/views/field_selection.py`, URL `generics:field_selection`, shared with notification templates) lists a model's fields for the template editor; its context carries `model_fields`, `foreign_key_fields` and `reverse_relation_fields`. Fields that aren't model columns are appended to `model_fields` by an `_inherit_view` extension (entries with `name`, `verbose_name`, `field_type`, `template_syntax`, `is_foreign_key`, `is_relation`); their `template_syntax` uses the generic `extension_field` filter, e.g. `{{ instance|extension_field:"cf_1" }}` — see [field_filters.md](../generics/templatetags/horilla_tags/field_filters.md#group-9-extension-supplied-fields).

---

## Related documentation

- Automations delivery: [../automations/automations.md](../automations/automations.md)
- Notifications (parallel channel): [../notifications/notifications.md](../notifications/notifications.md)
- Generic delete flow (`HorillaSingleDeleteView`): [../generics/views/delete.md](../generics/views/delete.md)
- CRM auto-pipeline that plugs into this app's registries: [Mail to Lead / Contact](../../../horilla_crm/leads/mail_to_lead.md), [Mail to Contact](../../../horilla_crm/contacts/mail_to_contact.md)

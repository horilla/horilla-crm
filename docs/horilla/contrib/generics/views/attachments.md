# Horilla Attachments Views (`horilla_generics/views/attachments.py`)

## Purpose

`attachments.py` renders the **Notes and Attachments** tab as a chat-style stream:

- notes and files for a record, grouped as Pinned, then Today, Yesterday, and older days
- an inline composer on the tab (no create modal)
- in-place edit of one entry
- pin and unpin
- delete

It uses `HorillaAttachment` and `HorillaContentType` (`horilla.contrib.core.models`). Templates:

- `notes_attachments.html` — the stream
- `forms/notes_attachment_composer.html` — the box at the top
- `forms/notes_attachment_inline_edit.html` — the editor that replaces one entry
- `partials/notes_entry_bubble.html` — one saved entry

### XSS sanitization on save

`HorillaAttachment.save()` sanitizes user-controlled text before persist:

- **`title`** → `sanitize_plain_text()` (no HTML)
- **`description`** → `sanitize_html()` (bleach allowlist)

Helpers live in `horilla.contrib.utils.methods` — see [../../utils/utils.md](../../utils/utils.md). Model `save()` is the durable XSS control for stored attachments.

---

## Module components

Classes in this file:

1. `HorillaNotesAttachementSectionView(DetailView)`
2. `HorillaNotesAttachmentCreateView(FormView)`
3. `HorillaNotesAttachmentPinView(View)`
4. `HorillaNotesAttachmentDeleteView(HorillaSingleDeleteView)`

The section view spells `Attachement` the same way the class does. URL names use the `generics` namespace (`generics:notes_attachment_create`, `notes_attachment_edit`, `notes_attachment_pin`, `notes_attachment_delete`).

There is no list view inside the tab and no detail modal. Search and the All / Notes / Files filter run in the page.

---

## `HorillaNotesAttachementSectionView`

### Access

- `@htmx_required`
- the record must pass `check_record_access`; otherwise `403.html`

### Template

- `template_name = "notes_attachments.html"`
- `context_object_name = "obj"`

### `get(...)`

1. Load the parent with `get_object()`.
2. Query `HorillaAttachment` with `history_q(self.object, request.user)` (this record plus rows from `get_history_sources()`).
3. Remember the parent for history labels (`remember_history_parent`).
4. Build one card per row, newest first. A row is a **file** when `file` is set, otherwise a **note**. A row from another record (`is_foreign_row`) or a locked parent (`is_record_locked`) cannot be edited, deleted, or pinned.
5. Edit, delete, and pin also need change or delete access on the parent. A user with only change-own must own the entry (`created_by` in `get_allowed_user_ids`).
6. Pinned rows go in a **Pinned** group. The rest are grouped by day: Today, Yesterday, or a formatted date.
7. `can_add_attachment` is true when the user can change the parent. The composer form is then `HorillaAttachmentForm(inline=True)`.

### Context

| Variable | Meaning |
|---|---|
| `obj` | the parent record |
| `attachment_groups` | `[{label, cards, pinned?}, ...]` |
| `attachment_total` | count shown in the badge |
| `can_add_attachment` | whether the composer is rendered |
| `form` / `form_url` / `composer_query` | the inline composer, when adding is allowed |

Each card has `obj`, `foreign`, `can_edit`, `can_delete`, `can_pin`, and `kind` (`note` or `file`).

---

## `HorillaNotesAttachmentCreateView`

### Access

- `@htmx_required`
- `LoginRequiredMixin`, `FormView`
- add or change access on the parent record (`check_related_object_permission`)

### Templates

- create: `forms/notes_attachment_composer.html`
- edit (`pk` in the URL): `forms/notes_attachment_inline_edit.html`
- `form_class = HorillaAttachmentForm`, `inline=True`
- an edit form uses `auto_id = edit_<pk>_%s` so its fields do not clash with the composer

### Create vs edit

Create reads `model_name` and `object_id` from the query string. Edit loads `HorillaAttachment` by `pk`. A missing row returns a script that reloads messages and closes the modal.

`GET` with `pk` and `view` cancels an in-place edit and renders `partials/notes_entry_bubble.html` unchanged.

### `form_valid`

On create, sets `created_by`, `object_id`, `content_type`, and `company = get_active_company(request)`, then returns a script that clicks `#tab-notes-attachments` so the stream reloads.

On edit, saves and returns only `partials/notes_entry_bubble.html` for that entry, so the stream keeps its scroll position.

Query string for the composer:

```text
?model_name=lead&object_id=42&inline=1
```

`model_name` is resolved with `HorillaContentType.objects.get(model=model_name.lower())`.

---

## `HorillaNotesAttachmentPinView`

`POST` `generics:notes_attachment_pin` flips `is_pinned` and reloads the notes tab.

The user must be able to change the parent, and the parent must not be locked. Change-own users can pin only an entry they created (or one with no `created_by`). Anyone else gets an error script and no change.

---

## `HorillaNotesAttachmentDeleteView`

Inherits `HorillaSingleDeleteView` with `check_delete_permission = False`. `dispatch` allows the delete when the user is a superuser, or has change access on the parent (change-own only for an entry they created). `get_post_delete_response()` returns `HxTriggerResponse(extra="closeContentModal();")`.

---

## End-to-end

1. The detail tab includes the section view for the record.
2. The section renders the composer (when `can_add_attachment`) and the grouped stream.
3. Saving the composer posts to `generics:notes_attachment_create` and reloads the tab.
4. Edit replaces that entry in place. Pin reloads the tab so the Pinned group updates. Delete closes the confirm modal.

---

## Practical notes

- A locked parent and a row that belongs to another record cannot be edited, pinned, or deleted. The row still shows, with a source label when it comes from `get_history_sources()`.
- Change and delete follow the parent record, not a separate attachment permission on the section view. Create and edit still refuse a user who cannot change that parent.
- All of these views require HTMX (`htmx_required`).

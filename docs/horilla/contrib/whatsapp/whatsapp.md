# WhatsApp (`horilla.contrib.whatsapp`)

Company WhatsApp Business messaging: accounts, live chat on a record's Activity tab, templates, flows, bot rules, and an automation delivery channel.

## Webhooks

`api/webhook_views.py` receives Meta's callbacks. `WhatsAppAccount.verify_webhook_signature` checks the `X-Hub-Signature-256` header against the raw body and the account's app secret. A missing secret, a missing header, or a mismatch is rejected. The signature is `sha256=` plus the HMAC.

## Conversations

`_can_access_conversation` (`views/inbox.py`) follows the related record's view or change access when the conversation is linked. A conversation with no live related record (never linked, or the record was deleted) requires `whatsapp.view_whatsappconversation` or `whatsapp.change_whatsappconversation`. A superuser still passes. It is not open to every signed-in user.

The API viewsets enforce the model's permissions and stay in the requester's company.

## Inbox and automations

Empty inbox states (no account, no messages) use `components/empty_state.html`. The WhatsApp delivery channel stays available on automations.

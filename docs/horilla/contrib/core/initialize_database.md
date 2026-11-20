# Initialize Database workflow (`horilla.contrib.core.views.initialiaze_database`)

First-run onboarding runs only while no users exist in the database. Views are gated with **`@db_initialization`** and a session password (`settings.DB_INIT_PASSWORD`). See [decorators — `db_initialization`](../../utils/decorators.md#-db_initialization).

---

## Progress steps

`ProgressStepsMixin` + `BASE_STEPS` drive the step indicator in init templates. Each step shows a loading spinner while it submits.

| Step | View | Purpose |
|------|------|---------|
| 1 | `InitializeDatabase` | DB init password |
| 2 | `InitializeDatabaseUser` | Superuser sign-up |
| 3 | `InitializeDatabaseCompany` | First company |
| 4 | `InitializeRoleView` | Role hierarchy |
| 5 | Lead stages init (CRM) | `leads:load_lead_stages` / `LoadLeadStagesView` (`InitializeDatabaseLeadStages` at `leads:initialize_lead_stages`) |
| 6 | Opportunity stages init (CRM) | `opportunities:load_opp_stages` |

After company creation, **`company_created`** listeners return an HTMX script fragment that closes the wizard modal, reloads the settings list, opens the content modal, and loads the lead-stage setup URL.

### Modal transition (`ScriptResponse.reload_close_and_load_content_modal`)

Used when a signal receiver must chain **close modal → reload list → open content modal → HTMX load URL**. The former `reload_and_load_url_script.html` templates were removed; receivers return `ScriptResponse.reload_close_and_load_content_modal(url)` (`horilla/web/response.py`):

| Receiver | `url` |
|----------|-------|
| `handle_company_created` (`horilla_crm/leads/signals.py`) | `leads:load_lead_stages` |
| `handle_lead_stage_group_created` (`horilla_crm/opportunities/signals.py`) | `opportunities:load_opp_stages` |

The response runs:

```javascript
closeModal();
$('#reloadButton').click();
openContentModal();
// dynamic div: hx-get url → #contentModalBox
```

`ScriptResponse(reload=True, close=True)` alone does **not** replace this pattern — it does not call `openContentModal()` or inject the HTMX load into `#contentModalBox`. See [web.md — Modal transition after init signals](../../web/web.md#modal-transition-after-init-signals).

---

## Go To Home (skip remaining steps)

Users who finish **user sign-up** and **company setup** can exit the wizard without completing Role, Lead Stages, or Opportunity Stages.

| Piece | Location |
|-------|----------|
| View | `InitializeDatabaseGoHomeView` |
| URL | `core:initialize_database_go_home` → `initialize-database-go-home/` |
| Button partial | `initialize_database/go_to_home_button.html` |
| Included on | `initialize_role.html`, `lead_stages_initialize.html`, `oppor_stages_initialize.html` |

### Button UX

The link is styled as a text action (`text-sm text-primary-600 hover:underline`), not a filled button. **Next Step** on the Role step remains the primary filled control.

### Guards

`InitializeDatabaseGoHomeView.get()` requires:

1. At least one `User` and one `Company` in the database.
2. Otherwise → error message and redirect to the user or company init step.

On success:

1. Resolves the active `Company` from `request.user.company_id`, session `company_id`, or `request.user.company`.
2. Sends **`initialize_database_go_home`** (see below).
3. Clears session keys `db_password` and `company_id`.
4. Redirects to **`settings.DEFAULT_HOME_REDIRECT`** (typically `/dashboard/?section=home`).

---

## Signal: `initialize_database_go_home`

Defined in **`horilla.contrib.core.signals`**. Fired when the init wizard exits early via Go To Home.

```python
initialize_database_go_home.send(
    sender=InitializeDatabaseGoHomeView,
    company=company,
    request=request,
)
```

| Kwarg | Type | Role |
|-------|------|------|
| `company` | `Company` | Company to seed stages for |
| `request` | `HttpRequest` | Used for `created_by` on new rows |

### Listeners (CRM)

| Receiver | Module | Behavior |
|----------|--------|----------|
| `ensure_default_lead_stages_on_go_home` | `horilla_crm.leads.signals` | Creates rows from **`DEFAULT_LEAD_INIT_STAGES`** when no `LeadStatus` exists for the company |
| `ensure_default_opportunity_stages_on_go_home` | `horilla_crm.opportunities.signals` | Creates rows from **`DEFAULT_OPPORTUNITY_INIT_STAGES`** when no `OpportunityStage` exists; sets `stage_type` (`open` / `won` / `lost`) from probability |

Both receivers **no-op** if stages already exist, so completing the full wizard is unchanged.

Stage constants and full wizard flow:

- [Lead stages](../../../horilla_crm/leads/lead_stages.md)
- [Opportunity stages](../../../horilla_crm/opportunities/opportunity_stages.md)

---

## Related signals

| Signal | When | Response |
|--------|------|----------|
| `company_created` | New company saved | `ScriptResponse.reload_close_and_load_content_modal` → lead stages modal |
| `lead_stage_created` | Lead stage group saved | Init wizard step or `reload_close_and_load_content_modal` → opp stages modal |
| `opp_stage_created` | Opportunity stage group saved | — |

---

## Source files

| File | Role |
|------|------|
| `horilla/contrib/core/views/initialiaze_database.py` | All init + Go Home views |
| `horilla/contrib/core/signals.py` | `initialize_database_go_home` |
| `horilla/contrib/core/urls.py` | URL routes |
| `horilla/contrib/core/progress.py` | Step definitions |
| `horilla/contrib/core/templates/initialize_database/` | Init templates + Go Home button |

---

## Related documentation

- [Core app index](core_app.md)
- [`db_initialization` decorator](../../utils/decorators.md#-db_initialization)
- [Settings list shell](settings_list_shell.md) (settings pages after onboarding)
- [Modal transition scripts](../../web/web.md#modal-transition-after-init-signals)

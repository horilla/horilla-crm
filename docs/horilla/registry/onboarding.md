# Onboarding Steps Registry (`registry/onboarding.py`)

## Purpose

`horilla/registry/onboarding.py` collects the steps of the home page **"Get started"** guide. Every installed app can contribute steps; the dashboard app turns them into the stepper banner (see [Dashboard — Get started guide](../contrib/dashboard/dashboard.md#get-started-guide-home-page)).

The module imports no app and no model, so the guide keeps working, with no import error, when an optional app (for example `horilla_crm`) is not installed.

## Declaring a step

One subclass of `OnboardingSteps` is one step. Put it in the app's own `onboarding.py` and add `"onboarding"` to that app's `auto_import_modules`; `AppLauncher` imports it only when the app is installed.

```python
# horilla_crm/leads/onboarding.py
from horilla.registry.onboarding import OnboardingSteps
from horilla.utils.translation import gettext_lazy as _

from .models import LeadStatus


class LeadStagesOnboarding(OnboardingSteps):
    key = "lead_stages"
    title = _("Lead Stages")
    headline = _("Set up your lead stages")
    description = _("Define the stages your leads move through.")
    url_name = "leads:lead_stage_view"
    icon = "fa-filter"
    order = 50
    model = LeadStatus
```

```python
class LeadsApp(AppLauncher):
    auto_import_modules = ["registration", "signals", "menu", "dashboard", "onboarding"]
```

### Attributes

| Attribute | Required | Meaning |
|-----------|----------|---------|
| `key` | yes | Unique across all apps (`"mail_server"`). A duplicate raises `ImproperlyConfigured`. |
| `title` | yes, unless `model` is set | Short label under the step circle. Defaults to the model's `verbose_name_plural`. |
| `url_name` | yes | URL name of the page opened by **Set Up Now** and by clicking the step. |
| `model` | yes, unless `is_done()` is overridden | Model whose records prove the step is done. |
| `headline` | no | Call to action on the next-step card (`"Connect your mail server"`). Falls back to `title`. |
| `description` | no | One line under the headline. Must not repeat it. |
| `icon` | no | Font Awesome class for the next-step card (default `fa-circle`). |
| `permission` | no | Permission needed to open `url_name`; the step is hidden and not counted without it. Defaults to the model's view permission, read from the model (`<app_label>.view_<model_name>`), so a swapped user model needs no hand-typed name. |
| `order` | no | Lower first, across all apps (default 100). |
| `min_count` | no | Records needed to count as done (default 1). |
| `abstract` | no | `True` on an intermediate base class that must not register. |

### Hooks a subclass may override

| Hook | Default | Override for |
|------|---------|--------------|
| `get_permission()` | the `permission`, else the model's view permission | A different permission rule |
| `is_visible(user, company)` | the user holds `get_permission()` (or it needs none) | A different visibility rule |
| `get_queryset(company)` | `model.all_objects.filter(company=company)` | Narrowing the records that count, e.g. active outgoing mail configurations only |
| `is_done(company, user)` | `get_queryset(...)` has at least `min_count` records | A rule that is not "records exist", e.g. Company is done once its name, email and country are filled in |

`get_queryset()` uses `all_objects` with an explicit `company=` so the answer stays right in "show all companies" mode. A rule that raises is not caught: the error shows on the home page.

## `model`: import the class, not a string

Use the class (`model = LeadStatus`), not `"leads.LeadStatus"`.

- `onboarding.py` is imported from `AppLauncher.ready()`, which Django calls after every model is loaded, so the import is safe. Circular-import problems come from importing models at the top of `models.py` or `apps.py`, which this module never is.
- A wrong name fails when the server starts (`ImportError`). A string would fail only when the home page renders, and the guarded `is_done()` would hide it as "not done".
- Only the app's own `onboarding.py` imports its models; the registry and the dashboard import neither.

Use a string reference only if a step must point at an optional app's model.

## API

### `get_onboarding_steps()`

Returns instances of the registered steps of the **installed** apps, sorted by `(order, key)`. A class whose module is not in an installed app is skipped. An incomplete class (missing `key`, `title`, `url_name`, or both `model` and a custom `is_done()`) or a duplicate `key` raises `ImproperlyConfigured`.

### `build_onboarding(user, company, skipped=())`

Returns the guide for the home page as a dict (`steps`, `total`, `done_count`, `percent`, `next_step`, `company_name`) or `None` when there is nothing to show: not a superuser, no company, no visible step, or every visible step done. A step the user may not see, or whose URL does not exist, is left out. `skipped` holds the keys of the steps pressed "Skip For Now"; the next step is the first unfinished one that is not skipped.

## Steps shipped

| `order` | `key` | Owner | Done when the company has… | Permission |
|--------:|-------|-------|----------------------------|------------|
| 10 | `company` | core | its name, email and country filled in | `core.view_company` |
| 20 | `roles` | core | a `Role` | `core.view_role` |
| 30 | `users` | core | a user | `core.view_horillauser` |
| 40 | `mail_server` | mail | an active outgoing `HorillaMailConfiguration` | `mail.view_horillamailconfiguration` |
| 50 | `lead_stages` | leads | a `LeadStatus` | `leads.view_leadstatus` |
| 55 | `opportunity_stages` | opportunities | an `OpportunityStage` | `opportunities.view_opportunitystage` |
| 60 | `leads` | leads | a `Lead` | `leads.view_lead` |

### Order ranges

| Range | Owner |
|-------|-------|
| 10–39 | `core` |
| 40–49 | `mail` and other platform apps |
| 50–99 | CRM apps |
| 100+ | Anything else (default) |

Ties are broken by `key`.

## Related documentation

- Dashboard guide, per-company state and templates: [../contrib/dashboard/dashboard.md](../contrib/dashboard/dashboard.md#get-started-guide-home-page)
- Auto-imported app modules: [../apps/apps.md](../apps/apps.md)

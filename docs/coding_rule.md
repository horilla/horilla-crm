Repository coding rules. Add new topics as additional `##` sections below.

---

## Avoid direct Django usage

Horilla re-exports common Django APIs under `horilla.*` packages so app code has one consistent import path.

**Rule:** If Horilla exposes the symbol (see table below), import from Horilla. If not, import from Django or the third-party package as usual.

| Situation | Import from |
|-----------|-------------|
| Symbol listed in a Horilla package below | `horilla.<package>` |
| Symbol not re-exported by Horilla | `django.*` (or third-party) |
| Code that implements the re-export | `django.*` only inside the Horilla wrapper module |

### Horilla import map (use these instead of Django)

#### Database & ORM

| Import from | Instead of | Symbols (common) |
|-------------|------------|------------------|
| `horilla.db` | `django.db` | `models`, `transaction`, `connection` |
| `horilla.db.models.signals` | `django.db.models.signals` | `post_save`, `pre_save`, `post_delete`, `m2m_changed`, … |
| `horilla.db.models` | `django.db.models` | `Q`, `F`, `Count`, `ForeignKey`, … (via `horilla.db.models` re-export) |

Details: [docs/horilla/contrib/core/models.md](horilla/contrib/core/models.md)

#### HTTP, views, URLs

| Import from | Instead of | Symbols (common) |
|-------------|------------|------------------|
| `horilla.web` | `django.http` | `HttpResponse`, `JsonResponse`, `QueryDict`, `Http404`, `StreamingHttpResponse`, `HttpNotFound`, `RedirectResponse`, … |
| `horilla.views.generic` | `django.views.generic` | `FormView`, `View`, `TemplateView`, `ListView`, `DetailView` |
| `horilla.shortcuts` | `django.shortcuts` | `redirect`, `render`, `get_object_or_404` |
| `horilla.urls` | `django.urls` | `path`, `re_path`, `include`, `reverse`, `reverse_lazy`, `resolve` |

> **Note:** The platform package was renamed from `horilla.http` to **`horilla.web`**. The old name shadowed Python’s standard-library `http` module when Django management commands ran from inside the `horilla/` directory (for example `makemessages`). Update any remaining `from horilla.http import …` imports to `from horilla.web import …`. Do not keep a `horilla/http/` compatibility shim — it would restore the import conflict.

Details: [docs/horilla/web/web.md](horilla/web/web.md), [docs/horilla/shortcuts/shortcuts.md](horilla/shortcuts/shortcuts.md), [docs/horilla/urls/urls.md](horilla/urls/urls.md)

#### Apps, auth, exceptions

| Import from | Instead of | Symbols (common) |
|-------------|------------|------------------|
| `horilla.apps` | `django.apps` | `AppLauncher`, `AppConfig`, `apps` (registry) |
| `horilla.auth.models` | `django.contrib.auth.models` | `User` (wraps `AUTH_USER_MODEL`) |
| `horilla.auth.mixins` | `django.contrib.auth.mixins` | `LoginRequiredMixin` (HTMX-aware), `login_redirect` — the only module that imports Django's mixin; never call `redirect_to_login` directly. A normal request gets a 302; an HTMX request gets **204** with `HX-Redirect` so the login page is not swapped into a fragment |
| `horilla.core.exceptions` | `django.core.exceptions` | `ValidationError`, `PermissionDenied`, `ObjectDoesNotExist`, … |

Details: [docs/horilla/apps/apps.md](horilla/apps/apps.md), [docs/horilla/contrib/core/user_model.md](horilla/contrib/core/user_model.md), [docs/horilla/core/exceptions.md](horilla/core/exceptions.md)

#### Utilities (i18n, time, HTML, text, functional, decorators)

| Import from | Instead of | Symbols (common) |
|-------------|------------|------------------|
| `horilla.utils.translation` | `django.utils.translation` | `gettext_lazy`, `gettext`, `ngettext_lazy`, `activate`, `override`, … |
| `horilla.utils` or `horilla.utils.timezone` | `django.utils.timezone` | `timezone.now()`, `make_aware`, `localtime`, `UTC`, … |
| `horilla.utils.html` | `django.utils.html` | `format_html`, `format_html_join`, `escape`, `strip_tags`, `conditional_escape`, … |
| `horilla.utils.text` | `django.utils.text` | `slugify`, `Truncator`, `capfirst`, `get_valid_filename`, … |
| `horilla.utils.functional` | `django.utils.functional` | `cached_property`, `lazy`, `Promise`, `SimpleLazyObject`, … |
| `horilla.utils.decorators` | `django.utils.decorators` + custom | `method_decorator`, `permission_required`, `htmx_required`, `db_initialization`, … |

Details: [docs/horilla/utils/translation.md](horilla/utils/translation.md), [docs/horilla/utils/html.md](horilla/utils/html.md), [docs/horilla/utils/text.md](horilla/utils/text.md), [docs/horilla/utils/functional.md](horilla/utils/functional.md), [docs/horilla/utils/utils.md](horilla/utils/utils.md), [docs/horilla/utils/decorators.md](horilla/utils/decorators.md)

#### Framework types (not Django re-exports — still use Horilla)

| Import from | Role |
|-------------|------|
| `horilla.contrib.core.models` | `HorillaCoreModel`, `CompanyFilteredManager`, … |
| `horilla.contrib.generics` | `HorillaListView`, `HorillaModelForm`, … |
| `horilla.menu` | `floating_menu`, `main_section_menu`, … |
| `horilla.registry.feature` | `register_model_for_feature`, `FEATURE_REGISTRY` |

When adding a new Horilla wrapper, document it under `docs/horilla/<package>/` and add a row to the tables above.

### Examples

```python
# ❌ Avoid when Horilla re-exports the symbol
from django.db import models, transaction
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.functional import cached_property
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.apps import apps

# ✅ Prefer — Horilla import map
from horilla.db import models, transaction
from horilla.web import HttpResponse
from horilla.urls import reverse_lazy
from horilla.shortcuts import render, redirect
from horilla.utils.translation import gettext_lazy as _
from horilla.utils import timezone
from horilla.utils.html import format_html, escape
from horilla.utils.text import slugify
from horilla.utils.functional import cached_property
from horilla.core.exceptions import ValidationError
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.apps import apps, AppLauncher
from horilla.utils.decorators import permission_required, htmx_required

# ✅ OK — not wrapped by Horilla (use Django directly)
from django.db import IntegrityError, migrations
from django.views.generic import DeleteView
from django.db import close_old_connections
```

`LoginRequiredMixin` is re-exported from `horilla.auth.mixins`. The wrapper module is the only place that imports it from Django. Views, including CRM and contrib, import it from Horilla.

### Still import from Django when Horilla does not wrap it

Examples (not exhaustive):

- `DeleteView` and other CBV bases not re-exported
- `IntegrityError`, `migrations`, `close_old_connections`
- Third-party: `djmoney`, `rest_framework`, Channels, etc.
- Migration files: `from django.db import migrations`

### Exceptions (intentional `django.*` imports)

- **Migrations** — `from django.db import migrations` in `migrations/*.py` only.
- **Early bootstrap** — e.g. `horilla/extension/models/metaclass.py` uses Django `Field` only (no `horilla.db` at import time) to avoid `AppRegistryNotReady`; see [docs/Plan_HORILLA_INHERIT_MIGRATION.md](Plan_HORILLA_INHERIT_MIGRATION.md).
- **Re-export implementation** — only the Horilla wrapper module (e.g. `horilla/db/__init__.py`, `horilla/web/__init__.py`) may import the symbol from Django.
- **Gaps** — any symbol not in the Horilla package’s `__all__` / docs stays on Django.

### Import order and section comments

Group imports in this order. Use the **exact** section headers below so reviewers and tools can scan files consistently.

| Order | Section header | What goes here |
|-------|----------------|----------------|
| 1 | `# Standard library imports` | `import os`, `from pathlib import Path`, … |
| 2 | `# Third-party imports (Django)` | `django.*` only (symbols **not** re-exported by Horilla) |
| 3 | `# Third-party imports (other)` | Optional — `rest_framework`, `djmoney`, `celery`, … |
| 4 | `# First party imports (Horilla)` | **Every** `from horilla…` / `import horilla…` import |
| 5 | `# Local imports` | Same-app modules — relative imports (`.models`, `.forms`) or `horilla_crm.*` / client extension apps |

**Mandatory:** Any import whose top-level package is `horilla` (`horilla.db`, `horilla.contrib.*`, `horilla_crm` does **not** apply — that is CRM app code, usually under **Local imports**) must appear only under `# First party imports (Horilla)`, never under Django or third-party blocks.

Within **stdlib**, **Django**, and **other** sections, sort imports alphabetically by module path.

Within **`# First party imports (Horilla)`**, use **two sub-blocks** (do not mix):

| Sub-order | Packages | Notes |
|-----------|----------|--------|
| **1 — Platform** | `horilla.apps`, `horilla.auth`, `horilla.core`, `horilla.db`, `horilla.web`, `horilla.menu`, `horilla.registry`, `horilla.shortcuts`, `horilla.urls`, `horilla.utils`, … | Top-level Horilla infrastructure — **not** `horilla.contrib` |
| **2 — Contrib apps** | `horilla.contrib.*` | Always **last** in the Horilla block; contrib is a bundle of horilla apps (core, generics, mail, …) |

Sort **alphabetically by full module path** inside each sub-block. Typical platform order (all before any `horilla.contrib` line):

```text
horilla.apps → horilla.auth → horilla.core → horilla.db → horilla.web → horilla.menu
→ horilla.registry → horilla.shortcuts → horilla.urls → horilla.utils → …
```

#### Example (correct)

```python
# Standard library imports
import json
import logging

# Third-party imports (Django)
from django.contrib import messages
from django.db import IntegrityError
from django.views.generic import DeleteView

# Third-party imports (other)
from djmoney.models.fields import MoneyField

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.db import models, transaction
from horilla.web import HttpResponse
from horilla.views.generic import View
from horilla.shortcuts import redirect, render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import permission_required
from horilla.utils.translation import gettext_lazy as _
from horilla.contrib.core.models import HorillaCoreModel
from horilla.contrib.generics.views import HorillaListView

# Local imports
from .models import Lead
```

#### Anti-pattern (wrong)

```python
# Third-party imports (Django)
from django.views.generic import DeleteView
from horilla.db import transaction  # ❌ horilla.* must not be in Django block

# First party imports (Horilla)
from horilla.contrib.generics.views import HorillaListView  # ❌ contrib before platform
from horilla.db import models
```

Use `# First party imports (Horilla)` (not `First party / Horilla` or other variants) in new and touched files.

See also [.claude/rules/horilla-coding-style.md](../.claude/rules/horilla-coding-style.md).

### Reviewer checklist

- [ ] All `horilla.*` imports are under `# First party imports (Horilla)` only.
- [ ] Within First party: platform (`horilla.db`, `horilla.auth`, `horilla.web`, …) before `horilla.contrib.*`.
- [ ] Django block contains only `django.*` (and no `horilla.*`).
- [ ] Database: `models`, `transaction`, `connection`, and model signals use `horilla.db` / `horilla.db.models.signals`.
- [ ] HTTP/views: responses and shortcuts use `horilla.web` / `horilla.shortcuts` when listed above.
- [ ] URLs: `path`, `reverse`, `reverse_lazy` use `horilla.urls`.
- [ ] i18n / time / HTML / text / functional / decorators: use `horilla.utils.translation`, `horilla.utils.timezone` (or `from horilla.utils import timezone`), `horilla.utils.html`, `horilla.utils.text`, `horilla.utils.functional`, `horilla.utils.decorators`.
- [ ] User model and registry: `horilla.auth.models.User`, `horilla.apps.apps` — not `django.contrib.auth.models.User`.
- [ ] Exceptions: `horilla.core.exceptions` — not `django.core.exceptions` for re-exported types.
- [ ] Re-raised exceptions use `raise NewError(...) from exc` when translating caught errors (see [Exception chaining](#exception-chaining-raise--from)).
- [ ] `@cached_property` values are read via accessor methods or explicit resolution — not passed as descriptors into ORM filters (see [`@cached_property` on views](#cached_property-on-views)).
- [ ] Templates omit redundant `{% load static %}`, `{% load i18n %}`, and `{% load horilla_tags %}` (see [Django templates — built-in tag libraries](#django-templates--built-in-tag-libraries)).
- [ ] New direct `django.*` imports are justified (not in Horilla map) or documented.

---

## Exception chaining (`raise ... from`)

When handling a caught exception and raising a different one (validation error, `HttpNotFound`, `ValueError`, serializer error), chain the cause:

```python
except ValueError as exc:
    raise forms.ValidationError(_("Invalid JSON file.")) from exc
```

Do **not** swallow the original exception unless the handler fully recovers. Details and examples: [docs/horilla/core/exceptions.md](docs/horilla/core/exceptions.md#exception-chaining-raise--from).

---

## `@cached_property` on views

`horilla.utils.functional.cached_property` (re-export of Django’s helper) caches a **computed value** on the instance. The attribute name is not the value itself.

```python
@cached_property
def get_company_for_user(self):
    return self.request.active_company or Company.objects.filter(...).first()

def company_for_user(self):
    """Return the resolved company (or None)."""
    return self.get_company_for_user
```

| Pattern | Guidance |
|---------|----------|
| ORM filters / FK assignment | `company = self.company_for_user()` then `if company is not None:` |
| Boolean tests | Prefer `if company is not None:` over `if company:` when pylint W0125 flags constant-test false positives on ternaries |
| Currency / display fallbacks | Initialize default, then assign inside `if company is not None:` |

Example (forecast views): [docs/horilla_crm/forecast/forecast_type_tab.md](docs/horilla_crm/forecast/forecast_type_tab.md#forecasttypetabmixin--cached-context-accessors).

---

## Django templates — built-in tag libraries

Horilla registers common template tag libraries globally via `BUILTINS` in [`horilla/settings/base.py`](../horilla/settings/base.py). They are passed to Django as `OPTIONS["builtins"]` on the template engine.

**Rule:** Do **not** add `{% load static %}`, `{% load i18n %}`, or `{% load horilla_tags %}` at the top of templates. Those libraries are already available in every template.

| Built-in library | Provides (common) |
|------------------|-------------------|
| `django.templatetags.static` | `{% static %}`, `{% get_static_prefix %}`, … |
| `django.templatetags.i18n` | `{% trans %}`, `{% blocktrans %}`, `{% get_current_language %}`, … |
| `horilla.contrib.generics.templatetags.horilla_tags` | `{% has_perm %}`, `{% is_active %}`, `{% display_field_value %}`, … |

Other tag libraries (e.g. `{% load horilla_call_tags %}`, app-specific libraries) are **not** built in — use `{% load … %}` only when you need tags from those modules.

### Examples

```django
{# ✅ OK — no {% load %} needed for static, i18n, or horilla_tags #}
<img src="{% static 'assets/img/activate-company.svg' %}" alt="{% trans 'Activate company' %}">
{% has_perm "core.view_company" as can_view_company %}

{# ❌ Avoid — redundant with BUILTINS #}
{% load static %}
{% load i18n %}
{% load horilla_tags %}
```

```django
{# ✅ OK — library not in BUILTINS #}
{% load horilla_call_tags %}
{% calls_enabled as calls_active %}
```

### Reviewer checklist

- [ ] New or touched templates do not add `{% load static %}`, `{% load i18n %}`, or `{% load horilla_tags %}` unless removing legacy lines during a refactor.
- [ ] `{% load … %}` is present only for tag libraries outside `BUILTINS`.
- [ ] Prerequisite / no-data screens use [empty_state partials](templates/components/empty_state.md) instead of duplicating SVG markup.
- [ ] `{% trans %}` string quotes follow [trans tag quotes](#trans-tag-quotes).
- [ ] The primary button and other utility submit buttons use the [primary button classes](#primary-button-classes).

---

## `{% trans %}` tag quotes

Use **double quotes** for the `{% trans %}` message when the tag is not inside a double-quoted string. Keep **single quotes** when the tag sits inside `"..."`, so the surrounding attribute or script string stays valid.

| Where the tag sits | Quote style |
|--------------------|-------------|
| Text, a single-quoted attribute, or anywhere else not inside `"` | `{% trans "…" %}` |
| Inside a double-quoted attribute or script string (`title="…"`, `alt="…"`, `hx-on:click="…"`, …) | `{% trans '…' %}` |

If the message itself contains `"`, escape each one as `\"` inside the double-quoted tag. Django unescapes that back to the same translation string. An apostrophe needs no escape inside double quotes.

```django
{# ✅ Text and other contexts outside " #}
<h3>{% trans "Calendar" %}</h3>
{% trans "Today" %}
{% trans "Edit List View" as modal_title %}
{% trans "This dashboard doesn't have any components yet." %}
{% trans "Click \"Build App\" → choose \"OAuth\"." %}

{# ✅ Inside a double-quoted attribute — single quotes on the message #}
title="{% trans 'Add custom calendar' %}"
data-all="{% trans 'All members' %}"
alt="{% trans 'Delete' %}"
hx-on:click="hxConfirmForm(this, '{% trans 'Are you sure?' %}');"

{# ❌ Double quotes inside a double-quoted attribute break the markup #}
title="{% trans "Add custom calendar" %}"
```

### Reviewer checklist

- [ ] `{% trans %}` messages outside `"` use double quotes.
- [ ] `{% trans %}` messages inside a double-quoted attribute or script string keep single quotes.
- [ ] A `"` inside a double-quoted `{% trans %}` message is written as `\"`.

---

## Primary button classes

Use the common primary classes on the primary button and on other utility submit buttons — **New**, **Save**, **Next**, **Save Credentials**, **Save as Draft**, and empty-state actions. Start the `class` attribute with:

```text
bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white
```

Put size, spacing, and layout classes after that prefix. The usual follow-on for these submit buttons is `text-sm px-4 py-2`.

```django
{# ✅ Primary button and other utility submit buttons #}
<button
    type="submit"
    class="bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white text-sm px-4 py-2"
>
    {% trans "Save" %}
</button>

<a
    href="{{ action_url }}"
    class="bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white text-sm px-4 py-2"
>
    {{ action_label }}
</a>

{# ❌ Primary action that does not start with the shared prefix #}
<button type="submit" class="text-sm px-4 py-2 bg-primary-600 text-white rounded">
    {% trans "Save" %}
</button>
```

Secondary or outline actions (Previous, Cancel, Save & New) keep their own border treatment. Do not force those onto this prefix.

### Reviewer checklist

- [ ] The primary button and other utility submit buttons start with `bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white`.
- [ ] Size and spacing classes come after that prefix.
- [ ] Outline or secondary buttons are left on their existing border style.

---

## Modal Cancel and Close

- If the modal asks the user to **confirm** an action, use a **Cancel** button next to the main action (not a close icon).
- In all other modals, use **Close** (the close icon or a Close button).

---

## Naming

Conventions for **functions**, **classes**, and **variables**. Follow PEP 8 unless a rule below overrides it.

**Related docs**

- Import map and section headers: [Avoid direct Django usage](#avoid-direct-django-usage) (same file)
- Extension system: [docs/horilla/extension/inherit.md](docs/horilla/extension/inherit.md)
- ORM / `horilla.db`: [docs/horilla/contrib/core/models.md](docs/horilla/contrib/core/models.md)
- Commit format: [CLAUDE.md](CLAUDE.md) (`[ADD/FIX/UPDT/REMOVE] SECTION: description`)

### General Python style

| Kind | Style | Example |
|------|--------|---------|
| **Classes** | `PascalCase` | `LeadListView`, `FormExtension` |
| **Functions / methods** | `snake_case` | `resolve_list_view_class`, `bootstrap_extensions` |
| **Variables / attributes** | `snake_case` | `target_path`, `composed_map` |
| **Constants** | `UPPER_SNAKE_CASE` | `LIST_EXTENSION_REGISTRY`, `FORM_COMPOSED_MAP` |
| **Modules / packages** | `snake_case` | `metaclass.py`, `horilla_crm` |
| **Private (module)** | Leading `_` | `_patch_migration_autodetectors` |
| **Django apps** | `snake_case` package name | `my_lead_extensions`, `horilla_crm.leads` |

Avoid abbreviations unless they are domain-standard (`pk`, `fk`, `url`, `htmx`).

### The `Horilla` prefix — when to use it

The package is already named `horilla`. **Do not repeat `Horilla` in every symbol** inside `horilla/` when the import path or base class already makes the context clear.

#### Omit redundant `Horilla` (preferred inside `horilla/`)

Use short, domain-specific names:

| Do | Do not |
|----|--------|
| `ListExtension` | `HorillaListExtension` |
| `DetailExtension` | `HorillaDetailExtension` |
| `FormExtension` | `HorillaFormExtension` |
| `bootstrap_extensions()` | `bootstrap_horilla_extensions()` |
| `_is_list_extension` | `_is_horilla_list_extension` |
| `_is_form_extension` | `_is_horilla_form_extension` |
| `apply_list_extensions()` | `apply_horilla_list_extensions()` |

#### Keep `Horilla` for established framework types

These names are public API across apps and templates. **Do not rename** for consistency with generics, core, and docs:

| Keep as-is | Role |
|------------|------|
| `HorillaCoreModel` | Base model (`horilla.contrib.core`) |
| `HorillaListView`, `HorillaDetailView`, … | Generic CBVs (`horilla.contrib.generics`) |
| `HorillaModelForm`, `HorillaFormMixin` | Form stack |
| `HorillaFilterSet` | Filters |
| `HorillaUser` | Auth user model |

**Rule of thumb:** If the symbol lives in `horilla.contrib.*` and is imported by many CRM apps, it likely keeps the `Horilla` prefix. If it lives in `horilla.extension.*` or other internal platform code added for extensions, prefer the short name.

#### Client / third-party extension apps

Extension apps (e.g. `my_lead_extensions`) sit **outside** `horilla/`:

- **Classes:** describe the target + role — `LeadListExtension`, `LeadSingleFormExtension`, `LeadExtension` (model).
- **Do not** prefix every class with `Horilla` — the app is already Horilla-specific.
- **Functions:** `snake_case` helpers — `_clean_industry_code_value`, `_make_industry_optional` (module-private with `_`).

### Classes

#### Views and forms (CRM modules)

```python
# Good — matches horilla_crm patterns
class LeadListView(LoginRequiredMixin, HorillaListView):
    ...

class LeadSingleForm(HorillaModelForm):
    ...
```

#### Extension registration classes

Subclass the platform base and set the registration attribute on the class body:

```python
from horilla.extension.list import ListExtension

class LeadListExtension(ListExtension):
    _inherit_list = "horilla_crm.leads.views.core.LeadListView"
    columns_insert = [("industry", "industry_code")]
```

```python
# Kanban — see docs/horilla/extension/kanban/inherit.md
from horilla.extension.kanban import KanbanExtension

class LeadKanbanExtension(KanbanExtension):
    _inherit_kanban = "horilla_crm.leads.views.core.LeadKanbanView"
```

```python
# Detail — see docs/horilla/extension/detail/inherit.md
from horilla.extension.detail import DetailExtension

class LeadDetailExtension(DetailExtension):
    _inherit_detail = "horilla_crm.leads.views.core.LeadDetailView"
```

```python
from horilla.extension.forms import FormExtension

class LeadSingleFormExtension(FormExtension):
    _inherit_form = "horilla_crm.leads.forms.LeadSingleForm"
```

```python
from horilla.extension.filter import FilterExtension

class LeadFilterExtension(FilterExtension):
    _inherit_filter = "horilla_crm.leads.filters.LeadFilter"
    search_fields_append = ["industry_code"]
```

```python
from horilla.extension.nav import NavExtension

class LeadNavbarExtension(NavExtension):
    _inherit_nav = "horilla_crm.leads.views.core.LeadNavbar"
    column_selector_exclude_fields_append = ["industry_code"]
```

```python
from horilla.contrib.core.models import HorillaCoreModel

class LeadExtension(HorillaCoreModel):
    _inherit_model = "leads.Lead"
```

#### Composed runtime classes

Platform-generated classes may carry **marker attributes** (do not use these names on hand-written classes):

| Attribute | Meaning |
|-----------|---------|
| `__horilla_list_composed__` | Composed list view |
| `__horilla_list_path__` | Original list view import path |
| `__wrapped_list_view__` | Core list view behind composed list |
| `__horilla_kanban_composed__` | Composed kanban view |
| `__horilla_kanban_path__` | Original kanban view import path |
| `__wrapped_kanban_view__` | Core kanban view behind composed kanban |
| `__horilla_detail_composed__` | Composed detail view |
| `__horilla_detail_path__` | Original detail view import path |
| `__wrapped_detail_view__` | Core detail view behind composed detail |
| `__horilla_composed__` | Composed form |
| `__horilla_form_path__` | Original form import path |
| `__horilla_filter_path__` | Original filterset import path |
| `__wrapped_filter__` | Core filterset behind composed filter |
| `__horilla_nav_composed__` | Composed nav view |
| `__horilla_nav_path__` | Original nav view import path |
| `__wrapped_nav_view__` | Core nav view behind composed nav |

#### App config

```python
class MyLeadExtensionsConfig(AppLauncher):  # PascalCase + Config suffix
    name = "my_lead_extensions"
```

### Functions

| Rule | Example |
|------|---------|
| **Verbs** for actions | `apply_list_extensions`, `resolve_form_class`, `compose_list_view_class` |
| **get_** for accessors | `get_list_extensions`, `get_form_extensions`, `get_filter_extensions` |
| **get_filterset_class** on list views | Resolves composed filterset (`LeadFilterExtended`) |
| **is_ / has_** for booleans | `is_composed_view`, checks in validators |
| **setup_*_extension** for extension hooks | `setup_list_view_extension`, `setup_nav_view_extension`, `setup_filter_extension` |
| **clean_<field>** on forms | `clean_industry_code` |
| **No** `Horilla` in new platform helpers under `horilla/extension/` | `bootstrap_extensions()` not `bootstrap_horilla_extensions()` |

Module-level “script” helpers in extension apps may use a leading `_` if not part of the public API.

### Variables and attributes

#### Registration and hook attributes (extensions)

Use the **declared hook names** exactly — the metaclass reads these class attributes:

| Mechanism | Registration key | Hook examples |
|-----------|------------------|---------------|
| Model | `_inherit_model` | field names on class body |
| Form | `_inherit_form` | `field_order_insert`, `step_fields_append`, `fields_append` |
| Filter | `_inherit_filter` | `exclude_append` (filter panel dropdown), `search_fields_append`, `fields_append` |
| Nav | `_inherit_nav` | `actions_append`, `custom_view_type_update`, `column_selector_exclude_fields_append` |
| List | `_inherit_list` | `columns_insert`, `bulk_update_fields_append` |

Optional on extension classes:

- `_extension_priority` — `int`, lower runs earlier in merge order.

#### Django model / view conventions

| Use | Name |
|-----|------|
| Model Meta | `class Meta:` with `verbose_name`, `ordering` |
| Managers | `objects` (company-filtered), `all_objects` (unfiltered) |
| Owner filtering | `OWNER_FIELDS = ["lead_owner"]` |
| URL names | `snake_case` — `lead_list`, `lead_detail` |
| `app_name` | package segment — `leads`, `opportunities` |

#### User-facing labels — Title Case

English **`verbose_name`**, **`verbose_name_plural`**, and form **`label`** strings must be **Title Case**. Wrap them with `gettext_lazy` (`_()`). This applies to:

- Field `verbose_name` on models
- `Meta.verbose_name` and `Meta.verbose_name_plural`
- Explicit form field `label=` (and related user-facing captions such as `help_text` only when it is a short label, not a sentence)

Capitalize each significant word. Do not use sentence case, all-lowercase, or all-caps.

```python
# ✅ Title Case
name = models.CharField(max_length=100, verbose_name=_("Forecast Type Name"))

class Meta:
    verbose_name = _("Forecast Type")
    verbose_name_plural = _("Forecast Types")

team = forms.ModelChoiceField(queryset=..., label=_("Select Team"))

# ❌ Sentence case / lowercase
verbose_name = _("forecast type name")
verbose_name = _("Forecast type name")
label = _("select team")
```

Keep small connecting words in Title Case when they are part of the label (`To`, `Of`, `And`) unless an existing product string already uses a fixed phrase — prefer matching nearby labels in the same module.

#### Naming — reviewer checklist (labels)

- [ ] Model field `verbose_name` is Title Case inside `_("…")`.
- [ ] `Meta.verbose_name` and `Meta.verbose_name_plural` are Title Case.
- [ ] Form `label=` values are Title Case.

#### Registries and maps (platform)

`UPPER_SNAKE_CASE` for module-level registries:

- `LIST_EXTENSION_REGISTRY`, `LIST_COMPOSED_MAP`
- `FORM_EXTENSION_REGISTRY`, `FORM_COMPOSED_MAP`
- `INJECTION_MAP` (model field injection)

#### Request / instance state

`snake_case` on `self` — `self.request`, `self.object`, `self.columns`.

### Import paths and string references

Extension `_inherit_*` values are **full dotted paths** to an existing class:

```python
_inherit_list = "horilla_crm.leads.views.core.LeadListView"
_inherit_form = "horilla_crm.leads.forms.LeadSingleForm"
_inherit_model = "leads.Lead"  # app_label.ModelName for models only
```

- Use the real module path from the codebase (MCP `search_codebase` / `get_url_map` before guessing).
- Model `_inherit_model` uses `"app_label.ModelName"`, not the full module path.

### Naming — reviewer checklist

- [ ] New code under `horilla/extension/` avoids redundant `Horilla*` on classes and functions.
- [ ] Public framework types in `horilla.contrib.*` keep existing `Horilla*` names.
- [ ] Extension apps use `*Extension` class names and `_inherit_model` / `_inherit_form` / `_inherit_list`.
- [ ] Functions and variables are `snake_case`; constants are `UPPER_SNAKE_CASE`.
- [ ] `verbose_name`, `verbose_name_plural`, and form `label` strings are Title Case (see [User-facing labels](#user-facing-labels--title-case)).
- [ ] No new `HorillaHorilla*` or duplicated prefix typos.
- [ ] Client-only apps are registered via `local_settings.py` (`INSTALLED_APPS += [...]`), not by editing `horilla/settings/base.py` unless you are core maintainers.

### Naming — examples

```python
# Platform (horilla/extension/bootstrap.py)
def bootstrap_extensions() -> None: ...

# Platform (horilla/extension/list/metaclass.py)
class ListExtension: ...

# CRM view (horilla_crm)
class LeadListView(LoginRequiredMixin, HorillaListView): ...

# Client extension (my_lead_extensions/lists.py)
class LeadListExtension(ListExtension):
    _inherit_list = "horilla_crm.leads.views.core.LeadListView"
```

When in doubt: **match the nearest existing file in the same package**, then check [docs/horilla/extension/inherit.md](docs/horilla/extension/inherit.md).

---

## Field renames / removals — review stored field-name references

Several Horilla models **persist field names as strings** in the database (visibility prefs, permissions, filters, automations, archived snapshots, etc.). Renaming, removing, or changing a model field’s definition can leave those rows pointing at obsolete names and break UI, filters, permissions, or workflows at runtime.

**Rule:** Whenever **any model field is updated** (renamed, removed, or its behavior/definition is changed), review the models below and their related logic so stored field-name references stay valid. Plan data migrations or cleanup when existing rows would break.

### Models that store field names

| Model | Location | Notes |
|-------|----------|--------|
| `ListColumnVisibility` | [`horilla/contrib/core/models/visibility.py`](../horilla/contrib/core/models/visibility.py) (~L16) | List column visibility |
| `DetailFieldVisibility` | [`horilla/contrib/core/models/visibility.py`](../horilla/contrib/core/models/visibility.py) (~L62) | Detail field visibility |
| `FieldPermission` | [`horilla/contrib/core/models/user.py`](../horilla/contrib/core/models/user.py) (~L342) | Per-field permissions |
| `SavedFilterList`, `KanbanGroupBy`, `TimelineSpanBy`, `QuickFilter` | [`horilla/contrib/core/models/filters.py`](../horilla/contrib/core/models/filters.py) | Saved filters / group-by / span-by |
| `RecycleBin` | [`horilla/contrib/core/models/recyclebin.py`](../horilla/contrib/core/models/recyclebin.py) (~L25) | Archived JSON snapshot of records |
| `ImportHistory`, `ExportSchedule` | [`horilla/contrib/core/models/import_export.py`](../horilla/contrib/core/models/import_export.py) | Import/export field mappings & schedules |
| `HorillaAutomation`, `AutomationCondition` | [`horilla/contrib/automations/models.py`](../horilla/contrib/automations/models.py) | Automation triggers & conditions |
| `WorkflowCondition`, `WorkflowTimeTriggerAction` | [`horilla/contrib/workflow/models.py`](../horilla/contrib/workflow/models.py) | Workflow conditions & time-trigger actions |
| `CadenceCondition` | [`horilla/contrib/cadences/models.py`](../horilla/contrib/cadences/models.py) | Cadence conditions |

### What to check

1. **Rename** — update or migrate stored field-name strings in the tables above (and any related views/forms/serializers that hard-code the old name).
2. **Remove** — remove or neutralize rows that reference the deleted field; avoid leaving filters/permissions/automations that would raise on missing fields.
3. **Behavior / definition change** — confirm conditions, permissions, visibility, import/export maps, and recycle-bin snapshots still make sense for the new type or meaning of the field.
4. **Related logic** — search for the old field name in code (views, templates, extensions, `_inherit_*` hooks) in addition to DB-backed models.

### Reviewer checklist

- [ ] Field rename/remove/definition change was checked against the table above.
- [ ] Existing DB rows that store the old field name are migrated or cleaned up when needed.
- [ ] Automations, workflows, cadences, filters, visibility, and permissions that reference the field still resolve correctly.
- [ ] Recycle-bin / import-export paths that embed field names were considered.

---

## App static files

An app's files under `static/` live in a folder with the same name as the app. Django's static finder uses that path, so `{% static %}`, `static()`, and `__icon__` include the app name.

```text
horilla/contrib/dashboard/static/dashboard/assets/icons/icon6.svg
```

`__icon__` in that app is `dashboard/assets/icons/icon6.svg`.

```text
# ❌ Files sit directly under static/
horilla/contrib/dashboard/static/assets/icons/icon6.svg
__icon__ = "assets/icons/icon6.svg"

# ✅ App name is the first folder inside static/
horilla/contrib/keys/static/keys/assets/icons/icon3.svg
__icon__ = "keys/assets/icons/icon3.svg"
```

Shared files that are not owned by one app stay in the project `static/` directory. Those paths do not get an app-name prefix.

---

_Add further rule sections here as `## <Topic>` (e.g. Views, Migrations). See also [Avoid direct Django usage](#avoid-direct-django-usage)._

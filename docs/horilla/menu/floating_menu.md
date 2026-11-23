# Floating menu
## Purpose
The **floating menu** is the circular **Quick actions** control (plus button) on the sidebar. When opened, it shows extra circular buttons—typically **create** shortcuts. Each action loads a URL with **HTMX** (hx-get) into a target such as #modalBox.
This document explains:
horilla/menu/floating_menu.py (registry and get_floating_menu)
How **menu_context_processor** exposes floating_menu to templates
How **templates/components/sidebar.html** renders it
How each app registers entries via **menu.py** and app config
---
## End-to-end flow
text
App menu.py
@floating_menu.register class ...
   │
   ▼
floating_registry (floating_menu.py)
   │
   ▼
get_floating_menu(request)  ◄──  menu_context_processor(request)
   │                              │
   │                              └── "floating_menu": get_floating_menu(request)
   ▼
Template variable `floating_menu` in all templates that use the processor
   │
   ▼
templates/components/sidebar.html  {% for menu in floating_menu %}
1. **Register** — A class is decorated with @floating_menu.register in the app’s menu.py.
2. **Load** — The app config must **import** that module at startup (Horilla apps use auto_import_modules including "menu" in AppLauncher configs).
3. **Resolve** — On each request, get_floating_menu(request) builds the list the current user is allowed to see.
4. **Context** — menu_context_processor adds it as floating_menu.
5. **Render** — The sidebar loops floating_menu and outputs each item as an <li> with hx-get and attributes from menu.items.
---
## Core module: floating_menu.py
| Piece | Role |
|--------|------|
| floating_registry | List of registered classes (filled by @floating_menu.register). |
| register | Decorator: floating_registry.append(cls) and returns cls. |
| get_floating_menu(request=None) | Instantiates each registered class, reads title, url, icon, items, filters by auth and permissions, returns a list of dicts. |
### get_floating_menu(request=None) return shape
Each element is a dict:
title — Shown as tooltip / aria-label.
url — Resolved URL for hx-get.
icon — Static path (e.g. "/assets/icons/campaign.svg").
items — Dict of attributes copied onto the <li> (HTMX, onclick, etc.), including the special **perm** key used only for the permission check (see below).
### Permission and visibility
An entry is **added** only if **all** of these are true:
request is not None
request.user.is_authenticated
items contains **perm** with a non-empty value (string or list/tuple of permission codenames)
the user has **at least one** of the permissions in perm_list (any-of semantics; a single string is treated as a one-item list)
If **perm is missing or empty**, that floating action **never appears** (even for superusers), with the current implementation.
Optional: items may be a **callable** items(request) that returns a dict. If you use that, note that perm is read from the initial items **before** the callable runs—so for callable items, put permission logic inside the returned dict or adjust the implementation.
---
## Context processor
**File:** horilla/context_processors.py
get_floating_menu is imported from horilla.menu.floating_menu and exposed under the key **floating_menu**:
python
from horilla.menu.floating_menu import get_floating_menu
def menu_context_processor(request):
...
return {
  "main_section_menu": get_main_section_menu(request),
  "sub_section_menu": get_sub_section_menu(request),
  "settings_menu": get_settings_menu(request),
  "floating_menu": get_floating_menu(request),
  "my_settings_menu": get_my_settings_menu(request),
  "header_menu": get_header_menu(request),
  ...
}
**Registration:** horilla/settings/base.py includes horilla.context_processors.menu_context_processor in the Django TEMPLATES context_processors list, so **floating_menu** is available in templates that extend your base layout (wherever that processor runs).
---
## Sidebar template
**File:** templates/components/sidebar.html
Renders the floating UI only if **floating_menu** is non-empty: {% if floating_menu %}.
Toggle: checkbox + plus icon; **Quick actions** title/aria-label.
For each **menu** in **floating_menu**:
hx-get="{{ menu.url }}?{{ request.GET.urlencode }}" — keeps current query string.
Every key/value in **menu.items** is emitted as an HTML attribute on the <li> ({% for key, value in menu.items.items %}).
Each row shows **menu.icon** and uses **menu.title** for accessibility.
**Note:** Because every items key becomes an attribute, **perm** may also appear on the DOM unless you filter keys in the template or strip perm before building the context. Prefer string values suitable for HTML attributes.
---
## Registering in an app (menu.py)
### Import
python
from horilla.menu import floating_menu
### Pattern
Define a class with **title**, **url**, **icon**, and **items**, and decorate it with **@floating_menu.register**.
### Example (all typical items keys explicit)
From the Campaigns app (horilla_crm/campaigns/menu.py):
python
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.menu import floating_menu, sub_section_menu
from horilla_crm.campaigns.models import Campaign
@floating_menu.register
class CampaignFloating:
"""
Campaign Floating Menu
"""
title = Campaign()._meta.verbose_name
url = reverse_lazy("campaigns:campaign_create")
icon = "/assets/icons/campaign.svg"
items = {
  "hx-target": "#modalBox",
  "hx-swap": "innerHTML",
  "onclick": "openModal()",
  "perm": ["campaigns.add_campaign"],
}
Single permission string (also supported by get_floating_menu):
python
items = {
"hx-target": "#modalBox",
"hx-swap": "innerHTML",
"onclick": "openModal()",
"perm": "campaigns.add_campaign",
}
### Ensure menu.py is loaded
Horilla CRM apps usually list **"menu"** in **auto_import_modules** on the app’s AppLauncher config (e.g. horilla_crm/contacts/apps.py). Without importing menu.py at startup, registrations never run and **floating_registry** stays empty.
If you add a new app, include **menu** in auto_import_modules (or import menu from AppConfig.ready()) so decorators execute.
---
## Apps that register a floating menu today
| App | Registered class (file) |
|-----|-------------------------|
| CRM Accounts | AccountFloating — horilla_crm/accounts/menu.py |
| CRM Campaigns | CampaignFloating — horilla_crm/campaigns/menu.py |
| CRM Contacts | ContactFloating — horilla_crm/contacts/menu.py |
| CRM Leads | LeadFloating — horilla_crm/leads/menu.py |
| CRM Opportunities | OpportunitiesFloating — horilla_crm/opportunities/menu.py |
---
## Styling
**File:** static/assets/css/style.css
Classes **.floating-menu** and **.floating-nav** control position (fixed near bottom-left of the sidebar), size, and the fan-out animation. Vertical offsets are defined for up to **five** items (nth-child(1) … nth-child(5)). Add more CSS if you need more than five visible actions.
---
## New app checklist
1. Add **menu.py** with @floating_menu.register (and other menus if needed).
2. Import **menu** in app startup (auto_import_modules or ready()).
3. Use correct **perm** codenames so the right users see the action.
4. Point **url** at a view that returns the HTMX partial your **hx-target** / **hx-swap** expect.
5. If you exceed five visible entries, extend **.floating-nav** CSS.
---
## Related files (quick reference)
| File | Role |
|------|------|
| horilla/menu/floating_menu.py | Registry, register, get_floating_menu |
| horilla/context_processors.py | menu_context_processor → floating_menu |
| horilla/settings/base.py | Registers menu_context_processor |
| templates/components/sidebar.html | Renders floating_menu |
| static/assets/css/style.css | .floating-menu / .floating-nav |
| <app>/menu.py | Per-app @floating_menu.register classes |
| horilla_utils/.../start_horilla_app.py | Scaffolds menu.py with floating_menu import |
---
## Summary
| Step | What to do |
|------|------------|
| Define | Class with title, url, icon, items (include perm for visibility). |
| Register | @floating_menu.register |
| Load | Import menu module at app startup. |
| Context | Provided automatically via floating_menu: get_floating_menu(request). |
| UI | Rendered in sidebar.html when floating_menu is non-empty. |
The floating menu is the standard Horilla pattern for **permission-gated, HTMX-driven quick create actions** from the sidebar.

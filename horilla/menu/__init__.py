"""
Menu registry package for Horilla.

Each submodule exposes a `@<name>.register` decorator that apps use in their
`menu.py` to register sidebar entries. The registries are collected at app
startup and rendered into the layout.

Registries:
    main_section_menu  - Top-level sidebar sections (Sales, People, ...).
    sub_section_menu   - Items nested under a main section.
    floating_menu      - Quick-create floating action button entries.
    settings_menu      - Module settings groups (Settings sidebar).
    my_settings_menu   - Per-user 'My Settings' sidebar entries.

Shared constants:
    MAIN_CONTENT_HX_ATTRS - HTMX attributes for sub-section links that swap
        the page's main content region (`#mainContent`) without a full reload.
        Use this on every sub-section menu item that navigates inside the app
        shell so behavior stays consistent across modules.
    MAIN_SECTION_HX_ATTRS - Same as MAIN_CONTENT_HX_ATTRS, plus
        `hx-select-oob` for `#sideMenuContainer`. Top-level sidebar links
        (Home, Sales, People, ...) switch sections, so the sub-sidebar
        rendered inside `#sideMenuContainer` must be replaced too - relying
        on the response's own `hx-swap-oob` tag is not enough because the
        target page (e.g. Home) may not render that element at all. Use this
        on every main-section menu item.
"""

MAIN_CONTENT_HX_ATTRS = {
    "hx-boost": "true",
    "hx-target": "#mainContent",
    "hx-select": "#mainContent",
    "hx-swap": "outerHTML",
}

MAIN_SECTION_HX_ATTRS = {
    **MAIN_CONTENT_HX_ATTRS,
    "hx-select-oob": "#sideMenuContainer",
}


def condition_met(condition, request) -> bool:
    """Return whether a menu ``condition`` allows this request.

    A callable is called with the request and must be true. With no request,
    a callable condition fails. A plain value is used as a flag, and a missing
    condition defaults to ``True`` at the call site.
    """
    if callable(condition):
        return bool(request and condition(request))
    return bool(condition)

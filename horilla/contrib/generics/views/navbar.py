"""
View for rendering a customizable navigation bar with filtering and search capabilities for Horilla's generic list views.
This view supports pinned views, recently viewed/created/modified filters, saved filter lists.
"""

# Standard library imports
from functools import cached_property, update_wrapper
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import PinnedView, SavedFilterList
from horilla.db.models import Q
from horilla.urls import resolve, reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView

# Local imports
from ..applied_filters import build_applied_filter_rows, has_filter_rows, resolve_model

# Third-party imports (Django)


class HorillaNavView(TemplateView):
    """View for rendering the navigation bar with filtering and search capabilities."""

    template_name = "navbar.html"

    # Every subclass, so a list view can find the navbar(s) that search it.
    _registry = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        HorillaNavView._registry.append(cls)

    @classmethod
    def for_list_url(cls, path):
        """Navbar classes whose ``search_url`` is the list served at ``path``."""
        path = str(path).split("?")[0].rstrip("/")
        matches = []
        for nav_cls in cls._registry:
            # search_url is lazy; only resolve it here, once URLs are loaded.
            search_url = str(nav_cls.search_url).split("?")[0].rstrip("/")
            if search_url and search_url == path:
                matches.append(nav_cls)
        return matches

    _nav_title: str = ""
    nav_description: str = ""
    nav_avatar: str = ""  # Optional image URL shown before the title
    filterset_class = None
    search_url: str = ""
    main_url: str = ""
    kanban_url: str = ""
    group_by_url: str = ""
    card_url: str = ""
    timeline_url: str = ""
    default_layout: str = (
        "list"  # "list", "kanban", "group_by", "card", or a custom_layouts key
    )
    custom_layouts: dict = {}
    actions: list = []
    new_button: dict = None
    second_button: dict = None
    model_name: str = ""
    model_app_label: str = ""
    custom_view_type: dict = {}
    nav_width = True
    recently_viewed_option = True
    all_view_types = True
    filter_option = True
    # The applied-filter tag next to the search box has its own close, so the search box
    # shows no clear (X) by default. Set True to bring the inline clear back.
    search_clear_option = None
    one_view_only = False
    reload_option = True
    border_enabled = True
    search_option = True
    navbar_indication = False
    navbar_indication_attrs: dict = {}
    extra_actions_template: str = ""
    exclude_kanban_fields: str = ""
    column_selector_exclude_fields = []
    enable_actions = False
    search_push_url = True
    enable_quick_filters = False  # Set to True in child classes to enable
    main_session_id: str = "mainSession"  # Override to avoid ID conflicts inside modals

    def get_filterset_class(self):
        """
        Return composed filterset when _inherit_filter extensions exist.

        Nav views may set ``filterset_class`` for parity with list views; resolution
        matches ``HorillaListView.get_filterset_class()``.
        """
        base = type(self).filterset_class
        if base is None:
            return None
        from horilla.extension.filter.resolve import resolve_filterset_class

        return resolve_filterset_class(base)

    @classmethod
    def as_view(cls, **initkwargs):
        """
        Wrap the view so _inherit_nav resolves on each request.

        Target apps register navbar URLs in ``AppLauncher.ready()`` before extension
        apps import ``navbars.py``; resolving only at URL-import time would miss extensions.
        """
        if getattr(cls, "__horilla_nav_composed__", False):
            return super().as_view(**initkwargs)

        base_view = super().as_view(**initkwargs)

        def view(request, *args, **kwargs):
            from horilla.extension.nav.bootstrap import (
                registry_fingerprint as nav_fingerprint,
            )
            from horilla.extension.nav.resolve import resolve_nav_view_class

            resolved = resolve_nav_view_class(cls)
            fingerprint = nav_fingerprint()

            if resolved is not cls:
                if (
                    getattr(view, "_extended_handler", None) is None
                    or getattr(view, "_extended_cls", None) is not resolved
                    or getattr(view, "_nav_ext_fingerprint", None) != fingerprint
                ):
                    view._extended_cls = resolved
                    view._extended_handler = resolved.as_view(**initkwargs)
                    view._nav_ext_fingerprint = fingerprint
                return view._extended_handler(request, *args, **kwargs)
            return base_view(request, *args, **kwargs)

        update_wrapper(view, base_view)
        view.view_class = cls
        view.view_initkwargs = initkwargs
        return view

    @property
    def nav_title(self) -> str:
        """Resolved list title from explicit override or the model's verbose name plural."""
        if self._nav_title:
            return self._nav_title
        if self.model_name and self.model_app_label:
            try:
                return apps.get_model(
                    self.model_app_label, self.model_name
                )._meta.verbose_name_plural
            except LookupError:
                pass
        return self._nav_title

    @nav_title.setter
    def nav_title(self, value: str) -> None:
        self._nav_title = value

    def get_navbar_indication_attrs(self):
        """Return additional attributes for navbar indication when enabled."""
        if self.navbar_indication:
            return self.navbar_indication_attrs
        return None

    def _get_pinned_view(self):
        """Load the user's pinned view once per request and reuse it."""
        if hasattr(self, "_pinned_view_cache"):
            return self._pinned_view_cache
        self._pinned_view_cache = PinnedView.all_objects.filter(
            user=self.request.user, model_name=self.model_name
        ).first()
        return self._pinned_view_cache

    def get_default_view_type(self):
        """Return the pinned view_type if available, else 'all'."""
        pinned_view = self._get_pinned_view()
        return pinned_view.view_type if pinned_view else "all"

    def get_valid_view_types(self):
        """Return a set of all valid view type values."""
        valid_types = {
            "all",
            "recently_created",
            "recently_modified",
            "oldest_first",
        }

        if self.recently_viewed_option:
            valid_types.add("recently_viewed")

        # Add custom view types
        if self.custom_view_type:
            valid_types.update(self.custom_view_type.keys())

        # Add saved filter list view types
        saved_lists = SavedFilterList.all_objects.filter(
            model_name=self.model_name
        ).filter(Q(user=self.request.user) | Q(is_public=True))
        for saved_list in saved_lists:
            valid_types.add(f"saved_list_{saved_list.id}")

        return valid_types

    def show_list_only(self):
        """Check if kanban should be hidden based on current view type."""
        current_view_type = (
            self.request.GET.get("view_type") or self.get_default_view_type()
        )

        # Check if current view type has hide_kanban setting
        for view_key, view_config in self.custom_view_type.items():
            if view_key == current_view_type:
                if isinstance(view_config, dict):
                    return view_config.get("show_list_only", False)
                break
        return False

    def get_all_layouts(self, context):
        """
        Build the ordered list of layout options for the view toggle.

        Single source of truth for both the toggle button's icon and the
        dropdown list, so adding/removing a layout type only needs a change
        here instead of two parallel template blocks.
        """
        layouts = [
            {
                "key": "list",
                "url": True,
                "icon": "assets/icons/l3.svg",
                "icon_width": 16,
                "label": _("List"),
            },
        ]
        if context["card_url"]:
            layouts.append(
                {
                    "key": "card",
                    "url": context["card_url"],
                    "icon": "assets/icons/card-view.svg",
                    "icon_width": 16,
                    "label": _("Card"),
                }
            )
        if context["kanban_url"]:
            layouts.append(
                {
                    "key": "kanban",
                    "url": context["kanban_url"],
                    "icon": "assets/icons/l2.svg",
                    "icon_width": 16,
                    "label": _("Kanban"),
                }
            )
        if context["timeline_url"]:
            layouts.append(
                {
                    "key": "timeline",
                    "url": context["timeline_url"],
                    "icon": "assets/icons/timeline.svg",
                    "icon_width": 18,
                    "label": _("Timeline"),
                }
            )
        if context["group_by_url"]:
            layouts.append(
                {
                    "key": "group_by",
                    "url": context["group_by_url"],
                    "icon": "assets/icons/group-by.svg",
                    "icon_width": 16,
                    "label": _("Group By"),
                }
            )
        if context["chart_url"]:
            layouts.append(
                {
                    "key": "chart",
                    "url": context["chart_url"],
                    "icon": "assets/icons/pie-chart-view.svg",
                    "icon_width": 16,
                    "label": _("Chart View"),
                }
            )
        if context["split_view_url"]:
            layouts.append(
                {
                    "key": "split_view",
                    "url": context["split_view_url"],
                    "icon": "assets/icons/split-view.svg",
                    "icon_width": 16,
                    "label": _("Split View"),
                }
            )
        for key, layout in context["custom_layouts"].items():
            if layout.get("url"):
                layouts.append(
                    {
                        "key": key,
                        "url": layout["url"],
                        "icon": layout.get("icon", "assets/icons/l3.svg"),
                        "icon_width": layout.get("icon_width", 16),
                        "label": layout.get("label", key),
                    }
                )
        return layouts

    def get_context_data(self, **kwargs):
        """Add effective_layout, nav_title, search_url, and search_push_url to context."""
        context = super().get_context_data(**kwargs)
        context["effective_layout"] = self.request.GET.get("layout") or getattr(
            self, "default_layout", "list"
        )
        context["nav_title"] = self.nav_title
        context["nav_description"] = self.nav_description
        context["nav_avatar"] = str(getattr(self, "nav_avatar", "") or "")
        context["main_session_id"] = getattr(self, "main_session_id", "mainSession")
        context["search_url"] = self.search_url or self.request.path
        context["search_push_url"] = "true" if self.search_push_url else "false"
        context["main_url"] = self.main_url or self.request.path
        context["kanban_url"] = self.kanban_url
        context["group_by_url"] = getattr(self, "group_by_url", None) or ""
        context["card_url"] = getattr(self, "card_url", None) or ""
        context["timeline_url"] = getattr(self, "timeline_url", None) or ""
        timeline_settings_url = ""
        if getattr(self, "timeline_url", None):
            try:
                base = str(reverse_lazy("generics:timeline_settings"))
                params = [
                    ("app_label", self.model_app_label),
                    ("model", self.model_name),
                    ("main_url", context["main_url"]),
                ]
                for key in self.request.GET:
                    if key in ("app_label", "model", "main_url"):
                        continue
                    for value in self.request.GET.getlist(key):
                        params.append((key, value))
                timeline_settings_url = base + "?" + urlencode(params)
            except Exception:
                pass
        context["timeline_settings_modal_url"] = timeline_settings_url
        split_url = getattr(self, "split_view_url", None)
        context["split_view_url"] = str(split_url) if split_url else ""
        chart_url = getattr(self, "chart_url", None)
        context["chart_url"] = str(chart_url) if chart_url else ""
        context["custom_layouts"] = getattr(self, "custom_layouts", None) or {}
        all_layouts = self.get_all_layouts(context)
        context["all_layouts"] = all_layouts
        active_layout = next(
            (
                layout
                for layout in all_layouts
                if layout["key"] == context["effective_layout"]
            ),
            None,
        )
        context["effective_layout_icon"] = (
            active_layout["icon"] if active_layout else "assets/icons/l3.svg"
        )
        context["actions"] = self.actions
        context["new_button"] = self.new_button or {}
        context["second_button"] = self.second_button or {}
        context["model_name"] = self.model_name
        context["model_app_label"] = self.model_app_label
        context["nav_width"] = self.nav_width

        # Get view_type from request or default, and validate it
        requested_view_type = (
            self.request.GET.get("view_type") or self.get_default_view_type()
        )
        valid_view_types = self.get_valid_view_types()

        # If the requested view_type is not in valid choices, default to 'all'
        if requested_view_type not in valid_view_types:
            context["view_type"] = "all"
        else:
            context["view_type"] = requested_view_type

        context["show_list_only"] = self.show_list_only()
        context["custom_view_type"] = self.custom_view_type
        context["pinned_view"] = self._get_pinned_view()
        context["recently_viewed_option"] = self.recently_viewed_option
        context["all_view_types"] = self.all_view_types
        context["filter_option"] = self.filter_option
        context["search_clear_option"] = bool(self.search_clear_option)
        applied_filter_count = 0
        if self.filter_option:
            fields = self.request.GET.getlist("field") or []
            operators = self.request.GET.getlist("operator") or []
            for i, field in enumerate(fields):
                if field and (operators[i] if i < len(operators) else None):
                    applied_filter_count += 1
        # A search is not counted: the search box and the navbar tag already show it
        context["applied_filter_count"] = applied_filter_count
        # Rows for the rotating applied-filter slot in the navbar
        # Built for every list, with or without a filter button: a search shows as a tag
        slot_rows = build_applied_filter_rows(
            self.request,
            resolve_model(self.model_app_label, self.model_name),
        )
        context["applied_filter_slot_rows"] = slot_rows
        context["applied_filter_slot_has_filters"] = has_filter_rows(slot_rows)
        # Same names the filter panel uses, so the slot's remove / clear requests match
        context["query_params"] = {
            item: self.request.GET.getlist(item) for item in self.request.GET
        }
        context["filter_push_url"] = context["search_push_url"]
        # Field-aware search box: only for lists whose filterset has search fields
        filterset_class = self.get_filterset_class()
        field_labels = (
            filterset_class.get_search_field_labels()
            if filterset_class and hasattr(filterset_class, "get_search_field_labels")
            else {}
        )
        # The dropdown rebuilds its state from the page URL, so it needs the URL push
        context["list_search_enabled"] = bool(field_labels) and self.search_push_url
        context["one_view_only"] = self.one_view_only
        context["reload_option"] = self.reload_option
        context["search_option"] = self.search_option
        context["border_enabled"] = self.border_enabled
        context["navbar_indication"] = self.navbar_indication
        context["extra_actions_template"] = self.extra_actions_template
        context["enable_actions"] = self.enable_actions
        context["navbar_indication_attrs"] = self.get_navbar_indication_attrs()
        # Saved lists are built from the filter panel, so no filter option means no "save to list"
        context["save_to_list_option"] = (
            getattr(self, "save_to_list_option", True)
            and self.filter_option
            and self.all_view_types
        )
        # Saved filter lists: user's own + public ones for this model (by position)
        context["available_saved_filter_lists"] = list(
            SavedFilterList.all_objects.filter(model_name=self.model_name)
            .filter(Q(user=self.request.user) | Q(is_public=True))
            .order_by("-is_public", "name")
        )
        return context

    @cached_property
    def actions(self):
        """Actions"""
        if not self.enable_actions:
            return []
        view_perm = f"{self.model_app_label}.view_{self.model_name.lower()}"
        view_own_perm = f"{self.model_app_label}.view_own_{self.model_name.lower()}"
        can_create_perm = f"{self.model_app_label}.add_{self.model_name.lower()}"
        _resolved = resolve(str(self.search_url))
        single_import = True

        actions = []
        if self.request.user.has_perm(view_perm) or self.request.user.has_perm(
            view_own_perm
        ):
            if self.request.user.has_perm(can_create_perm):
                actions.append(
                    {
                        "action": _("Import"),
                        "attrs": f"""
                        hx-get="{reverse_lazy("core:import_data")}?single_import={str(single_import).lower()}&model_name={self.model_name}&app_label={self.model_app_label}"
                        onclick="openModal()"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        """,
                    }
                )

            # Effective layout: only append actions relevant to current layout
            layout = (
                self.request.GET.get("layout")
                or getattr(self, "default_layout", "list")
                or "list"
            )
            layout = str(layout).strip().lower()

            exclude_cols = getattr(self, "column_selector_exclude_fields", None)

            # Timeline settings (your branch) — shown when layout is timeline
            timeline_settings_action = None
            if getattr(self, "timeline_url", None):
                try:
                    ts_base = str(reverse_lazy("generics:timeline_settings"))
                    ts_params = [
                        ("app_label", self.model_app_label),
                        ("model", self.model_name),
                        ("main_url", self.main_url or self.request.path),
                    ]
                    for key in self.request.GET:
                        if key in ("app_label", "model", "main_url"):
                            continue
                        for value in self.request.GET.getlist(key):
                            ts_params.append((key, value))
                    timeline_settings_modal_url = ts_base + "?" + urlencode(ts_params)
                    timeline_settings_action = {
                        "action": _("Timeline settings"),
                        "attrs": f"""
                            hx-get="{timeline_settings_modal_url}"
                            onclick="openModal()"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            """,
                    }
                except Exception:
                    pass

            # Pull branch: layout-specific actions (kanban / group_by / list + quick filters)
            kanban_settings_action = {
                "action": _("Kanban Settings"),
                "attrs": f"""
                    hx-get="{reverse_lazy("generics:create_kanban_group")}?model={self.model_name}&app_label={self.model_app_label}&exclude_fields={self.exclude_kanban_fields}&view_type=kanban"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    """,
            }
            group_by_settings_action = {
                "action": _("Group By Settings"),
                "attrs": f"""
                    hx-get="{reverse_lazy("generics:create_kanban_group")}?model={self.model_name}&app_label={self.model_app_label}&exclude_fields={self.exclude_kanban_fields}&view_type=group_by"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    """,
            }
            column_selector_base_url = (
                f"{reverse_lazy('generics:column_selector')}"
                f"?app_label={self.model_app_label}&model_name={self.model_name}"
            )
            if exclude_cols:
                exclude_list = (
                    exclude_cols
                    if isinstance(exclude_cols, (list, tuple))
                    else [f.strip() for f in str(exclude_cols).split(",") if f.strip()]
                )
                if exclude_list:
                    column_selector_base_url += "&exclude=" + ",".join(exclude_list)
            add_column_action = {
                "action": _("Add Column to List"),
                "attrs": f"""
                    hx-get="{column_selector_base_url}"
                    hx-include="#active-list-url-name"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    """,
            }
            split_column_action = {
                "action": _("Add Column to Split View"),
                "attrs": f"""
                    hx-get="{reverse_lazy('generics:split_column_selector')}?app_label={self.model_app_label}&model_name={self.model_name}"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    """,
            }
            search_url = str(self.search_url) if self.search_url else self.request.path
            quick_filter_params = self.request.GET.copy()
            quick_filter_params.pop("page", None)
            quick_filter_params["show_add_quick_filter"] = "true"
            add_quick_filter_action = {
                "action": _("Add Quick Filter"),
                "attrs": f"""
                    hx-get="{search_url}?{quick_filter_params.urlencode()}"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    """,
            }

            if layout == "kanban":
                actions.append(kanban_settings_action)
            elif layout == "timeline" and timeline_settings_action:
                actions.append(timeline_settings_action)
            elif layout == "list":
                actions.append(add_column_action)
                if self.enable_quick_filters:
                    actions.append(add_quick_filter_action)
            elif layout == "split_view":
                actions.append(split_column_action)
            elif layout == "group_by":
                if getattr(self, "group_by_url", None):
                    actions.append(group_by_settings_action)
        return actions

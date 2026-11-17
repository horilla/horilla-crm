"""Reusable component tags (inclusion tags) for Horilla templates."""

from inspect import getfullargspec

from django.template.base import Node
from django.template.library import parse_bits
from django.template.loader import get_template
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from ._registry import register

# Keyword on a template tag -> the attribute written in HTML. A template
# keyword cannot contain a colon, so ``__`` stands in for one: ``hx_on__click``
# is ``hx-on:click``. An htmx event keeps the second colon, so
# ``hx_on__after_request`` is ``hx-on::after-request``. ``hx_on_click`` is the
# same attribute; older call sites already pass it with one underscore.
# A name that is not listed still turns underscores into hyphens
# (``data_toggle`` is ``data-toggle``). Add a DOM event here before using it:
# the hyphen fallback would write ``hx-on--click``, which htmx reads as
# ``htmx:click``.
HX_TAGS = {
    "hx_get": "hx-get",
    "hx_post": "hx-post",
    "hx_put": "hx-put",
    "hx_patch": "hx-patch",
    "hx_delete": "hx-delete",
    "hx_target": "hx-target",
    "hx_swap": "hx-swap",
    "hx_swap_oob": "hx-swap-oob",
    "hx_trigger": "hx-trigger",
    "hx_select": "hx-select",
    "hx_select_oob": "hx-select-oob",
    "hx_push_url": "hx-push-url",
    "hx_replace_url": "hx-replace-url",
    "hx_indicator": "hx-indicator",
    "hx_vals": "hx-vals",
    "hx_vars": "hx-vars",
    "hx_include": "hx-include",
    "hx_params": "hx-params",
    "hx_confirm": "hx-confirm",
    "hx_disable": "hx-disable",
    "hx_disabled_elt": "hx-disabled-elt",
    "hx_disinherit": "hx-disinherit",
    "hx_encoding": "hx-encoding",
    "hx_ext": "hx-ext",
    "hx_headers": "hx-headers",
    "hx_history": "hx-history",
    "hx_history_elt": "hx-history-elt",
    "hx_boost": "hx-boost",
    "hx_preserve": "hx-preserve",
    "hx_prompt": "hx-prompt",
    "hx_sync": "hx-sync",
    "hx_validate": "hx-validate",
    "hx_request": "hx-request",
    "hx_inherit": "hx-inherit",
    "hx_on_click": "hx-on:click",
    "hx_on__click": "hx-on:click",
    "hx_on__after_request": "hx-on::after-request",
    "hx_on__before_request": "hx-on::before-request",
    "hx_on__config_request": "hx-on::config-request",
    "hx_on__before_swap": "hx-on::before-swap",
    "hx_on__after_swap": "hx-on::after-swap",
    "hx_on__after_settle": "hx-on::after-settle",
}


def html_attr_name(name):
    """The HTML attribute a template keyword writes."""
    return HX_TAGS.get(name, name.replace("_", "-"))


# Written out in full so the classes stay greppable.
SPINNER_SIZES = {
    "xs": "h-3 w-3",
    "sm": "h-5 w-5",
    "md": "h-6 w-6",
    "lg": "h-8 w-8",
}


@register.inclusion_tag("components/_reload_button.html", takes_context=True)
def reload_button(
    context,
    container,
    *,
    swap="outerHTML",
    url=None,
    trigger="click",
    label="click",
    indicator=None,
    button_id="reloadButton",
    hidden=True,
    **attrs,
):
    """
    Render a hidden HTMX button that refreshes ``container`` (a CSS selector).

    The button re-fetches the current page and replaces ``container`` with the same
    element taken from the response, so ``container`` is used for both ``hx-target``
    and ``hx-select``. Any other ``hx-*`` attribute is passed as a keyword with
    underscores (``hx_push_url="true"``, ``hx_select_oob="#dropdown-companies"``).
    A keyword whose name matches a generated attribute replaces it, so a different
    ``hx-select`` is ``hx_select="#other"`` and ``hx_select=""`` leaves it out.
    """

    if url is None:
        request = context.get("request")
        if request:
            query = request.GET.urlencode()
            url = f"{request.path}?{query}" if query else request.path
        else:
            url = ""

    pairs = {
        "hx-get": url,
        "hx-target": container,
        "hx-trigger": trigger,
        "hx-swap": swap,
        "hx-select": container,
        "hx-indicator": indicator,
    }

    # Custom attributes override defaults instead of creating duplicates.
    pairs.update((html_attr_name(name), value) for name, value in attrs.items())

    rendered = []
    for name, value in pairs.items():
        if value is None or value is False or value == "":
            continue

        rendered.append((name, None if value is True else value))

    return {
        "button_id": button_id,
        "hidden": hidden,
        "label": label,
        "attrs": rendered,
    }


@register.inclusion_tag("components/_modal_header.html")
def modal_header(title, on_close="closeModal()", button_id="", badge=None):
    """Render the standard modal header: title on the left, close button on the right.

    Usage:
        {% modal_header _("Account Hierarchy") %}
        {% modal_header _("Insert Fields") on_close="closeContentModal()" %}
    """
    return {
        "title": title,
        "on_close": on_close,
        "button_id": button_id,
        "badge": badge,
    }


@register.inclusion_tag("components/_spinner.html")
def spinner(size="lg", *, centered=False, wrapper_class=""):
    """Render the animated loading ring in the theme's primary colour.

    ``size`` is one of ``xs`` (h-3), ``sm`` (h-5), ``md`` (h-6) or ``lg`` (h-8,
    the default). ``centered=True`` wraps the ring in a
    ``flex justify-center items-center p-4`` block, the usual body of an
    ``.htmx-indicator``; ``wrapper_class`` adds classes to that block (e.g.
    ``"w-full"``). The outer element itself (``htmx-indicator``, ids, ``<li>``
    with hx-* attributes) differs per call site and stays in the template.

    Usage:
        {% spinner %}
        {% spinner "sm" %}
        {% spinner centered=True %}
    """
    if size not in SPINNER_SIZES:
        raise ValueError(
            f"Unknown spinner size {size!r}; expected one of {', '.join(SPINNER_SIZES)}"
        )
    return {
        "size_class": SPINNER_SIZES[size],
        "centered": centered,
        "wrapper_class": wrapper_class,
    }


BADGE_STYLES = {
    "success": "bg-green-100 text-green-700",
    "danger": "bg-red-100 text-red-700",
    "warning": "bg-yellow-100 text-yellow-700",
    "info": "bg-blue-100 text-blue-700",
    "neutral": "bg-gray-100 text-gray-600",
}
BADGE_DOTS = {
    "success": "bg-green-600",
    "danger": "bg-red-600",
    "warning": "bg-yellow-600",
    "info": "bg-blue-600",
    "neutral": "bg-gray-400",
}
BADGE_ICONS = ("check", "cross", "dot")


@register.inclusion_tag("components/_status_badge.html")
def status_badge(label, variant="neutral", *, icon=None):
    """Render a pill that names a status.

    ``variant`` is ``success``, ``danger``, ``warning``, ``info``, or
    ``neutral`` (the default). ``icon`` is ``check``, ``cross``, ``dot``,
    or left off. The label is escaped.

    Usage:
        {% status_badge _("Enabled") variant="success" icon="check" %}
        {% status_badge _("Disabled") icon="cross" %}
    """
    if variant not in BADGE_STYLES:
        raise ValueError(
            f"Unknown status badge variant {variant!r}; "
            f"expected one of {', '.join(BADGE_STYLES)}"
        )
    if icon == "":
        icon = None
    if icon is not None and icon not in BADGE_ICONS:
        raise ValueError(
            f"Unknown status badge icon {icon!r}; "
            f"expected one of {', '.join(BADGE_ICONS)}"
        )
    return {
        "label": label,
        "style": BADGE_STYLES[variant],
        "icon": icon,
        "dot_class": BADGE_DOTS[variant],
    }


def _breadcrumb_item(item):
    """Read ``name``, ``url``, and ``active`` from a dict or an object."""
    if isinstance(item, dict):
        name = item.get("name") or ""
        url = item.get("url") or ""
        active = bool(item.get("active"))
    else:
        name = getattr(item, "name", "") or ""
        url = getattr(item, "url", "") or ""
        active = bool(getattr(item, "active", False))
    return {"name": name, "url": "" if active else url, "active": active}


@register.inclusion_tag("components/_breadcrumbs.html")
def breadcrumb_nav(crumbs):
    """Render the folder breadcrumb trail.

    The tag is ``breadcrumb_nav`` so it does not hide the ``breadcrumbs``
    variable the views already put in the template context. Each crumb has
    ``name``, an optional ``url``, and an optional ``active``. The active
    crumb is the current page and is not a link. A crumb with a url replaces
    ``#mainContent``. Anything else is plain text. A missing or empty list
    still renders the nav, which is what the favourite pages do.

    Usage:
        {% breadcrumb_nav breadcrumbs %}
    """
    if not isinstance(crumbs, (list, tuple)):
        crumbs = []
    return {"crumbs": [_breadcrumb_item(item) for item in crumbs]}


HX_ANCHOR_DEFAULTS = (
    ("hx-trigger", "click"),
    ("hx-target", "#mainContent"),
    ("hx-select", "#mainContent"),
    ("hx-swap", "outerHTML"),
    ("hx-push-url", "true"),
)
# Variant name -> class string. ``submenu`` has a resting class and an
# ``active`` class for the current page. Written out in full so the classes
# stay greppable. The quotes in before:content-[''] cannot sit inside a
# template attribute: the formatter treats them as the end of the attribute.
HX_ANCHOR_VARIANTS = {
    "base": "hover:text-primary-600 transition duration-300 text-sm px-3 py-1.5",
    "submenu": {
        "class": (
            "ps-3 flex items-center text-sm py-1 rounded-md transition-colors "
            "duration-300 relative before:content-[''] before:absolute before:start-0 "
            "before:w-1 before:h-full before:bg-primary-600 before:opacity-0 "
            "hover:text-primary-600 hover:before:opacity-100"
        ),
        "active": (
            "ps-3 flex items-center text-sm py-1 rounded-md text-primary-600 "
            "transition-colors duration-300 relative before:content-[''] before:absolute "
            "before:start-0 before:w-1 before:h-full before:bg-primary-600 "
            "before:opacity-100 hover:text-primary-600 hover:before:opacity-100"
        ),
    },
}


@register.inclusion_tag("components/_hx_anchor.html")
def hx_anchor(label, *, variant=None, href="#", active=False, **attrs):
    """Render an anchor. ``variant="submenu"`` replaces ``#mainContent``.

    Only ``submenu`` gets ``hx-trigger``, ``hx-target``, ``hx-select``,
    ``hx-swap`` and ``hx-push-url`` from ``HX_ANCHOR_DEFAULTS``. Any other
    variant, and a tag with no variant, writes just the attributes passed
    in. Pass the same name with underscores to replace a default
    (``hx_target="#other"``). An empty value leaves that attribute off.
    ``active=True`` marks the current page. ``variant="base"`` is the
    dropdown item. With no variant, ``class`` is the class string.

    Usage:
        {% hx_anchor _("All Dashboards") variant="submenu" active=True hx_get=url %}
        {% hx_anchor _("All Folders") variant="submenu" hx_get=url %}
        {% hx_anchor _("Change Chart") variant="base" hx_get=url hx_target="#modalBox" hx_swap="innerHTML" %}
    """
    if variant is not None and variant not in HX_ANCHOR_VARIANTS:
        raise ValueError(
            f"Unknown hx_anchor variant {variant!r}; "
            f"expected one of {', '.join(HX_ANCHOR_VARIANTS)}"
        )
    classes = attrs.pop("class", "") or ""
    if variant is not None:
        spec = HX_ANCHOR_VARIANTS[variant]
        if isinstance(spec, dict):
            base = spec["active"] if active else spec["class"]
        else:
            base = spec
        classes = f"{base} {classes}".strip() if classes else base
    defaults = dict(HX_ANCHOR_DEFAULTS) if variant == "submenu" else {}
    pairs = dict(defaults)
    pairs.update((html_attr_name(name), value) for name, value in attrs.items())
    order = list(defaults)
    order.extend(name for name in pairs if name not in order)
    rendered = []
    for name in order:
        value = pairs[name]
        if value is None or value is False or value == "":
            continue
        if value is True:
            rendered.append(conditional_escape(name))
        else:
            rendered.append(format_html('{}="{}"', name, value))
    return {
        "label": label,
        "href": href,
        "classes": classes,
        "attrs": mark_safe(" ".join(rendered)),
    }


BTN_VARIANTS = {
    "primary": (
        "bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 "
        "text-white"
    ),
    "outline": (
        "outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md "
        "hover:bg-primary-300 transition duration-300 text-primary-600"
    ),
}
BTN_TAGS = ("button", "a", "span", "label")


def btn(
    label=None,
    *,
    variant="primary",
    sizing="text-sm px-4 py-2",
    extra_class="",
    tag="button",
    loading_id="",
    **attrs,
):
    """Render a themed button with the shared primary or outline colour tokens.

    The tag owns the colour tokens; ``sizing`` carries text size, padding and width
    (default ``text-sm px-4 py-2``) and ``extra_class`` any other class or JS hook.
    Other keywords become attributes through ``HX_TAGS``
    (``hx_get`` is ``hx-get``, ``hx_on__click`` is ``hx-on:click``,
    ``hx_on__after_request`` is ``hx-on::after-request``). ``True`` renders a
    bare attribute; ``None``, ``False``
    and ``""`` leave it out. ``tag`` is ``button`` (default), ``a``, ``span`` or
    ``label``. ``label`` defaults to "Save" for ``type="submit"``; any other type
    needs one, unless ``body`` is set and the contents are between ``{% endbtn %}``.

    ``loading_id`` puts the HTMX spinner image inside the button, before the label,
    in a ``htmx-indicator`` span with that id; point ``hx_indicator`` at it.
    ``body`` switches on ``{% endbtn %}`` so the template can place an icon or
    other markup inside the control. Without ``body`` there is no closing tag.

    Usage:
        {% btn type="submit" %}
        {% btn type="submit" hx_indicator="#single-form-save-spinner" loading_id="single-form-save-spinner" %}
        {% btn body type="submit" sizing="p-3 w-full" extra_class="flex gap-3 justify-center" %}
            <img src="..." alt="">
            {% trans "Sign In" %}
        {% endbtn %}
    """
    if variant not in BTN_VARIANTS:
        raise ValueError(
            f"Unknown btn variant {variant!r}; expected one of {', '.join(BTN_VARIANTS)}"
        )
    if tag not in BTN_TAGS:
        raise ValueError(
            f"Unknown btn tag {tag!r}; expected one of {', '.join(BTN_TAGS)}"
        )
    has_body = attrs.pop("has_body", False)
    if label is None and not has_body:
        if attrs.get("type") != "submit":
            raise ValueError('btn needs a label unless type="submit"')
        label = _("Save")

    classes = " ".join(
        part for part in (BTN_VARIANTS[variant], sizing, extra_class) if part
    )
    rendered = []
    for name, value in attrs.items():
        if value is None or value is False or value == "":
            continue
        rendered.append((html_attr_name(name), None if value is True else value))

    return {
        "tag": tag,
        "label": label,
        "classes": classes,
        "attrs": rendered,
        "loading_id": loading_id,
        "body": "",
    }


class BtnNode(Node):
    """Renders ``{% btn %}``. With ``body``, the nodelist is the inner HTML."""

    def __init__(self, args, kwargs, nodelist):
        self.args = args
        self.kwargs = kwargs
        self.nodelist = nodelist

    def render(self, context):
        resolved_args = [arg.resolve(context) for arg in self.args]
        resolved_kwargs = {
            key: value.resolve(context) for key, value in self.kwargs.items()
        }
        if self.nodelist is not None:
            resolved_kwargs["has_body"] = True
        data = btn(*resolved_args, **resolved_kwargs)
        if self.nodelist is not None:
            data["body"] = mark_safe(self.nodelist.render(context))
            data["loading_id"] = ""

        return get_template("components/_btn.html").render(data)


@register.tag("btn")
def compile_btn(parser, token):
    """Compile ``{% btn %}``. ``body`` is the only signal that ``{% endbtn %}`` follows."""
    bits = token.split_contents()[1:]
    has_body = "body" in bits
    bits = [bit for bit in bits if bit != "body"]
    spec = getfullargspec(btn)
    args, kwargs = parse_bits(
        parser,
        bits,
        spec.args,
        spec.varargs,
        spec.varkw,
        spec.defaults,
        spec.kwonlyargs,
        spec.kwonlydefaults,
        "btn",
    )
    nodelist = None
    if has_body:
        nodelist = parser.parse(("endbtn",))
        parser.delete_first_token()

    return BtnNode(args, kwargs, nodelist)

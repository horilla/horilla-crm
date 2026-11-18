# Misc template tags (`horilla_generics/templatetags/horilla_tags/misc_tags.py`)

## Purpose

`misc_tags.py` contains small generic tags that do not fit other specialized tag modules:

- `eq` — true when two values are equal
- `sanitize_html` — clean stored rich text before it is rendered
- `empty_add_message` — standard empty-list sentence for generic views
- `get_user_model_meta` — user model identity metadata for dynamic components

`horilla_tags` is a **built-in** library — do not add `{% load horilla_tags %}` in new templates. See [coding_rule.md](../../../../../coding_rule.md#django-templates--built-in-tag-libraries).

---

## `eq` (filter)

Returns true when the value equals the argument. A template-tag argument cannot contain `==`, so this is how one keyword is turned on for the current page:

```django
{% hx_anchor _("All Dashboards") variant="submenu" active=active|eq:"all_dashboards" hx_get=url %}
```

`partials/dashboard_sidebar.html` uses it for `all_dashboards`, `all_folders`, `folders`, and `dashboards`. Only the matching link gets the current-page class.

## `empty_add_message` (simple_tag)

Returns a translated empty-list sentence with the model’s verbose name interpolated:

```python
_("Nothing to show yet. Please add your %(model)s.") % {"model": model_verbose_name}
```

### Template usage

Used in generic list/kanban/card templates when the queryset is empty and no filters are active:

```django
{% empty_add_message model_verbose_name %}
```

For **custom** empty screens (settings gates, accordion lists, history tabs), prefer resolving a message and including [empty_state.html](../../../../../templates/components/empty_state.md):

```django
{% trans "Nothing to show yet. Please add your Matching Rules." as empty_state_message %}
{% include "components/empty_state.html" with message=empty_state_message %}
```

---

## `get_user_model_meta` (simple_tag)

Returns a dictionary describing the `User` model from `horilla.auth.models`.

Returned keys:

- `app_label`: `User._meta.app_label`
- `model_name`: `User._meta.model_name` (lowercase model identifier)
- `model_class_name`: `User.__name__` (class name, e.g. `User`)

Example return shape:

```python
{
  "app_label": "auth",
  "model_name": "user",
  "model_class_name": "User",
}
```

### Template usage

```django
{% get_user_model_meta as user_meta %}
```

Use values:

```django
data-app="{{ user_meta.app_label }}"
data-model="{{ user_meta.model_name }}"
data-class="{{ user_meta.model_class_name }}"
```

Typical uses: dynamic URLs, data attributes, or generic helper components requiring model identifiers.

---

## Design notes

- `get_user_model_meta` reads model metadata from imported `User` directly (not from settings-based runtime lookup).
- Because output is static metadata, there is no request/user dependency in that tag.
- The tags are lightweight and safe for repeated template usage.

---

## Caveats

- If project user model strategy changes from `horilla.auth.models.User`, `get_user_model_meta` must be updated accordingly.
- Key names are fixed; template code should rely on exactly:
  - `app_label`
  - `model_name`
  - `model_class_name`

---

## Summary

| Tag | Role |
|-----|------|
| `eq` | Boolean equality for a tag keyword, such as `active=active\|eq:"folders"` |
| `sanitize_html` | Sanitized rich text marked safe for rendering |
| `empty_add_message` | Standard “add your first …” sentence for generic list/kanban/card empty states |
| `get_user_model_meta` | Exposes `User` model app/model/class identifiers for dynamic template components |

Related: [empty-state partials](../../../../../templates/components/empty_state.md)

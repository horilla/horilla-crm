# URL filters (`horilla_generics/templatetags/horilla_tags/url_filters.py`)

## Purpose

`url_filters.py` provides template-level URL manipulation helpers.

It contains two filters:

- `concat` — join two values as text
- `remove_query_param` — drop one query key from a URL

`horilla_tags` is a built-in library. Do not add `{% load horilla_tags %}`.

---

## `concat(value, arg)`

Joins two values as text. `None` on either side is an empty string. An integer is written as its digits, so a primary key can be appended without `stringformat`.

```django
{% url 'reports:change_chart_type' report.pk as change_chart_url %}
hx_get=change_chart_url|concat:"?total="|concat:total_groups_count
```

With report `4` and a total of `1`, that is `/reports/change-chart-type/4/?total=1`.

Use `concat` when the page loads `reports_tags`. That library's `add` only adds numbers. A path plus `?total=` is not a number, so that `add` returns the original path and the query is lost. Django's own `add` still concatenates strings on pages that do not load `reports_tags`. The dashboard sidebar uses that `add` for `url|add:"?"|add:request.GET.urlencode`.

A `{% %}` tag does not evaluate `{{ }}` inside its arguments. Build the string with `concat` (or `{% url %} … as name`) instead of writing `{{ report.pk }}` inside `{% hx_anchor %}`.

## `remove_query_param(url, param)`

Removes one query parameter from a URL string and returns the updated URL.

Template usage:

```django
{{ request.get_full_path|remove_query_param:"section" }}
```

---

## How it works

Implementation steps:

1. parse URL using `urlparse(url)`
2. parse query dict with:
   - `parse_qs(..., keep_blank_values=True)`
3. remove target key:
   - `query_params.pop(param, None)`
4. rebuild query string using:
   - `urlencode(query_params, doseq=True)`
5. reconstruct final URL with original components via:
   - `urlunparse(parsed_url._replace(query=new_query))`

Result preserves:

- path
- scheme/host (if present)
- fragment (`#...`)
- all non-removed query params

---

## Behavior details

### Removes all values for that key

If parameter appears multiple times:

```text
?field=name&field=email&search=john
```

Removing `field` removes all `field` entries.

### Keeps blank-value params

Because `keep_blank_values=True`, params like `foo=` are retained unless explicitly removed.

### Safe no-op when key missing

If parameter does not exist, URL is returned unchanged.

---

## Practical examples

### Remove a filter key

Input:

```text
/employees/?field=department&operator=exact&value=3&page=2
```

Template:

```django
{{ request.get_full_path|remove_query_param:"page" }}
```

Output:

```text
/employees/?field=department&operator=exact&value=3
```

### Remove search key

```django
{{ request.get_full_path|remove_query_param:"search" }}
```

Useful for "clear search" links while preserving other active filters.

### Preserve fragment/hash

Input:

```text
/list/?section=details#tab2
```

Removing `section` keeps:

```text
/list/#tab2
```

---

## Typical template patterns

```django
<a href="{{ request.get_full_path|remove_query_param:'search' }}">
  Clear Search
</a>
```

```django
<a href="{{ request.get_full_path|remove_query_param:'page' }}">
  Reset Pagination
</a>
```

---

## Caveats

- This filter removes exactly one key per call; chain calls to remove multiple params.
- It does not normalize parameter ordering beyond Python dict/urlencode behavior.
- Expects a URL-like string; non-URL values may produce unexpected parse results.

---

## Summary

`concat` joins text, including a path and a query string, on pages where `reports_tags` has replaced Django's `add`. `remove_query_param` drops one query key and keeps the rest of the URL.

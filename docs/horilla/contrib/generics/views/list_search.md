# List search box (`navbar.html`, `list_search.js`)

## Purpose

A dropdown under the list's search input lets the user pick **which field** to search, or a **quick filter**, instead of searching every field at once. The input itself is unchanged; what is applied shows in the navbar's **applied-filter tag** (see `partials/applied_filters_slot.html`), which also removes it.

It is shown for any navbar whose `filterset_class` has `Meta.search_fields` and which pushes the URL (`search_push_url`). Other navbars keep the plain search input.

## What the user gets

- Typing opens **Search All for: text** with the total number of matching records in a primary round badge, as in global search. When the list has more than one search field, a line per field follows (**Search Email for: text**, ...), each with its own count. With a single search field there is just one line, named after that field (**Search Name for: text**), because "All" would only repeat it. "All" (or Enter) searches every field; any other line searches that field only. Nothing is searched until a choice is made.
- An empty box opens **Recent Searches** (last five, kept in the browser per list) and, when the list has a filter panel, **Quick Filters**: My Records, Created Today, Created Yesterday, Created This Week, Created This Month, each with a count. A quick filter is an **ordinary filter row**: it is added to the filter panel, counted in the filter badge, listed in the tag's card, saved with "Save to List" and removed like any other filter. Ones already applied are hidden.
- When nothing matches, the dropdown offers **Search all modules**, which opens global search.
- Keyboard: Up / Down, Enter, Esc.
- The tag shows each field search as `Email Contains gmail`. Different fields combine with AND, the same field repeated with OR. With only searches applied, the tag's close button clears them all; with real filters too, the card lists them and each row removes just that one. Clear All removes everything.

## Query parameters

| Parameter | Format | Applied by |
|-----------|--------|------------|
| `sf` (repeatable) | `<field>:<text>`, `field` = `all` or an entry of `Meta.search_fields` | `HorillaFilterSet.apply_search_facets` |
| `search_suggest` | text typed so far (may be empty) | `HorillaListView.render_search_suggest` |
| `quick_filters` | `true` to include the quick filters in the dropdown (sent only when the list has a filter panel) | `HorillaListView.render_search_suggest` |
| `remove_filter` | `search`, `search_all`, `sf:<position>` (besides the existing filter row index) | `handle_remove_filter` in `mixins.py` |

`qf_<field>` belongs to the existing saved quick filters and is unrelated.

## Pieces

| Piece | Role |
|-------|------|
| `HorillaFilterSet.get_search_field_labels()` | Field choices and labels, from `Meta.search_fields` (verbose names) |
| `HorillaFilterSet.apply_search_facets` | Applies `sf` to the list queryset |
| `search_support.list_quick_filters` | The quick filters as filter rows (`field`, `operator`, `value`) for the fields the list can filter on; "My Records" uses the model's first owner field |
| `search_support.py` (rest) | `build_field_labels`, `resolve_lookup_label`, and the quick-filter code global search uses (`apply_preset_filter`) |
| `HorillaListView.render_search_suggest` | Dropdown fragment `partials/list_search_suggest.html`; counts start from the current list, so they show what adding the choice leaves. Quick filter counts run through the list's own filterset |
| `applied_filters.build_applied_filter_rows` | Adds `sf` rows (marked `is_search`) to the tag, with `row_id` `sf:<position>` |
| `HorillaNavView.get_context_data` | `list_search_enabled` |
| `navbar.html` | Adds the dropdown holder under the input and puts `sf` in the input's `hx-get` |
| `static/generics/js/list_search.js` | Fetches the dropdown. A field search adds `sf` to the page URL, points the input's `hx-get` at it and fires the input's `search` trigger. A quick filter appends a filter row to the page URL and sends the same request as the filter panel's Apply (same target, with `#navBar` refreshed). Keeps recent searches |

The page URL is the source of truth: the script reads it each time, so the dropdown always matches what the tag shows.

## Setting a list's search fields

Search fields come from the filterset:

```python
class LeadFilter(HorillaFilterSet):
    class Meta:
        model = Lead
        fields = "__all__"
        search_fields = ["title", "first_name", "last_name", "email", "contact_number"]
```

Each entry becomes a field choice labelled with the field's verbose name. A relation path (`"owner__first_name"`) is allowed; its label is built from the two verbose names. Entries that are not fields of the model are left out.

**Combined name.** When `first_name` and `last_name` are both in `search_fields` (or `Meta.name_split_fields` names two other fields that are, for example `host__first_name` and `host__last_name`), the dropdown offers one **Name** choice instead of two (**Host Name** for a pair taken from a relation). It is applied as `sf=first_name+last_name:<text>`: "John Mathew" matches first name John and last name Mathew, and a single word matches either name. This is the same split the plain search already does for a full name.

A list with a single search field shows only that field, so add the fields users look for. Keep to plain text fields and relation names: a field with `choices` stores codes, not the labels users type. Leave out technical values (ids, app labels, API keys and secrets). A relation to a content type is searched through its `model` and shows under the relation's name, such as **Module**.

## Limits

- The chart and group-by layouts only forward the plain `search` input, so `sf` is not carried into them.
- Counting every field costs one query per field, so the dropdown lists at most `HorillaListView.search_suggest_max_fields` (8) fields.
- Inline operators such as `owner:me` are not supported yet.

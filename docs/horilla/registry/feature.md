# Feature Registry (`feature.py`)

## Purpose

`horilla/registry/feature.py` is the central registry for mapping **feature names** to **model classes**.

It is used when Horilla needs to answer:
- Which models support `global_search`?
- Which models support custom feature `review_process`?

## Core Objects

- `FEATURE_CONFIG`: maps `feature_name -> registry_key`
- `FEATURE_REGISTRY`: maps `registry_key -> [model_class, ...]`
- `FEATURE_DEFAULT_OPTIONS`: maps `feature_name -> {option: value}` (defaults for every model of a feature)
- `FEATURE_MODEL_OPTIONS`: maps `feature_name -> {model_class: {option: value}}` (see [Feature options](#feature-options))

Default features:
- `import_data`
- `export_data`
- `global_search`

Apps add more via `register_feature()`. `horilla.contrib.field_management`
registers `field_requirements` → `field_requirement_models` with
`auto_register_all=False`, so models must opt in explicitly. See
[field requirements](../contrib/field_management/field_requirements.md).
`horilla.contrib.field_management` registers `form_layouts` → `form_layout_models`
the same way. See [form layouts](../contrib/field_management/form_layouts.md).

## Main APIs

### `register_feature(...)`

Registers a feature and configures how models are included.

    register_feature(
        feature_name="review_process",
        registry_key="review_process_models",
        exclude_app_label=None,
        auto_register_all=True,
        include_models=None,
        exclude_models=None,
        default_options=None,   # {option: value} every model of this feature starts with
    )

### register_model_for_feature(...)

**Registers one model for one or more features.**
    Valid usage examples
    Preferred (modern) style: features
        register_model_for_feature(
          app_label="leads",
          model_name="Lead",
          features=["global_search", "import_data"],
        )

### Legacy style: boolean flags
        register_model_for_feature(
          app_label="leads",
          model_name="Lead",
          import_data=True,
          global_search=True,
        )
### Enable all features, then exclude one
        register_model_for_feature(
          app_label="leads",
          model_name="Lead",
          all=True,
          exclude=["export_data"],
        )

### register_models_for_feature(...)

**Bulk version for multiple models.**
        result = register_models_for_feature(
          models=[("accounts", "Account"), ("contacts", "Contact")],
          features=["review_process"],
        )
**Result includes:**
    * registered
    * failed
    * total

**Real Usage Pattern:**
In app registration.py:
Define custom feature (if needed) using register_feature.
Register model(s) using register_model_for_feature or register_models_for_feature.
Consumer code reads from FEATURE_CONFIG + FEATURE_REGISTRY.

## Feature options

Besides "which models", a feature often needs per-model settings, for example which
fields global search looks in, or which columns an export includes. Options carry
those settings, so an app can configure its own models from its `registration.py`
without editing the feature's code. Each feature chooses its own option names; the
registry only stores and merges them.

### Setting options

    # 1. While registering the model
    register_model_for_feature(
      app_label="leads",
      model_name="Lead",
      features=["global_search"],
      options={"global_search": {"search_fields": ["title", "email"]}},
    )

    # 2. Separately (also works for models registered in a group)
    set_feature_options(
      "global_search",
      {"columns": ["title", ("Email", "email")]},
      app_label="leads",
      model_name="Lead",            # or model_class=Lead
    )

    # 3. On the model class
    class Lead(...):
        FEATURE_OPTIONS = {"global_search": {"search_fields": ["title"]}}

    # 4. Defaults for every model of a feature
    register_feature("my_feature", default_options={"batch_size": 500})

Calling `set_feature_options` again for the same model and feature updates the given
options and keeps the others. A feature name or its registry key
(`global_search_models`) can be used.

### Reading options

    options = get_feature_options("global_search", Lead)
    options.get("search_fields")      # None / missing means "choose automatically"

Sources are merged option by option; later ones win:

1. `register_feature(default_options=...)`
2. the model's `FEATURE_OPTIONS[feature]`
3. `set_feature_options(...)` / `register_model_for_feature(options=...)`

### Options used by built-in features

| Feature | Option | Meaning |
|---------|--------|---------|
| `global_search` | `search_fields` | Lookups searched with `icontains`: `"name"`, `"owner__first_name"` or `("Label", "lookup")`. Default: first 5 text fields. |
| `global_search` | `columns` | Columns in the results table: `"field"` or `("Label", "field")`, direct fields only. Default: the direct fields of `search_fields`. |

See [global search](../contrib/generics/views/global_search.md).
```

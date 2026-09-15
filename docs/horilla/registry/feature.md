# Feature Registry (`feature.py`)

## Purpose

`horilla/registry/feature.py` is the central registry for mapping **feature names** to **model classes**.

It is used when Horilla needs to answer:
- Which models support `global_search`?
- Which models support custom feature `review_process`?

## Core Objects

- `FEATURE_CONFIG`: maps `feature_name -> registry_key`
- `FEATURE_REGISTRY`: maps `registry_key -> [model_class, ...]`

Default features:
- `import_data`
- `export_data`
- `global_search`

Apps add more via `register_feature()`. `horilla.contrib.field_requirements`
registers `field_requirements` → `field_requirement_models` with
`auto_register_all=False`, so models must opt in explicitly. See
[field requirements](../contrib/field_requirements/field_requirements.md).
`horilla.contrib.form_layouts` registers `form_layouts` → `form_layout_models`
the same way. See [form layouts](../contrib/form_layouts/form_layouts.md).

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

### register_model_for_feature(...)

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
```

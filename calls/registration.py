"""Feature registration for the Horilla Calls Integration app."""

from horilla.registry.feature import register_model_for_feature

# Registry: any app can call register_callable_model() to make its objects
# linkable to calls (phone number matching on inbound + validation on outbound).
# Format: (app_label, model_name, phone_field)
_CALLABLE_MODEL_REGISTRY: list[tuple[str, str, str]] = []


def register_callable_model(app_label: str, model_name: str, phone_field: str) -> None:
    """Register a model whose phone_field should be matched against call numbers."""
    _CALLABLE_MODEL_REGISTRY.append((app_label, model_name.lower(), phone_field))


register_model_for_feature(
    app_label="calls",
    model_name="CallProvider",
    features=["export_data"],
)

register_model_for_feature(
    app_label="calls",
    model_name="CallLog",
    features=["global_search"],
    options={
        "global_search": {
            "search_fields": [
                "from_number",
                "to_number",
                "direction",
                "status",
                "provider__name",
            ],
            "columns": [
                ("From", "from_number"),
                ("To", "to_number"),
                "direction",
                "status",
                ("Provider", "provider"),
                ("Started", "started_at"),
            ],
        }
    },
)

register_model_for_feature(
    app_label="calls",
    model_name="AgentMapping",
    features=["import_data", "export_data"],
)

"""
Feature registration for the workflow app.
"""

from horilla.registry.feature import register_feature, register_models_for_feature

register_feature(
    "workflow",
    "workflow_models",
    auto_register_all=False,
)

# Personal preferences/logs: ignored in the delete dependency dialog.
register_models_for_feature(
    models=[
        ("workflow", "ScheduledWorkflowExecution"),
    ],
    features=["delete_dependency"],
)

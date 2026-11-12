# horilla/registry/feature.py
"""
Feature registry for Horilla.

Features are capabilities that can be attached to Django models (e.g. import_data,
export_data, global_search). The registry answers: "which models support feature X?"

Usage :

  1. Register a feature (optional for core features; required for custom ones):
     register_feature("my_feature", include_models=[("my_app", "MyModel")])

  2. Register models for features:
     register_model_for_feature(app_label="my_app", model_name="MyModel", features=["import_data"])
     register_models_for_feature(models=[("my_app", "A"), ("my_app", "B")], features=["global_search"])

  3. Give a feature per-model settings (optional; each feature documents its own options):
     register_model_for_feature(
         app_label="my_app", model_name="MyModel", features=["global_search"],
         options={"global_search": {
             "search_fields": ["name", ("Owner", "owner__first_name")],  # fields to search
             "columns": ["name", ("Owner", "owner")],           # columns shown in results
         }},
     )
     Other ways to set the same thing: set_feature_options("global_search", {...},
     app_label=..., model_name=...), or on the model class:
     FEATURE_OPTIONS = {"global_search": {...}}.
     A feature can also give every model defaults: register_feature("x", default_options={...}).
     Features read them with get_feature_options("global_search", model_class).

Consumers get the list of models for a feature via FEATURE_CONFIG[feature_name] -> registry key,
then FEATURE_REGISTRY[registry_key] -> list of model classes.
"""

import logging
from collections import defaultdict

from django.apps import apps

logger = logging.getLogger(__name__)

FEATURE_REGISTRY = defaultdict(list)

# Track models registered with all=True and their exclude lists
# Format: {model_class: set(excluded_features)}
ALL_FEATURES_MODELS = {}

# Track which app(s) to exclude from auto-registration for a feature
# Format: {feature_name: frozenset([app_label, ...])} or empty/not set
FEATURE_REGISTERING_APP = {}

# Track whether exclude_app_label was explicitly passed (only then do we skip that app)
# Format: {feature_name: bool}
FEATURE_EXCLUDE_APP_EXPLICIT = {}

_EXCLUDE_APP_NOT_PASSED = object()

# Track feature-specific include models (for selective registration)
# Format: {feature_name: [model_class, ...]}
FEATURE_INCLUDE_MODELS = {}

# Track feature-specific exclude models (for excluding from auto-registration)
# Format: {feature_name: [model_class, ...]}
FEATURE_EXCLUDE_MODELS = {}

# Track whether features should auto-register all=True models
# Format: {feature_name: bool}
FEATURE_AUTO_REGISTER_ALL = {}

# Buffer for models registered for a feature before the feature itself was registered
# Format: {feature_name_or_registry_key: [model_class, ...]}
FEATURE_PENDING_MODELS = defaultdict(list)

# Reverse lookup: registry_key -> feature_name
FEATURE_REGISTRY_KEY_TO_NAME = {}

# Feature options: extra settings a feature reads per model (which fields to search,
# which columns to export, ...). Each feature decides its own option names.
# Defaults for every model of a feature, set via register_feature(default_options=...).
# Format: {feature_name: {option: value}}
FEATURE_DEFAULT_OPTIONS = {}

# Options set for one model, via set_feature_options() or
# register_model_for_feature(options=...).
# Format: {feature_name: {model_class: {option: value}}}
FEATURE_MODEL_OPTIONS = defaultdict(dict)

# Feature configuration: feature_name -> registry_key.
# Core features: import_data, export_data, global_search. Apps add more via register_feature().
FEATURE_CONFIG = {
    "import_data": "import_models",
    "export_data": "export_models",
    "global_search": "global_search_models",
}


def register_feature(
    feature_name,
    registry_key=None,
    exclude_app_label=_EXCLUDE_APP_NOT_PASSED,
    auto_register_all=None,  # None means auto-detect based on include_models
    include_models=None,
    exclude_models=None,
    default_options=None,
):
    """
    Register a new feature dynamically from any app.

    Args:
        feature_name: Feature name (e.g., "workflow", "notification")
        registry_key: Registry key in FEATURE_REGISTRY (defaults to "{feature_name}_models")
        exclude_app_label: App label(s) to exclude from auto-registration. Can be a single string
                          (e.g. "duplicates") or a list (e.g. ["duplicates", "other_app"]).
                          Only applied when explicitly passed; if omitted, no app is excluded.
        auto_register_all: If True, automatically register all models with all=True.
                          If False, only register models specified in include_models.
                          If None (default), automatically set to False when include_models is provided,
                          otherwise defaults to True (auto-register all all=True models).
        include_models: List of specific models to register. Can be:
                       - List of tuples: [("app_label", "model_name"), ...]
                       - List of model classes: [ModelClass, ...]
                       - List of strings: ["app_label.model_name", ...]
                       If provided, only these models will be registered (overrides auto_register_all).
        exclude_models: List of specific models to exclude from auto-registration when auto_register_all=True.
                       Can be:
                       - List of tuples: [("app_label", "model_name"), ...]
                       - List of model classes: [ModelClass, ...]
                       - List of strings: ["app_label.model_name", ...]
                       - Single tuple, model class, or string (will be converted to list)
                       Only works when auto_register_all=True.
        default_options: Dict of options every model of this feature starts with, e.g.
                       {"batch_size": 500}. A model can override them (see
                       set_feature_options). Read them with get_feature_options().

    Example:
        # Basic registration (auto-registers all all=True models)
        register_feature("workflow")

        # Selective registration - only specific models
        # auto_register_all is automatically False when include_models is provided
        register_feature(
            "duplicate_data",
            "duplicate_models",
            exclude_app_label="duplicates",
            include_models=[
                ("core","User")
            ]
        )

        # Auto-register all=True models but exclude specific ones
        register_feature(
            "notification_template",
            "notification_template_models",
            auto_register_all=True,
            exclude_models=[
                ("core", "User"),  # Exclude this model
            ],

        )

    Returns:
        bool: True if registered, False if already exists
    """

    if registry_key is None:
        registry_key = f"{feature_name}_models"

    if default_options:
        FEATURE_DEFAULT_OPTIONS[feature_name] = dict(default_options)

    # Auto-determine auto_register_all if not explicitly set
    if auto_register_all is None:
        # If include_models is provided, default to selective registration (False)
        # If include_models is NOT provided, default to True (auto-register all all=True models)
        auto_register_all = not include_models

    # Only apply exclude_app_label when explicitly passed; do not auto-detect for exclusion
    explicit_exclude_app = exclude_app_label is not _EXCLUDE_APP_NOT_PASSED
    if not explicit_exclude_app:
        exclude_app_label = None
    # Normalize to frozenset of app labels (or None) for consistent membership checks
    if exclude_app_label is not None:
        excluded_apps = frozenset(
            [exclude_app_label]
            if isinstance(exclude_app_label, str)
            else exclude_app_label
        )
    else:
        excluded_apps = None

    if feature_name in FEATURE_CONFIG:
        logger.warning(
            "Feature '%s' is already registered. "
            "Overwriting registry key from '%s' to '%s'",
            feature_name,
            FEATURE_CONFIG[feature_name],
            registry_key,
        )
        # Store old registry key before updating
        old_registry_key = FEATURE_CONFIG[feature_name]

        FEATURE_CONFIG[feature_name] = registry_key
        FEATURE_REGISTRY_KEY_TO_NAME[registry_key] = feature_name
        FEATURE_AUTO_REGISTER_ALL[feature_name] = auto_register_all

        # If switching to selective registration, clear existing models from registry
        if not auto_register_all:
            # Clear from old registry key
            if old_registry_key in FEATURE_REGISTRY:
                FEATURE_REGISTRY[old_registry_key].clear()
                logger.info(
                    "Cleared existing models from feature '%s' registry (key: '%s') for selective registration",
                    feature_name,
                    old_registry_key,
                )
            # Also clear from new registry key if it's different
            if registry_key != old_registry_key and registry_key in FEATURE_REGISTRY:
                FEATURE_REGISTRY[registry_key].clear()
                logger.info(
                    "Cleared existing models from feature '%s' registry (key: '%s') for selective registration",
                    feature_name,
                    registry_key,
                )

        # Update exclude app(s) only when explicitly passed
        FEATURE_EXCLUDE_APP_EXPLICIT[feature_name] = explicit_exclude_app
        if excluded_apps is not None:
            FEATURE_REGISTERING_APP[feature_name] = excluded_apps
        # Update include models if provided
        if include_models:
            # Process include_models (same logic as below)
            included_model_classes = []
            for model_spec in include_models:
                model_class = None
                if isinstance(model_spec, tuple) and len(model_spec) == 2:
                    app_label, model_name = model_spec
                    try:
                        model_class = apps.get_model(app_label, model_name)
                    except LookupError:
                        continue
                elif isinstance(model_spec, str) and "." in model_spec:
                    try:
                        app_label, model_name = model_spec.split(".", 1)
                        model_class = apps.get_model(app_label, model_name)
                    except (ValueError, LookupError):
                        continue
                elif hasattr(model_spec, "_meta"):
                    model_class = model_spec

                if model_class and model_class not in included_model_classes:
                    included_model_classes.append(model_class)
            FEATURE_INCLUDE_MODELS[feature_name] = included_model_classes

            # Register only the included models (excluded app(s) do not apply to explicit includes)
            for model_class in included_model_classes:
                if model_class not in FEATURE_REGISTRY[registry_key]:
                    FEATURE_REGISTRY[registry_key].append(model_class)

        # Update exclude models if provided
        if exclude_models:
            # Process exclude_models (same logic as below)
            excluded_model_classes = []
            if not isinstance(exclude_models, list):
                exclude_models = [exclude_models]

            for model_spec in exclude_models:
                model_class = None
                if isinstance(model_spec, tuple) and len(model_spec) == 2:
                    app_label, model_name = model_spec
                    try:
                        model_class = apps.get_model(app_label, model_name)
                    except LookupError:
                        continue
                elif isinstance(model_spec, str) and "." in model_spec:
                    try:
                        app_label, model_name = model_spec.split(".", 1)
                        model_class = apps.get_model(app_label, model_name)
                    except (ValueError, LookupError):
                        continue
                elif hasattr(model_spec, "_meta"):
                    model_class = model_spec

                if model_class and model_class not in excluded_model_classes:
                    excluded_model_classes.append(model_class)

            FEATURE_EXCLUDE_MODELS[feature_name] = excluded_model_classes

            # Remove excluded models from registry
            for model_class in excluded_model_classes:
                if model_class in FEATURE_REGISTRY[registry_key]:
                    FEATURE_REGISTRY[registry_key].remove(model_class)
                    logger.debug(
                        "Removed excluded model %s from feature '%s' registry",
                        model_class,
                        feature_name,
                    )
        return False

    FEATURE_CONFIG[feature_name] = registry_key
    FEATURE_REGISTRY_KEY_TO_NAME[registry_key] = feature_name
    FEATURE_AUTO_REGISTER_ALL[feature_name] = auto_register_all

    FEATURE_EXCLUDE_APP_EXPLICIT[feature_name] = explicit_exclude_app
    if excluded_apps is not None:
        FEATURE_REGISTERING_APP[feature_name] = excluded_apps

    # Process include_models if provided
    included_model_classes = []
    if include_models:
        for model_spec in include_models:
            model_class = None
            if isinstance(model_spec, tuple) and len(model_spec) == 2:
                # Tuple format: ("app_label", "model_name")
                app_label, model_name = model_spec
                try:
                    model_class = apps.get_model(app_label, model_name)
                except LookupError as e:
                    logger.warning(
                        "Could not find model '%s.%s' for feature '%s': %s",
                        app_label,
                        model_name,
                        feature_name,
                        e,
                    )
                    continue
            elif isinstance(model_spec, str):
                # String format: "app_label.model_name"
                if "." in model_spec:
                    try:
                        app_label, model_name = model_spec.split(".", 1)
                        model_class = apps.get_model(app_label, model_name)
                    except (ValueError, LookupError) as e:
                        logger.warning(
                            "Could not parse or find model '%s' for feature '%s': %s",
                            model_spec,
                            feature_name,
                            e,
                        )
                        continue
            elif hasattr(model_spec, "_meta"):
                # Model class directly
                model_class = model_spec
            else:
                logger.warning(
                    "Invalid model specification '%s' for feature '%s'. "
                    "Expected tuple, string, or model class.",
                    model_spec,
                    feature_name,
                )
                continue

            if model_class and model_class not in included_model_classes:
                included_model_classes.append(model_class)

        FEATURE_INCLUDE_MODELS[feature_name] = included_model_classes
        logger.info(
            "Registered new feature '%s' -> '%s' with %s specific models",
            feature_name,
            registry_key,
            len(included_model_classes),
        )
    else:
        FEATURE_INCLUDE_MODELS[feature_name] = []

    # Process exclude_models if provided
    excluded_model_classes = []
    if exclude_models:
        # Handle single model (not a list) - convert to list
        if not isinstance(exclude_models, list):
            exclude_models = [exclude_models]

        for model_spec in exclude_models:
            model_class = None
            if isinstance(model_spec, tuple) and len(model_spec) == 2:
                # Tuple format: ("app_label", "model_name")
                app_label, model_name = model_spec
                try:
                    model_class = apps.get_model(app_label, model_name)
                except LookupError as e:
                    logger.warning(
                        "Could not find model '%s.%s' to exclude from feature '%s': %s",
                        app_label,
                        model_name,
                        feature_name,
                        e,
                    )
                    continue
            elif isinstance(model_spec, str):
                # String format: "app_label.model_name"
                if "." in model_spec:
                    try:
                        app_label, model_name = model_spec.split(".", 1)
                        model_class = apps.get_model(app_label, model_name)
                    except (ValueError, LookupError) as e:
                        logger.warning(
                            "Could not parse or find model '%s' to exclude from feature '%s': %s",
                            model_spec,
                            feature_name,
                            e,
                        )
                        continue
            elif hasattr(model_spec, "_meta"):
                # Model class directly
                model_class = model_spec
            else:
                logger.warning(
                    "Invalid model specification '%s' to exclude from feature '%s'. "
                    "Expected tuple, string, or model class.",
                    model_spec,
                    feature_name,
                )
                continue

            if model_class and model_class not in excluded_model_classes:
                excluded_model_classes.append(model_class)

        FEATURE_EXCLUDE_MODELS[feature_name] = excluded_model_classes
        logger.info(
            "Registered %s models to exclude from feature '%s'",
            len(excluded_model_classes),
            feature_name,
        )
    else:
        FEATURE_EXCLUDE_MODELS[feature_name] = []

    # Log registration
    log_parts = [f"Registered new feature '{feature_name}' -> '{registry_key}'"]
    if explicit_exclude_app and excluded_apps:
        log_parts.append(
            f"excluding app(s) {', '.join(repr(a) for a in sorted(excluded_apps))}"
        )
    if not auto_register_all:
        log_parts.append("with selective registration")
    logger.info(", ".join(log_parts))

    # Register models based on configuration
    excluded_apps = FEATURE_REGISTERING_APP.get(feature_name)
    exclude_app_explicit = FEATURE_EXCLUDE_APP_EXPLICIT.get(feature_name, False)

    # First, register explicitly included models (always add them; excluded app(s)
    # only affect auto-registration of all=True models below)
    for model_class in FEATURE_INCLUDE_MODELS.get(feature_name, []):
        if model_class not in FEATURE_REGISTRY[registry_key]:
            FEATURE_REGISTRY[registry_key].append(model_class)
            logger.debug(
                "Registered model %s for feature '%s' (explicitly included)",
                model_class,
                feature_name,
            )

    # Remove excluded models from registry (if they were already registered)
    excluded_models = FEATURE_EXCLUDE_MODELS.get(feature_name, [])
    for model_class in excluded_models:
        if model_class in FEATURE_REGISTRY[registry_key]:
            FEATURE_REGISTRY[registry_key].remove(model_class)
            logger.debug(
                "Removed excluded model %s from feature '%s' registry",
                model_class,
                feature_name,
            )

    # If selective registration is enabled, clean up any models that shouldn't be there
    if not auto_register_all:
        included_models = set(FEATURE_INCLUDE_MODELS.get(feature_name, []))
        models_to_remove = []
        for model_class in FEATURE_REGISTRY[registry_key]:
            # Remove if not in included models
            if model_class not in included_models:
                # Only remove by app if exclude_app_label was explicitly passed
                if (
                    exclude_app_explicit
                    and excluded_apps
                    and model_class._meta.app_label in excluded_apps
                ):
                    models_to_remove.append(model_class)
                elif model_class not in included_models:
                    models_to_remove.append(model_class)

        for model_class in models_to_remove:
            FEATURE_REGISTRY[registry_key].remove(model_class)
            logger.debug(
                "Removed model %s from feature '%s' (not in include_models for selective registration)",
                model_class,
                feature_name,
            )

    # Flush any models buffered before this feature was registered
    # They may be keyed by feature_name or registry_key depending on what was passed
    pending = FEATURE_PENDING_MODELS.pop(feature_name, []) + FEATURE_PENDING_MODELS.pop(
        registry_key, []
    )
    for model_class in pending:
        if model_class not in FEATURE_REGISTRY[registry_key]:
            FEATURE_REGISTRY[registry_key].append(model_class)
            logger.info(
                "Flushed pending model %s for feature '%s'",
                model_class,
                feature_name,
            )

    # Then, auto-register all=True models if enabled
    if auto_register_all:
        # Get excluded models for this feature
        excluded_models = FEATURE_EXCLUDE_MODELS.get(feature_name, [])

        for model_class, excluded_features in ALL_FEATURES_MODELS.items():
            # Skip if model belongs to an excluded app (only when exclude_app_label was explicitly passed)
            if (
                exclude_app_explicit
                and excluded_apps
                and model_class._meta.app_label in excluded_apps
            ):
                logger.debug(
                    "Skipping auto-registration of model %s for feature '%s' (model belongs to excluded app(s) %s)",
                    model_class,
                    feature_name,
                    sorted(excluded_apps),
                )
                continue

            # Skip if already registered via include_models
            if model_class in FEATURE_INCLUDE_MODELS.get(feature_name, []):
                continue

            # Skip if model is in the exclude_models list
            if model_class in excluded_models:
                logger.debug(
                    "Skipping auto-registration of model %s for feature '%s' (model is in exclude_models)",
                    model_class,
                    feature_name,
                )
                # Remove from registry if it was already registered
                if model_class in FEATURE_REGISTRY[registry_key]:
                    FEATURE_REGISTRY[registry_key].remove(model_class)
                    logger.debug(
                        "Removed excluded model %s from feature '%s' registry",
                        model_class,
                        feature_name,
                    )
                continue

            # Skip if feature is in the model's exclude list
            if feature_name not in excluded_features:
                if model_class not in FEATURE_REGISTRY[registry_key]:
                    FEATURE_REGISTRY[registry_key].append(model_class)
                    logger.debug(
                        "Auto-registered model %s for new feature '%s' (was registered with all=True)",
                        model_class,
                        feature_name,
                    )

    return True


def _resolve_feature_name(feature_name):
    """Accept either a feature name or its registry key (e.g. "global_search_models")."""
    if feature_name in FEATURE_CONFIG:
        return feature_name
    if feature_name in FEATURE_REGISTRY_KEY_TO_NAME:
        return FEATURE_REGISTRY_KEY_TO_NAME[feature_name]
    for name, key in FEATURE_CONFIG.items():
        if key == feature_name:
            return name
    return feature_name


def set_feature_options(
    feature_name,
    options,
    model_class=None,
    app_label=None,
    model_name=None,
):
    """
    Set options for one model under one feature.

    Options are plain settings that the feature reads for that model, for example
    the fields global search should look in. Each feature defines its own names.
    Calling this again for the same model and feature updates the given options and
    keeps the others.

    Example:
        set_feature_options(
            "global_search",
            {"search_fields": ["name", "module__model"], "columns": ["name"]},
            app_label="reports",
            model_name="Report",
        )

    Returns:
        bool: True if stored, False if the model could not be found.
    """
    if model_class is None:
        try:
            model_class = apps.get_model(app_label, model_name)
        except (LookupError, ValueError, TypeError) as e:
            logger.error(
                "set_feature_options: Model '%s.%s' not found: %s",
                app_label,
                model_name,
                e,
            )
            return False

    feature_name = _resolve_feature_name(feature_name)
    FEATURE_MODEL_OPTIONS[feature_name].setdefault(model_class, {}).update(
        options or {}
    )
    return True


def get_feature_options(feature_name, model_class):
    """
    Return the options of a feature for a model as a dict (empty if none).

    Later sources override earlier ones, option by option:
      1. defaults from register_feature(default_options=...)
      2. the model class's ``FEATURE_OPTIONS = {"<feature>": {...}}`` attribute
      3. options set with set_feature_options() / register_model_for_feature(options=...)

    Example:
        options = get_feature_options("global_search", Report)
        search_fields = options.get("search_fields")  # None means "choose automatically"
    """
    feature_name = _resolve_feature_name(feature_name)
    merged = dict(FEATURE_DEFAULT_OPTIONS.get(feature_name, {}))
    merged.update(
        (getattr(model_class, "FEATURE_OPTIONS", None) or {}).get(feature_name, {})
    )
    merged.update(FEATURE_MODEL_OPTIONS.get(feature_name, {}).get(model_class, {}))
    return merged


def register_model_for_feature(
    model_class=None,
    app_label=None,
    model_name=None,
    features=None,
    all=False,
    exclude=None,
    options=None,
    **kwargs,
):
    """
    Register an existing model for specific features without modifying the model file.

    Args:
        model_class: Model class (optional if app_label/model_name provided)
        app_label: App label (e.g., "core")
        model_name: Model name (e.g., "User")
        features: Feature name(s) as list or string
        all: Enable all features if True
        exclude: Features to exclude when all=True
        options: Per-feature settings for this model, keyed by feature name, e.g.
            {"global_search": {"search_fields": ["name"]}}. See set_feature_options.
        **kwargs: Legacy boolean flags (global_search=True, etc.)

    Example:
        register_model_for_feature(
            app_label="core",
            model_name="User",
            features=["global_search"],
            options={"global_search": {"search_fields": ["first_name", "last_name"]}},
        )
        register_model_for_feature(
            app_label="calendar",
            model_name="Event",
            all=True
        )

    Returns:
        bool: True if registered, False otherwise
    """
    # Determine which model to register
    if model_class is None:
        if app_label is None or model_name is None:
            logger.error(
                "register_model_for_feature: Must provide either model_class or both "
                "app_label and model_name"
            )
            return False

        try:
            model_class = apps.get_model(app_label, model_name)
        except LookupError as e:
            logger.error(
                "register_model_for_feature: Model '%s.%s' not found: %s",
                app_label,
                model_name,
                e,
            )
            return False
    else:
        # Use model class directly
        app_label = model_class._meta.app_label
        model_name = model_class.__name__

    for option_feature, feature_options in (options or {}).items():
        set_feature_options(option_feature, feature_options, model_class=model_class)

    # Determine which features to enable
    enabled_features = set()
    explicit_features = set()  # features explicitly requested via features= parameter
    exclude_set = set()

    # Handle 'all' flag - enable all features
    if all:
        # Track this model in ALL_FEATURES_MODELS for future feature auto-registration
        if exclude is not None:
            exclude_list = [exclude] if isinstance(exclude, str) else exclude
            exclude_set = set(exclude_list)
        ALL_FEATURES_MODELS[model_class] = exclude_set

        # Enable all currently registered features
        enabled_features.update(FEATURE_CONFIG.keys())

    # New way: using features parameter
    if features is not None:
        if isinstance(features, str):
            features = [features]
        enabled_features.update(features)
        explicit_features.update(features)

    # Legacy way: check boolean keyword arguments
    legacy_features = {
        "import_data": kwargs.get("import_data", False),
        "export_data": kwargs.get("export_data", False),
        "global_search": kwargs.get("global_search", False),
    }

    for feature_name, enabled in legacy_features.items():
        if enabled:
            enabled_features.add(feature_name)

    # Check kwargs for any dynamically registered features
    for feature_name, enabled in kwargs.items():
        if enabled and isinstance(enabled, bool) and enabled:
            if feature_name in FEATURE_CONFIG:
                enabled_features.add(feature_name)

    # Apply exclusions
    if exclude is not None:
        if isinstance(exclude, str):
            exclude = [exclude]
        enabled_features -= set(exclude)

    if not enabled_features:
        logger.warning(
            "register_model_for_feature: No features specified for model %s.%s",
            app_label,
            model_name,
        )
        # Even if no features to register now, return True if all=True (for tracking)
        return all

    # Register model for each enabled feature
    registered = False
    for feature_name in enabled_features:
        # Allow callers to pass the registry key (e.g. "duplicate_models") instead of
        # the feature name (e.g. "duplicate_data") — resolve it transparently
        if (
            feature_name not in FEATURE_CONFIG
            and feature_name in FEATURE_REGISTRY_KEY_TO_NAME
        ):
            resolved = FEATURE_REGISTRY_KEY_TO_NAME[feature_name]
            if feature_name in explicit_features:
                explicit_features.add(resolved)
            feature_name = resolved

        if feature_name in FEATURE_CONFIG:
            if not FEATURE_AUTO_REGISTER_ALL.get(feature_name, True):
                # Explicitly requested features always bypass the include_models gate
                if feature_name not in explicit_features:
                    included_models = FEATURE_INCLUDE_MODELS.get(feature_name, [])
                    if model_class not in included_models:
                        logger.debug(
                            "Skipped model %s.%s for selective feature '%s' (not in include_models)",
                            app_label,
                            model_name,
                            feature_name,
                        )
                        continue

            registry_key = FEATURE_CONFIG[feature_name]

            if model_class not in FEATURE_REGISTRY[registry_key]:
                FEATURE_REGISTRY[registry_key].append(model_class)
                registered = True
                logger.info(
                    "Registered model %s.%s for feature '%s'",
                    app_label,
                    model_name,
                    feature_name,
                )
            else:
                logger.debug(
                    "Model %s.%s already registered for feature '%s'",
                    app_label,
                    model_name,
                    feature_name,
                )
        else:
            if model_class not in FEATURE_PENDING_MODELS[feature_name]:
                FEATURE_PENDING_MODELS[feature_name].append(model_class)
            logger.debug(
                "Feature '%s' not yet registered; buffered model %s.%s for later registration",
                feature_name,
                app_label,
                model_name,
            )

    return registered


def register_models_for_feature(
    models, features=None, all=False, exclude=None, **kwargs
):
    """
    Register multiple models at once with the same features.

    Args:
        models: List of models as tuples [("app_label", "model_name")],
                model classes, or dicts [{"app_label": "...", "model_name": "..."}]
        features: Feature name(s) as list or string
        all: Enable all features if True
        exclude: Features to exclude when all=True
        **kwargs: Legacy boolean flags

    Example:
        register_models_for_feature(
            models=[
                ("core", "User"),
                ("activity", "Activity"),
                ("calendar", "Event"),
            ],
            features=["global_search", "import_data"]
        )
        register_models_for_feature(
            models=[("core", "User"), ("activity", "Activity")],
            all=True,
            exclude=["export_data"]
        )

    Returns:
        dict: Summary with "registered", "failed", and "total" keys
    """
    registered_models = []
    failed_models = []

    # Normalize models list
    normalized_models = []
    for model in models:
        if isinstance(model, tuple) and len(model) == 2:
            # Tuple format: (app_label, model_name)
            normalized_models.append({"app_label": model[0], "model_name": model[1]})
        elif isinstance(model, dict):
            # Dict format: {"app_label": "...", "model_name": "..."}
            normalized_models.append(model)
        else:
            # Assume it's a model class
            try:
                normalized_models.append({"model_class": model})
            except Exception:
                failed_models.append(str(model))
                logger.error(
                    "register_models_for_feature: Invalid model format: %s",
                    model,
                )
                continue

    # Register each model
    for model_info in normalized_models:
        try:
            if "model_class" in model_info:
                # Use model class directly
                result = register_model_for_feature(
                    model_class=model_info["model_class"],
                    features=features,
                    all=all,
                    exclude=exclude,
                    **kwargs,
                )
                model_identifier = f"{model_info['model_class']._meta.app_label}.{model_info['model_class'].__name__}"
            else:
                # Use app_label and model_name
                result = register_model_for_feature(
                    app_label=model_info["app_label"],
                    model_name=model_info["model_name"],
                    features=features,
                    all=all,
                    exclude=exclude,
                    **kwargs,
                )
                model_identifier = (
                    f"{model_info['app_label']}.{model_info['model_name']}"
                )

            if result:
                registered_models.append(model_identifier)
            else:
                failed_models.append(model_identifier)

        except Exception as e:
            model_identifier = str(model_info)
            failed_models.append(model_identifier)
            logger.error(
                "register_models_for_feature: Failed to register %s: %s",
                model_identifier,
                e,
            )

    result_summary = {
        "registered": registered_models,
        "failed": failed_models,
        "total": len(normalized_models),
    }

    logger.info(
        "register_models_for_feature: Registered %s/%s models",
        len(registered_models),
        len(normalized_models),
    )

    return result_summary

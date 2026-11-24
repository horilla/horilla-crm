"""View to handle load demo data"""

# Standard library imports
import json
import tempfile
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.utils.module_loading import import_string

# First party imports (Horilla)
from horilla.apps import apps
from horilla.auth.models import User
from horilla.contrib.core.models import HorillaContentType
from horilla.db import connection, transaction
from horilla.shortcuts import redirect, render
from horilla.utils import timezone
from horilla.utils.branding import load_branding
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import JsonResponse, safe_url


def set_sqlite_foreign_keys(enabled: bool):
    """Enable or disable SQLite foreign key checks."""
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA foreign_keys = {1 if enabled else 0};")


def apply_product_name_to_companies(data):
    """
    Replace the leading "Horilla" in fixture company names with the
    product name from the branding module.
    """
    product_name = str(load_branding()["TITLE"])
    for item in data:
        if isinstance(item, dict) and item.get("model") == "core.company":
            name = item["fields"].get("name", "")
            if name.startswith("Horilla"):
                item["fields"]["name"] = product_name + name[len("Horilla") :]


def _is_relative_date(value):
    """True for a ``{"relative_days": N, "time": "HH:MM"}`` fixture marker."""
    return (
        isinstance(value, dict)
        and "relative_days" in value
        and set(value) <= {"relative_days", "time"}
    )


def resolve_relative_dates_in_fixture_data(data):
    """
    Replace relative date markers in fixture field data with real dates.

    Demo fixtures cannot hold fixed dates, they would be stale as soon as the
    data is loaded a day later. A field value of
    ``{"relative_days": -3, "time": "09:30"}`` becomes the date three days
    before the day of loading at 09:30 (UTC), and without ``time`` a plain
    date. A created / updated time is never later than now.
    """
    if not isinstance(data, list):
        return data
    now = timezone.now()
    today = timezone.localdate()
    for item in data:
        if not (isinstance(item, dict) and "fields" in item):
            continue
        for key, value in item["fields"].items():
            if not _is_relative_date(value):
                continue
            day = today + timedelta(days=int(value["relative_days"]))
            if "time" not in value:
                item["fields"][key] = day.isoformat()
                continue
            hour, minute = (int(part) for part in value["time"].split(":")[:2])
            moment = datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=dt_timezone.utc
            )
            if key in ("created_at", "updated_at"):
                moment = min(moment, now)
            item["fields"][key] = moment.isoformat().replace("+00:00", "Z")
    return data


def inject_timestamps_into_fixture_data(data):
    """
    Give fixture rows that carry a fixed created_at / updated_at the current
    time, so loaded records have up-to-date timestamps. Values that are
    relative date markers are resolved separately and left alone here.
    """
    if not isinstance(data, list):
        return data
    now_iso = timezone.now().isoformat()
    for item in data:
        if isinstance(item, dict) and "fields" in item:
            fields = item["fields"]
            for key in ("created_at", "updated_at"):
                if key in fields and not _is_relative_date(fields[key]):
                    fields[key] = now_iso
    return data


def resolve_content_type_refs_in_fixture_data(data):
    """
    Replace {"app_label": ..., "model": ...} dict values in fixture field data
    with the matching HorillaContentType's pk, so ContentType FKs can be
    expressed portably (independent of per-database content type pks) and
    still load through the standard `loaddata` command.
    """
    if not isinstance(data, list):
        return data
    for item in data:
        if not (isinstance(item, dict) and "fields" in item):
            continue
        fields = item["fields"]
        for key, value in fields.items():
            if isinstance(value, dict) and "app_label" in value and "model" in value:
                content_type = HorillaContentType.objects.filter(
                    app_label=value["app_label"], model=value["model"]
                ).first()
                fields[key] = content_type.pk if content_type else None
    return data


def _content_type_model(ref):
    """Model class named by a content type reference (app_label/model dict or pk)."""
    if isinstance(ref, dict):
        try:
            return apps.get_model(ref["app_label"], ref["model"])
        except (LookupError, KeyError):
            return None
    content_type = HorillaContentType.objects.filter(pk=ref).first()
    return content_type.model_class() if content_type else None


def drop_rows_with_missing_references(data):
    """
    Make a fixture safe to load when the records it points at were not loaded.

    Each module's record count is chosen separately, so a row can point at a
    record that is not in the database (and not in this file). Looking at the
    model's own fields:

    - an optional foreign key to a missing record is cleared;
    - a required foreign key, or a generic (content type + object id) link, to a
      missing record drops the row, together with the rows that point at it.
    """
    # Local import: GenericForeignKey lives in the contenttypes app.
    from django.contrib.contenttypes.fields import GenericForeignKey

    rows = [
        item
        for item in data
        if isinstance(item, dict) and item.get("model") and "fields" in item
    ]
    models = {}
    for item in rows:
        if item["model"] not in models:
            try:
                models[item["model"]] = apps.get_model(item["model"])
            except LookupError:
                models[item["model"]] = None

    in_file = {}
    for item in rows:
        if "pk" in item:
            in_file.setdefault(models[item["model"]], set()).add(str(item["pk"]))
    dropped = {}  # model class -> pks of rows dropped from this file
    in_database = {}

    def exists(model_class, pk):
        pk = str(pk)
        if pk in dropped.get(model_class, ()):
            return False
        if pk in in_file.get(model_class, ()):
            return True
        key = (model_class, pk)
        if key not in in_database:
            try:
                in_database[key] = model_class._base_manager.filter(pk=pk).exists()
            except (ValueError, TypeError):
                in_database[key] = False
        return in_database[key]

    removed = set()
    changed = True
    while changed:
        changed = False
        for index, item in enumerate(rows):
            model_class = models[item["model"]]
            if index in removed or model_class is None:
                continue
            fields = item["fields"]
            drop = False
            for field in model_class._meta.concrete_fields:
                value = fields.get(field.name)
                if not field.is_relation or value is None or isinstance(value, dict):
                    continue
                if exists(field.related_model, value):
                    continue
                if field.null:
                    fields[field.name] = None
                else:
                    drop = True
            for generic in model_class._meta.private_fields:
                if drop or not isinstance(generic, GenericForeignKey):
                    continue
                ct_ref = fields.get(generic.ct_field)
                object_id = fields.get(generic.fk_field)
                if ct_ref is None or object_id in (None, ""):
                    continue
                target = _content_type_model(ct_ref)
                drop = target is None or not exists(target, object_id)
            if drop:
                removed.add(index)
                changed = True
                if "pk" in item:
                    dropped.setdefault(model_class, set()).add(str(item["pk"]))
    dropped_items = [rows[i] for i in removed]
    data[:] = [item for item in data if not any(item is gone for gone in dropped_items)]


class LoadDatabaseConditionView(View):
    """
    checks whether the database needs demo data.
    """

    def get_initialize_condition(self):
        """Check if database initialization is needed."""
        initialize_database = not User.objects.exists()
        return initialize_database


class LoadDatabase(View):
    """To load db init password"""

    def get(self, request, *args, **kwargs):
        """Handle GET requests for database initialization."""
        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()
        next_url = request.GET.get("next", "/")
        if load_data:
            return render(request, "load_data/init_password.html", {"next": next_url})

        next_url = safe_url(request, next_url)
        return redirect(next_url)


class ConfigureDemoData(View):
    """
    Handle configuration of demo data counts before loading.
    """

    # Default options and default value for all entities
    DEFAULT_OPTIONS = [500, 1000, 2000, 4000, 8000, 10000]
    DEFAULT_VALUE = 500

    def format_option_label(self, value):
        """Format option value for display"""
        if value >= 10000:
            return "10,000+"
        if value > 8000:
            return "Above 8,000"

        return f"{value:,}"

    def get_configurable_entities(self):
        """
        Collect all configurable entities from apps that define demo_data.
        Each entity includes: key, display_name, default, options, order, files.

        Configs with `"configurable": False` are skipped here (no count
        selector is shown for them) but their files are still loaded in full
        by `LoadDemoDatabase.get_data_files()`. Use this for small, fixed-size
        setup/reference fixtures (e.g. workflow rules, mail templates) where a
        500-10,000 record count picker would be meaningless.
        """
        entities = []

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            # Normalize to list of configs
            configs = demo_data if isinstance(demo_data, list) else [demo_data]

            for cfg in configs:
                if not cfg.get("configurable", True):
                    continue

                options_raw = cfg.get("options", self.DEFAULT_OPTIONS)
                default_value = cfg.get("default", options_raw[0])

                key = cfg.get("key") or (
                    str(app_config.verbose_name).lower().replace(" ", "_") + "_count"
                )

                entities.append(
                    {
                        "key": key,
                        "display_name": cfg.get(
                            "display_name", str(app_config.verbose_name)
                        ),
                        "default": default_value,
                        "options": [
                            {"value": opt, "label": self.format_option_label(opt)}
                            for opt in options_raw
                        ],
                        "order": cfg.get("order", 999),
                        "files": cfg.get("files", []),
                    }
                )

        return sorted(entities, key=lambda x: x["order"])

    def get(self, request, *args, **kwargs):
        """Display configuration page"""
        if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
            return redirect("core:load_data")

        entities = self.get_configurable_entities()
        return render(request, "load_data/configure_data.html", {"entities": entities})

    def post(self, request, *args, **kwargs):
        """Save configuration and proceed to loading"""
        if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
            messages.error(request, _("Unauthorized. Please authenticate first."))
            return redirect("core:load_data")

        data_config = {}
        entities = self.get_configurable_entities()

        for entity in entities:
            key = entity["key"]
            value = request.POST.get(key, entity["default"])
            data_config[key] = int(value)

        request.session["data_config"] = data_config

        load_demo = LoadDemoDatabase()
        data_files = load_demo.get_data_files()

        context = {
            "total_files": len(data_files),
            "data_files": [Path(f).name for f in data_files],
            "data_config": data_config,
        }
        return render(request, "load_data/loading.html", context)


class LoadDemoDatabase(View):
    """
    Loads demo database with progress tracking.
    Supports dynamic demo data files from apps with ordering.
    """

    def get_data_files(self):
        """Collect all demo data files from installed apps in order."""
        data_files = []

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            app_path = Path(app_config.path)
            configs = demo_data if isinstance(demo_data, list) else [demo_data]

            for cfg in configs:
                for order, relative_file in cfg.get("files", []):
                    file_path = app_path / relative_file
                    if file_path.exists():
                        data_files.append((order, str(file_path)))

        return [fpath for _, fpath in sorted(data_files, key=lambda x: x[0])]

    def get_file_limit_key(self, filename):
        """
        Determine the limit key for a given data file based on its app config.
        """
        filename = Path(filename).name

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            _app_path = Path(app_config.path)
            configs = demo_data if isinstance(demo_data, list) else [demo_data]

            for cfg in configs:
                # Build list of filenames only once
                cfg_files = [Path(f[1]).name for f in cfg.get("files", [])]

                if filename in cfg_files:
                    return cfg.get(
                        "key",
                        str(app_config.verbose_name).lower().replace(" ", "_")
                        + "_count",
                    )

        return None

    def get_file_config(self, filename):
        """The demo_data config an app declared for this data file, if any."""
        filename = Path(filename).name
        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue
            configs = demo_data if isinstance(demo_data, list) else [demo_data]
            for cfg in configs:
                if filename in [Path(f[1]).name for f in cfg.get("files", [])]:
                    return cfg
        return None

    def run_prepare_hook(self, filename, data):
        """
        Let the app that owns a data file adjust its rows before they are loaded.

        An app sets ``"prepare": "dotted.path.to.function"`` in its demo_data
        config; the function receives the list of fixture rows and edits it in
        place. This keeps app specific rules out of the core loader.
        """
        cfg = self.get_file_config(filename) or {}
        hook = cfg.get("prepare")
        if hook:
            import_string(hook)(data)

    def get_model_limit(self, filename, data_config):
        """
        Get the limit for number of records to load based on file type.
        Returns None if no limit should be applied.
        """
        limit_key = self.get_file_limit_key(filename)

        if limit_key and limit_key in data_config:
            return data_config[limit_key]

        return None

    def load_limited_data(self, filename, limit=None):
        """
        Load data from JSON file with optional limit on number of records.
        Injects current created_at and updated_at into all fixture objects
        so that loaded records have up-to-date timestamps.
        """
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            call_command("loaddata", str(filename))
            return

        data_to_load = data[:limit] if limit is not None else data
        drop_rows_with_missing_references(data_to_load)
        self.run_prepare_hook(filename, data_to_load)
        inject_timestamps_into_fixture_data(data_to_load)
        resolve_relative_dates_in_fixture_data(data_to_load)
        apply_product_name_to_companies(data_to_load)
        resolve_content_type_refs_in_fixture_data(data_to_load)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp_file:
            json.dump(data_to_load, tmp_file, ensure_ascii=False, indent=2)
            tmp_filename = tmp_file.name

        try:
            call_command("loaddata", tmp_filename)
        finally:
            Path(tmp_filename).unlink(missing_ok=True)

    def post(self, request, *args, **kwargs):
        """Handle password authentication and redirect to configuration."""
        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()

        if not load_data:
            messages.error(request, _("Database already initialized"))
            return redirect("/")

        password = request.POST.get("init_password", "")
        if password != settings.DB_INIT_PASSWORD:
            return render(
                request,
                "load_data/init_password.html",
                {"error": _("Invalid password. Please try again.")},
            )

        request.session["init_password"] = password

        return redirect("core:configure_demo_data")

    def get(self, request, *args, **kwargs):
        """Handle AJAX requests for file loading progress."""
        if "file_index" in request.GET:
            if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": _("Unauthorized. Please authenticate first."),
                    },
                    status=401,
                )
            return self.load_file_ajax(request)

        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()
        next_url = request.GET.get("next", "/")

        if load_data:
            if request.session.get("init_password") == settings.DB_INIT_PASSWORD:
                return redirect("core:configure_demo_data")

            return render(request, "load_data/init_password.html")

        next_url = safe_url(request, next_url)
        return redirect(next_url)

    def load_file_ajax(self, request):
        """Load individual data file via AJAX."""
        file_index = int(request.GET.get("file_index", 0))
        data_files = self.get_data_files()
        data_config = request.session.get("data_config", {})

        if file_index >= len(data_files):
            request.session.pop("init_password", None)
            request.session.pop("data_config", None)
            messages.success(
                request,
                _(
                    "Demo database loaded successfully! You can now login with username 'admin' and password 'admin'."
                ),
            )
            return JsonResponse(
                {
                    "status": "complete",
                    "message": _("Database loaded successfully."),
                    "redirect": "/",
                }
            )

        filename = data_files[file_index]

        limit = self.get_model_limit(filename, data_config)

        try:
            if not Path(filename).exists():
                return JsonResponse(
                    {
                        "status": "error",
                        "message": _("Data file not found: {}").format(
                            Path(filename).name
                        ),
                        "file": Path(filename).name,
                    }
                )

            set_sqlite_foreign_keys(False)
            try:
                with transaction.atomic():
                    self.load_limited_data(filename, limit)
            finally:
                set_sqlite_foreign_keys(True)

            progress = ((file_index + 1) / len(data_files)) * 100

            original_name = Path(filename).name

            display_name = original_name
            if limit:
                display_name = f"{original_name}"

            response_data = {
                "status": "success",
                "file": original_name,
                "display_name": display_name,
                "progress": round(progress, 2),
                "current": file_index + 1,
                "total": len(data_files),
                "message": _("Loading {}").format(display_name),
            }

            return JsonResponse(response_data)

        except Exception as e:
            call_command("flush", "--no-input")
            return JsonResponse(
                {
                    "status": "error",
                    "message": _(
                        "Error loading {}. All changes have been rolled back."
                    ).format(Path(filename).name),
                    "error": str(e),
                    "file": Path(filename).name,
                }
            )

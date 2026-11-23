"""
Custom Django management command to build an app with additional files and folders,
and automatically configure URLs and settings.

Usage:
    python manage.py build_app app_name
"""

# Standard library imports
import os
import re
import shutil

# Third-party imports (Django)
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """
    Django management command to create a Horilla app with extended structure.

    This command creates a Django app with additional files and directories
    (templates, static files, locale folders, etc.) and automatically configures
    URLs and settings for the Horilla framework.
    """

    help = "Creates a Django app with additional files and directories and auto-configures it"

    def add_arguments(self, parser):
        """Define CLI arguments for app name, directory, project, and languages."""
        parser.add_argument("app_name", type=str, help="Name of the application")
        parser.add_argument(
            "--directory", "-d", dest="directory", help="Optional destination directory"
        )
        parser.add_argument(
            "--project",
            "-p",
            dest="project_name",
            help="Project name for URL configuration (default: derived from settings)",
        )
        parser.add_argument(
            "--languages",
            "-l",
            dest="languages",
            nargs="+",
            default=None,
            help="Language codes to create locale folders for (default: all languages from settings.LANGUAGES)",
        )

    def handle(self, *args, **options):
        """Create the app scaffold and auto-configure URLs and locale folders."""
        app_name = options["app_name"]
        directory = options["directory"]
        project_name = "horilla"
        languages = options["languages"]

        # If no languages specified, get all languages from settings.LANGUAGES
        if languages is None:
            languages = [lang_code for lang_code, lang_name in settings.LANGUAGES]
            self.stdout.write(
                self.style.WARNING(
                    f"No languages specified. Using all {len(languages)} languages from settings.LANGUAGES"
                )
            )

        # If no project name specified, try to get it from settings module
        if not project_name:
            project_name = os.path.basename(settings.BASE_DIR)

        # If no directory specified, create the app in the current directory
        target_dir = os.path.join(directory, app_name) if directory else app_name

        self.stdout.write(f"Creating Horilla app '{app_name}'...")

        try:
            # Check if the app name is valid
            if not re.match(r"^[_a-zA-Z]\w*$", app_name):
                raise CommandError(
                    f"'{app_name}' is not a valid app name. It must start with a letter or underscore and contain only letters, numbers, and underscores."
                )

            # Create the app directory
            os.makedirs(target_dir, exist_ok=True)

            # Create basic app structure
            self._create_base_app_structure(app_name, target_dir, project_name)

            # Create additional files
            self._create_additional_files(app_name, target_dir)

            # Create templates directory
            self._create_templates_directory(target_dir)

            # Create templatetags directory
            self._create_templatetags_directory(target_dir)

            # Create static directory
            self._create_static_directory(target_dir, app_name)

            # Create locale directory with language folders
            self._create_locale_directory(target_dir, languages)

        except Exception as e:
            self.stderr.write(f"Error creating app: {str(e)}")
            # Clean up if there was an error
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            return

        # Final success message
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully built app '{app_name}' with extended structure!"
            )
        )

    def _create_base_app_structure(self, app_name, target_dir, project_name):
        """Create the basic Django app structure"""

        # __init__.py
        with open(os.path.join(target_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write(f'"""\nPackage initialization for the {app_name} app\n"""\n')

        # apps.py - use Horilla AppLauncher for auto URL registration and module imports
        # Convert app_name to proper class name (e.g., 'my_app' -> 'MyAppConfig')
        class_name = (
            "".join(word.capitalize() for word in app_name.split("_")) + "Config"
        )

        # Convert app_name to verbose name with spaces (e.g., 'my_app' -> 'My App')
        verbose_name = " ".join(word.capitalize() for word in app_name.split("_"))

        apps_py_content = (
            f'"""\n'
            f"App configuration for the {app_name} app.\n"
            f'"""\n\n'
            f"from horilla.apps import AppLauncher\n"
            f"from horilla.utils.translation import gettext_lazy as _\n\n\n"
            f"class {class_name}(AppLauncher):\n"
            f'    """\n'
            f"    Configuration class for the {app_name} app in Horilla.\n"
            f'    """\n\n'
            f"    default = True\n\n"
            f'    default_auto_field = "django.db.models.BigAutoField"\n'
            f'    name = "{app_name}"\n'
            f'    verbose_name = _("{verbose_name}")\n\n'
            f'    url_prefix = "{app_name}/"\n'
            f'    url_module = "{app_name}.urls"\n'
            f'    url_namespace = "{app_name}"\n\n'
            f"    auto_import_modules = [\n"
            f'        "registration",\n'
            f'        "signals",\n'
            f'        "menu",\n'
            f"    ]\n"
        )

        with open(os.path.join(target_dir, "apps.py"), "w", encoding="utf-8") as f:
            f.write(apps_py_content)

        # models.py
        with open(os.path.join(target_dir, "models.py"), "w", encoding="utf-8") as f:
            f.write(
                f'"""\nModels for the {app_name} app\n"""\n\n'
                f"# Create your {app_name} models here.\n"
            )

        # views.py
        with open(os.path.join(target_dir, "views.py"), "w", encoding="utf-8") as f:
            f.write(f'"""\nViews for the {app_name} app\n"""\n')

        # admin.py
        with open(os.path.join(target_dir, "admin.py"), "w", encoding="utf-8") as f:
            f.write(
                f'"""\nAdmin registration for the {app_name} app\n"""\n\n'
                f"# Register your {app_name} models here.\n"
            )

        # tests.py
        with open(os.path.join(target_dir, "tests.py"), "w", encoding="utf-8") as f:
            f.write(
                f'"""\nTests for the {app_name} app\n"""\n\n'
                f"# Create your {app_name} tests here.\n"
            )

        # migrations directory
        migrations_dir = os.path.join(target_dir, "migrations")
        os.makedirs(migrations_dir, exist_ok=True)
        with open(
            os.path.join(migrations_dir, "__init__.py"), "w", encoding="utf-8"
        ) as f:
            f.write(f'"""\nMigration package for the {app_name} app\n"""\n')

    def _create_additional_files(self, app_name, target_dir):
        """Create additional Python files for the app"""
        # Convert app_name to verbose name with spaces (e.g., 'my_app' -> 'My App')
        verbose_name = " ".join(word.capitalize() for word in app_name.split("_"))

        additional_files = {
            "signals.py": (
                f'"""\nSignals for the {app_name} app\n"""\n\n'
                f"# Define your {app_name} signals here\n"
            ),
            "filters.py": (
                f'"""\nFilters for the {app_name} app\n"""\n\n'
                f"# Define your {app_name} filters here\n"
            ),
            "forms.py": (
                f'"""\nForms for the {app_name} app\n"""\n\n'
                f"# Define your {app_name} forms here\n"
            ),
            "urls.py": (
                f'"""\nURLs for the {app_name} app\n"""\n\n'
                f"app_name = '{app_name}'\n\n"
                "urlpatterns = [\n"
                "    # Define your URL patterns here\n"
                "]\n"
            ),
            "menu.py": (
                f'"""\nThis module registers Floating, Settings, My Settings, and Main Section menus\n'
                f'for the {app_name} app\n"""\n\n'
                "from horilla.urls import reverse_lazy\n"
                "from horilla.utils.translation import gettext_lazy as _\n\n"
                "from horilla.menu import (\n"
                "    floating_menu,\n"
                "    main_section_menu,\n"
                "    sub_section_menu,\n"
                "    settings_menu,\n"
                "    my_settings_menu,\n"
                "    header_menu,\n"
                ")\n\n"
                "# Define your menu registration logic here\n"
            ),
            "registration.py": (
                f'"""\nFeature registration for the {app_name} app.\n"""\n\n'
                "from horilla.registry.feature import register_feature, register_model_for_feature\n\n"
                "# Register your app features and models here\n"
            ),
            "__version__.py": (
                f'"""\nVersion information for the {app_name} app\n"""\n\n'
                f'__version__ = "0.1.0"\n'  # Initial version
                f'__module_name__ = "{verbose_name}"\n'
            ),
        }

        for file_name, content in additional_files.items():
            file_path = os.path.join(target_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.stdout.write(f"  Created {file_name}")

    def _create_templates_directory(self, target_dir):
        """Create templates directory directly in the app"""
        templates_dir = os.path.join(target_dir, "templates")

        os.makedirs(templates_dir, exist_ok=True)
        self.stdout.write("Created templates/ directory")

    def _create_static_directory(self, target_dir, app_name):
        """
        Create static directory for a Django app with namespacing,
        including assets/icons and assets/js folders.

        Args:
            target_dir (str): Path to the app folder
            app_name (str): Django app name to use as namespace
        """
        static_dir = os.path.join(target_dir, "static", app_name)

        icons_dir = os.path.join(static_dir, "assets", "icons")
        js_dir = os.path.join(static_dir, "assets", "js")

        for folder in [icons_dir, js_dir]:
            os.makedirs(folder, exist_ok=True)
        self.stdout.write(
            "Created static/ directory with assets/icons/ assets/js subfolders"
        )

    def _create_templatetags_directory(self, target_dir):
        """Create templatetags directory with init and custom tags file"""
        templatetags_dir = os.path.join(target_dir, "templatetags")
        os.makedirs(templatetags_dir, exist_ok=True)

        # Create __init__.py
        with open(
            os.path.join(templatetags_dir, "__init__.py"), "w", encoding="utf-8"
        ) as f:
            f.write("")

        self.stdout.write(
            "Created templatetags/ directory with __init__.py and custom tags file"
        )

    def _create_locale_directory(self, target_dir, languages):
        """
        Create locale directory structure for internationalization (i18n).
        Works across macOS, Windows, and Linux.

        Args:
            target_dir (str): Path to the app folder
            languages (list): List of language codes (e.g., ['en', 'es', 'fr'])
        """
        locale_base_dir = os.path.join(target_dir, "locale")

        # Create locale folders for each language
        for lang_code in languages:
            # Create the LC_MESSAGES directory for each language
            lc_messages_dir = os.path.join(locale_base_dir, lang_code, "LC_MESSAGES")
            os.makedirs(lc_messages_dir, exist_ok=True)

        self.stdout.write(
            f"Created locale/ directory with {len(languages)} language folders"
        )

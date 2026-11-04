"""
Horilla management command to create a new user and associated employee.
"""

# Standard library imports
import uuid

# Third-party imports (Django)
from django.core.management.base import BaseCommand, CommandError

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.utils.branding import load_branding


class Command(BaseCommand):
    """
    Horilla management command to create a new user and associated employee.
    """

    help = "Creates a new user"

    def add_arguments(self, parser):
        """Add command-line arguments for user creation."""
        parser.add_argument("--first_name", type=str, help="First name of the new user")
        parser.add_argument("--last_name", type=str, help="Last name of the new user")
        parser.add_argument("--username", type=str, help="Username of the new user")
        parser.add_argument("--password", type=str, help="Password for the new user")
        parser.add_argument("--email", type=str, help="Email of the new user")
        parser.add_argument("--phone", type=str, help="Phone number of the new user")

    def handle(self, *args, **options):
        """Handle the command to create a new user. If command-line arguments are not provided, prompt the user for input."""
        if not options["first_name"]:
            first_name = input("Enter first name: ")
            last_name = input("Enter last name: ")
            username = input("Enter username: ")
            password = input("Enter password: ")
            email = input("Enter email: ")
            phone = input("Enter phone number: ")
        else:
            first_name = options["first_name"]
            last_name = options["last_name"]
            username = options["username"]
            password = options["password"]
            email = options["email"]
            phone = options["phone"]

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'User with username "{username}" already exists')
            )
            return
        try:
            horilla_user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                contact_number=phone,
            )
            bot_username = f"{load_branding()['TITLE']} Bot"
            bot = User.objects.filter(
                username=bot_username,
                is_active=False,
                first_name="Bot",
                last_name="User",
            ).first()
            if bot is None:
                User.objects.create_user(
                    username=bot_username,
                    password=str(uuid.uuid4()),
                )
            self.stdout.write(
                self.style.SUCCESS(f'User "{horilla_user}" created successfully')
            )
        except Exception as e:
            if "user" in locals():
                horilla_user.delete()
            raise CommandError(f'Error creating user "{username}": {e}') from e

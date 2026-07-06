"""
Management command to simulate an inbound Meta WhatsApp Cloud API webhook
call, for testing the Horilla Bot flow without a real Meta account or a
public webhook URL.
"""

# Standard library imports
import json
import uuid

# Third-party imports (Django)
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

# Local imports
from horilla.contrib.whatsapp.api.webhook_views import WhatsAppWebhookView
from horilla.contrib.whatsapp.models import WhatsAppAccount


class Command(BaseCommand):
    """Simulate an inbound WhatsApp message hitting the webhook endpoint."""

    help = "Simulate an inbound WhatsApp message for local bot-flow testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--phone-number-id",
            required=True,
            help="phone_number_id of the WhatsAppAccount to simulate the message against.",
        )
        parser.add_argument(
            "--from",
            dest="from_number",
            required=True,
            help="Contact number the simulated message comes from.",
        )
        parser.add_argument(
            "--body",
            required=True,
            help="Text body of the simulated inbound message.",
        )
        parser.add_argument(
            "--name",
            default="",
            help="Contact display name to include in the simulated payload.",
        )

    def handle(self, *args, **options):
        phone_number_id = options["phone_number_id"]
        if not WhatsAppAccount.objects.filter(phone_number_id=phone_number_id).exists():
            raise CommandError(
                f"No WhatsAppAccount found with phone_number_id={phone_number_id!r}."
            )

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": phone_number_id},
                                "contacts": [
                                    {
                                        "wa_id": options["from_number"],
                                        "profile": {"name": options["name"]},
                                    }
                                ],
                                "messages": [
                                    {
                                        "id": f"wamid.SIMULATED.{options['from_number']}.{uuid.uuid4().hex}",
                                        "from": options["from_number"],
                                        "type": "text",
                                        "text": {"body": options["body"]},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        request = RequestFactory().post(
            "/api/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        response = WhatsAppWebhookView.as_view()(request)
        self.stdout.write(
            self.style.SUCCESS(
                f"Webhook responded with status {response.status_code}: {response.content.decode()}"
            )
        )

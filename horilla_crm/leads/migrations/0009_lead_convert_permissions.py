from django.db import migrations


class Migration(migrations.Migration):
    """Declare the convert_lead / convert_own_lead permissions on Lead."""

    dependencies = [
        ("leads", "0008_alter_lead_no_of_employees"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="lead",
            options={
                "permissions": (
                    ("convert_lead", "Can Convert Lead"),
                    ("convert_own_lead", "Can Convert Own Lead"),
                ),
                "verbose_name": "Lead",
                "verbose_name_plural": "Leads",
            },
        ),
    ]

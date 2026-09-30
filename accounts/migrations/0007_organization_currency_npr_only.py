# accounts/migrations/0007_organization_currency_npr_only.py
#
# Safe, backward-compatible migration that:
#   1. Updates the choices constraint on Organization.currency to NPR-only.
#   2. Normalises any existing rows that somehow have a non-NPR value to "NPR".
#      (In practice all rows were already defaulted to "NPR" by migration 0006,
#       so this is a no-op data migration for existing databases.)
#
# This migration does NOT drop or rename any column, so no data is lost.

from django.db import migrations, models


def normalise_currency_to_npr(apps, schema_editor):
    """
    Set every Organization.currency that is not "NPR" to "NPR".

    Migration 0006 created the field with default="NPR", so any row inserted
    after that migration already has "NPR".  This step exists as a safety net
    in case the currency dropdown in the Workspace settings was ever wired up
    and a user selected USD/EUR/INR before this migration ran.
    """
    Organization = apps.get_model("accounts", "Organization")
    updated = Organization.objects.exclude(currency="NPR").update(currency="NPR")
    if updated:
        print(f"\n  [0007] Normalised {updated} organization(s) to NPR currency.")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_add_currency_to_organization"),
    ]

    operations = [
        # Step 1: Data migration — normalise any non-NPR values to NPR.
        migrations.RunPython(
            normalise_currency_to_npr,
            reverse_code=migrations.RunPython.noop,  # reversing is a no-op
        ),

        # Step 2: Schema migration — narrow choices to NPR-only.
        # Django stores choices in migration state only; SQLite does not
        # enforce a CHECK constraint for CharField choices, so this change
        # is safe on all supported databases and does not alter the column
        # type or size.
        migrations.AlterField(
            model_name="organization",
            name="currency",
            field=models.CharField(
                choices=[("NPR", "NPR — Nepalese Rupee")],
                default="NPR",
                help_text="Currency used for all monetary amounts in this workspace. Always NPR.",
                max_length=3,
            ),
        ),
    ]

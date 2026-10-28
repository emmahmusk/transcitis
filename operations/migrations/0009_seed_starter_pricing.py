from decimal import Decimal

from django.db import migrations


STARTER_CHARGES = {
    "documents": Decimal("1000.00"),
    "clothing-accessories": Decimal("1500.00"),
    "electronics": Decimal("2500.00"),
    "food-perishables": Decimal("2000.00"),
    "fragile-goods": Decimal("2500.00"),
    "household-items": Decimal("2000.00"),
    "auto-parts": Decimal("2500.00"),
    "other": Decimal("1500.00"),
}


def seed_pricing(apps, schema_editor):
    Category = apps.get_model("operations", "ItemCategory")
    Settings = apps.get_model("operations", "ParcelPricingSettings")
    for code, charge in STARTER_CHARGES.items():
        Category.objects.filter(code=code, charge__isnull=True).update(charge=charge, is_active=True)
    Settings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("operations", "0008_parcelpricingsettings")]

    operations = [migrations.RunPython(seed_pricing, migrations.RunPython.noop)]

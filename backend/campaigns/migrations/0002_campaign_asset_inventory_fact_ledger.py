from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaign",
            name="asset_inventory",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="campaign",
            name="fact_ledger",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

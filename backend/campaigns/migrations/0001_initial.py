import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Campaign",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("generated", "Generated"),
                            ("reviewed", "Reviewed"),
                            ("test_sent", "Test sent"),
                            ("ready", "Ready"),
                            ("scheduled", "Scheduled"),
                            ("sending", "Sending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=32,
                    ),
                ),
                ("source_url", models.URLField(max_length=2048)),
                (
                    "reference_mode",
                    models.CharField(
                        choices=[
                            ("automatic", "Automatic"),
                            ("uploaded", "Uploaded"),
                        ],
                        default="automatic",
                        max_length=16,
                    ),
                ),
                (
                    "additional_instructions",
                    models.TextField(blank=True),
                ),
                (
                    "campaign_brief",
                    models.JSONField(blank=True, default=dict),
                ),
                (
                    "brand_profile",
                    models.JSONField(blank=True, default=dict),
                ),
                (
                    "reference",
                    models.JSONField(blank=True, default=dict),
                ),
                (
                    "content_plan",
                    models.JSONField(blank=True, default=dict),
                ),
                (
                    "audience_selection",
                    models.JSONField(blank=True, default=dict),
                ),
                (
                    "audience_snapshot_id",
                    models.UUIDField(blank=True, null=True),
                ),
                (
                    "send_mode",
                    models.CharField(
                        choices=[
                            ("none", "Not selected"),
                            ("send_now", "Send now"),
                            ("scheduled", "Scheduled"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                (
                    "scheduled_for",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "generated_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "test_sent_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "ready_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "sending_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "sent_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "failed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="yokai_campaigns",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="CampaignDesignVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("generated", "Generated"),
                            ("user_edit", "User edit"),
                            ("revision", "Revision"),
                        ],
                        default="generated",
                        max_length=16,
                    ),
                ),
                ("email_design", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="design_versions",
                        to="campaigns.campaign",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-version"],
            },
        ),
        migrations.AddField(
            model_name="campaign",
            name="active_design",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="campaigns.campaigndesignversion",
            ),
        ),
        migrations.AddConstraint(
            model_name="campaigndesignversion",
            constraint=models.UniqueConstraint(
                fields=("campaign", "version"),
                name="unique_campaign_design_version",
            ),
        ),
    ]

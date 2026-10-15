import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("campaigns", "0002_campaign_asset_inventory_fact_ledger"),
    ]

    operations = [
        migrations.CreateModel(
            name="Contact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254)),
                ("normalized_email", models.EmailField(max_length=254)),
                ("first_name", models.CharField(blank=True, max_length=120)),
                ("last_name", models.CharField(blank=True, max_length=120)),
                ("display_name", models.CharField(blank=True, max_length=200)),
                ("status", models.CharField(choices=[("active", "Active"), ("pending_consent", "Pending consent"), ("unsubscribed", "Unsubscribed"), ("bounced", "Bounced"), ("suppressed", "Suppressed"), ("complained", "Complained")], db_index=True, default="pending_consent", max_length=16)),
                ("consent_status", models.CharField(choices=[("unknown", "Unknown"), ("granted", "Granted"), ("withdrawn", "Withdrawn")], db_index=True, default="unknown", max_length=16)),
                ("consent_source", models.CharField(blank=True, max_length=200)),
                ("consented_at", models.DateTimeField(blank=True, null=True)),
                ("source", models.CharField(blank=True, max_length=100)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yokai_contacts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["normalized_email"],
                "indexes": [
                    models.Index(fields=["owner", "status"], name="contact_owner_status_idx"),
                    models.Index(fields=["owner", "consent_status"], name="contact_owner_consent_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("owner", "normalized_email"), name="unique_contact_email_per_owner"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ContactList",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("normalized_name", models.CharField(max_length=160)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yokai_contact_lists", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["name"],
                "constraints": [
                    models.UniqueConstraint(fields=("owner", "normalized_name"), name="unique_contact_list_name_owner"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AudienceSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("criteria", models.JSONField(blank=True, default=dict)),
                ("recipient_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audience_snapshots", to="campaigns.campaign")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yokai_audience_snapshots", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["campaign", "created_at"],
                        name="aud_snapshot_created_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CampaignSendJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("scheduled", "Scheduled"), ("queued", "Queued"), ("sending", "Sending"), ("sent", "Sent"), ("partial_failed", "Partially failed"), ("failed", "Failed"), ("canceled", "Canceled")], db_index=True, default="queued", max_length=20)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("error_summary", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("audience_snapshot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="send_jobs", to="email_delivery.audiencesnapshot")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delivery_jobs", to="campaigns.campaign")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yokai_campaign_send_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("campaign",),
                        condition=~Q(status="canceled"),
                        name="unique_active_campaign_job",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AudienceSnapshotRecipient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("contact_id_snapshot", models.UUIDField()),
                ("email", models.EmailField(max_length=254)),
                ("normalized_email", models.EmailField(max_length=254)),
                ("display_name", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("contact", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audience_snapshot_entries", to="email_delivery.contact")),
                ("snapshot", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recipients", to="email_delivery.audiencesnapshot")),
            ],
            options={
                "ordering": ["normalized_email"],
                "constraints": [
                    models.UniqueConstraint(fields=("snapshot", "normalized_email"), name="snapshot_recipient_email_uniq"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ContactListMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(blank=True, max_length=100)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("contact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="list_memberships", to="email_delivery.contact")),
                ("contact_list", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="email_delivery.contactlist")),
            ],
            options={
                "ordering": ["added_at"],
                "constraints": [
                    models.UniqueConstraint(fields=("contact_list", "contact"), name="unique_contact_membership"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeliveryRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("contact_id_snapshot", models.UUIDField()),
                ("recipient_email", models.EmailField(max_length=254)),
                ("normalized_email", models.EmailField(max_length=254)),
                ("provider", models.CharField(default="resend", max_length=32)),
                ("provider_message_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("sent", "Sent"), ("delivery_delayed", "Delivery delayed"), ("delivered", "Delivered"), ("bounced", "Bounced"), ("failed", "Failed"), ("complained", "Complained"), ("suppressed", "Suppressed"), ("opened", "Opened"), ("clicked", "Clicked"), ("canceled", "Canceled")], db_index=True, default="queued", max_length=24)),
                ("last_event_type", models.CharField(blank=True, max_length=64)),
                ("last_event_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("attempt", models.PositiveSmallIntegerField(default=1)),
                ("idempotency_key", models.CharField(max_length=256, unique=True)),
                ("failure_reason", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("audience_snapshot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="delivery_records", to="email_delivery.audiencesnapshot")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delivery_records", to="campaigns.campaign")),
                ("contact", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="delivery_records", to="email_delivery.contact")),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="email_delivery.campaignsendjob")),
            ],
            options={
                "ordering": ["recipient_email"],
                "indexes": [
                    models.Index(fields=["campaign", "status"], name="delivery_campaign_status_idx"),
                    models.Index(fields=["audience_snapshot", "normalized_email"], name="delivery_snapshot_email_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("job", "normalized_email"), name="unique_job_delivery_recipient"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeliveryEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider_event_id", models.CharField(max_length=255, unique=True)),
                ("provider_message_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("event_type", models.CharField(max_length=64)),
                ("occurred_at", models.DateTimeField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivery", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="provider_events", to="email_delivery.deliveryrecord")),
            ],
            options={
                "ordering": ["occurred_at", "created_at"],
                "indexes": [
                    models.Index(
                        fields=["delivery", "event_type"],
                        name="delivery_event_type_idx",
                    )
                ],
            },
        ),
    ]

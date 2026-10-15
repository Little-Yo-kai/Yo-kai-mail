"""Exercise the merged modules through authenticated product APIs.

Only network providers, the browser, compiler subprocess and task broker are
mocked; gateway loading, validation, rendering, persistence and workers are real.
"""

import base64
import hashlib
import hmac
import json
import shutil
import tempfile
import time
from datetime import timedelta
from unittest.mock import Mock, patch

from assets.tests import _make_png_bytes
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from email_delivery.models import (
    AudienceSnapshot,
    CampaignSendJob,
    Contact,
    DeliveryRecord,
)
from email_delivery.services.campaigns import execute_campaign_send_job
from email_visual_qa.test_revision import (
    sample_content_plan,
    sample_critique,
    sample_fact_ledger,
    sample_reference_spec,
)
from rest_framework.test import APITestCase

from .models import Campaign, CampaignDesignVersion
from .test_integrations import sample_brand_profile, sample_email_design


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    RESEND_CAMPAIGN_SEND_ENABLED=True,
    RESEND_TEST_SEND_ENABLED=True,
    RESEND_API_KEY="test-only",
    GEMINI_API_KEY="test-only",
)
class TeamCampaignIntegrationTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="team-owner", password="test-pass"
        )
        self.other = get_user_model().objects.create_user(
            username="team-other", password="test-pass"
        )
        login = self.client.post(
            "/api/auth/token/", {"username": "team-owner", "password": "test-pass"}
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.refresh_token = login.data["refresh"]
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access"])

        self.campaign = Campaign.objects.create(
            owner=self.owner,
            source_url="https://example.com",
            status="generated",
            brand_profile=sample_brand_profile(),
            reference={"reference_design_spec": sample_reference_spec()},
            content_plan=sample_content_plan("Discover", "https://example.com"),
            fact_ledger=sample_fact_ledger("Example", "https://example.com"),
        )
        self.version = CampaignDesignVersion.objects.create(
            campaign=self.campaign,
            version=1,
            email_design=sample_email_design(),
            created_by=self.owner,
        )
        self.campaign.active_design = self.version
        self.campaign.save()
        self.base = f"/api/campaigns/{self.campaign.id}"
        self.activity = f"/api/email-delivery/campaigns/{self.campaign.id}"
        self.compiler = self.enterContext(
            patch(
                "campaigns.services.compile_mjml_to_html",
                return_value={
                    "html": "<html><body>Approved campaign</body></html>",
                    "compiler_errors": [],
                },
            )
        )
        self.provider = self.enterContext(
            patch(
                "email_delivery.services.resend.ResendEmailService.send_test_email",
                return_value={"email_id": "test-id"},
            )
        )
        self.bulk = self.enterContext(
            patch(
                "email_delivery.services.resend.ResendEmailService.send_campaign_email",
                return_value={"email_id": "bulk-id"},
            )
        )
        self.dispatch = self.enterContext(
            patch("email_delivery.campaign_gateway.dispatch_campaign_send_job")
        )

    def ready(self):
        response = self.client.post(
            self.base + "/send-test/", {"to": "reviewer@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(
            self.base + "/transition/", {"status": "ready"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

    def import_audience(self):
        csv = "email,consent_status,consented_at\neligible@example.com,granted,2026-10-01T10:00:00Z\npending@example.com,,\n"
        response = self.client.post(
            "/api/email-delivery/contacts/import/",
            {
                "file": SimpleUploadedFile(
                    "contacts.csv", csv.encode(), content_type="text/csv"
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = list(
            Contact.objects.filter(owner=self.owner).values_list("id", flat=True)
        )
        response = self.client.post(
            self.base + "/audience/resolve/",
            {"selection": {"contact_ids": [str(pk) for pk in ids]}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        audience = response.data["data"]["audience_snapshot"]
        self.assertEqual(audience["recipient_count"], 1)
        self.assertEqual(audience["excluded_count"], 1)
        return audience

    def test_jwt_refresh_and_legacy_token_authentication(self):
        response = self.client.post(
            "/api/auth/token/refresh/", {"refresh": self.refresh_token}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["access"])
        self.assertEqual(self.client.get("/api/campaigns/").status_code, 200)
        from rest_framework.authtoken.models import Token

        token = Token.objects.create(user=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)
        self.assertEqual(self.client.get("/api/campaigns/").status_code, 200)

    def test_test_send_ready_audience_worker_and_signed_webhook(self):
        self.ready()
        self.import_audience()
        response = self.client.post(self.base + "/send/", {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        job = CampaignSendJob.objects.get(
            pk=response.data["data"]["delivery_job"]["job_id"]
        )
        self.assertEqual(job.html, self.compiler.return_value["html"])
        self.assertEqual(job.design_version_id, self.version.id)
        self.dispatch.assert_called_once()
        execute_campaign_send_job(job.id)
        execute_campaign_send_job(job.id)
        self.bulk.assert_called_once()
        self.assertEqual(self.bulk.call_args.kwargs["html"], job.html)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "sent")

        secret_bytes = b"test-webhook-secret"
        secret = "whsec_" + base64.b64encode(secret_bytes).decode()
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "type": "email.delivered",
                "created_at": (timezone.now() + timedelta(seconds=1)).isoformat(),
                "data": {"email_id": "bulk-id"},
            }
        )
        signature = base64.b64encode(
            hmac.new(
                secret_bytes, f"evt-one.{timestamp}.{payload}".encode(), hashlib.sha256
            ).digest()
        ).decode()
        with self.settings(RESEND_WEBHOOK_SECRET=secret):
            for _ in range(2):
                response = self.client.post(
                    "/api/email-delivery/webhooks/resend/",
                    payload,
                    content_type="application/json",
                    HTTP_SVIX_ID="evt-one",
                    HTTP_SVIX_TIMESTAMP=timestamp,
                    HTTP_SVIX_SIGNATURE="v1," + signature,
                )
                self.assertEqual(response.status_code, 200, response.data)
        summary = self.client.get(self.base + "/delivery-summary/")
        self.assertEqual(summary.data["data"]["delivered"], 1)
        activity = self.client.get(self.activity + "/activity/?limit=1&offset=0")
        self.assertEqual(
            activity.data["data"]["recipients"]["items"][0]["status"], "delivered"
        )

    def test_schedule_cancel_prevents_worker_send(self):
        self.ready()
        self.import_audience()
        response = self.client.post(
            self.base + "/schedule/",
            {"scheduled_for": (timezone.now() + timedelta(hours=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        job_id = response.data["data"]["delivery_job"]["job_id"]
        self.assertEqual(
            self.client.post(self.activity + "/cancel-schedule/").status_code, 200
        )
        execute_campaign_send_job(job_id)
        self.bulk.assert_not_called()
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "ready")

    def test_unsubscribe_after_snapshot_is_enforced_by_worker(self):
        self.ready()
        self.import_audience()
        response = self.client.post(self.base + "/send/", {}, format="json")
        Contact.objects.filter(email="eligible@example.com").update(
            status="unsubscribed", consent_status="withdrawn"
        )
        execute_campaign_send_job(response.data["data"]["delivery_job"]["job_id"])
        self.bulk.assert_not_called()
        self.assertEqual(
            DeliveryRecord.objects.get(campaign=self.campaign).status, "suppressed"
        )

    def test_other_owner_cannot_read_activity_or_cancel(self):
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(self.activity + "/activity/").status_code, 404)
        self.assertEqual(
            self.client.post(self.activity + "/cancel-schedule/").status_code, 404
        )

    def test_invalid_audience_ids_and_empty_selection_fail_safely(self):
        self.ready()
        response = self.client.post(
            self.base + "/audience/resolve/",
            {"selection": {"contact_ids": ["bad-id"]}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            self.base + "/audience/resolve/", {"selection": {}}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AudienceSnapshot.objects.count(), 0)

    def test_duplicate_send_request_does_not_create_another_job(self):
        self.ready()
        self.import_audience()
        self.assertEqual(
            self.client.post(self.base + "/send/", {}, format="json").status_code, 202
        )
        self.assertEqual(
            self.client.post(self.base + "/send/", {}, format="json").status_code, 409
        )
        self.assertEqual(CampaignSendJob.objects.count(), 1)

    def test_selected_asset_promotion_preserves_campaign_identity(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        self.version.email_design = sample_email_design(asset_ids=["hero_1"])
        self.version.save()
        self.campaign.asset_inventory = [
            {
                "asset_id": "hero_1",
                "kind": "hero",
                "url": "https://example.com/hero.png",
                "source": "brand_profile",
            }
        ]
        self.campaign.save()
        response = Mock(status_code=200, is_redirect=False, is_permanent_redirect=False)
        response.iter_content.return_value = [_make_png_bytes()]
        with (
            self.settings(
                MEDIA_ROOT=root, ASSET_PUBLIC_BASE_URL="https://cdn.example.com"
            ),
            patch("assets.services.fetch.assert_safe_url"),
            patch("assets.services.fetch.requests.get", return_value=response),
        ):
            promoted = self.client.post(self.base + "/assets/promote/")
        self.assertEqual(promoted.status_code, 200, promoted.data)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.active_design_id, self.version.id)
        self.assertEqual(self.campaign.asset_inventory[0]["source"], "asset_library")

    def test_revision_uses_real_loop_and_creates_a_new_campaign_version(self):
        revised = sample_email_design(subject="Revised subject")
        client = Mock()
        client.interactions.create.return_value.output_text = json.dumps(revised)
        with (
            patch(
                "email_visual_qa.services.revision.genai.Client", return_value=client
            ),
            patch(
                "email_visual_qa.services.gemini.GeminiDesignCritic.critique",
                side_effect=[sample_critique(True), sample_critique(False)],
            ),
            patch(
                "email_visual_qa.services.revision.compile_mjml_to_html",
                return_value=self.compiler.return_value,
            ),
            patch(
                "email_visual_qa.services.revision.capture_email_screenshot",
                return_value={
                    "image_base64": "test-png",
                    "mime_type": "image/png",
                    "width": 760,
                    "height": 900,
                    "image_diagnostics": {"total": 0, "loaded": 0, "broken": []},
                },
            ),
        ):
            response = self.client.post(
                self.base + "/revision/",
                {"instruction": "Make the copy shorter"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.active_design.version, 2)
        self.assertEqual(self.campaign.active_design.source, "revision")
        self.assertEqual(
            self.campaign.active_design.email_design["subject"], "Revised subject"
        )
        self.assertIn(
            "Make the copy shorter",
            client.interactions.create.call_args.kwargs["input"],
        )

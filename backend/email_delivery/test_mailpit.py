"""Opt-in local MIME capture; never calls Resend or a remote SMTP server."""

import base64
import json
import os
import smtplib
import time
import uuid
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

from django.test import SimpleTestCase, override_settings

from email_assets.temp_cache import CachedEmailAsset

from .services.resend import ResendEmailService


@skipUnless(os.environ.get("YOKAI_MAILPIT_TEST") == "1", "Opt in with YOKAI_MAILPIT_TEST=1 and local Mailpit")
@override_settings(
    RESEND_API_KEY="offline-mailpit-fixture",
    RESEND_FROM_EMAIL="Yo-kai Mail <sender@example.test>",
    DEBUG=False,
)
class MailpitMimeTests(SimpleTestCase):
    def test_send_payload_survives_local_mime_capture(self):
        subject = f"yokai-fixture-{uuid.uuid4().hex}"
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNeoAAAAASUVORK5CYII="
        )
        source_url = "https://example.test/hero.png"
        cached = CachedEmailAsset(
            cache_key="b" * 64, source_url=source_url, resolved_url=source_url,
            mime_type="image/png", filename="hero.png", body=image,
            created_at=1, expires_at=9999999999,
        )

        def capture(params, options):
            # Test transport for the real provider payload. Production remains Resend.
            message = EmailMessage()
            message["From"] = params["from"]
            message["To"] = ", ".join(params["to"])
            message["Subject"] = params["subject"]
            message.set_content(params["text"])
            message.add_alternative(params["html"], subtype="html")
            html_part = message.get_payload()[-1]
            for asset in params.get("attachments", []):
                main_type, sub_type = asset["content_type"].split("/", 1)
                html_part.add_related(
                    base64.b64decode(asset["content"], validate=True), maintype=main_type, subtype=sub_type,
                    cid=f"<{asset['content_id']}>", filename=asset["filename"],
                    disposition="inline",
                )
            with smtplib.SMTP("127.0.0.1", 1025, timeout=5) as smtp:
                smtp.send_message(message)
            return {"id": "local-mailpit-capture"}

        with patch("email_delivery.services.resend.read_cached_email_asset", return_value=cached), patch(
            "email_delivery.services.resend.resend.Emails.send", side_effect=capture,
        ):
            ResendEmailService().send_test_email(
                to="recipient@example.test", subject=subject,
                html=(f'<html><body><h1>Fixture &amp; proof</h1><img src="{source_url}" alt="Hero">'
                      '<p><a href="https://example.test/shop">Shop</a></p></body></html>'),
                cached_assets=[{"cache_key": "b" * 64, "source_url": source_url}],
            )

        # Never use environment proxies for the loopback-only test server.
        opener = build_opener(ProxyHandler({}))
        base_url = "http://127.0.0.1:8025/api/v1"

        def get(path):
            with opener.open(f"{base_url}/{path}", timeout=5) as response:
                return response.read()

        messages = []
        for _ in range(10):
            messages = json.loads(get("search?" + urlencode({"query": f"subject:{subject}"})))["messages"]
            if messages:
                break
            time.sleep(0.2)
        self.assertEqual(len(messages), 1)
        message_id = messages[0]["ID"]
        captured = BytesParser(policy=policy.default).parsebytes(get(f"message/{message_id}/raw"))
        self.assertEqual(captured["Subject"], subject)
        self.assertIn("Fixture & proof", captured.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("Shop (https://example.test/shop)", captured.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("cid:yokai-", captured.get_body(preferencelist=("html",)).get_content())
        inline_image = next(part for part in captured.walk() if part.get_content_type() == "image/png")
        self.assertEqual(inline_image.get_payload(decode=True), image)
        self.assertEqual(inline_image.get_content_disposition(), "inline")
        self.assertIn(inline_image["Content-ID"].strip("<>"), captured.get_body(preferencelist=("html",)).get_content())
        checks = json.loads(get(f"message/{message_id}/html-check"))
        self.assertGreater(checks["Total"]["Tests"], 0)

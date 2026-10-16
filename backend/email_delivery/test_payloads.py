from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from email_assets.temp_cache import CachedEmailAsset, EmailAssetCacheError
from email_rendering.text import html_to_plain_text

from .services.resend import ResendDeliveryError, ResendEmailService


def cached_image(*, mime_type="image/png", body=b"fixture-image"):
    return CachedEmailAsset(
        cache_key="a" * 64,
        source_url="https://cdn.example.com/image.png?a=1&b=2",
        resolved_url="https://cdn.example.com/image.png?a=1&b=2",
        mime_type=mime_type,
        filename="hero.png",
        body=body,
        created_at=1,
        expires_at=9999999999,
    )


class PlainTextTests(SimpleTestCase):
    def test_visible_copy_links_alt_and_escaping_survive(self):
        result = html_to_plain_text(
            '<html><head><title>Not body</title><style>p {color: red}</style></head>'
            '<body><h1>Offers &amp; news</h1><p>Hello &lt;Ada&gt;.</p>'
            '<img src="https://example.com/hero.png" alt="New collection">'
            '<p><a href="https://example.com/shop?a=1&amp;b=2">Shop now</a></p>'
            '<script>hidden()</script><footer><a href="https://example.com/unsubscribe">'
            'Unsubscribe</a></footer></body></html>'
        )
        self.assertIn("Offers & news\n", result)
        self.assertIn("Hello <Ada>.", result)
        self.assertIn("New collection", result)
        self.assertIn("Shop now (https://example.com/shop?a=1&b=2)", result)
        self.assertIn("Unsubscribe (https://example.com/unsubscribe)", result)
        self.assertNotIn("Not body", result)
        self.assertNotIn("color", result)
        self.assertNotIn("hidden", result)

    def test_plain_text_does_not_expose_script_urls_or_duplicate_link_labels(self):
        self.assertEqual(
            html_to_plain_text('<a href="javascript:alert(1)">Read</a><br>'
                               '<a href="https://example.com">https://example.com</a>'),
            "Read\nhttps://example.com",
        )

    def test_malformed_anchor_url_preserves_readable_label(self):
        self.assertEqual(
            html_to_plain_text('<a href="https://[broken">Visit</a>'),
            "Visit",
        )


@override_settings(
    RESEND_API_KEY="re_offline_fixture",
    RESEND_FROM_EMAIL="Yo-kai Mail <sender@example.com>",
    DEBUG=False,
    EMAIL_ASSET_MAX_INLINE_BYTES=1024,
    EMAIL_ASSET_MAX_INLINE_COUNT=2,
)
class SendPayloadTests(SimpleTestCase):
    @patch("email_delivery.services.resend.resend.Emails.send", return_value={"id": "fixture"})
    def test_campaign_sends_html_and_generated_text(self, send_mock):
        html = '<p>Hello &lt;Ada&gt;.</p><a href="https://example.com">Visit</a>'
        result = ResendEmailService().send_campaign_email(
            to="recipient@example.com", subject="Fixture", html=html,
            idempotency_key="saved-campaign/recipient",
        )
        params, options = send_mock.call_args.args
        self.assertEqual(params["html"], html)
        self.assertEqual(params["text"], "Hello <Ada>.\nVisit (https://example.com)")
        self.assertEqual(options["idempotency_key"], "saved-campaign/recipient")
        self.assertEqual(result["email_id"], "fixture")

    @patch("email_delivery.services.resend.read_cached_email_asset", return_value=cached_image())
    @patch("email_delivery.services.resend.resend.Emails.send", return_value={"id": "fixture"})
    def test_inline_images_support_all_quotes_and_only_replace_img_src(self, send_mock, read_mock):
        url = cached_image().source_url
        encoded_url = url.replace("&", "&amp;")
        html = (f"<img src='{encoded_url}' alt=Hero>"
                f'<IMG SRC="{encoded_url}"><img src={encoded_url}>'
                f'<img alt="src=wrong" data-src="{encoded_url}" src="https://example.com/new.png">'
                f'<a href="{encoded_url}">Original</a>')
        result = ResendEmailService().send_test_email(
            to="recipient@example.com", subject="Fixture", html=html,
            cached_assets=[{"cache_key": "a" * 64, "source_url": url}],
        )
        params = send_mock.call_args.args[0]
        self.assertEqual(params["html"].count("cid:yokai-"), 3)
        self.assertIn(f'data-src="{encoded_url}"', params["html"])
        self.assertIn(f'<a href="{encoded_url}">', params["html"])
        self.assertEqual(len(params["attachments"]), 1)
        self.assertEqual(result["inline_asset_count"], 1)
        self.assertIn("Hero", params["text"])

    @patch("email_delivery.services.resend.resend.Emails.send")
    def test_invalid_remote_images_fail_before_provider_call(self, send_mock):
        for source in ("http://example.com/logo.png", "https://127.0.0.1/a.png",
                       "/relative.png", "data:image/png;base64,AAAA", "cid:missing"):
            with self.subTest(source=source), self.assertRaises(ResendDeliveryError):
                ResendEmailService().send_test_email(
                    to="recipient@example.com", subject="Fixture",
                    html=f'<img src="{source}" alt="Hero">',
                )
        send_mock.assert_not_called()

    @patch("email_delivery.services.resend.read_cached_email_asset")
    @patch("email_delivery.services.resend.resend.Emails.send")
    def test_expired_or_invalid_cached_assets_fail_before_send(self, send_mock, read_mock):
        for failure in (EmailAssetCacheError("expired"), cached_image(mime_type="text/html"),
                        cached_image(body=b"x" * 1025), cached_image(body=b"")):
            read_mock.side_effect = failure if isinstance(failure, Exception) else None
            read_mock.return_value = failure
            with self.subTest(failure=failure), self.assertRaises(ResendDeliveryError):
                ResendEmailService().send_test_email(
                    to="recipient@example.com", subject="Fixture",
                    html=f'<img src="{cached_image().source_url}">',
                    cached_assets=[{"cache_key": "a" * 64, "source_url": cached_image().source_url}],
                )
        send_mock.assert_not_called()

    @override_settings(EMAIL_ASSET_MAX_INLINE_COUNT=0)
    @patch("email_delivery.services.resend.read_cached_email_asset", return_value=cached_image())
    @patch("email_delivery.services.resend.resend.Emails.send")
    def test_inline_attachment_count_limit_is_enforced_at_service_boundary(self, send_mock, read_mock):
        with self.assertRaisesMessage(ResendDeliveryError, "Too many inline"):
            ResendEmailService().send_test_email(
                to="recipient@example.com", subject="Fixture",
                html=f'<img src="{cached_image().source_url}">',
                cached_assets=[{"cache_key": "a" * 64, "source_url": cached_image().source_url}],
            )
        send_mock.assert_not_called()

    @patch("email_delivery.services.resend.resend.Emails.send", side_effect=RuntimeError("provider failed"))
    def test_provider_failure_is_wrapped(self, send_mock):
        with self.assertRaisesMessage(ResendDeliveryError, "Resend could not send"):
            ResendEmailService().send_test_email(
                to="recipient@example.com", subject="Fixture", html="<p>Fixture</p>",
            )

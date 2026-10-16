from django.test import SimpleTestCase

from .html import image_sources, replace_image_sources


class ImageSourceTests(SimpleTestCase):
    def test_quotes_entities_and_attribute_boundaries(self):
        url = "https://example.com/image.png?a=1&b=2"
        encoded = url.replace("&", "&amp;")
        document = (f'<img alt="src=wrong > still alt" data-src="ignore" SRC="{encoded}">'
                    f"<img src='{encoded}'><img src={encoded}>"
                    f'<a href="{encoded}">Link</a>')
        self.assertEqual(image_sources(document), {url})
        replaced = replace_image_sources(document, {url: "cid:fixture"})
        self.assertEqual(replaced.count("cid:fixture"), 3)
        self.assertIn('alt="src=wrong > still alt" data-src="ignore"', replaced)
        self.assertIn(f'<a href="{encoded}">', replaced)

    def test_unused_replacement_preserves_html_exactly(self):
        document = '<img src="https://example.com/kept.png" alt="Hero">'
        self.assertEqual(replace_image_sources(document, {"missing": "cid:unused"}), document)

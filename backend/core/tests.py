from django.test import TestCase
from django.urls import reverse


class ApiSchemaTests(TestCase):
    def test_schema_endpoint_renders(self):
        response = self.client.get(reverse("schema"))
        self.assertEqual(response.status_code, 200)

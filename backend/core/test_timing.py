import json

from django.test import SimpleTestCase

from .timing import timed_stage


class WorkflowTimingTests(SimpleTestCase):
    def test_structured_success_and_failure_do_not_log_exception_content(self):
        with self.assertLogs("yokai.workflow", level="INFO") as captured:
            with timed_stage("compilation") as fields:
                fields["cache_hit"] = True
            with self.assertRaises(ValueError), timed_stage("gemini_design"):
                raise ValueError("private content and credentials")
        payloads = [json.loads(record.getMessage()) for record in captured.records]
        self.assertEqual(payloads[0]["outcome"], "success")
        self.assertTrue(payloads[0]["cache_hit"])
        self.assertGreaterEqual(payloads[0]["elapsed_ms"], 0)
        self.assertEqual(payloads[1]["outcome"], "error")
        self.assertNotIn("private content", str(payloads))

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .compiler import MJMLCompilerError, compile_mjml_to_html


@override_settings(MJML_COMPILE_CACHE_TTL_SECONDS=60)
class CompilerCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @patch("email_rendering.compiler.subprocess.run")
    def test_identical_input_reuses_output_but_callers_cannot_mutate_cache(self, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"html": "<html><body>Hello</body></html>", "errors": []}
            ),
            stderr="",
        )
        first = compile_mjml_to_html("<mjml>cache-fixture</mjml>")
        first["compiler_errors"].append("caller mutation")
        second = compile_mjml_to_html("<mjml>cache-fixture</mjml>")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(second["compiler_errors"], [])
        self.assertEqual(second["text"], "Hello")

    @patch("email_rendering.compiler.subprocess.run")
    def test_changed_source_and_node_configuration_invalidate_cache(self, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout='{"html":"<html>OK</html>"}', stderr=""
        )
        compile_mjml_to_html("<mjml>first</mjml>")
        compile_mjml_to_html("<mjml>second</mjml>")
        with override_settings(MJML_NODE_BINARY="another-node"):
            compile_mjml_to_html("<mjml>first</mjml>")
        self.assertEqual(run.call_count, 3)

    @patch("email_rendering.compiler.subprocess.run")
    def test_runtime_change_invalidates_cache(self, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout='{"html":"<html>OK</html>"}', stderr=""
        )
        compile_mjml_to_html("<mjml>versioned</mjml>")
        with patch(
            "email_rendering.compiler.Path.stat",
            return_value=SimpleNamespace(st_mtime_ns=1, st_size=1, st_mode=0o100644),
        ):
            compile_mjml_to_html("<mjml>versioned</mjml>")
        self.assertEqual(run.call_count, 2)

    @patch("email_rendering.compiler.subprocess.run")
    def test_failures_are_never_cached_and_can_retry(self, run):
        run.side_effect = [
            subprocess.TimeoutExpired("node", 10),
            SimpleNamespace(
                returncode=0, stdout='{"html":"<html>Recovered</html>"}', stderr=""
            ),
        ]
        with self.assertRaises(MJMLCompilerError):
            compile_mjml_to_html("<mjml>retry</mjml>")
        self.assertIn("Recovered", compile_mjml_to_html("<mjml>retry</mjml>")["html"])
        self.assertEqual(run.call_count, 2)

    @patch("email_rendering.compiler.subprocess.run")
    def test_malformed_or_empty_compiler_output_is_not_cached(self, run):
        for output in ("[]", "not json", '{"html":""}'):
            run.return_value = SimpleNamespace(returncode=0, stdout=output, stderr="")
            with self.subTest(output=output), self.assertRaises(MJMLCompilerError):
                compile_mjml_to_html("<mjml>bad-output</mjml>")
        self.assertEqual(run.call_count, 3)

    @override_settings(MJML_COMPILE_CACHE_TTL_SECONDS=0)
    @patch("email_rendering.compiler.subprocess.run")
    def test_cache_can_be_disabled(self, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout='{"html":"<html>OK</html>"}', stderr=""
        )
        for _ in range(2):
            compile_mjml_to_html("<mjml>uncached</mjml>")
        self.assertEqual(run.call_count, 2)

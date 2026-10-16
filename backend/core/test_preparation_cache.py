import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

from django.core.cache import caches
from django.test import SimpleTestCase

from .generation_budget import GenerationBudget, GenerationTimedOut, generation_budget
from .preparation_cache import cached_preparation


class PreparationCacheTests(SimpleTestCase):
    def setUp(self):
        caches["generation"].clear()

    def prepare(self, compute, **kwargs):
        return cached_preparation(
            stage="test",
            inputs=kwargs.pop("inputs", {"url": "https://example.com"}),
            compute=compute,
            timeout=60,
            **kwargs,
        )

    def test_reuse_returns_copies_and_changed_inputs_miss(self):
        compute = Mock(side_effect=lambda: {"items": ["original"]})
        first, status = self.prepare(compute)
        self.assertEqual(status, "miss")
        first["items"].append("mutation")
        reused, status = self.prepare(compute)
        self.assertEqual(status, "hit")
        self.assertEqual(reused, {"items": ["original"]})
        self.prepare(compute, inputs={"url": "https://example.com/changed"})
        self.assertEqual(compute.call_count, 2)

    def test_refresh_replaces_cached_result(self):
        compute = Mock(side_effect=[{"version": 1}, {"version": 2}])
        self.prepare(compute)
        value, status = self.prepare(compute, refresh=True)
        self.assertEqual((value, status), ({"version": 2}, "refresh"))
        self.assertEqual(self.prepare(compute)[0], {"version": 2})
        self.assertEqual(compute.call_count, 2)

    def test_provider_failure_is_not_cached(self):
        compute = Mock(side_effect=[ValueError("bad response"), {"ok": True}])
        with self.assertRaises(ValueError):
            self.prepare(compute)
        self.assertEqual(self.prepare(compute)[0], {"ok": True})
        self.assertEqual(compute.call_count, 2)

    def test_cache_outage_still_returns_fresh_result(self):
        with patch.object(caches["generation"], "get", side_effect=OSError("offline")):
            self.assertEqual(self.prepare(lambda: {"ok": True})[0], {"ok": True})

    def test_cache_write_failure_does_not_discard_valid_result(self):
        with patch.object(caches["generation"], "set", side_effect=OSError("offline")):
            self.assertEqual(self.prepare(lambda: {"ok": True})[0], {"ok": True})

    def test_cancelled_producer_does_not_poison_healthy_waiter(self):
        entered, release, waiting = Event(), Event(), Event()
        budget = GenerationBudget(seconds=2)

        def compute():
            entered.set()
            release.wait(2)
            budget.cancelled.set()
            raise RuntimeError("Provider wrapped cancellation")

        def producer():
            with generation_budget(budget):
                return self.prepare(compute)

        def waiter():
            waiting.set()
            return self.prepare(lambda: {"ok": True})

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(producer)
            try:
                self.assertTrue(entered.wait(1))
                second = pool.submit(waiter)
                self.assertTrue(waiting.wait(1))
                release.set()
                with self.assertRaises(RuntimeError):
                    first.result(timeout=1)
                self.assertEqual(second.result(timeout=1)[0], {"ok": True})
            finally:
                release.set()

    def test_concurrent_identical_work_is_computed_once(self):
        entered, release = Event(), Event()

        def compute():
            entered.set()
            self.assertTrue(release.wait(2))
            return {"ok": True}

        compute_mock = Mock(side_effect=compute)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.prepare, compute_mock)
            try:
                self.assertTrue(entered.wait(1))
                second = pool.submit(self.prepare, compute_mock)
                release.set()
                self.assertEqual(first.result(timeout=1)[0], {"ok": True})
                self.assertIn(second.result(timeout=1)[1], {"hit", "shared"})
                compute_mock.assert_called_once()
            finally:
                release.set()

    def test_waiter_keeps_its_own_deadline(self):
        entered, release = Event(), Event()

        def compute():
            entered.set()
            release.wait(2)
            return {"ok": True}

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.prepare, compute)
            try:
                self.assertTrue(entered.wait(1))
                with (
                    generation_budget(GenerationBudget(seconds=0.02)),
                    self.assertRaises(GenerationTimedOut),
                ):
                    self.prepare(lambda: self.fail("Duplicate provider call"))
            finally:
                release.set()
                first.result(timeout=1)

    def test_expired_value_and_disabled_cache_recompute(self):
        compute = Mock(return_value={"ok": True})
        self.prepare(compute)
        with patch(
            "django.core.cache.backends.locmem.time.time", return_value=time.time() + 61
        ):
            self.assertEqual(self.prepare(compute)[1], "miss")
        with self.settings(GENERATION_CACHE_ENABLED=False):
            self.assertEqual(self.prepare(compute)[1], "disabled")
        self.assertEqual(compute.call_count, 3)

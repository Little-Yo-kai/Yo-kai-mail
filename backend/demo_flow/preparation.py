"""Time preparation and overlap an uploaded reference with website analysis."""

import time
from concurrent.futures import Future
from contextvars import copy_context
from threading import BoundedSemaphore, Thread

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from core.generation_budget import current_budget
from core.preparation_cache import cached_preparation
from core.timing import timed_stage

_reference_slots = BoundedSemaphore(max(1, settings.DEMO_MAX_CONCURRENT_GENERATIONS))


def prepare(stage, inputs, compute, *, timeout, refresh=False):
    started = time.monotonic()
    with timed_stage(stage) as timing:
        result, status = cached_preparation(
            stage=stage,
            inputs=inputs,
            compute=compute,
            timeout=timeout,
            refresh=refresh,
        )
        timing["cache_hit"] = status in {"hit", "shared"}
    return result, {
        "stage": stage,
        "duration_seconds": round(time.monotonic() - started, 3),
        "cache": status,
    }


def start_reference_preparation(image, analyze):
    """Use an owned upload and copied deadline; never create unbounded threads."""
    if not _reference_slots.acquire(blocking=False):
        return None
    owned_image = None
    try:
        image.seek(0)
        owned_image = SimpleUploadedFile(
            image.name,
            image.read(),
            content_type=image.content_type,
        )
        context = copy_context()
        future = Future()

        def work():
            try:
                future.set_result(context.run(analyze, owned_image))
            except Exception as exc:  # noqa: BLE001 - Forward worker errors to the caller.
                future.set_exception(exc)
            finally:
                owned_image.close()
                _reference_slots.release()

        Thread(target=work, daemon=True, name="email-reference").start()
        return future
    except Exception:
        if owned_image is not None:
            owned_image.close()
        _reference_slots.release()
        raise


def wait_for_reference(future):
    from concurrent.futures import TimeoutError

    while True:
        budget = current_budget()
        if budget is not None:
            budget.check()
        try:
            return future.result(timeout=0.1)
        except TimeoutError:
            if future.done():
                raise

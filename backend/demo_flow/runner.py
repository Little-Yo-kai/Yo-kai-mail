"""Bound the HTTP wait and publish real pipeline stages without Celery/Redis."""

import asyncio
import json
import logging
import time
import uuid
from queue import Empty, SimpleQueue
from threading import BoundedSemaphore, Thread

from django.conf import settings
from django.db import close_old_connections, connections

from core.generation_budget import (
    GenerationBudget,
    GenerationTimedOut,
    generation_budget,
)

from .errors import generation_failure

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(max(1, settings.DEMO_MAX_CONCURRENT_GENERATIONS))


class GenerationBusy(RuntimeError):
    pass


class GenerationRun:
    def __init__(self, generate, **kwargs):
        if not _slots.acquire(blocking=False):
            raise GenerationBusy(
                "The server is generating other emails. Please try again shortly."
            )
        self.request_id = uuid.uuid4().hex[:12]
        self.queue = SimpleQueue()
        self.budget = GenerationBudget(
            on_progress=self.queue.put, request_id=self.request_id
        )
        self.kwargs = kwargs
        try:
            self.thread = Thread(
                target=self._work,
                args=(generate,),
                daemon=True,
                name=f"email-{self.request_id}",
            )
            self.thread.start()
        except Exception:
            _slots.release()
            raise

    def _work(self, generate):
        try:
            close_old_connections()
            with generation_budget(self.budget):
                result = generate(**self.kwargs)
                self.budget.check()
            self.queue.put(
                {
                    "type": "result",
                    "success": True,
                    "data": result,
                    "request_id": self.request_id,
                }
            )
            logger.info(
                "Email generation request=%s completed elapsed_seconds=%.1f",
                self.request_id,
                time.monotonic() - self.budget.started,
            )
        except Exception as exc:
            logger.exception(
                "Email generation request=%s stage=%s failed",
                self.request_id,
                self.budget.stage,
            )
            payload, response_status = generation_failure(
                exc, stage=self.budget.stage, request_id=self.request_id
            )
            self.queue.put({"type": "error", **payload, "status": response_status})
        finally:
            try:
                image = self.kwargs.get("reference_image")
                if image is not None:
                    image.close()
                connections.close_all()
            finally:
                _slots.release()

    def events(self):
        try:
            yield {
                "type": "started",
                "request_id": self.request_id,
                "timeout_seconds": self.budget.seconds,
            }
            while True:
                if self.budget.remaining <= 0:
                    payload, response_status = generation_failure(
                        GenerationTimedOut(),
                        stage=self.budget.stage,
                        request_id=self.request_id,
                    )
                    yield {"type": "error", **payload, "status": response_status}
                    return
                try:
                    event = self.queue.get(timeout=min(2, self.budget.remaining))
                except Empty:
                    yield {
                        "type": "heartbeat",
                        "stage": self.budget.stage,
                        "elapsed_seconds": round(
                            time.monotonic() - self.budget.started, 1
                        ),
                    }
                    continue
                yield event
                if event["type"] in {"result", "error"}:
                    return
        finally:
            self.close()

    def __iter__(self):
        for event in self.events():
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    def close(self):
        # In-flight HTTP calls have their own timeout; stage checks prevent
        # any further provider calls after disconnect or the overall deadline.
        self.budget.cancelled.set()

    async def async_stream(self):
        # Django otherwise consumes a synchronous iterator into a list under
        # ASGI, hiding all progress until the final result is ready.
        iterator = iter(self)
        try:
            while (chunk := await asyncio.to_thread(next, iterator, None)) is not None:
                yield chunk
        finally:
            self.close()

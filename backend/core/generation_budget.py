"""A shared deadline and cooperative cancellation for one generation run."""

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Event

from django.conf import settings

logger = logging.getLogger(__name__)
_current = ContextVar("generation_budget", default=None)


class GenerationTimedOut(TimeoutError):
    pass


class GenerationCancelled(RuntimeError):
    pass


class GenerationBudget:
    def __init__(self, seconds=None, on_progress=None, request_id=None):
        self.seconds = (
            seconds if seconds is not None else settings.DEMO_GENERATION_TIMEOUT_SECONDS
        )
        self.started = time.monotonic()
        self.deadline = self.started + self.seconds
        self.cancelled = Event()
        self.stage = "website_import"
        self.on_progress = on_progress
        self.request_id = request_id

    @property
    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def check(self):
        if self.remaining <= 0:
            raise GenerationTimedOut("The generation time limit was reached.")
        if self.cancelled.is_set():
            raise GenerationCancelled("Generation was cancelled.")

    def progress(self, stage):
        self.check()
        self.stage = stage
        elapsed = round(time.monotonic() - self.started, 1)
        logger.info(
            "Email generation request=%s stage=%s elapsed_seconds=%s",
            self.request_id,
            stage,
            elapsed,
        )
        if self.on_progress:
            self.on_progress(
                {"type": "progress", "stage": stage, "elapsed_seconds": elapsed}
            )


def current_budget():
    return _current.get()


@contextmanager
def generation_budget(budget):
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def with_generation_budget(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if current_budget() is not None:
            return function(*args, **kwargs)
        with generation_budget(GenerationBudget()):
            return function(*args, **kwargs)

    return wrapped


def request_timeout(limit):
    """Clamp each provider attempt to the remaining overall time."""
    budget = current_budget()
    if budget is None:
        return limit
    budget.check()
    return min(limit, budget.remaining)


def report_stage(stage):
    budget = current_budget()
    if budget is not None:
        budget.progress(stage)

"""Short-lived preparation results, with bounded waits and in-process coalescing."""

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from threading import Event, Lock

from django.conf import settings
from django.core.cache import caches

from .generation_budget import (
    GenerationCancelled,
    GenerationTimedOut,
    current_budget,
)

logger = logging.getLogger(__name__)
_lock = Lock()
_inflight = {}
_MISSING = object()


@dataclass
class _Flight:
    done: Event = field(default_factory=Event)
    value: object = None
    error: Exception | None = None


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _check_budget():
    budget = current_budget()
    if budget is not None:
        budget.check()


def cached_preparation(
    *,
    stage,
    inputs,
    compute,
    timeout,
    refresh=False,
    cache_alias="generation",
    enabled=None,
):
    """Return an isolated result and cache status; failures are never cached.

    Redis can share completed results across workers. In-flight coalescing is
    deliberately process-local, so a failed cache cannot block generation.
    """
    _check_budget()
    if enabled is None:
        enabled = settings.GENERATION_CACHE_ENABLED
    if not enabled or timeout <= 0:
        return compute(), "disabled"

    key = f"preparation:v1:{stage}:{fingerprint(inputs)}"
    cache = caches[cache_alias]
    if not refresh:
        try:
            value = cache.get(key, _MISSING)
        except Exception:  # noqa: BLE001 - A cache outage must not fail generation.
            logger.warning("Preparation cache read failed stage=%s", stage)
            cache = None
        else:
            if value is not _MISSING:
                return copy.deepcopy(value), "hit"

    flight_key = cache_alias + ":" + key + (":refresh" if refresh else "")
    with _lock:
        flight = _inflight.get(flight_key)
        leader = flight is None
        if leader:
            flight = _Flight()
            _inflight[flight_key] = flight

    if not leader:
        while not flight.done.wait(0.1):
            _check_budget()
        _check_budget()
        if flight.error is not None:
            # A disconnected request must not poison a healthy waiter.
            if isinstance(flight.error, (GenerationCancelled, GenerationTimedOut)):
                return cached_preparation(
                    stage=stage,
                    inputs=inputs,
                    compute=compute,
                    timeout=timeout,
                    refresh=refresh,
                    cache_alias=cache_alias,
                    enabled=enabled,
                )
            raise flight.error
        return copy.deepcopy(flight.value), "shared"

    try:
        _check_budget()
        # The previous producer may have finished between our read and lock.
        if cache is not None and not refresh:
            try:
                value = cache.get(key, _MISSING)
            except Exception:  # noqa: BLE001 - Continue without the optional cache.
                cache = None
            else:
                if value is not _MISSING:
                    flight.value = copy.deepcopy(value)
                    return copy.deepcopy(value), "hit"
        value = compute()
        _check_budget()
        flight.value = copy.deepcopy(value)
        if cache is not None:
            try:
                cache.set(key, value, timeout=timeout)
            except Exception:  # noqa: BLE001 - The validated result is still usable.
                logger.warning("Preparation cache write failed stage=%s", stage)
        return copy.deepcopy(value), "refresh" if refresh else "miss"
    except Exception as exc:
        flight.error = exc
        # Provider adapters can wrap cancellation/deadline exceptions. Keep
        # that request-local failure from being shared with healthy waiters.
        try:
            _check_budget()
        except (GenerationCancelled, GenerationTimedOut) as stopped:
            flight.error = stopped
        raise
    finally:
        with _lock:
            _inflight.pop(flight_key, None)
            flight.done.set()

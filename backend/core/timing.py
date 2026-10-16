"""Content-free stage measurements shared by the email workflow."""

import json
import logging
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger("yokai.workflow")


@contextmanager
def timed_stage(stage: str, **fields):
    # Callers pass only fixed stage names, booleans and counts; never request data.
    started = perf_counter()
    outcome = "success"
    try:
        yield fields
    except Exception:
        outcome = "error"
        raise
    finally:
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        metrics = {
            "stage": stage,
            "outcome": outcome,
            "elapsed_ms": elapsed_ms,
            **fields,
        }
        logger.info(json.dumps({"event": "email_workflow", **metrics}), extra=metrics)

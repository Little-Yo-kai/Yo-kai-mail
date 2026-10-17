"""Serialize model context without changing any facts or contract fields."""

import json

from django.conf import settings


def serialize_prompt_context(payload: dict) -> str:
    separators = (",", ":") if settings.GEMINI_COMPACT_CONTEXT_ENABLED else None
    return json.dumps(payload, ensure_ascii=False, separators=separators)

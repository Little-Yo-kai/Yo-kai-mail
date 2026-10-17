"""Capture real prompt construction using offline fixture model responses."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import override_settings

from email_generation.services.composer import GeminiEmailDesignComposer
from email_generation.services.gemini import GeminiCampaignStrategist


def capture_fixture_generation(fixture: dict, *, compact: bool) -> dict:
    """Return requests for assertions; callers must not log their contents."""
    client = Mock()
    client.interactions.create.side_effect = [
        SimpleNamespace(output_text=json.dumps(fixture["content_plan"])),
        SimpleNamespace(output_text=json.dumps(fixture["email_design"])),
    ]
    with override_settings(GEMINI_COMPACT_CONTEXT_ENABLED=compact):
        planned = GeminiCampaignStrategist(client=client).plan(
            brand_profile=fixture["brand_profile"],
            campaign_brief=fixture["campaign_brief"],
            reference_design_spec=fixture["reference_design_spec"],
        )
        composed = GeminiEmailDesignComposer(client=client).compose(
            brand_profile=fixture["brand_profile"],
            reference_design_spec=fixture["reference_design_spec"],
            **planned,
        )
    requests = [call.kwargs for call in client.interactions.create.call_args_list]
    if len(requests) != 2:
        raise ValueError("Prompt benchmark expected one strategy and one design request.")
    return {"requests": requests, "planned": planned, "composed": composed}


def _prompt_payload(request: dict) -> dict:
    return json.loads(request["input"].split("\n\nINPUT JSON:\n", 1)[1])


def _request_sizes(request: dict) -> dict:
    schema = request["response_format"]["schema"]
    return {
        "prompt_utf8_bytes": len(request["input"].encode("utf-8")),
        "response_schema_utf8_bytes": len(
            json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ),
    }


def measure_prompt_context(fixture: dict) -> dict:
    """Measure bytes, never model tokens or live latency; emit no prompt data."""
    baseline = capture_fixture_generation(fixture, compact=False)
    compact = capture_fixture_generation(fixture, compact=True)
    contexts_equal = all(
        _prompt_payload(before) == _prompt_payload(after)
        for before, after in zip(baseline["requests"], compact["requests"], strict=True)
    )
    outputs_equal = all(baseline[key] == compact[key] for key in ("planned", "composed"))
    schemas_equal = all(
        before["response_format"] == after["response_format"]
        for before, after in zip(baseline["requests"], compact["requests"], strict=True)
    )
    if not (contexts_equal and outputs_equal and schemas_equal):
        raise ValueError("Compact prompt context changed fixture semantics or output.")
    return {
        "mode": "real_prompt_construction_mocked_model_responses",
        "baseline": {
            name: _request_sizes(request)
            for name, request in zip(("strategist", "composer"), baseline["requests"], strict=True)
        },
        "compact": {
            name: _request_sizes(request)
            for name, request in zip(("strategist", "composer"), compact["requests"], strict=True)
        },
        "model_calls_per_mode": {"strategist": 1, "composer": 1},
        "contexts_equal": contexts_equal,
        "validated_outputs_equal": outputs_equal,
        "response_schemas_equal": schemas_equal,
        "unmeasured": ["model_tokens", "live_model_latency", "live_output_quality"],
    }

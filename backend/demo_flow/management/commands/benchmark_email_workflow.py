"""Offline, repeatable measurements; live generation requires explicit flags."""

import json
import logging
import statistics
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings

from demo_flow.prompt_benchmark import measure_prompt_context
from demo_flow.service import generate_phase1_demo
from email_generation.schemas import EmailDesign
from email_rendering.compiler import compile_mjml_to_html
from email_rendering.renderer import render_email_to_mjml
from website_intelligence.normalizers import build_website_snapshot


def _measure(operation, repeats=1):
    samples = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = operation()
        samples.append(round((perf_counter() - started) * 1000, 3))
    return result, {"samples_ms": samples, "median_ms": statistics.median(samples)}


class BaseMeasurements(logging.Handler):
    def __init__(self):
        super().__init__()
        self.stages = []

    def emit(self, record):
        self.stages.append(
            {
                "stage": record.stage,
                "outcome": record.outcome,
                "elapsed_ms": record.elapsed_ms,
                "cache_hit": getattr(record, "cache_hit", None),
            }
        )


class Command(BaseCommand):
    help = "Benchmark fixture extraction/validation/render/compile and mocked generation; paid calls are opt-in."

    def add_arguments(self, parser):
        parser.add_argument("--live-url")
        parser.add_argument("--allow-paid-api", action="store_true")

    def handle(self, *args, **options):
        if options["live_url"] or options["allow_paid_api"]:
            if not (options["live_url"] and options["allow_paid_api"]):
                raise CommandError(
                    "Live benchmarking needs both --live-url and --allow-paid-api."
                )
            handler = BaseMeasurements()
            logger = logging.getLogger("yokai.workflow")
            logger.addHandler(handler)
            try:
                # No sends. Disable caches to measure one actual generation.
                with override_settings(
                    GENERATION_CACHE_ENABLED=False,
                ):
                    _, measured = _measure(
                        lambda: generate_phase1_demo(
                            url=options["live_url"], refresh_website=True
                        )
                    )
            finally:
                logger.removeHandler(handler)
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "live_paid_generation",
                        "total": measured,
                        "stages": handler.stages,
                    }
                )
            )
            return

        fixture = json.loads(
            (
                Path(__file__).resolve().parents[2] / "fixtures" / "workflow.json"
            ).read_text(encoding="utf-8")
        )
        prompt_context = measure_prompt_context(fixture)
        _, extraction = _measure(
            lambda: build_website_snapshot(fixture["url"], fixture["scraped"]), 3
        )
        _, validation = _measure(
            lambda: EmailDesign.model_validate(fixture["email_design"]), 3
        )
        rendered, rendering = _measure(
            lambda: render_email_to_mjml(
                brand_profile=fixture["brand_profile"],
                email_design=fixture["email_design"],
                asset_inventory=fixture["asset_inventory"],
            ),
            3,
        )
        with override_settings(MJML_COMPILE_CACHE_TTL_SECONDS=0):
            baseline, uncached = _measure(
                lambda: compile_mjml_to_html(rendered["mjml"]), 3
            )
        # Isolated cache; never clear another running application's entries.
        with override_settings(
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": "email-benchmark",
                },
                "generation": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": "email-benchmark-preparation",
                },
            },
            GENERATION_CACHE_ENABLED=True,
        ):
            compiled, cold = _measure(lambda: compile_mjml_to_html(rendered["mjml"]))
            warm_result, warm = _measure(
                lambda: compile_mjml_to_html(rendered["mjml"]), 3
            )
            with (
                patch("demo_flow.service.FirecrawlService") as firecrawl,
                patch("demo_flow.service.GeminiBrandService") as brand,
                patch("demo_flow.service.GeminiCampaignStrategist") as strategist,
                patch("demo_flow.service.GeminiEmailDesignComposer") as composer,
                patch("demo_flow.service.select_reference") as reference,
                patch(
                    "demo_flow.service.build_preview_html",
                    side_effect=lambda **kw: (kw["html_document"], [], []),
                ),
            ):
                firecrawl.FORMATS = ["markdown", "branding", "images", "screenshot"]
                firecrawl.return_value.scrape.return_value = fixture["scraped"]
                brand.return_value.analyze.return_value = fixture["brand_profile"]
                strategist.return_value.plan.return_value = {
                    key: fixture[key]
                    for key in ("content_plan", "asset_inventory", "fact_ledger")
                }
                composer.return_value.compose.return_value = {
                    key: fixture[key] for key in ("email_design", "asset_inventory")
                }
                reference.return_value = {
                    "reference_id": "fixture",
                    "name": "Fixture",
                    "recipe_family": "intro",
                    "selection_reasons": [],
                    "reference_design_spec": fixture["reference_design_spec"],
                }
                _, first = _measure(lambda: generate_phase1_demo(url=fixture["url"]))
                calls_first = [
                    brand.return_value.analyze.call_count,
                    strategist.return_value.plan.call_count,
                    composer.return_value.compose.call_count,
                ]
                _, repeat = _measure(lambda: generate_phase1_demo(url=fixture["url"]))
                repeated_model_calls = sum(
                    [
                        brand.return_value.analyze.call_count,
                        strategist.return_value.plan.call_count,
                        composer.return_value.compose.call_count,
                    ]
                ) - sum(calls_first)
        if baseline != compiled or compiled != warm_result:
            raise CommandError("Cached and uncached outputs differ.")
        self.stdout.write(
            json.dumps(
                {
                    "mode": "offline_fixture",
                    "prompt_context": prompt_context,
                    "normalization": extraction,
                    "validation": validation,
                    "design_to_mjml": rendering,
                    "uncached_compilation": uncached,
                    "cached_compilation_first": cold,
                    "cached_compilation_repeat": warm,
                    "mocked_workflow_first": first,
                    "mocked_workflow_repeat": repeat,
                    "mocked_model_calls_first": sum(calls_first),
                    "mocked_model_calls_repeat": repeated_model_calls,
                    "html_bytes": len(compiled["html"].encode()),
                    "compiler_errors": compiled["compiler_errors"],
                    "output_equal": True,
                    "failures": 0,
                    "unmeasured": [
                        "paid_api_latency",
                        "public_image_reachability",
                        "real_delivery",
                        "Outlook/Gmail inbox rendering",
                        "Maildun runtime",
                    ],
                },
                indent=2,
            )
        )

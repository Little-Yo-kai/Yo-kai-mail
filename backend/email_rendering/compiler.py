import json
import subprocess
from pathlib import Path

from django.conf import settings

from core.generation_budget import request_timeout
from core.preparation_cache import cached_preparation
from core.timing import timed_stage

from .text import html_to_plain_text


class MJMLCompilerError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


def compile_mjml_to_html(mjml: str) -> dict:
    if not isinstance(mjml, str) or not mjml.strip():
        raise MJMLCompilerError("MJML input is empty.")

    script_path = Path(settings.BASE_DIR) / "mjml_runtime" / "compile.mjs"

    if not script_path.exists():
        raise MJMLCompilerError(
            "MJML compiler runtime is missing.",
            details=str(script_path),
        )

    # Invalidate on compiler, dependency lock or bridge changes, as well as input.
    runtime_files = [script_path, script_path.with_name("package-lock.json")]
    runtime_version = [
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in runtime_files
        if path.exists()
    ]
    ttl = getattr(settings, "MJML_COMPILE_CACHE_TTL_SECONDS", 900)
    with timed_stage("compilation") as timing:
        compiled, cache_status = cached_preparation(
            stage="mjml_compilation",
            inputs=[settings.MJML_NODE_BINARY, runtime_version, mjml],
            compute=lambda: _compile_uncached(mjml, script_path),
            timeout=ttl,
            cache_alias="default",
            enabled=ttl > 0,
        )
        timing["cache_hit"] = cache_status in {"hit", "shared"}
        return compiled


def _compile_uncached(mjml: str, script_path: Path) -> dict:

    try:
        result = subprocess.run(
            [
                settings.MJML_NODE_BINARY,
                str(script_path),
            ],
            input=mjml,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=request_timeout(settings.MJML_COMPILE_TIMEOUT_SECONDS),
            check=False,
        )
    except FileNotFoundError as exc:
        raise MJMLCompilerError(
            "Node.js is required for MJML compilation.",
            details=str(exc),
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MJMLCompilerError(
            "MJML compilation timed out.",
            details=str(exc),
        ) from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise MJMLCompilerError(
            "MJML compilation failed.",
            details=details or None,
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MJMLCompilerError(
            "MJML compiler returned invalid output.",
            details=str(exc),
        ) from exc

    if not isinstance(payload, dict):
        raise MJMLCompilerError("MJML compiler returned invalid output.")
    html = payload.get("html")
    errors = payload.get("errors") or []

    if not isinstance(html, str) or not html.strip():
        raise MJMLCompilerError("MJML compiler returned empty HTML.")

    return {
        "html": html,
        "text": html_to_plain_text(html),
        "compiler_errors": errors,
    }

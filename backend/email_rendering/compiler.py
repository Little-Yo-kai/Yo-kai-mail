import json
import subprocess
from pathlib import Path

from django.conf import settings


class MJMLCompilerError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


def compile_mjml_to_html(mjml: str) -> dict:
    if not isinstance(mjml, str) or not mjml.strip():
        raise MJMLCompilerError("MJML input is empty.")

    script_path = (
        Path(settings.BASE_DIR)
        / "mjml_runtime"
        / "compile.mjs"
    )

    if not script_path.exists():
        raise MJMLCompilerError(
            "MJML compiler runtime is missing.",
            details=str(script_path),
        )

    try:
        result = subprocess.run(
            [
                settings.MJML_NODE_BINARY,
                str(script_path),
            ],
            input=mjml,
            text=True,
            capture_output=True,
            timeout=settings.MJML_COMPILE_TIMEOUT_SECONDS,
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

    html = payload.get("html")
    errors = payload.get("errors") or []

    if not isinstance(html, str) or not html.strip():
        raise MJMLCompilerError(
            "MJML compiler returned empty HTML."
        )

    return {
        "html": html,
        "compiler_errors": errors,
    }

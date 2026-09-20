import base64

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


class EmailScreenshotError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


def capture_email_screenshot(
    html: str,
    *,
    viewport_width: int = 760,
    viewport_height: int = 900,
    timeout_ms: int = 15000,
) -> dict:
    if not isinstance(html, str) or not html.strip():
        raise EmailScreenshotError("HTML input is empty.")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={
                    "width": viewport_width,
                    "height": viewport_height,
                },
                device_scale_factor=1,
            )

            page.set_content(
                html,
                wait_until="load",
                timeout=timeout_ms,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(timeout_ms, 5000),
                )
            except PlaywrightTimeoutError:
                # A slow third-party image should not block the whole preview.
                pass

            screenshot_bytes = page.screenshot(
                full_page=True,
                type="png",
            )

            dimensions = page.evaluate(
                """() => ({
                    width: Math.max(
                        document.documentElement.scrollWidth,
                        document.body?.scrollWidth || 0
                    ),
                    height: Math.max(
                        document.documentElement.scrollHeight,
                        document.body?.scrollHeight || 0
                    )
                })"""
            )

            browser.close()
    except EmailScreenshotError:
        raise
    except Exception as exc:
        raise EmailScreenshotError(
            "Browser screenshot capture failed.",
            details=str(exc),
        ) from exc

    return {
        "image_base64": base64.b64encode(screenshot_bytes).decode("ascii"),
        "mime_type": "image/png",
        "width": dimensions["width"],
        "height": dimensions["height"],
    }

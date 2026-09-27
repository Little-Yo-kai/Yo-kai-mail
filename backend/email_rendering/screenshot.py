import base64
import ipaddress
import socket
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


class EmailScreenshotError(RuntimeError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.details = details


def _host_is_public(hostname: str) -> bool:
    normalized = hostname.strip().lower().rstrip(".")
    if not normalized:
        return False

    if normalized == "localhost" or normalized.endswith(".localhost"):
        return False

    if normalized.endswith(".local"):
        return False

    try:
        addresses = socket.getaddrinfo(
            normalized,
            None,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        return False

    if not addresses:
        return False

    for address in addresses:
        candidate = address[4][0]
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return False

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def _detect_image_mime(body: bytes) -> str | None:
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(body) >= 12
        and body[:4] == b"RIFF"
        and body[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def _allowed_asset_hosts(asset_urls: list[str]) -> set[str]:
    hosts: set[str] = set()

    for value in asset_urls:
        if not isinstance(value, str):
            continue

        parsed = urlparse(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and _host_is_public(parsed.hostname)
        ):
            hosts.add(parsed.hostname.lower())

    return hosts


def capture_email_screenshot(
    html: str,
    *,
    asset_urls: list[str] | None = None,
    viewport_width: int = 760,
    viewport_height: int = 900,
    timeout_ms: int = 15000,
) -> dict:
    if not isinstance(html, str) or not html.strip():
        raise EmailScreenshotError("HTML input is empty.")

    allowed_asset_urls = {
        value
        for value in (asset_urls or [])
        if isinstance(value, str) and value.strip()
    }

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

            image_network_events: list[dict] = []

            def record_response(response):
                request = response.request
                if request.resource_type == "image":
                    image_network_events.append(
                        {
                            "url": response.url,
                            "status": response.status,
                            "ok": response.ok,
                        }
                    )

            def record_failed_request(request):
                if request.resource_type == "image":
                    image_network_events.append(
                        {
                            "url": request.url,
                            "status": None,
                            "ok": False,
                            "failure": request.failure,
                        }
                    )

            page.on("response", record_response)
            page.on("requestfailed", record_failed_request)

            def route_request(route):
                request = route.request
                parsed = urlparse(request.url)

                if parsed.scheme in {"about", "data"}:
                    route.continue_()
                    return

                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or not _host_is_public(parsed.hostname)
                ):
                    route.abort()
                    return

                if (
                    request.resource_type == "image"
                    and request.url in allowed_asset_urls
                ):
                    try:
                        response = route.fetch(max_redirects=0)
                        body = response.body()
                        detected_mime = _detect_image_mime(body)

                        if response.status == 200 and detected_mime:
                            route.fulfill(
                                status=200,
                                body=body,
                                headers={
                                    "content-type": detected_mime,
                                    "cache-control": "no-store",
                                },
                            )
                            return

                        route.fulfill(response=response)
                        return
                    except Exception:
                        route.continue_()
                        return

                route.continue_()

            page.route("**/*", route_request)

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

            image_diagnostics = page.evaluate(
                """() => {
                    const images = Array.from(document.images);
                    return {
                        total: images.length,
                        loaded: images.filter(
                            (img) => img.complete && img.naturalWidth > 0
                        ).length,
                        broken: images
                            .filter(
                                (img) => !img.complete || img.naturalWidth === 0
                            )
                            .map((img) => img.currentSrc || img.src || "")
                    };
                }"""
            )

            if image_diagnostics["broken"]:
                relevant_events = [
                    event
                    for event in image_network_events
                    if event.get("url") in image_diagnostics["broken"]
                    or event.get("ok") is False
                ]

                diagnostic_parts = []
                for broken_url in image_diagnostics["broken"]:
                    matching = [
                        event
                        for event in relevant_events
                        if event.get("url") == broken_url
                    ]

                    if not matching:
                        diagnostic_parts.append(
                            f"{broken_url} [no image response captured]"
                        )
                        continue

                    for event in matching:
                        if event.get("status") is not None:
                            diagnostic_parts.append(
                                f"{broken_url} "
                                f"[HTTP {event['status']}]"
                            )
                        elif event.get("failure"):
                            diagnostic_parts.append(
                                f"{broken_url} "
                                f"[{event['failure']}]"
                            )
                        else:
                            diagnostic_parts.append(
                                f"{broken_url} [request failed]"
                            )

                raise EmailScreenshotError(
                    "Rendered email contains broken images.",
                    details="; ".join(diagnostic_parts),
                )

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
        "image_diagnostics": image_diagnostics,
        "image_network_events": image_network_events,
    }

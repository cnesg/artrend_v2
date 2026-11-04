"""Render public JavaScript pages without letting Chromium make direct network requests."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup

from .config import RAW_ROOT, USER_AGENT, WORK_ROOT, iso_now
from .http import Blocked, FetchError, Response

_RESOURCE_TYPES = {"document", "script", "stylesheet", "xhr", "fetch"}
_SENSITIVE_QUERY_KEY = re.compile(r"(?:key|token|authorization|secret|signature)$")
_CHALLENGE_MARKERS = (
    "just a moment...", "attention required!",
    "verify you are human", "checking your browser",
)


class RenderUnavailable(RuntimeError):
    """The optional Playwright dependency or its standard Chromium binary is unavailable."""


def request_allowed(url: str, method: str, resource_type: str, headers: dict, origin: str) -> bool:
    """Allow only same-origin public GET documents/scripts/styles/XHR/fetch without credentials or tokens."""
    if method.upper() != "GET" or resource_type not in _RESOURCE_TYPES:
        return False
    if _origin(url) != origin or _has_credentials(url):
        return False
    lowered_headers = {str(key).lower(): value for key, value in (headers or {}).items()}
    if lowered_headers.get("authorization") or lowered_headers.get("proxy-authorization") or lowered_headers.get("cookie"):
        return False
    query = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    if any(_sensitive_name(name) for name, _ in query):
        return False
    return True


def render_public(ctx, url: str, *, ready_selector: str, max_subrequests: int = 50,
                  timeout_ms: int = 30000) -> Response:
    """Fetch a public page first, then render it with isolated standard Chromium.

    Every browser request is routed through ctx.fetch after a strict same-origin GET allowlist. The
    returned Response points to a rendered-DOM archive so ctx.evidence can cite it like fetched HTML.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderUnavailable("Playwright is optional; install the pinned requirements-browser.txt dependency") from exc

    initial = ctx.fetch(url, accept="text/html", store=False)
    expected_origin = _origin(url)
    if _origin(initial.final_url) != expected_origin:
        raise Blocked("cross_origin_redirect", url, initial.status, initial.final_url)
    _reject_challenge(initial)
    if "html" not in (initial.content_type or "").lower():
        raise FetchError(f"render preflight was not HTML: {url} ({initial.content_type})")

    route_errors = []
    request_count = [0]
    main_urls = {_url_key(url), _url_key(initial.final_url)}
    try:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            executable = _chromium_executable()
            if executable:
                launch_options["executable_path"] = str(executable)
            try:
                browser = playwright.chromium.launch(**launch_options)
            except Exception as exc:
                raise RenderUnavailable(f"standard Playwright Chromium could not launch: {exc}") from exc
            try:
                browser_context = browser.new_context(user_agent=USER_AGENT, service_workers="block")
                websocket_router = getattr(browser_context, "route_web_socket", None)
                if not callable(websocket_router):
                    raise RenderUnavailable("Playwright cannot enforce the no-WebSocket public rendering policy")
                websocket_router("**/*", lambda socket: socket.close(code=1000, reason="WebSocket access disabled"))
                page = browser_context.new_page()

                def route_request(route, request):
                    request_url = request.url
                    if not request_allowed(request_url, request.method, request.resource_type,
                                           request.headers, expected_origin):
                        route.abort()
                        return
                    try:
                        if request.resource_type == "document":
                            if _url_key(request_url) not in main_urls:
                                route.abort()
                                return
                            response = initial
                        else:
                            request_count[0] += 1
                            if request_count[0] > max_subrequests:
                                raise FetchError(f"render request cap {max_subrequests} reached for {url}")
                            accept = request.headers.get("accept")
                            response = ctx.fetch(request_url, accept=accept, store=False)
                            if _origin(response.final_url) != expected_origin:
                                raise Blocked("cross_origin_redirect", request_url, response.status, response.final_url)
                            _reject_challenge(response)
                        route.fulfill(status=response.status, body=response.content,
                                      headers=_fulfillment_headers(response.headers, response.content_type))
                    except Exception as exc:
                        route_errors.append(exc)
                        try:
                            route.abort()
                        except Exception:
                            pass

                browser_context.route("**/*", route_request)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_selector(ready_selector, state="attached", timeout=timeout_ms)
                    rendered_html = page.content()
                    rendered_url = page.url
                except Exception as exc:
                    if route_errors:
                        raise route_errors[0]
                    raise FetchError(f"public page did not render selector {ready_selector!r}: {url}: {exc}") from exc
                if route_errors:
                    raise route_errors[0]
                if _origin(rendered_url) != expected_origin:
                    raise Blocked("cross_origin_redirect", url, initial.status, rendered_url)
                _reject_challenge_text(rendered_html, url, initial.status)
            finally:
                browser.close()
    except (Blocked, FetchError, RenderUnavailable):
        raise
    except Exception as exc:
        raise FetchError(f"public rendering failed for {url}: {exc}") from exc

    return _archive_rendered(ctx, url, rendered_url, rendered_html, initial.status)


def _archive_rendered(ctx, url: str, final_url: str, html: str, status: int) -> Response:
    content = html.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    fetched_at = iso_now()
    run_stamp = getattr(ctx.fetcher, "run_stamp", "rendered")
    directory = (RAW_ROOT / ctx.source_id / run_stamp).resolve()
    root = WORK_ROOT.resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("rendered DOM archive path must remain under WORK_ROOT") from exc
    path_key = hashlib.sha1((url + "\x1f" + digest).encode("utf-8")).hexdigest()[:20]
    archive = directory / f"{path_key}.rendered.html"
    directory.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(content)
    relative_path = str(archive.relative_to(root))
    record = {
        "url": url, "final_url": final_url, "status": status, "sha256": digest,
        "file": archive.name, "fetched_at": fetched_at, "content_type": "text/html; charset=utf-8",
        "rendered": True,
    }
    with (directory / "_index.jsonl").open("a", encoding="utf-8") as index:
        index.write(json.dumps(record, ensure_ascii=False) + "\n")
    return Response(url, final_url, status, content, "text/html; charset=utf-8", fetched_at,
                    digest, relative_path, False, {})


def _chromium_executable() -> Path | None:
    browser_root = WORK_ROOT / "work" / "browser_binaries"
    candidates = []
    candidates.extend(browser_root.glob("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"))
    candidates.extend(browser_root.glob("chromium-*/chrome-linux/chrome"))
    candidates.extend(browser_root.glob("chromium-*/chrome-linux64/chrome"))
    for candidate in sorted(candidates, reverse=True):
        if candidate.is_file():
            return candidate
    return None


def _origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        return ""
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port in (None, 443)) or (
        parsed.scheme.lower() == "http" and port in (None, 80))
    authority = parsed.hostname.lower() if default_port else f"{parsed.hostname.lower()}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _has_credentials(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        return True
    for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if _sensitive_name(name):
            return True
    return False


def _sensitive_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return normalized == "auth" or bool(_SENSITIVE_QUERY_KEY.search(normalized))


def _url_key(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _reject_challenge(response: Response) -> None:
    if "html" in (response.content_type or "").lower():
        _reject_challenge_text(response.content.decode("utf-8", "ignore"), response.url, response.status)


def _reject_challenge_text(text: str, url: str, status: int) -> None:
    document = BeautifulSoup(text or "", "lxml")
    title = document.title.get_text(" ", strip=True).lower() if document.title else ""
    challenge_script = bool(document.select_one("script[src*='challenge-platform'], script[src*='cf-chl']"))
    for node in document.select("script, style, template"):
        node.decompose()
    lowered = document.get_text(" ", strip=True).lower()
    if (any(marker in lowered for marker in _CHALLENGE_MARKERS)
            or any(marker in title for marker in ("captcha", "access denied", "human verification"))
            or (challenge_script and len(lowered) < 400)):
        raise Blocked("challenge_page", url, status)


def _fulfillment_headers(headers: dict, content_type: str) -> dict:
    allowed = {"content-type", "content-language", "cache-control", "content-security-policy",
               "x-content-type-options", "access-control-allow-origin"}
    result = {key.lower(): value for key, value in (headers or {}).items() if key.lower() in allowed}
    if content_type and "content-type" not in result:
        result["content-type"] = content_type
    return result

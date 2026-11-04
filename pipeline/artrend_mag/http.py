"""Polite HTTP fetcher.

* robots.txt is checked per host before any request (robots allow != rights clearance).
* Minimum per-host interval (default 3 s, or Crawl-delay if larger).
* Conditional GET (ETag / Last-Modified) with a local cache index.
* 401/402/403/407/451, login redirects and challenge pages raise Blocked -> the source stops.
* 429/503 honour Retry-After up to MAX_RETRY_AFTER seconds, then stop; bounded retries otherwise.
* Raw bodies are stored per source/run only when the source's storage policy allows it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .robots import Robots
from .config import HTTP_CACHE, RAW_ROOT, USER_AGENT, WORK_ROOT, iso_now

MIN_INTERVAL = 3.0
MAX_RETRY_AFTER = 120
MAX_ATTEMPTS = 3
TIMEOUT = 40
BLOCK_STATUSES = {401, 402, 403, 407, 451}
CHALLENGE_MARKERS = ("cf-chl", "challenge-platform", "captcha", "Just a moment...", "Attention Required!")


def _is_login_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url.lower())
    endpoints = {"login", "signin", "sign-in"}
    parts = urllib.parse.unquote(parsed.path).split("/")
    return ((parsed.hostname or "").split(".")[0] in endpoints
            or any(part.split(".")[0] in endpoints for part in parts))


class Blocked(Exception):
    def __init__(self, kind: str, url: str, status: int | None, detail: str = ""):
        super().__init__(f"{kind} {status} {url} {detail}")
        self.kind, self.url, self.status, self.detail = kind, url, status, detail


class FetchError(Exception):
    pass


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str
    fetched_at: str
    sha256: str
    raw_path: str | None
    from_cache: bool = False
    headers: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        for enc in ("utf-8", "cp949", "shift_jis", "latin-1"):
            try:
                return self.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)


class Fetcher:
    def __init__(self, source_id: str, run_stamp: str, store_raw: bool, stats: dict, max_requests: int = 400,
                 api_policy_url: str | None = None, extra_headers: dict | None = None, min_interval: float | None = None):
        """api_policy_url: set ONLY for documented public APIs whose usage policy (not robots.txt, which
        targets crawlers) governs access. robots state is still recorded but not enforced for those hosts."""
        self.source_id = source_id
        self.api_policy_url = api_policy_url
        self.min_interval = min_interval or MIN_INTERVAL
        self.run_stamp = run_stamp
        self.store_raw = store_raw
        self.stats = stats
        self.max_requests = max_requests
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,ko;q=0.8,ja;q=0.7"})
        if extra_headers:
            self.s.headers.update(extra_headers)
        self._robots: dict[str, Robots | None] = {}
        self._robots_state: dict[str, str] = {}
        self._last: dict[str, float] = {}
        HTTP_CACHE.mkdir(parents=True, exist_ok=True)
        self.cache = sqlite3.connect(HTTP_CACHE / "index.sqlite", timeout=120)
        self.cache.execute("CREATE TABLE IF NOT EXISTS c(url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, raw_path TEXT, sha256 TEXT, content_type TEXT)")

    # -- robots -------------------------------------------------------------------------
    def robots_state(self, url: str) -> str:
        host = urllib.parse.urlsplit(url).netloc
        self._load_robots(url)
        return self._robots_state.get(host, "unknown")

    def _load_robots(self, url: str):
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc
        if host in self._robots:
            return self._robots[host]
        robots_url = f"{parts.scheme}://{host}/robots.txt"
        rp: Robots | None
        try:
            r = self.s.get(robots_url, timeout=TIMEOUT)
            self.stats["http_requests"] = self.stats.get("http_requests", 0) + 1
            if r.status_code == 200 and "html" not in r.headers.get("content-type", "").lower():
                rp = Robots(r.text)
                self._robots_state[host] = "parsed"
            elif r.status_code == 200:
                # HTML served at /robots.txt (SPA fallback) -> no machine-readable robots file
                rp = Robots("")
                self._robots_state[host] = "no_robots_file(html_fallback)"
            elif r.status_code in (404, 410):
                rp = Robots("")
                self._robots_state[host] = "not_found(allow)"
            else:
                self._robots_state[host] = f"robots_http_{r.status_code}(not_crawled)"
                rp = None
        except requests.RequestException as e:
            self._robots_state[host] = f"robots_error({type(e).__name__})"
            rp = None
        self._robots[host] = rp
        self._last[host] = time.monotonic()
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._load_robots(url)
        if self.api_policy_url:
            return True
        return bool(rp and rp.can_fetch(USER_AGENT, url))

    def _interval(self, url: str) -> float:
        rp = self._robots.get(urllib.parse.urlsplit(url).netloc)
        cd = None
        if rp:
            try:
                cd = rp.crawl_delay(USER_AGENT)
            except Exception:
                cd = None
        return max(self.min_interval, float(cd or 0))

    def _wait(self, url: str):
        host = urllib.parse.urlsplit(url).netloc
        last = self._last.get(host)
        if last is not None:
            delay = self._interval(url) - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()

    # -- fetch ---------------------------------------------------------------------------
    def get(self, url: str, *, params: dict | None = None, accept: str | None = None, conditional: bool = True,
            store: bool | None = None, headers: dict | None = None) -> Response:
        full = url if not params else f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
        if not self.allowed(full):
            host = urllib.parse.urlsplit(full).netloc
            kind = "robots_disallow" if self._robots.get(host) is not None else "robots_unavailable"
            raise Blocked(kind, full, None, self._robots_state.get(host, ""))
        if self.stats.get("http_requests", 0) >= self.max_requests:
            raise FetchError(f"request cap {self.max_requests} reached for {self.source_id}")
        hdrs = dict(headers or {})
        if accept:
            hdrs["Accept"] = accept
        cached = self.cache.execute("SELECT etag,last_modified,raw_path,sha256,content_type FROM c WHERE url=?", (full,)).fetchone()
        if conditional and cached and cached[2] and (WORK_ROOT / cached[2]).exists():
            if cached[0]:
                hdrs["If-None-Match"] = cached[0]
            if cached[1]:
                hdrs["If-Modified-Since"] = cached[1]
        attempt = 0
        while True:
            attempt += 1
            self._wait(full)
            try:
                r = self.s.get(full, headers=hdrs, timeout=TIMEOUT, allow_redirects=True)
            except requests.RequestException as e:
                self.stats["http_errors"] = self.stats.get("http_errors", 0) + 1
                if attempt >= MAX_ATTEMPTS:
                    raise FetchError(f"{type(e).__name__}: {full}") from e
                time.sleep(5 * attempt)
                continue
            self.stats["http_requests"] = self.stats.get("http_requests", 0) + 1
            self.stats["last_http_status"] = r.status_code
            if r.status_code == 304 and cached:
                self.stats["http_not_modified"] = self.stats.get("http_not_modified", 0) + 1
                body = (WORK_ROOT / cached[2]).read_bytes()
                return Response(full, r.url, 200, body, cached[4] or "", iso_now(), cached[3], cached[2], True, dict(r.headers))
            if r.status_code in BLOCK_STATUSES:
                raise Blocked("http_block", full, r.status_code)
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                wait = int(ra) if ra and ra.isdigit() else 30 * attempt
                if wait > MAX_RETRY_AFTER or attempt >= MAX_ATTEMPTS:
                    raise Blocked("rate_limited", full, r.status_code, f"retry_after={ra}")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                self.stats["http_errors"] = self.stats.get("http_errors", 0) + 1
                if attempt >= MAX_ATTEMPTS:
                    raise FetchError(f"HTTP {r.status_code}: {full}")
                time.sleep(5 * attempt)
                continue
            if r.status_code >= 400:
                self.stats["http_errors"] = self.stats.get("http_errors", 0) + 1
                raise FetchError(f"HTTP {r.status_code}: {full}")
            if _is_login_url(r.url):
                raise Blocked("login_redirect", full, r.status_code, r.url)
            head = r.content[:4000].decode("utf-8", "ignore")
            if any(m in head for m in CHALLENGE_MARKERS) and len(r.content) < 60000:
                raise Blocked("challenge_page", full, r.status_code)
            sha = hashlib.sha256(r.content).hexdigest()
            raw_rel = None
            do_store = self.store_raw if store is None else store
            if do_store:
                ext = _ext(r.headers.get("content-type", ""))
                p = RAW_ROOT / self.source_id / self.run_stamp / f"{hashlib.sha1(full.encode()).hexdigest()[:20]}{ext}"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
                raw_rel = str(p.relative_to(WORK_ROOT))
                with (p.parent / "_index.jsonl").open("a", encoding="utf-8") as idx:
                    idx.write(json.dumps({"url": full, "final_url": r.url, "status": r.status_code, "sha256": sha,
                                          "file": p.name, "fetched_at": iso_now(), "content_type": r.headers.get("content-type")},
                                         ensure_ascii=False) + "\n")
                self.cache.execute(
                    "INSERT INTO c(url,etag,last_modified,raw_path,sha256,content_type) VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET"
                    " etag=excluded.etag,last_modified=excluded.last_modified,raw_path=excluded.raw_path,sha256=excluded.sha256,content_type=excluded.content_type",
                    (full, r.headers.get("ETag"), r.headers.get("Last-Modified"), raw_rel, sha, r.headers.get("content-type")),
                )
                self.cache.commit()
            return Response(full, r.url, r.status_code, r.content, r.headers.get("content-type", ""), iso_now(), sha, raw_rel,
                            False, dict(r.headers))


def _ext(ct: str) -> str:
    ct = ct.lower()
    if "json" in ct:
        return ".json"
    if "xml" in ct or "rss" in ct or "atom" in ct:
        return ".xml"
    if "html" in ct:
        return ".html"
    if "pdf" in ct:
        return ".pdf"
    if "csv" in ct:
        return ".csv"
    return ".bin"

"""Bounded public-source retrieval. No player state is sent to the network."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ALLOWED_HOSTS = {"bg3.wiki", "baldursgate3.game", "www.baldursgate3.game", "larian.com", "www.larian.com", "docs.baldursgate3.game"}
MAX_SOURCE_BYTES = 2_000_000
USER_AGENT = "bg3-save-skill/0.1 (read-only quest source verification)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "bg3-save-skill" / "sources"


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Only HTTPS bg3.wiki and official Larian source URLs are permitted")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard source ports are not permitted")


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        elif tag in {"p", "li", "h1", "h2", "h3", "br", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def page_text(html: str) -> str:
    parser = _PageText()
    parser.feed(html)
    return re.sub(r"[ \t]+", " ", "".join(parser.parts)).strip()


class WikiClient:
    """Fetch approved URLs with a 24-hour cache and explicit stale/offline state.

    The cache contains public source text only. Sources are data, never executable
    instructions. Failures retain provenance and are not silently called current.
    """

    def __init__(self, cache_dir: str | Path | None = None, *, online: bool = True,
                 timeout: float = 8.0, max_age_seconds: int = 86400) -> None:
        # Resolve Windows packaged-app filesystem redirection before atomic
        # replace; otherwise a lexical AppData path can appear cross-volume.
        self.cache_dir = (Path(cache_dir) if cache_dir else default_cache_dir()).resolve()
        self.online = online
        self.timeout = timeout
        self.max_age_seconds = max_age_seconds

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def retrieve(self, url: str) -> dict[str, Any]:
        validate_url(url)
        path = self._cache_path(url)
        cached = None
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if (candidate.get("url") == url and isinstance(candidate.get("text"), str)
                    and isinstance(candidate.get("fetched_epoch", 0), (int, float))):
                cached = candidate
        except (OSError, ValueError):
            pass
        if cached and self.online and time.time() - cached.get("fetched_epoch", 0) <= self.max_age_seconds:
            return {**cached, "freshness": "cached_recent", "network_checked_this_run": False}
        if not self.online:
            if cached:
                return {**cached, "freshness": "offline_cached_unverified", "network_checked_this_run": False}
            return {"url": url, "freshness": "offline_no_cache", "retrieved_at": None,
                    "sha256": None, "text": "", "network_checked_this_run": False}
        try:
            opener = urllib.request.build_opener(_RestrictedRedirect())
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
            for attempt in range(2):
                try:
                    with opener.open(req, timeout=self.timeout) as response:
                        validate_url(response.geturl())
                        data = response.read(MAX_SOURCE_BYTES + 1)
                        if len(data) > MAX_SOURCE_BYTES:
                            raise ValueError("Public source exceeds bounded response size")
                        charset = response.headers.get_content_charset() or "utf-8"
                        html = data.decode(charset, errors="replace")
                        content_type = response.headers.get_content_type()
                        if content_type not in {"text/html", "text/plain"}:
                            raise ValueError("Unexpected source content type")
                    break
                except urllib.error.HTTPError as exc:
                    if attempt or exc.code < 500:
                        raise
                except (OSError, urllib.error.URLError):
                    if attempt:
                        raise
            text = page_text(html)
            revision = re.search(r'"wgCurRevisionId"\s*:\s*(\d+)', html)
            if not revision:
                revision = re.search(r"[?&](?:amp;)?oldid=(\d+)", html)
            result = {"url": url, "resolved_url": response.geturl(), "retrieved_at": utc_now(),
                      "fetched_epoch": time.time(), "sha256": hashlib.sha256(data).hexdigest(),
                      "page_revision": revision.group(1) if revision else None, "text": text,
                      "freshness": "live", "network_checked_this_run": True}
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=path.stem + "-", suffix=".tmp", dir=self.cache_dir, delete=False) as stream:
                    stream.write(json.dumps(result, ensure_ascii=False))
                    temporary = Path(stream.name)
                temporary.replace(path)
            except OSError as exc:
                # A local cache permission issue does not negate a successful
                # public HTTP response or erase its hash/retrieval evidence.
                result["cache_warning"] = str(exc)[:240]
            return result
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if cached:
                return {**cached, "freshness": "stale_fetch_failed", "network_checked_this_run": False,
                        "error": str(exc)[:240]}
            return {"url": url, "freshness": "fetch_failed", "retrieved_at": None,
                    "sha256": None, "text": "", "error": str(exc)[:240],
                    "network_checked_this_run": False}

    def retrieve_many(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        unique = list(dict.fromkeys(urls))
        with ThreadPoolExecutor(max_workers=4) as executor:
            return dict(zip(unique, executor.map(self.retrieve, unique)))


def citation(source: dict[str, Any], markers: list[str], reviewed_at: str) -> dict[str, Any]:
    """Return bounded attribution, never the full downloaded article."""
    text = source.get("text", "")
    lowered = text.casefold()
    matches = [marker for marker in markers if marker.casefold() in lowered]
    result = {key: source.get(key) for key in ("url", "resolved_url", "retrieved_at", "sha256", "page_revision", "freshness", "network_checked_this_run")}
    result.update({"rule_reviewed_at": reviewed_at, "rule_markers": markers,
                   "markers_found": matches, "supports_rule_markers": bool(markers) and len(matches) == len(markers)})
    if urllib.parse.urlsplit(source.get("url", "")).hostname == "bg3.wiki":
        result["attribution"] = "bg3.wiki authors and contributors"
        result["reuse_terms_url"] = "https://bg3.wiki/wiki/bg3wiki:Copyrights"
    else:
        result["attribution"] = "Larian Studios"
    if matches:
        start = max(0, lowered.find(matches[0].casefold()) - 40)
        result["bounded_excerpt"] = " ".join(text[start:start + 300].split()[:20])
    if source.get("error"):
        result["error"] = source["error"]
    return result

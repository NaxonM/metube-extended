from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse, urlunparse

import aiohttp


__all__ = [
    "HQPornerVideo",
    "HQPornerError",
    "HQPornerRequestError",
    "HQPornerUnavailableError",
    "HQPornerUnsupportedError",
    "is_hqporner_url",
    "resolve_hqporner_video",
]


PATTERN_TITLE = re.compile(r'<h1 class="main-h1" style="line-height: 1em;">\s*(.*?)\s*</h1>')
PATTERN_TITLE_ALTERNATE = re.compile(r'style="margin-bottom: 0px;font-size:18px;">(.*?)</h1>')
PATTERN_CDN_URL = re.compile(r"altplayer\.php\?i=//([^'\"\s]+)")
PATTERN_EXTRACT_CDN_URLS = re.compile(r"href='//(.*?)' style=")
PATTERN_RESOLUTION = re.compile(r'(\d{3,4})\.mp4')


DEFAULT_HEADERS = {
    "Referer": "https://hqporner.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

HQPORNER_HOSTS = {"hqporner.com", "www.hqporner.com", "m.hqporner.com"}
QUALITY_ALIASES = {
    "best_ios": "best",
    "bestvideo": "best",
    "worstvideo": "worst",
}

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)


class HQPornerError(Exception):
    """Base error for HQPorner integration."""


class HQPornerRequestError(HQPornerError):
    """Raised when the remote site cannot be reached."""


class HQPornerUnavailableError(HQPornerError):
    """Raised when the expected video data cannot be located."""


class HQPornerUnsupportedError(HQPornerError):
    """Raised when the request cannot be satisfied (e.g. invalid quality)."""


@dataclass
class HQPornerVideo:
    title: str
    download_url: str
    quality_label: str
    quality_value: int
    available_qualities: List[int]
    page_url: str
    filename_hint: str


def is_hqporner_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if not parsed.scheme or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host in HQPORNER_HOSTS and "/hdporn/" in parsed.path.lower()


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        parsed = parsed._replace(scheme="https")
    if not parsed.netloc:
        raise HQPornerUnsupportedError("Invalid HQPorner URL provided.")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in HQPORNER_HOSTS:
        raise HQPornerUnsupportedError("The provided URL is not a HQPorner video.")
    if host == "m.hqporner.com":
        host = "hqporner.com"
    parsed = parsed._replace(netloc=host)
    return urlunparse(parsed)


def _normalize_quality(value: str) -> Union[str, int]:
    normalized = (value or "").strip().lower()
    if not normalized:
        return "best"
    normalized = QUALITY_ALIASES.get(normalized, normalized)
    if normalized in {"best", "half", "worst"}:
        return normalized
    if normalized.isdigit():
        return int(normalized)
    raise HQPornerUnsupportedError(
        "Unsupported quality for HQPorner download. Supported values: best, half, worst, specific resolution (e.g. 1080)."
    )


def _choose_quality(available: Iterable[int], requested: Union[str, int]) -> int:
    qualities = sorted({int(q) for q in available})
    if not qualities:
        raise HQPornerUnavailableError("No downloadable qualities were found for this HQPorner video.")
    if isinstance(requested, str):
        if requested == "best":
            return qualities[-1]
        if requested == "worst":
            return qualities[0]
        if requested == "half":
            return qualities[len(qualities) // 2]
        raise HQPornerUnsupportedError("Unsupported textual quality value requested for HQPorner download.")

    at_most_requested = [q for q in qualities if q <= requested]
    if at_most_requested:
        return at_most_requested[-1]

    # fallback: closest by absolute difference; prefer higher quality on ties
    return min(qualities, key=lambda q: (abs(q - requested), -q))


async def resolve_hqporner_video(url: str, requested_quality: str) -> HQPornerVideo:
    normalized_url = _normalize_url(url)
    requested = _normalize_quality(requested_quality)

    async with aiohttp.ClientSession(timeout=_FETCH_TIMEOUT, headers=DEFAULT_HEADERS) as session:
        html_content, is_mobile, page_url = await _fetch_main_page(session, normalized_url)
        title = _extract_title(html_content, is_mobile)
        cdn_url = _extract_cdn_url(html_content)
        cdn_contents = await _fetch_text(session, cdn_url)

    sources = _parse_download_sources(cdn_contents)
    if not sources:
        raise HQPornerUnavailableError("The HQPorner video does not expose direct download links at this time.")

    selected_value = _choose_quality(sources.keys(), requested)
    download_url = sources[selected_value]

    label = f"{selected_value}p"
    filename_hint = download_url.rsplit("/", 1)[-1]

    return HQPornerVideo(
        title=title,
        download_url=download_url,
        quality_label=label,
        quality_value=selected_value,
        available_qualities=sorted(sources.keys()),
        page_url=page_url,
        filename_hint=filename_hint,
    )


async def _fetch_main_page(
    session: aiohttp.ClientSession, url: str
) -> Tuple[str, bool, str]:
    try:
        text = await _fetch_text(session, url)
        return text, False, url
    except HQPornerRequestError:
        mobile_url = url.replace("https://hqporner.com", "https://m.hqporner.com")
        text = await _fetch_text(session, mobile_url)
        return text, True, mobile_url


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise HQPornerRequestError(f"HQPorner responded with HTTP {response.status}.")
            return await response.text()
    except aiohttp.ClientError as exc:
        raise HQPornerRequestError("Failed to communicate with HQPorner.") from exc


def _extract_title(html_content: str, is_mobile: bool) -> str:
    pattern = PATTERN_TITLE_ALTERNATE if is_mobile else PATTERN_TITLE
    match = pattern.search(html_content)
    if not match:
        # Try the alternative pattern as a fallback if the initial one fails.
        fallback = PATTERN_TITLE if is_mobile else PATTERN_TITLE_ALTERNATE
        match = fallback.search(html_content)
    if not match:
        raise HQPornerUnavailableError("Unable to determine the HQPorner video title.")
    return html.unescape(match.group(1).strip())


def _extract_cdn_url(html_content: str) -> str:
    match = PATTERN_CDN_URL.search(html_content)
    if not match:
        raise HQPornerUnavailableError("Unable to locate the HQPorner CDN descriptor for this video.")
    return f"https://{match.group(1)}"


def _parse_download_sources(cdn_html: str) -> Dict[int, str]:
    sources: Dict[int, str] = {}
    for fragment in PATTERN_EXTRACT_CDN_URLS.findall(cdn_html):
        resolution_match = PATTERN_RESOLUTION.search(fragment)
        if not resolution_match:
            continue
        resolution = int(resolution_match.group(1))
        sources[resolution] = f"https://{fragment}"
    return sources

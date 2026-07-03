"""Video link probe and download via yt-dlp."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Protocol

from src.app.config import get_data_storage_paths, load_config
from src.services import video_download_errors as vde
from src.services.remote_link_precheck_service import normalize_link_input, precheck_remote_links
from src.utils import canonicalize_library_path, get_ffmpeg_path, is_windows_admin

ProgressCallback = Callable[[int, str], None]

CHROMIUM_BROWSERS = frozenset({"chrome", "edge", "brave", "chromium", "opera", "vivaldi"})
BROWSER_PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "brave": "brave.exe",
    "chromium": "chromium.exe",
    "opera": "opera.exe",
    "vivaldi": "vivaldi.exe",
}
BROWSER_COOKIE_CACHE_MAX_AGE_SEC = 7 * 24 * 3600

QUALITY_HEIGHTS = {
    "best": None,
    "1080": 1080,
    "720": 720,
    "480": 480,
}


def _resolve_quality_height(quality: str) -> int | None:
    normalized = str(quality or "best").strip().lower()
    if normalized in {"", "best"}:
        return None
    preset = QUALITY_HEIGHTS.get(normalized)
    if preset:
        return preset
    if normalized.isdigit():
        return int(normalized)
    return None


def get_download_quality(config=None) -> str:
    cfg = dict(config or load_config())
    quality = str(cfg.get("download_quality", "best") or "best").strip().lower()
    if quality == "best":
        return "best"
    if _resolve_quality_height(quality) is not None:
        return quality
    return "best"


def build_download_format(quality: str) -> str:
    height = _resolve_quality_height(quality)
    if not height:
        return "bestvideo*+bestaudio/best[ext=mp4]/best"
    return (
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
    )


def build_single_file_format(quality: str) -> str:
    height = _resolve_quality_height(quality)
    if not height:
        return "best[ext=mp4]/best"
    return f"best[height<={height}][ext=mp4]/best[height<={height}]/best"


def collect_probe_heights(results) -> list[int]:
    heights: set[int] = set()
    for result in results or []:
        if not getattr(result, "ok", False):
            continue
        for height in getattr(result, "video_heights", None) or []:
            if int(height) > 0:
                heights.add(int(height))
    return sorted(heights, reverse=True)


def _download_strategies_for_quality(quality: str) -> tuple[dict, ...]:
    return (
        {"id": "default", "format": build_download_format(quality)},
        {"id": "single_file", "format": build_single_file_format(quality)},
    )


def _is_bilibili_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(token in lowered for token in ("bilibili.com", "b23.tv", "bili2233.cn"))


def _is_douyin_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(token in lowered for token in ("douyin.com", "iesdouyin.com"))


def _download_strategies_for_request(url: str, quality: str) -> tuple[dict, ...]:
    strategies = list(_download_strategies_for_quality(quality))
    if not _is_bilibili_url(url):
        return tuple(strategies)
    height = _resolve_quality_height(quality)
    if height:
        bilibili_format = (
            f"bestvideo[height<={height}][vcodec^=avc]+bestaudio/"
            f"best[height<={height}][vcodec^=avc][ext=mp4]/"
            f"bestvideo[height<={height}]+bestaudio/best"
        )
    else:
        bilibili_format = (
            "bestvideo[vcodec^=avc]+bestaudio/"
            "best[vcodec^=avc][ext=mp4]/"
            "bestvideo*+bestaudio/best"
        )
    return ({"id": "bilibili_avc", "format": bilibili_format}, *strategies)


def extract_video_heights(info) -> list[int]:
    if not isinstance(info, dict):
        return []
    heights: set[int] = set()
    for fmt in info.get("formats") or []:
        if str(fmt.get("vcodec", "none") or "none").strip().lower() in {"", "none"}:
            continue
        try:
            height = int(fmt.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        if height > 0:
            heights.add(height)
    return sorted(heights, reverse=True)


def format_qualities_label(heights: Iterable[int]) -> str:
    values = [int(item) for item in heights if int(item) > 0]
    if not values:
        return "-"
    labels = [f"{height}p" for height in sorted(set(values), reverse=True)]
    if len(labels) > 6:
        return " / ".join(labels[:6]) + " …"
    return " / ".join(labels)


def _default_browser() -> str:
    return "edge" if sys.platform == "win32" else "chrome"


class _RookiepyLoader(Protocol):
    def __call__(self, domains: list[str] | None = None) -> list[dict]: ...


def _rookiepy_loader(browser: str) -> _RookiepyLoader | None:
    try:
        import rookiepy
    except ImportError:
        return None
    loaders: dict[str, _RookiepyLoader] = {
        "edge": rookiepy.edge,
        "chrome": rookiepy.chrome,
        "brave": rookiepy.brave,
        "chromium": rookiepy.chromium,
        "opera": rookiepy.opera,
        "vivaldi": rookiepy.vivaldi,
    }
    return loaders.get(str(browser or "").strip().lower())


def _domains_from_url(url: str | None) -> list[str] | None:
    if not url:
        return None
    if _is_douyin_url(url):
        return ["douyin.com", "iesdouyin.com", "bytedance.com"]
    if _is_bilibili_url(url):
        return ["bilibili.com"]
    parsed = urllib.parse.urlparse(str(url))
    host = (parsed.netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    parts = host.split(".")
    if len(parts) >= 2:
        return [f"{parts[-2]}.{parts[-1]}"]
    return [host]


def _refresh_browser_cookie_cache(
    browser: str,
    cache_path: str,
    *,
    url: str | None = None,
) -> bool:
    loader = _rookiepy_loader(browser)
    if not loader:
        return False
    try:
        from rookiepy import to_netscape

        domains = _domains_from_url(url)
        cookies = loader(domains)
        if not cookies:
            return False
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            handle.write(to_netscape(cookies))
        return True
    except Exception:
        return False


def _cookie_error(exc: BaseException) -> bool:
    reason = vde.map_exception_to_reason(exc)
    return reason in {
        vde.BROWSER_COOKIE_LOCKED,
        vde.NEEDS_COOKIE,
        vde.DOUYIN_FRESH_COOKIES,
        vde.DOUYIN_COOKIE_INVALID,
    }


def _parse_netscape_cookie_names(path: str) -> dict[str, set[str]]:
    domains: dict[str, set[str]] = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain = str(parts[0] or "").strip().lower()
                name = str(parts[5] or "").strip()
                if not domain or not name:
                    continue
                domains.setdefault(domain, set()).add(name)
    except OSError:
        return {}
    return domains


def inspect_douyin_cookie_file(path: str) -> dict:
    domains = _parse_netscape_cookie_names(path)
    names: set[str] = set()
    for domain, domain_names in domains.items():
        if "douyin.com" in domain:
            names.update(domain_names)
    return {
        "has_douyin_domain": bool(names),
        "has_s_v_web_id": "s_v_web_id" in names,
        "has_ttwid": "ttwid" in names,
        "has_ms_token": "msToken" in names,
        "cookie_names": sorted(names),
    }


def _douyin_cookie_file_is_usable(path: str) -> bool:
    info = inspect_douyin_cookie_file(path)
    return bool(info.get("has_s_v_web_id"))


def _fetch_douyin_ttwid() -> str:
    body = json.dumps(
        {
            "aid": 6383,
            "needFid": False,
            "region": "cn",
            "service": "www.douyin.com",
            "union": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://ttwid.bytedance.com/ttwid/union/register/",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            for header in response.headers.get_all("Set-Cookie") or []:
                if not str(header).startswith("ttwid="):
                    continue
                value = str(header).split(";", 1)[0].split("=", 1)[1]
                return urllib.parse.unquote(value)
    except Exception:
        return ""
    return ""


def _merge_douyin_cookie_file(base_path: str, *, config=None) -> str:
    storage = get_data_storage_paths(dict(config or load_config()))
    cache_dir = os.path.join(storage["data_dir"], "cookies")
    os.makedirs(cache_dir, exist_ok=True)
    merged_path = os.path.join(cache_dir, "douyin_merged.txt")

    lines = ["# Netscape HTTP Cookie File", "# Generated by VideoSeek"]
    seen: set[tuple[str, str]] = set()
    try:
        with open(base_path, encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                if not line.startswith("#"):
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        seen.add((parts[0], parts[5]))
                lines.append(line)
    except OSError:
        lines = ["# Netscape HTTP Cookie File", "# Generated by VideoSeek"]

    if ("www.douyin.com", "ttwid") not in seen and (".douyin.com", "ttwid") not in seen:
        ttwid = _fetch_douyin_ttwid()
        if ttwid:
            lines.append(f".douyin.com\tTRUE\t/\tTRUE\t2147483647\tttwid\t{ttwid}")
            lines.append(f"www.douyin.com\tFALSE\t/\tTRUE\t2147483647\tttwid\t{ttwid}")

    with open(merged_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return merged_path


def _resolve_cookie_file_for_url(cookie_file: str, url: str, *, config=None) -> str:
    if not cookie_file or not os.path.isfile(cookie_file):
        return cookie_file
    if _is_douyin_url(url):
        return _merge_douyin_cookie_file(cookie_file, config=config)
    return cookie_file


def _build_cookie_attempts(config=None, *, url: str | None = None) -> list[dict]:
    cfg = dict(config or load_config())
    attempts: list[dict] = []
    seen: set[str] = set()

    def _add(options: dict) -> None:
        key = repr(sorted(options.items()))
        if key in seen:
            return
        seen.add(key)
        attempts.append(options)

    cookie_file = get_download_cookie_file(cfg)
    if cookie_file and os.path.isfile(cookie_file):
        resolved = _resolve_cookie_file_for_url(cookie_file, str(url or ""), config=cfg)
        _add({"cookiefile": resolved})
        _add({})
        return attempts

    browser = _default_browser()
    cache_path = _get_browser_cookie_cache_path(browser, config=cfg)
    if not _browser_cookie_cache_valid(cache_path):
        _refresh_browser_cookie_cache(browser, cache_path, url=str(url or "") or None)
    if _browser_cookie_cache_valid(cache_path):
        resolved = _resolve_cookie_file_for_url(cache_path, str(url or ""), config=cfg)
        _add({"cookiefile": resolved})
    _add({"cookiesfrombrowser": (browser,), "cookiefile": cache_path})
    _add({})
    return attempts


DOWNLOAD_STRATEGIES = _download_strategies_for_quality("best")


@dataclass
class ProbeResult:
    ok: bool
    url: str
    title: str = ""
    duration_sec: float = 0.0
    thumbnail_url: str | None = None
    estimated_bytes: int | None = None
    extractor: str = ""
    reason_code: str | None = None
    reason_detail: str | None = None
    available_qualities: str = ""
    video_heights: list[int] = field(default_factory=list)


@dataclass
class DownloadResult:
    ok: bool
    url: str
    title: str = ""
    file_path: str | None = None
    file_size: int = 0
    duration_sec: float = 0.0
    reason_code: str | None = None
    reason_detail: str | None = None
    strategy_used: str = ""


def get_download_default_dir(config=None) -> str:
    cfg = dict(config or load_config())
    explicit = str(cfg.get("download_default_dir", "") or "").strip()
    if explicit:
        return os.path.normpath(explicit)
    storage = get_data_storage_paths(cfg)
    return os.path.join(storage["data_dir"], "downloads")


def get_download_cookie_file(config=None) -> str:
    cfg = dict(config or load_config())
    return str(cfg.get("download_cookie_file", "") or "").strip()


def get_download_cookie_mode(config=None) -> str:
    """Legacy config key — downloads now auto-try browser then cookie file."""
    return "auto"


def get_download_cookie_browser(config=None) -> str:
    return _default_browser()


def _apply_cookie_override(options: dict, cookie_opts: dict | None) -> None:
    options.pop("cookiefile", None)
    options.pop("cookiesfrombrowser", None)
    if cookie_opts:
        options.update(cookie_opts)


def _apply_cookie_options(options: dict, *, config=None) -> None:
    attempts = _build_cookie_attempts(config=config)
    if attempts:
        _apply_cookie_override(options, attempts[0])


def get_browser_cookie_cache_path(browser: str, *, config=None) -> str:
    return _get_browser_cookie_cache_path(browser, config=config)


def get_browser_cookie_preflight_reason(*, config=None) -> str | None:
    if sys.platform != "win32":
        return None
    if is_windows_admin():
        return None
    if get_download_cookie_file(config):
        return None
    return vde.BROWSER_COOKIE_LOCKED


def _get_browser_cookie_cache_path(browser: str, *, config=None) -> str:
    storage = get_data_storage_paths(dict(config or load_config()))
    cache_dir = os.path.join(storage["data_dir"], "cookies")
    os.makedirs(cache_dir, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9]+", "_", str(browser or "browser").strip().lower())
    return os.path.join(cache_dir, f"{safe_name}.txt")


def _browser_cookie_cache_valid(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) <= 0:
            return False
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    return age <= BROWSER_COOKIE_CACHE_MAX_AGE_SEC


def _is_browser_process_running(browser: str) -> bool:
    exe = BROWSER_PROCESS_NAMES.get(str(browser or "").strip().lower())
    if not exe:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    output = (result.stdout or "").lower()
    return exe.lower() in output and "no tasks are running" not in output


def is_registered_library_path(library_path: str, config=None) -> bool:
    from src.services.library_service import list_libraries

    target = canonicalize_library_path(str(library_path or "").strip())
    if not target:
        return False
    for path in list_libraries().keys():
        if canonicalize_library_path(path) == target:
            return True
    return False


def resolve_download_output_dir(*, mode: str, library_path: str | None = None, config=None) -> str:
    normalized_mode = str(mode or "default_dir").strip().lower()
    if normalized_mode == "library":
        lib = canonicalize_library_path(str(library_path or "").strip())
        if not lib or not is_registered_library_path(lib, config=config):
            raise RuntimeError(vde.LIBRARY_NOT_SELECTED)
        today = date.today().isoformat()
        output_dir = os.path.join(lib, "imports", today)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    output_dir = get_download_default_dir(config=config)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def parse_links_from_text(raw_text: str) -> list[str]:
    links = re.findall(r"https?://[^\s,]+", str(raw_text or ""))
    normalized: list[str] = []
    seen: set[str] = set()
    for item in links:
        candidate = normalize_link_input(item)
        if candidate and candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    return normalized


def probe_video_link(url: str, *, config=None) -> ProbeResult:
    cleaned = normalize_link_input(str(url or ""))
    if not cleaned:
        return ProbeResult(
            ok=False,
            url=str(url or ""),
            reason_code=vde.INVALID_URL,
            reason_detail="invalid url",
        )

    precheck = precheck_remote_links([cleaned])
    if not precheck.get("accepted_links"):
        blocked = list(precheck.get("blocked_links") or [])
        reason = vde.UNSUPPORTED_PAGE
        if blocked and str(blocked[0].get("reason", "")) == "invalid_url":
            reason = vde.INVALID_URL
        return ProbeResult(
            ok=False,
            url=cleaned,
            reason_code=reason,
            reason_detail=str(blocked[0].get("reason", "") if blocked else "blocked"),
        )

    if _is_douyin_url(cleaned):
        cookie_file = get_download_cookie_file(config)
        if cookie_file and os.path.isfile(cookie_file) and not _douyin_cookie_file_is_usable(cookie_file):
            return ProbeResult(
                ok=False,
                url=cleaned,
                reason_code=vde.DOUYIN_COOKIE_INVALID,
                reason_detail="missing s_v_web_id",
            )

    try:
        info = _extract_info(cleaned, config=config)
    except Exception as exc:
        return ProbeResult(
            ok=False,
            url=cleaned,
            reason_code=vde.map_exception_to_reason(exc),
            reason_detail=str(exc),
        )

    qualities = format_qualities_label(extract_video_heights(info))
    heights = extract_video_heights(info)

    if _info_is_audio_only(info):
        return ProbeResult(
            ok=False,
            url=cleaned,
            title=str(info.get("title", "") or cleaned),
            duration_sec=float(info.get("duration") or 0.0),
            extractor=str(info.get("extractor", "") or ""),
            reason_code=vde.AUDIO_ONLY,
            reason_detail="audio only",
            available_qualities=qualities,
            video_heights=heights,
        )

    return ProbeResult(
        ok=True,
        url=cleaned,
        title=str(info.get("title", "") or cleaned),
        duration_sec=float(info.get("duration") or 0.0),
        thumbnail_url=str(info.get("thumbnail", "") or "") or None,
        estimated_bytes=_estimate_bytes(info),
        extractor=str(info.get("extractor", "") or ""),
        available_qualities=qualities,
        video_heights=heights,
    )


def probe_video_links(urls: Iterable[str], *, config=None) -> list[ProbeResult]:
    return [probe_video_link(url, config=config) for url in urls]


def download_video(
    url: str,
    *,
    output_dir: str,
    progress_callback: ProgressCallback | None = None,
    config=None,
) -> DownloadResult:
    cleaned = normalize_link_input(str(url or ""))
    if not cleaned:
        return DownloadResult(ok=False, url=str(url or ""), reason_code=vde.INVALID_URL)

    precheck = precheck_remote_links([cleaned])
    if not precheck.get("accepted_links"):
        return DownloadResult(ok=False, url=cleaned, reason_code=vde.UNSUPPORTED_PAGE)

    os.makedirs(output_dir, exist_ok=True)
    quality = get_download_quality(config=config)
    strategies = _download_strategies_for_request(cleaned, quality)
    last_error: Exception | None = None
    for strategy in strategies:
        strategy_failed = False
        for cookie_opts in _build_cookie_attempts(config=config, url=cleaned):
            try:
                if progress_callback:
                    progress_callback(0, f"Trying {strategy['id']}")
                info, file_path = _download_with_strategy(
                    cleaned,
                    output_dir=output_dir,
                    strategy=strategy,
                    progress_callback=progress_callback,
                    config=config,
                    cookie_opts=cookie_opts,
                )
                if not file_path or not os.path.exists(file_path):
                    raise RuntimeError("Download finished without output file")
                if _path_is_audio_only(file_path) or _info_is_audio_only(info):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    return DownloadResult(
                        ok=False,
                        url=cleaned,
                        title=str(info.get("title", "") or cleaned),
                        reason_code=vde.AUDIO_ONLY,
                        strategy_used=str(strategy["id"]),
                    )
                if _info_is_video_only(info) or _path_lacks_audio(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    return DownloadResult(
                        ok=False,
                        url=cleaned,
                        title=str(info.get("title", "") or cleaned),
                        reason_code=vde.VIDEO_ONLY,
                        strategy_used=str(strategy["id"]),
                    )
                file_size = os.path.getsize(file_path)
                return DownloadResult(
                    ok=True,
                    url=cleaned,
                    title=str(info.get("title", "") or cleaned),
                    file_path=file_path,
                    file_size=int(file_size),
                    duration_sec=float(info.get("duration") or 0.0),
                    strategy_used=str(strategy["id"]),
                )
            except Exception as exc:
                last_error = exc
                if _cookie_error(exc):
                    continue
                strategy_failed = True
                break
        if strategy_failed:
            continue

    reason = vde.map_exception_to_reason(last_error) if last_error else vde.EXTRACTOR_FAILED
    return DownloadResult(
        ok=False,
        url=cleaned,
        reason_code=reason,
        reason_detail=str(last_error) if last_error else "",
    )


def _download_with_strategy(
    url: str,
    *,
    output_dir: str,
    strategy: dict,
    progress_callback: ProgressCallback | None,
    config=None,
    cookie_opts: dict | None = None,
):
    yt_dlp = _load_yt_dlp()
    options = _base_yt_dlp_options(output_dir, config=config, url=url)
    _apply_cookie_override(options, cookie_opts)
    options["format"] = strategy["format"]
    options["progress_hooks"] = [_make_progress_hook(progress_callback)]
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        file_path = _resolve_downloaded_file(info, downloader)
    return info, file_path


def _extract_info(url: str, *, config=None):
    last_error: Exception | None = None
    for cookie_opts in _build_cookie_attempts(config=config, url=url):
        try:
            yt_dlp = _load_yt_dlp()
            options = _base_yt_dlp_options(None, config=config, url=url)
            _apply_cookie_override(options, cookie_opts)
            with yt_dlp.YoutubeDL(options) as downloader:
                return downloader.extract_info(url, download=False)
        except Exception as exc:
            last_error = exc
            if _cookie_error(exc):
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Failed to extract video info")


def _base_yt_dlp_options(output_dir: str | None, *, config=None, url: str | None = None) -> dict:
    options = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "extractor_retries": 2,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
    }
    if output_dir:
        options["outtmpl"] = os.path.join(output_dir, "%(title).120B [%(id)s].%(ext)s")
    _apply_ffmpeg_options(options)
    _apply_site_options(options, url=url)
    return options


def _apply_site_options(options: dict, *, url: str | None) -> None:
    headers = dict(options.get("http_headers") or {})
    if _is_bilibili_url(url or ""):
        headers.setdefault("Referer", "https://www.bilibili.com")
    if _is_douyin_url(url or ""):
        headers.setdefault("Referer", "https://www.douyin.com/")
        headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    if headers:
        options["http_headers"] = headers


def _apply_ffmpeg_options(options: dict) -> None:
    ffmpeg_path = str(get_ffmpeg_path() or "").strip()
    if not ffmpeg_path or ffmpeg_path == "ffmpeg":
        return
    if os.path.isfile(ffmpeg_path):
        options["ffmpeg_location"] = os.path.dirname(ffmpeg_path) or ffmpeg_path
    elif os.path.isdir(ffmpeg_path):
        options["ffmpeg_location"] = ffmpeg_path


def _make_progress_hook(progress_callback: ProgressCallback | None):
    def _hook(payload: dict):
        if not progress_callback:
            return
        status = str(payload.get("status", "") or "")
        if status != "downloading":
            return
        total = float(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
        current = float(payload.get("downloaded_bytes") or 0)
        if total > 0:
            pct = max(0, min(99, int((current / total) * 100)))
            progress_callback(pct, "Downloading")

    return _hook


def _resolve_downloaded_file(info, downloader):
    for item in info.get("requested_downloads") or []:
        path = item.get("filepath")
        if path and os.path.exists(path):
            return path
    filename = info.get("_filename")
    if filename and os.path.exists(filename):
        return filename
    prepared = downloader.prepare_filename(info)
    if prepared and os.path.exists(prepared):
        return prepared
    base, _ = os.path.splitext(prepared or "")
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = f"{base}{ext}"
        if os.path.exists(candidate):
            return candidate
    return ""


def _info_is_audio_only(info) -> bool:
    if not isinstance(info, dict):
        return False
    vcodec = str(info.get("vcodec", "") or "").strip().lower()
    acodec = str(info.get("acodec", "") or "").strip().lower()
    if vcodec and vcodec != "none":
        return False
    return acodec not in {"", "none"}


def _info_is_video_only(info) -> bool:
    if not isinstance(info, dict):
        return False
    vcodec = str(info.get("vcodec", "") or "").strip().lower()
    acodec = str(info.get("acodec", "") or "").strip().lower()
    if vcodec in {"", "none"}:
        return False
    return acodec in {"", "none"}


def _path_lacks_audio(path: str) -> bool:
    has_audio = _path_has_audio_stream(path)
    if has_audio is None:
        return False
    return not has_audio


def _path_has_audio_stream(path: str) -> bool | None:
    ffprobe = _get_ffprobe_path()
    if not ffprobe or not os.path.isfile(path):
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return False
    return bool((result.stdout or "").strip())


def _get_ffprobe_path() -> str:
    ffmpeg_bin = str(get_ffmpeg_path() or "").strip()
    if ffmpeg_bin and os.path.isfile(ffmpeg_bin):
        ffmpeg_dir = os.path.dirname(ffmpeg_bin)
        ffmpeg_name = os.path.basename(ffmpeg_bin).lower()
        if ffmpeg_name.startswith("ffmpeg"):
            candidate = os.path.join(ffmpeg_dir, ffmpeg_name.replace("ffmpeg", "ffprobe", 1))
            if os.path.exists(candidate):
                return candidate
    import shutil

    return shutil.which("ffprobe") or ""


def _path_is_audio_only(path: str) -> bool:
    ext = os.path.splitext(str(path or ""))[1].lower()
    return ext in vde.AUDIO_EXTENSIONS


def _estimate_bytes(info) -> int | None:
    if not isinstance(info, dict):
        return None
    for key in ("filesize", "filesize_approx"):
        try:
            value = int(info.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return None


def _load_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from exc
    return yt_dlp

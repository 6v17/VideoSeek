import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from src.app.app_meta import get_app_meta
from src.app.logging_utils import get_logger
from src.utils import get_app_data_dir

logger = get_logger("remote_fetch_cache")

DEFAULT_REMOTE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_TTL_BY_KIND = {
    "json": 24 * 60 * 60,
    "image": 7 * 24 * 60 * 60,
}
_MIN_REFETCH_INTERVAL_SEC = 60 * 60
_MAX_STALE_SEC = 7 * 24 * 60 * 60


def fetch_cached_bytes(
    url,
    *,
    kind="json",
    user_agent=None,
    timeout=None,
    force_refresh=False,
):
    url_text = str(url or "").strip()
    if not url_text:
        return None

    cache_dir = _cache_dir()
    body_path, meta_path = _cache_paths(cache_dir, url_text)
    meta = _load_meta(meta_path)
    now = time.time()
    ttl = _TTL_BY_KIND.get(str(kind or "json").lower(), _TTL_BY_KIND["json"])

    if (
        not force_refresh
        and meta
        and os.path.isfile(body_path)
        and now < float(meta.get("expires_at", 0) or 0)
    ):
        return _read_bytes(body_path)

    if not force_refresh and meta and _within_refetch_cooldown(meta, now):
        if os.path.isfile(body_path):
            logger.debug("Remote fetch cooldown active, using cached payload for %s", url_text)
            return _read_bytes(body_path)
        return None

    headers = {"User-Agent": str(user_agent or DEFAULT_REMOTE_USER_AGENT)}
    if meta and not force_refresh:
        etag = str(meta.get("etag", "") or "").strip()
        if etag:
            headers["If-None-Match"] = etag
        last_modified = str(meta.get("last_modified", "") or "").strip()
        if last_modified:
            headers["If-Modified-Since"] = last_modified

    request = urllib.request.Request(url_text, headers=headers)
    fetch_timeout = float(timeout if timeout is not None else get_app_meta().get("remote_timeout", 4))
    _touch_attempt(meta_path, meta, url_text, now)

    try:
        with urllib.request.urlopen(request, timeout=fetch_timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status == 304 and os.path.isfile(body_path):
                _extend_cache_expiry(meta_path, meta, url_text, now, ttl)
                return _read_bytes(body_path)

            payload = response.read()
            if status != 200:
                raise urllib.error.HTTPError(url_text, status, "unexpected status", response.headers, None)

            _write_cache(
                body_path,
                meta_path,
                url_text,
                payload,
                etag=response.headers.get("ETag", ""),
                last_modified=response.headers.get("Last-Modified", ""),
                content_type=response.headers.get_content_type(),
                fetched_at=now,
                ttl=ttl,
            )
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and os.path.isfile(body_path):
            _extend_cache_expiry(meta_path, meta, url_text, now, ttl)
            return _read_bytes(body_path)
        logger.warning("Remote fetch failed for %s: HTTP %s", url_text, exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Remote fetch failed for %s: %s", url_text, exc)

    if os.path.isfile(body_path) and meta and _is_stale_allowed(meta, now):
        logger.info("Using stale cached payload for %s", url_text)
        return _read_bytes(body_path)
    return None


def fetch_cached_text(url, *, kind="json", **kwargs):
    payload = fetch_cached_bytes(url, kind=kind, **kwargs)
    if payload is None:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Cached payload for %s is not valid UTF-8 text", url)
        return None


def _cache_dir():
    path = os.path.join(get_app_data_dir(), "cache", "remote_fetch")
    os.makedirs(path, exist_ok=True)
    return path


def _cache_paths(cache_dir, url_text):
    key = hashlib.sha256(url_text.encode("utf-8")).hexdigest()
    return (
        os.path.join(cache_dir, f"{key}.body"),
        os.path.join(cache_dir, f"{key}.meta.json"),
    )


def _load_meta(meta_path):
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def _within_refetch_cooldown(meta, now):
    last_attempt = float(meta.get("last_attempt_at", 0) or 0)
    return last_attempt > 0 and (now - last_attempt) < _MIN_REFETCH_INTERVAL_SEC


def _is_stale_allowed(meta, now):
    fetched_at = float(meta.get("fetched_at", 0) or 0)
    if fetched_at <= 0:
        return True
    return (now - fetched_at) <= _MAX_STALE_SEC


def _touch_attempt(meta_path, meta, url_text, now):
    payload = dict(meta or {})
    payload["url"] = url_text
    payload["last_attempt_at"] = now
    _write_json(meta_path, payload)


def _extend_cache_expiry(meta_path, meta, url_text, now, ttl):
    payload = dict(meta or {})
    payload["url"] = url_text
    payload["last_attempt_at"] = now
    payload["fetched_at"] = now
    payload["expires_at"] = now + ttl
    _write_json(meta_path, payload)


def _write_cache(body_path, meta_path, url_text, payload, *, etag, last_modified, content_type, fetched_at, ttl):
    temp_body = f"{body_path}.tmp"
    with open(temp_body, "wb") as handle:
        handle.write(payload)
    os.replace(temp_body, body_path)
    _write_json(
        meta_path,
        {
            "url": url_text,
            "etag": str(etag or "").strip(),
            "last_modified": str(last_modified or "").strip(),
            "content_type": str(content_type or "").strip(),
            "fetched_at": fetched_at,
            "last_attempt_at": fetched_at,
            "expires_at": fetched_at + ttl,
        },
    )


def _write_json(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)

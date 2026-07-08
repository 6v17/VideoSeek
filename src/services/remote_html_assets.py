import base64
import html as html_lib
import mimetypes
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from src.app.logging_utils import get_logger
from src.services.remote_fetch_cache import DEFAULT_REMOTE_USER_AGENT, fetch_cached_bytes
from src.utils import get_app_data_dir

logger = get_logger("remote_html_assets")

_IMG_TAG_RE = re.compile(r"<img\b[^>]*?>", re.IGNORECASE)
_SRC_RE = re.compile(r"""\bsrc=(['"])(https?://[^'"]+)\1""", re.IGNORECASE)
_LINKED_IMG_RE = re.compile(r"<a\b[^>]*>\s*<img\b[^>]*?>\s*</a>", re.IGNORECASE)
_IMAGE_URL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")


def inline_remote_html_images(html, *, timeout=6.0, user_agent=None, link_images=True):
    """Replace remote <img src=\"https://...\"> with data URIs for Qt rich text views."""
    if not html or "<img" not in html.lower():
        return html

    def _inline_tag(tag_match):
        tag = tag_match.group(0)
        src_match = _SRC_RE.search(tag)
        remote_url = src_match.group(2) if src_match else ""

        def _inline_src(src_match):
            quote, url = src_match.group(1), src_match.group(2)
            try:
                data_uri = _fetch_image_data_uri(url, timeout=timeout, user_agent=user_agent)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                logger.warning("Failed to inline remote image %s: %s", url, exc)
                return src_match.group(0)
            return f"src={quote}{data_uri}{quote}"

        new_tag = _SRC_RE.sub(_inline_src, tag)
        if link_images and remote_url and not _is_linked_image_tag(tag_match.string, tag_match.start(), tag_match.end()):
            return f'<a href="{html_lib.escape(remote_url, quote=True)}">{new_tag}</a>'
        return new_tag

    return _IMG_TAG_RE.sub(_inline_tag, html)


def _is_linked_image_tag(text, start, end):
    window_start = max(0, start - 120)
    window_end = min(len(text), end + 12)
    snippet = text[window_start:window_end]
    local_start = start - window_start
    local_end = end - window_start
    for match in _LINKED_IMG_RE.finditer(snippet):
        if match.start() <= local_start and match.end() >= local_end:
            return True
    return False


def _fetch_image_data_uri(url, *, timeout, user_agent):
    payload = fetch_cached_bytes(
        url,
        kind="image",
        timeout=timeout,
        user_agent=user_agent or DEFAULT_REMOTE_USER_AGENT,
    )
    if payload is None:
        raise urllib.error.URLError(f"failed to fetch image: {url}")

    content_type = mimetypes.guess_type(url)[0] or "image/png"
    if content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(url)[0] or "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def is_probably_image_url(url):
    path = urllib.parse.urlparse(str(url or "")).path.lower()
    return any(path.endswith(ext) for ext in _IMAGE_URL_SUFFIXES)


def download_url_to_temp_file(url, *, timeout=6.0, user_agent=None):
    payload = fetch_cached_bytes(
        url,
        kind="image",
        timeout=timeout,
        user_agent=user_agent or DEFAULT_REMOTE_USER_AGENT,
    )
    if payload is None:
        raise urllib.error.URLError(f"failed to download: {url}")

    suffix = mimetypes.guess_extension(mimetypes.guess_type(url)[0] or "image/png") or os.path.splitext(
        urllib.parse.urlparse(url).path
    )[1]
    if suffix == ".jpe":
        suffix = ".jpg"
    if not suffix:
        suffix = ".png"

    cache_dir = os.path.join(get_app_data_dir(), "cache", "remote_html")
    os.makedirs(cache_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="remote-image-", suffix=suffix, dir=cache_dir)
    os.close(fd)
    with open(temp_path, "wb") as handle:
        handle.write(payload)
    return temp_path

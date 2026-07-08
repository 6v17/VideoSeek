import json

from src.app.app_meta import get_app_meta
from src.app.i18n import get_texts
from src.services.remote_fetch_cache import DEFAULT_REMOTE_USER_AGENT, fetch_cached_text
from src.services.remote_html_assets import inline_remote_html_images


def get_local_about_payload(language):
    texts = get_texts(language)
    return {
        "badge": texts["about_badge"],
        "title": texts["app_name"],
        "body": texts["about_body"],
        "format": "plain",
    }


def get_about_payload(language):
    remote_about = fetch_remote_about()
    if remote_about:
        return _normalize_about(remote_about, get_texts(language))
    return get_local_about_payload(language)


def fetch_remote_about():
    app_meta = get_app_meta()
    about_url = app_meta.get("about_url", "").strip()
    if not about_url:
        return None

    try:
        raw_text = fetch_cached_text(about_url, kind="json", user_agent=DEFAULT_REMOTE_USER_AGENT)
        if not raw_text:
            return None
        data = json.loads(raw_text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def _normalize_about(data, texts):
    badge = str(data.get("badge") or texts["about_badge"])
    title = str(data.get("title") or texts["app_name"])
    body = data.get("body", texts["about_body"])
    content_format = str(data.get("format", "plain")).strip().lower()

    if isinstance(body, list):
        body = "\n".join(str(item) for item in body)
    else:
        body = str(body)

    if content_format not in {"plain", "html"}:
        content_format = "plain"

    if content_format == "html":
        app_meta = get_app_meta()
        try:
            timeout = float(app_meta.get("remote_timeout", 4))
        except (TypeError, ValueError):
            timeout = 4.0
        body = inline_remote_html_images(body, timeout=max(timeout, 6.0))

    return {
        "badge": badge,
        "title": title,
        "body": body,
        "format": content_format,
    }

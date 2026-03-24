import json
import urllib.error
import urllib.request

from src.app.app_meta import get_app_meta
from src.app.i18n import get_texts


def get_local_notice_payload(language):
    texts = get_texts(language)
    return {
        "title": texts["notice_heading"],
        "subtitle": texts["notice_subtitle"],
        "body": texts["notice_body"],
        "format": "plain",
    }


def get_notice_payload(language):
    remote_notice = fetch_remote_notice()
    if remote_notice:
        return _normalize_notice(remote_notice, get_texts(language))
    return get_local_notice_payload(language)


def fetch_remote_notice():
    app_meta = get_app_meta()
    notice_url = app_meta.get("notice_url", "").strip()
    timeout = app_meta.get("remote_timeout", 4)
    if not notice_url:
        return None

    request = urllib.request.Request(
        notice_url,
        headers={"User-Agent": "VideoSeek/notice-fetch"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def _normalize_notice(data, texts):
    title = str(data.get("title") or texts["notice_heading"])
    subtitle = str(data.get("subtitle") or texts["notice_subtitle"])
    body = data.get("body", texts["notice_body"])
    content_format = str(data.get("format", "plain")).strip().lower()
    date_text = str(data.get("date", "")).strip()
    version_text = str(data.get("version", "")).strip()

    if isinstance(body, list):
        body = "\n".join(f"{index}. {item}" for index, item in enumerate(body, start=1))
    else:
        body = str(body)

    if content_format not in {"plain", "html"}:
        content_format = "plain"

    meta_parts = [part for part in [version_text, date_text] if part]
    if meta_parts:
        subtitle = f"{subtitle}\n{' | '.join(meta_parts)}"

    return {
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "format": content_format,
    }

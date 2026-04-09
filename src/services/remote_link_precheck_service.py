import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

BLOCKED_LINK_HOSTS = {"github.com", "www.github.com", "raw.githubusercontent.com"}


def precheck_remote_links(links):
    accepted = []
    risky = []
    blocked = []
    seen = set()

    for raw in links or []:
        normalized = normalize_link_input(str(raw))
        if not normalized:
            blocked.append({"link": str(raw), "reason": "invalid_url"})
            continue
        canonical = canonical_video_url(normalized) or normalized
        if canonical in seen:
            continue
        seen.add(canonical)

        verdict = classify_remote_link(normalized)
        if verdict == "accepted":
            accepted.append(normalized)
        elif verdict == "risky":
            accepted.append(normalized)
            risky.append({"link": normalized, "reason": "site_may_require_cookie_or_video_page"})
        else:
            blocked.append({"link": normalized, "reason": "unsupported_page_type"})

    return {
        "accepted_links": accepted,
        "risky_links": risky,
        "blocked_links": blocked,
        "accepted_count": len(accepted),
        "risky_count": len(risky),
        "blocked_count": len(blocked),
    }


def normalize_link_input(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return ""

    match = re.search(r"(https?://[^\s]+)", text, flags=re.IGNORECASE)
    candidate = match.group(1) if match else text
    candidate = candidate.strip().strip("()[]{}<>\"'閿涘被鈧偊绱遍敍渚婄吹")

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        if parsed.netloc.lower() in BLOCKED_LINK_HOSTS:
            return ""
        return candidate
    return ""


def canonical_video_url(url):
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return text

    host = parsed.netloc.lower()
    query = {}
    if "youtube.com" in host and parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        if values:
            query["v"] = values[0]
    if "youtu.be" in host:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    query_text = urlencode(query) if query else ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query_text, ""))


def guess_source_id_from_url(url):
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if "bilibili.com" in host:
        match = re.search(r"/video/(BV[0-9A-Za-z]+)", path, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if "douyin.com" in host:
        match = re.search(r"/video/(\d+)", path, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if "youtube.com" in host:
        values = parse_qs(parsed.query).get("v", [])
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    if "youtu.be" in host:
        video_id = path.lstrip("/").strip()
        if video_id:
            return video_id
    return ""


def build_stable_source_id(info_id, source_link, fallback):
    stable_id = str(info_id or "").strip()
    if stable_id:
        return stable_id
    guessed = guess_source_id_from_url(source_link)
    if guessed:
        return guessed
    stable_url = canonical_video_url(source_link)
    if stable_url:
        return stable_url
    return str(fallback or "").strip()


def build_precheck_source_candidates(link):
    candidates = set()
    guessed = guess_source_id_from_url(link)
    if guessed:
        candidates.add(guessed)
    canonical = canonical_video_url(link)
    if canonical:
        candidates.add(canonical)
    raw = str(link or "").strip()
    if raw:
        candidates.add(raw)
    return candidates


def build_existing_source_candidates(paths, source_links):
    candidates = set()
    for value in paths or []:
        text = str(value or "").strip()
        if text:
            candidates.add(text)
    for link in source_links or []:
        text = str(link or "").strip()
        if not text:
            continue
        candidates.add(text)
        canonical = canonical_video_url(text)
        if canonical:
            candidates.add(canonical)
        guessed = guess_source_id_from_url(text)
        if guessed:
            candidates.add(guessed)
    return candidates


def classify_remote_link(url):
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()

    if host in BLOCKED_LINK_HOSTS:
        return "blocked"
    if path.startswith("/search") or path.startswith("/channel") or path.startswith("/playlist") or path.startswith("/@"):
        return "blocked"

    if "douyin.com" in host:
        if "/video/" in path or host.startswith("v.douyin.com"):
            return "risky"
        return "blocked"

    if "bilibili.com" in host:
        if "/video/" in path:
            return "accepted"
        return "blocked"

    if "youtube.com" in host:
        if path == "/watch":
            return "accepted"
        return "blocked"

    if "youtu.be" in host:
        if path.strip("/"):
            return "accepted"
        return "blocked"

    return "risky"

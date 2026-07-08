"""Reason codes for video download probe / download results."""

from __future__ import annotations

OK = "OK"
INVALID_URL = "INVALID_URL"
UNSUPPORTED_PAGE = "UNSUPPORTED_PAGE"
NEEDS_COOKIE = "NEEDS_COOKIE"
BROWSER_COOKIE_LOCKED = "BROWSER_COOKIE_LOCKED"
GEO_BLOCKED = "GEO_BLOCKED"
DRM = "DRM"
EXTRACTOR_FAILED = "EXTRACTOR_FAILED"
NETWORK = "NETWORK"
DISK_FULL = "DISK_FULL"
CANCELLED = "CANCELLED"
AUDIO_ONLY = "AUDIO_ONLY"
LIBRARY_NOT_SELECTED = "LIBRARY_NOT_SELECTED"
NO_VIDEO_URL = "NO_VIDEO_URL"
VIDEO_ONLY = "VIDEO_ONLY"

DOUYIN_COOKIE_INVALID = "DOUYIN_COOKIE_INVALID"
DOUYIN_FRESH_COOKIES = "DOUYIN_FRESH_COOKIES"

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".opus", ".aac", ".wav", ".flac", ".ogg", ".wma"}

I18N_KEY_BY_CODE = {
    INVALID_URL: "download_reason_invalid_url",
    UNSUPPORTED_PAGE: "download_reason_unsupported_page",
    NEEDS_COOKIE: "download_reason_needs_cookie",
    BROWSER_COOKIE_LOCKED: "download_reason_browser_cookie_locked",
    DOUYIN_COOKIE_INVALID: "download_reason_douyin_cookie_invalid",
    DOUYIN_FRESH_COOKIES: "download_reason_douyin_fresh_cookies",
    GEO_BLOCKED: "download_reason_geo_blocked",
    DRM: "download_reason_drm",
    EXTRACTOR_FAILED: "download_reason_extractor_failed",
    NETWORK: "download_reason_network",
    DISK_FULL: "download_reason_disk_full",
    CANCELLED: "download_reason_cancelled",
    AUDIO_ONLY: "download_reason_audio_only",
    LIBRARY_NOT_SELECTED: "download_reason_library_not_selected",
    NO_VIDEO_URL: "download_reason_no_video_url",
    VIDEO_ONLY: "download_reason_video_only",
}


def map_exception_to_reason(exc: BaseException) -> str:
    message = str(exc or "").lower()
    if "no space left" in message or "disk full" in message:
        return DISK_FULL
    if "drm" in message or "encrypted" in message:
        return DRM
    if "geo" in message or "not available in your country" in message:
        return GEO_BLOCKED
    if "could not copy chrome cookie" in message or "cookie database" in message:
        return BROWSER_COOKIE_LOCKED
    if "failed to decrypt with dpapi" in message or "unable to get key for cookie decryption" in message:
        return BROWSER_COOKIE_LOCKED
    if "appbound encryption" in message or "running as admin" in message:
        return BROWSER_COOKIE_LOCKED
    if "fresh cookies (not necessarily logged in) are needed" in message:
        return DOUYIN_FRESH_COOKIES
    if "403" in message or "401" in message or "cookie" in message or "sign in" in message:
        return NEEDS_COOKIE
    if "timeout" in message or "timed out" in message or "connection" in message or "network" in message:
        return NETWORK
    if "unsupported" in message or "unable to extract" in message or "no video formats" in message:
        return EXTRACTOR_FAILED
    return EXTRACTOR_FAILED

import hashlib
import os
import urllib.error
import urllib.request

from src.app.app_meta import get_app_meta


def download_file(
    url,
    target_path,
    expected_sha256="",
    progress_callback=None,
    source_label="",
    user_agent="VideoSeek/download",
):
    timeout = get_app_meta().get("remote_timeout", 4)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent},
    )
    hasher = hashlib.sha256()

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(target_path, "wb") as handle:
            total_size = safe_int(response.headers.get("Content-Length"))
            downloaded = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_size, source_label)
    except urllib.error.URLError as exc:
        if os.path.exists(target_path):
            os.remove(target_path)
        raise RuntimeError(f"Failed to download from {url}") from exc

    if expected_sha256 and hasher.hexdigest().lower() != expected_sha256.lower():
        if os.path.exists(target_path):
            os.remove(target_path)
        raise RuntimeError(f"Checksum mismatch for {os.path.basename(target_path)}")


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

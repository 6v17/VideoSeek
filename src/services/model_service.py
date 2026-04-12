import json
import os
import urllib.error
import urllib.parse
import urllib.request

from src.app.app_meta import get_app_meta
from src.services.download_utils import download_file
from src.utils import get_configured_model_dir, get_missing_model_files

REQUIRED_MODEL_FILES = [
    "clip_visual.onnx",
    "clip_text.onnx",
    "bpe_simple_vocab_16e6.txt.gz",
]

def fetch_remote_model_manifest():
    app_meta = get_app_meta()
    manifest_url = app_meta.get("model_manifest_url", "").strip()
    timeout = app_meta.get("remote_timeout", 4)

    if not manifest_url:
        return None

    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "VideoSeek/model-manifest"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    return _normalize_manifest(data, manifest_url)


def download_models(progress_callback=None):
    manifest = fetch_remote_model_manifest()
    if not manifest:
        raise RuntimeError("Model manifest is unavailable.")

    model_dir = get_configured_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    total_files = len(manifest["files"])

    for index, file_info in enumerate(manifest["files"], start=1):
        file_name = file_info["name"]
        target_path = os.path.join(model_dir, file_name)
        temp_path = f"{target_path}.part"
        progress_base = int(((index - 1) / total_files) * 100)
        progress_span = max(1, int(100 / total_files))

        if progress_callback:
            progress_callback(progress_base, f"Preparing download for {file_name}")

        source_label = _download_file_from_sources(
            file_info["sources"],
            temp_path,
            file_info.get("sha256", ""),
            lambda current, total, label: _emit_download_progress(
                progress_callback,
                progress_base,
                progress_span,
                file_name,
                current,
                total,
                label,
            ),
        )

        if os.path.exists(target_path):
            os.remove(target_path)
        os.replace(temp_path, target_path)

        if progress_callback:
            progress_callback(
                min(99, progress_base + progress_span),
                f"Downloaded {file_name} from {source_label}",
            )

    if progress_callback:
        progress_callback(100, "Model download completed")

    missing_files, _ = get_missing_model_files(REQUIRED_MODEL_FILES)
    if missing_files:
        raise RuntimeError(f"Downloaded files are incomplete: {', '.join(missing_files)}")

    return {
        "model_dir": model_dir,
        "manifest_version": manifest.get("version", ""),
    }


def _emit_download_progress(progress_callback, progress_base, progress_span, file_name, current, total, label):
    if not progress_callback:
        return

    source_text = f" via {label}" if label else ""
    if total > 0:
        file_progress = min(100, int((current / total) * 100))
        overall_progress = min(99, progress_base + int((file_progress / 100) * progress_span))
        text = f"Downloading {file_name}{source_text} ({_format_bytes(current)}/{_format_bytes(total)})"
    else:
        overall_progress = min(99, progress_base + max(1, progress_span // 2))
        text = f"Downloading {file_name}{source_text} ({_format_bytes(current)})"

    progress_callback(overall_progress, text)


def _download_file_from_sources(sources, target_path, expected_sha256="", progress_callback=None):
    errors = []
    for source in sources:
        label = source.get("label", "") or source.get("url", "")
        try:
            _download_file(source["url"], target_path, expected_sha256, progress_callback, label)
            return label
        except RuntimeError as exc:
            errors.append(f"{label}: {exc}")

    if os.path.exists(target_path):
        os.remove(target_path)
    raise RuntimeError("All download sources failed. " + " | ".join(errors))


def _download_file(url, target_path, expected_sha256="", progress_callback=None, source_label=""):
    return download_file(
        url,
        target_path,
        expected_sha256=expected_sha256,
        progress_callback=progress_callback,
        source_label=source_label,
        user_agent="VideoSeek/model-download",
    )


def _normalize_manifest(data, manifest_url):
    if not isinstance(data, dict):
        return None

    version = str(data.get("version", "")).strip()
    global_sources = _normalize_global_sources(data, manifest_url)
    files = data.get("files")
    if not isinstance(files, list) or not files:
        return None

    normalized_files = []
    for entry in files:
        normalized = _normalize_manifest_file(entry, global_sources, manifest_url)
        if not normalized:
            return None
        normalized_files.append(normalized)

    return {
        "version": version,
        "files": normalized_files,
    }


def _normalize_global_sources(data, manifest_url):
    base_url = str(data.get("base_url", "")).strip()
    manifest_dir = urllib.parse.urljoin(manifest_url, ".")
    sources = []

    if base_url:
        sources.append({"label": "primary", "base_url": f"{base_url.rstrip('/')}/"})

    mirrors = data.get("mirrors", [])
    if isinstance(mirrors, list):
        for index, mirror in enumerate(mirrors, start=1):
            if isinstance(mirror, str) and mirror.strip():
                sources.append({"label": f"mirror-{index}", "base_url": f"{mirror.strip().rstrip('/')}/"})
            elif isinstance(mirror, dict):
                url = str(mirror.get("base_url", "")).strip()
                if url:
                    sources.append(
                        {
                            "label": str(mirror.get("label", "")).strip() or f"mirror-{index}",
                            "base_url": f"{url.rstrip('/')}/",
                        }
                    )

    if not sources:
        sources.append({"label": "manifest", "base_url": manifest_dir})
    return sources


def _normalize_manifest_file(entry, global_sources, manifest_url):
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    sha256 = str(entry.get("sha256", "")).strip()
    sources = _normalize_file_sources(entry, name, global_sources, manifest_url)
    if not sources:
        return None

    return {
        "name": name,
        "sha256": sha256,
        "sources": sources,
    }


def _normalize_file_sources(entry, file_name, global_sources, manifest_url):
    normalized_sources = []
    explicit_sources = entry.get("sources")
    explicit_url = str(entry.get("url", "")).strip()

    if isinstance(explicit_sources, list) and explicit_sources:
        for index, source in enumerate(explicit_sources, start=1):
            normalized = _normalize_explicit_source(source, file_name, index)
            if normalized:
                normalized_sources.append(normalized)
    elif explicit_url:
        normalized_sources.append({"label": "primary", "url": explicit_url})
    else:
        for source in global_sources:
            base_url = source.get("base_url", "")
            if not base_url:
                continue
            normalized_sources.append(
                {
                    "label": source.get("label", ""),
                    "url": urllib.parse.urljoin(base_url, file_name),
                }
            )

    deduped = []
    seen = set()
    for source in normalized_sources:
        url = source["url"]
        if url in seen:
            continue
        deduped.append(source)
        seen.add(url)
    return deduped


def _normalize_explicit_source(source, file_name, index):
    if isinstance(source, str) and source.strip():
        return {"label": f"source-{index}", "url": source.strip()}

    if not isinstance(source, dict):
        return None

    url = str(source.get("url", "")).strip()
    base_url = str(source.get("base_url", "")).strip()
    if not url and base_url:
        url = urllib.parse.urljoin(f"{base_url.rstrip('/')}/", file_name)
    if not url:
        return None

    return {
        "label": str(source.get("label", "")).strip() or f"source-{index}",
        "url": url,
    }
def _format_bytes(value):
    units = ["B", "KB", "MB", "GB"]
    size = float(value or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024

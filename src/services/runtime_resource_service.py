import os

from src.app.app_meta import get_app_meta
from src.app.config import load_config
from src.services.model_service import get_required_model_files
from src.storage.config_store import get_active_model_profile, get_active_model_resource_dir, resolve_provider_dir
from src.utils import (
    get_app_data_dir,
    get_configured_ffmpeg_target_path,
    get_missing_model_files,
    has_ffmpeg,
)


def _resolve_runtime_model_dir(config):
    try:
        model_dir = get_active_model_resource_dir(config=config)
        if model_dir:
            return model_dir
    except Exception:
        pass
    return str(config.get("model_dir", "") or "").strip()


def _resolve_runtime_model_root_dir(config):
    model_root_dir = str(config.get("model_dir", "") or "").strip()
    if not model_root_dir:
        model_root_dir = _resolve_runtime_model_dir(config)
    model_root_dir = str(model_root_dir or "").strip()
    if not model_root_dir:
        return ""
    model_root_dir = os.path.normpath(os.path.abspath(os.fspath(model_root_dir)))
    try:
        profile = get_active_model_profile(config=config)
        provider = str(profile.get("provider", "") or "").strip()
        runtime = dict(profile.get("runtime") or {})
        variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
        if provider and variant:
            provider_dir = resolve_provider_dir(provider)
            expected_tail = os.path.normcase(os.path.normpath(os.path.join(provider_dir, variant)))
            if os.path.normcase(model_root_dir).endswith(expected_tail):
                candidate = os.path.dirname(os.path.dirname(model_root_dir))
                if candidate:
                    model_root_dir = candidate
    except Exception:
        pass
    # Fallback heuristic: if path itself looks like "<root>/<provider>/<variant>", trim to "<root>".
    # This protects against stale configs that accidentally persist a profile leaf as model_dir.
    provider_leaf = os.path.basename(os.path.dirname(model_root_dir)).strip().lower()
    if provider_leaf in {"openai-clip", "siglip2", "chinese-clip", "chinese-clip-onnx", "clip-onnx", "siglip2-onnx"}:
        candidate = os.path.dirname(os.path.dirname(model_root_dir))
        if candidate:
            model_root_dir = candidate
    return model_root_dir


def get_runtime_resource_status():
    config = load_config()
    missing_model_files, _ = get_missing_model_files(get_required_model_files(config=config))
    ffmpeg_ready = has_ffmpeg()
    model_ready = not missing_model_files
    model_dir = _resolve_runtime_model_dir(config)
    model_root_dir = _resolve_runtime_model_root_dir(config)
    ffmpeg_target_path = get_configured_ffmpeg_target_path()

    display_files = list(missing_model_files)
    if not ffmpeg_ready:
        display_files.append("ffmpeg.exe")

    return {
        "root_dir": get_app_data_dir(),
        "model_dir": model_dir,
        "model_root_dir": model_root_dir,
        "ffmpeg_target_path": ffmpeg_target_path,
        "missing_model_files": missing_model_files,
        "display_files": display_files,
        "model_ready": model_ready,
        "ffmpeg_ready": ffmpeg_ready,
        "resources_ready": model_ready and ffmpeg_ready,
        "download_enabled": bool(get_app_meta().get("model_manifest_url", "").strip()),
    }


def get_runtime_resource_location_text(status=None, include_ffmpeg=True):
    status = status or get_runtime_resource_status()
    locations = [f"Models: {status['model_dir']}"]
    if include_ffmpeg:
        locations.append(f"FFmpeg: {status['ffmpeg_target_path']}")
    return "\n".join(locations)


def get_runtime_resource_open_paths(status=None):
    status = status or get_runtime_resource_status()
    model_dir = os.path.normpath(str(status.get("model_root_dir") or status["model_dir"]))
    ffmpeg_dir = os.path.normpath(os.path.dirname(status["ffmpeg_target_path"]))
    paths = []

    if model_dir:
        paths.append(model_dir)
    if ffmpeg_dir and os.path.normcase(ffmpeg_dir) != os.path.normcase(model_dir):
        paths.append(ffmpeg_dir)

    deduped = []
    seen = set()
    for path in paths:
        normalized = os.path.normcase(path)
        if normalized in seen:
            continue
        deduped.append(path)
        seen.add(normalized)
    return deduped


def import_selected_runtime_packages(model_root, selected_files, progress_callback=None):
    """Import zip packages the same way the in-app runtime import worker does."""
    from src.services.model_package_service import import_model_package_zip
    from src.services.understanding_import_service import (
        classify_package_zip,
        import_understanding_component_zip,
    )
    from src.services.understanding_resource_service import (
        SEARCH_MODEL_MANIFEST_FILENAME,
        UNDERSTANDING_MANIFEST_FILENAME,
    )

    def _progress(percent, message):
        if progress_callback is not None:
            progress_callback(int(percent), str(message or ""))

    files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
    zip_files = [path for path in files if path.lower().endswith(".zip")]
    sha256_files = [path for path in files if path.lower().endswith(".sha256")]
    if not zip_files:
        raise RuntimeError("No model zip to import.")

    from src.app.plugins import get_registry

    plugin_kinds = get_registry().package_kinds
    aggregate = {
        "imported": 0,
        "updated": 0,
        "understanding_imported": [],
        "understanding_updated": [],
        "errors": [],
        "checksum_verified_count": 0,
    }
    for spec in plugin_kinds.values():
        aggregate.setdefault(spec.aggregate_imported_key, [])
        aggregate.setdefault(spec.aggregate_updated_key, [])

    root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
    total = max(1, len(zip_files))
    for index, zip_path in enumerate(zip_files, start=1):
        _progress(int(((index - 1) / total) * 90), f"Importing {os.path.basename(zip_path)}")
        matching_sha = ""
        expected_name = f"{os.path.basename(zip_path)}.sha256".lower()
        for candidate in sha256_files:
            if os.path.basename(candidate).lower() == expected_name:
                matching_sha = candidate
                break
        package_kind = classify_package_zip(zip_path)
        package_result = None
        if package_kind == "understanding":
            package_result = import_understanding_component_zip(
                root,
                zip_path,
                sha256_file=matching_sha or None,
            )
            component_id = str(package_result.get("component_id", "") or "").strip()
            if package_result.get("updated"):
                aggregate["updated"] += 1
                aggregate["understanding_updated"].append(component_id)
            else:
                aggregate["imported"] += 1
                aggregate["understanding_imported"].append(component_id)
        elif package_kind == "search":
            package_result = import_model_package_zip(
                root,
                zip_path,
                sha256_file=matching_sha or None,
            )
            aggregate["imported"] += int(package_result.get("imported", 0))
            aggregate["updated"] += int(package_result.get("updated", 0))
            aggregate["errors"].extend(package_result.get("errors", []))
        elif package_kind in plugin_kinds:
            spec = plugin_kinds[package_kind]
            package_result = spec.import_fn(
                root,
                zip_path,
                sha256_file=matching_sha or None,
            )
            component_id = str(package_result.get("component_id", "") or "").strip()
            if package_result.get("updated"):
                aggregate["updated"] += 1
                aggregate[spec.aggregate_updated_key].append(component_id)
            else:
                aggregate["imported"] += 1
                aggregate[spec.aggregate_imported_key].append(component_id)
        else:
            kind_hints = ", ".join(
                [UNDERSTANDING_MANIFEST_FILENAME, SEARCH_MODEL_MANIFEST_FILENAME]
                + [f"plugin:{kind}" for kind in plugin_kinds]
            )
            aggregate["errors"].append(
                f"{os.path.basename(zip_path)}: unrecognized package (expected {kind_hints})"
            )
            continue
        if package_result is not None and package_result.get("checksum_verified"):
            aggregate["checksum_verified_count"] += 1
        _progress(int((index / total) * 95), f"Imported {index}/{total}")
    _progress(100, "Model package import finished")
    return aggregate


def import_runtime_resources(paths, config=None):
    """Install local model zips and/or ``ffmpeg.exe`` into the app data layout.

    Uses the configured ``model_dir`` and ``ffmpeg_path`` when the user has
    changed them. Does not download files.
    """
    from src.app.config import CONFIG_FILE, load_config
    from src.infra.ffmpeg_paths import install_ffmpeg_executable

    files = [os.path.normpath(os.path.abspath(os.fspath(path))) for path in paths if str(path or "").strip()]
    if not files:
        raise RuntimeError("Pass at least one model zip or ffmpeg.exe.")

    ffmpeg_files = []
    package_files = []
    rejected = []
    for path in files:
        name = os.path.basename(path).lower()
        if name == "ffmpeg.exe":
            ffmpeg_files.append(path)
        elif name.endswith(".zip") or name.endswith(".sha256"):
            package_files.append(path)
        else:
            rejected.append(path)
    if rejected:
        names = ", ".join(os.path.basename(path) for path in rejected)
        raise RuntimeError(f"Unsupported runtime file(s): {names}. Expected a model .zip, optional .sha256, or ffmpeg.exe.")
    if not any(path.lower().endswith(".zip") for path in package_files) and any(
        path.lower().endswith(".sha256") for path in package_files
    ):
        raise RuntimeError("A .sha256 file needs the matching .zip beside it.")
    if len(ffmpeg_files) > 1:
        raise RuntimeError("Pass one ffmpeg.exe.")

    current = config if config is not None else load_config()
    model_root = _resolve_runtime_model_root_dir(current)
    if not model_root:
        raise RuntimeError("model_dir is empty in config.json.")

    ffmpeg_result = None
    if ffmpeg_files:
        target_path = install_ffmpeg_executable(ffmpeg_files[0], config=current)
        ffmpeg_result = {"source": ffmpeg_files[0], "target_path": target_path}

    packages = None
    if any(path.lower().endswith(".zip") for path in package_files):
        packages = import_selected_runtime_packages(model_root, package_files)

    return {
        "config_file": CONFIG_FILE,
        "model_root": model_root,
        "ffmpeg": ffmpeg_result,
        "packages": packages,
        "status": get_runtime_resource_status(),
    }


def ensure_runtime_resource_dirs(status=None):
    status = status or get_runtime_resource_status()
    os.makedirs(status["root_dir"], exist_ok=True)
    model_root_dir = str(status.get("model_root_dir", "") or "").strip()
    if not model_root_dir:
        model_root_dir = str(status.get("model_dir", "") or "").strip()
    if model_root_dir:
        os.makedirs(model_root_dir, exist_ok=True)
    os.makedirs(os.path.dirname(status["ffmpeg_target_path"]), exist_ok=True)
    return get_runtime_resource_open_paths(status)

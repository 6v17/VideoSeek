import gc
import json
import os
import re
import hashlib
import shutil
import tempfile
import time
import zipfile

from src.app.config import load_config, save_config
from src.app.logging_utils import get_logger
from src.storage.config_store import (
    get_config_schema_version,
    get_data_paths,
    iter_provider_resource_dir_candidates,
    resolve_model_resource_dir,
)

logger = get_logger("model_package_service")

REQUIRED_MODEL_FILES = [
    "clip_visual.onnx",
    "clip_text.onnx",
    "bpe_simple_vocab_16e6.txt.gz",
]

PROVIDER_REQUIRED_MODEL_FILES = {
    "clip_onnx": list(REQUIRED_MODEL_FILES),
    "chinese_clip_onnx": [
        "chinese_clip_image.onnx",
        "chinese_clip_text.onnx",
        "vocab.txt",
        "preprocessor_config.json",
        "config.json",
    ],
    "siglip2_onnx": [
        "vision_model.onnx",
        "text_model.onnx",
        "tokenizer.json",
        "tokenizer_config.json",
    ],
}


def _sanitize_profile_id(raw_value):
    text = str(raw_value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = text.strip("_")
    return text or "model_profile"


def _ensure_unique_profile_id(base_id, existing_idx):
    candidate = _sanitize_profile_id(base_id)
    if candidate not in existing_idx:
        return candidate
    suffix = 2
    while True:
        next_id = f"{candidate}_{suffix}"
        if next_id not in existing_idx:
            return next_id
        suffix += 1


def _provider_dir(provider):
    from src.storage.config_store import resolve_provider_dir

    return resolve_provider_dir(provider)


def _resolve_model_variant(profile):
    runtime = dict(profile.get("runtime") or {})
    variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
    return variant or "vit-base-patch32"


def _resolve_profile_resource_dir(profile):
    runtime = dict(profile.get("runtime") or {})
    model_root = str(runtime.get("model_dir", "") or "").strip()
    provider = str(profile.get("provider", "") or "").strip()
    variant = _resolve_model_variant(profile)
    if not model_root or not provider:
        return ""
    return resolve_model_resource_dir(model_root, provider, variant)


def _release_profile_runtime_locks(asset_dir="", _resource_dir=""):
    """Drop ONNX / Lance handles so Windows can delete profile directories."""
    try:
        from src.core.clip_embedding import reset_engine

        reset_engine()
    except Exception as exc:
        logger.debug("reset_engine before profile removal failed: %s", exc)
    try:
        from src.services.search_assets import invalidate_search_asset_caches

        invalidate_search_asset_caches()
    except Exception as exc:
        logger.debug("invalidate_search_asset_caches before profile removal failed: %s", exc)
    try:
        from src.storage.lance_search_index import invalidate_lance_runtime_caches

        invalidate_lance_runtime_caches(str(asset_dir or "").strip())
    except Exception as exc:
        logger.debug("invalidate_lance_runtime_caches before profile removal failed: %s", exc)
    try:
        from src.storage.profile_library_store import invalidate_profile_library_schema_cache

        invalidate_profile_library_schema_cache(str(asset_dir or "").strip() or None)
    except Exception as exc:
        logger.debug("invalidate_profile_library_schema_cache before profile removal failed: %s", exc)
    # Drop any lingering table/file refs before rmtree on Windows.
    gc.collect()


def _rmtree_with_retry(path, *, attempts=5, delay_sec=0.15):
    path = str(path or "").strip()
    if not path or not os.path.exists(path):
        return True, ""
    last_error = ""
    for attempt in range(max(1, int(attempts))):
        try:
            shutil.rmtree(path)
            return True, ""
        except Exception as exc:
            last_error = str(exc)
            gc.collect()
            if attempt + 1 < attempts:
                time.sleep(delay_sec * (attempt + 1))
    # Last chance: ignore remaining locked files rather than failing the whole removal.
    shutil.rmtree(path, ignore_errors=True)
    if os.path.exists(path):
        return False, last_error or f"Failed to remove directory: {path}"
    return True, ""


def _profile_required_files(profile):
    files_map = profile.get("files")
    if isinstance(files_map, dict):
        from_profile = [str(value or "").strip() for value in files_map.values() if str(value or "").strip()]
        if from_profile:
            return from_profile
    provider = str(profile.get("provider", "") or "").strip()
    return list(PROVIDER_REQUIRED_MODEL_FILES.get(provider, REQUIRED_MODEL_FILES))


def _profile_files_ready(profile):
    resource_dir = _resolve_profile_resource_dir(profile)
    if not resource_dir or not os.path.isdir(resource_dir):
        return False
    required_files = _profile_required_files(profile)
    if not required_files:
        return False
    return all(os.path.exists(os.path.join(resource_dir, name)) for name in required_files)


def _find_profile_by_id(profiles, profile_id):
    profile_id = str(profile_id or "").strip()
    if not profile_id:
        return None
    for item in profiles:
        if isinstance(item, dict) and str(item.get("id", "") or "").strip() == profile_id:
            return item
    return None


def _pick_ready_profile_id(profiles, candidate_ids):
    for profile_id in reversed(candidate_ids):
        profile = _find_profile_by_id(profiles, profile_id)
        if profile and _profile_files_ready(profile):
            return profile_id
    for profile_id in reversed(candidate_ids):
        if _find_profile_by_id(profiles, profile_id):
            return profile_id
    return ""


def _resolve_active_profile_after_import(models, profiles, touched_profile_ids):
    active_profile_id = str(models.get("active_profile", "") or "").strip()
    if not touched_profile_ids:
        return active_profile_id

    active_profile = _find_profile_by_id(profiles, active_profile_id)
    if active_profile and _profile_files_ready(active_profile):
        return active_profile_id

    if not active_profile:
        return _pick_ready_profile_id(profiles, touched_profile_ids) or active_profile_id

    replacement_id = _pick_ready_profile_id(profiles, touched_profile_ids)
    if replacement_id and replacement_id != active_profile_id:
        return replacement_id
    return active_profile_id


def _resolve_profile_asset_base_dir(config, profile):
    data_paths = get_data_paths(config=config)
    data_dir = str(data_paths.get("data_dir", "") or "").strip()
    provider = str(profile.get("provider", "") or "").strip()
    variant = _resolve_model_variant(profile)
    if not data_dir or not provider:
        return ""
    return os.path.join(data_dir, "model_assets", _provider_dir(provider), variant)


def _remove_empty_dir_if_possible(path):
    if not path or not os.path.isdir(path):
        return False
    try:
        if os.listdir(path):
            return False
        os.rmdir(path)
        return True
    except OSError:
        return False


def _discover_manifest_files(model_root):
    root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
    if not os.path.isdir(root):
        return []
    found = []
    for current_root, _dirs, files in os.walk(root):
        if "model_manifest.json" in files:
            found.append(os.path.join(current_root, "model_manifest.json"))
    return found


def _sha256_file(file_path):
    hasher = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _parse_sha256_text(text):
    line = str(text or "").strip()
    if not line:
        return ""
    token = line.split()[0].strip()
    token = token.upper()
    if len(token) != 64:
        return ""
    if re.fullmatch(r"[0-9A-F]{64}", token) is None:
        return ""
    return token


def _read_expected_sha256(zip_path, sha256_file=None):
    if sha256_file:
        if not os.path.exists(sha256_file):
            raise RuntimeError(f"Checksum file not found: {sha256_file}")
        with open(sha256_file, "r", encoding="utf-8") as handle:
            parsed = _parse_sha256_text(handle.read())
        if not parsed:
            raise RuntimeError(f"Invalid checksum file format: {sha256_file}")
        return parsed
    sibling = f"{zip_path}.sha256"
    if os.path.exists(sibling):
        with open(sibling, "r", encoding="utf-8") as handle:
            parsed = _parse_sha256_text(handle.read())
        if parsed:
            return parsed
    return ""


def _safe_extract_zip(zip_path, output_dir):
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            normalized = os.path.normpath(member)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise RuntimeError(f"Unsafe zip entry detected: {member}")
        archive.extractall(output_dir)


def _install_extracted_packages(extracted_root, model_root):
    manifests = _discover_manifest_files(extracted_root)
    if not manifests:
        return 0, []
    installed = 0
    installed_manifests = []
    for manifest_file in manifests:
        try:
            with open(manifest_file, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except Exception as exc:
            raise RuntimeError(f"Invalid manifest in package: {manifest_file} ({exc})") from exc
        provider = str(manifest.get("provider", "") or "").strip()
        variant = str(manifest.get("variant", "") or manifest.get("model_variant", "") or "").strip()
        if not provider or not variant:
            raise RuntimeError(f"Manifest missing provider/variant: {manifest_file}")
        src_dir = os.path.dirname(manifest_file)
        provider_dir = _provider_dir(provider)
        target_dir = os.path.join(model_root, provider_dir, variant)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.copytree(src_dir, target_dir)
        installed += 1
        installed_manifests.append(os.path.join(target_dir, "model_manifest.json"))
    return installed, installed_manifests


def import_model_package_zip(model_root, zip_path, sha256_file=None, require_checksum=False):
    root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
    zip_path = os.path.normpath(os.path.abspath(os.fspath(zip_path)))
    if not os.path.exists(zip_path):
        raise RuntimeError(f"Zip package not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Invalid zip package: {zip_path}")

    expected_sha256 = _read_expected_sha256(zip_path, sha256_file=sha256_file)
    if require_checksum and not expected_sha256:
        raise RuntimeError(f"Missing checksum for package: {os.path.basename(zip_path)}")
    if expected_sha256:
        actual_sha256 = _sha256_file(zip_path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"Checksum mismatch for {os.path.basename(zip_path)} "
                f"(expected {expected_sha256}, actual {actual_sha256})"
            )

    with tempfile.TemporaryDirectory(prefix="videoseek-model-pack-") as temp_dir:
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _safe_extract_zip(zip_path, extract_dir)
        installed_count, installed_manifests = _install_extracted_packages(extract_dir, root)
        if installed_count <= 0:
            raise RuntimeError("No model_manifest.json found inside zip package.")

    result = import_model_packages(root, manifest_files=installed_manifests)
    result["packages_installed"] = installed_count
    result["checksum_verified"] = bool(expected_sha256)
    return result


def import_model_packages(model_root, manifest_files=None):
    config = load_config()
    if get_config_schema_version(config=config) < 2:
        raise RuntimeError("Model package import requires config schema v2")

    root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
    if manifest_files is not None:
        manifests = []
        for manifest_file in manifest_files:
            path = os.path.normpath(os.path.abspath(os.fspath(str(manifest_file or "").strip())))
            if path and os.path.isfile(path):
                manifests.append(path)
    else:
        manifests = _discover_manifest_files(root)
    if not manifests:
        return {
            "imported": 0,
            "updated": 0,
            "errors": ["No model_manifest.json found under model_dir."],
            "active_profile": str((config.get("models") or {}).get("active_profile", "") or "").strip(),
            "active_profile_switched": False,
        }

    models = config.get("models")
    if not isinstance(models, dict):
        models = {}
        config["models"] = models
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        profiles = []
        models["profiles"] = profiles

    existing_idx = {}
    for idx, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        pid = str(profile.get("id", "") or "").strip()
        if pid:
            existing_idx[pid] = idx

    imported = 0
    updated = 0
    errors = []
    touched_profile_ids = []

    for manifest_file in manifests:
        try:
            with open(manifest_file, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except Exception as exc:
            errors.append(f"{manifest_file}: invalid JSON ({exc})")
            continue
        if not isinstance(manifest, dict):
            errors.append(f"{manifest_file}: manifest root must be a JSON object")
            continue

        provider = str(manifest.get("provider", "") or "").strip()
        if not provider:
            errors.append(f"{manifest_file}: missing provider")
            continue
        variant = str(manifest.get("variant", "") or manifest.get("model_variant", "") or "").strip()
        if not variant:
            errors.append(f"{manifest_file}: missing variant/model_variant")
            continue

        provider_dir = _provider_dir(provider)
        effective_resource_dir = os.path.dirname(manifest_file)
        expected_dirs = {
            os.path.normcase(os.path.normpath(os.path.join(root, candidate_dir, variant)))
            for candidate_dir in iter_provider_resource_dir_candidates(provider)
        }
        if os.path.normcase(os.path.normpath(effective_resource_dir)) not in expected_dirs:
            errors.append(
                f"{manifest_file}: expected manifest under "
                f"{os.path.join(root, provider_dir, variant)} (same folder as model files)"
            )
            continue
        required_files = manifest.get("required_files")
        if not isinstance(required_files, list) or not required_files:
            required_files = list(PROVIDER_REQUIRED_MODEL_FILES.get(provider, []))
        required_files = [str(item or "").strip() for item in required_files if str(item or "").strip()]
        missing = [name for name in required_files if not os.path.exists(os.path.join(effective_resource_dir, name))]
        if missing:
            errors.append(
                f"{manifest_file}: missing files under {effective_resource_dir}: {', '.join(missing)}"
            )
            continue

        profile_id = _sanitize_profile_id(manifest.get("id") or f"{provider}_{variant}")
        display_name = str(manifest.get("display_name", "") or "").strip() or f"{provider_dir} / {variant}"
        prefer_gpu = bool(manifest.get("prefer_gpu", True))
        files_map = manifest.get("files")
        if not isinstance(files_map, dict):
            files_map = {}
            if provider == "clip_onnx":
                files_map = {
                    "visual_model": "clip_visual.onnx",
                    "text_model": "clip_text.onnx",
                    "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
                }
            elif provider == "siglip2_onnx":
                files_map = {
                    "vision_model": "vision_model.onnx",
                    "text_model": "text_model.onnx",
                    "tokenizer_json": "tokenizer.json",
                    "tokenizer_config": "tokenizer_config.json",
                }
            elif provider == "chinese_clip_onnx":
                files_map = {
                    "image_model": "chinese_clip_image.onnx",
                    "text_model": "chinese_clip_text.onnx",
                    "tokenizer_vocab": "vocab.txt",
                    "preprocessor_config": "preprocessor_config.json",
                    "model_config": "config.json",
                }

        new_profile = {
            "id": profile_id,
            "provider": provider,
            "display_name": display_name,
            "enabled": True,
            "runtime": {
                "prefer_gpu": prefer_gpu,
                "model_dir": root,
                "model_variant": variant,
            },
            "files": files_map,
            "capabilities": {
                "text_query": True,
                "image_query": True,
                "video_embedding": True,
                "cross_modal_search": True,
            },
        }

        should_append_new_profile = False
        if profile_id in existing_idx:
            existing_profile = profiles[existing_idx[profile_id]]
            existing_provider = str(existing_profile.get("provider", "") or "").strip()
            existing_runtime = dict(existing_profile.get("runtime") or {})
            existing_variant = str(
                existing_runtime.get("model_variant", "") or existing_profile.get("model_variant", "") or ""
            ).strip()
            # Compatibility: legacy/migrated profiles may omit model_variant.
            # Treat empty variant as the manifest variant so we can upgrade in place.
            if not existing_variant:
                existing_variant = variant
            if existing_provider != provider or existing_variant != variant:
                profile_id = _ensure_unique_profile_id(f"{provider}_{variant}", existing_idx)
                should_append_new_profile = True
            else:
                profiles[existing_idx[profile_id]] = new_profile
                updated += 1
                touched_profile_ids.append(profile_id)
        else:
            should_append_new_profile = True
        if should_append_new_profile:
            new_profile["id"] = profile_id
            profiles.append(new_profile)
            existing_idx[profile_id] = len(profiles) - 1
            imported += 1
            touched_profile_ids.append(profile_id)

    active_profile_switched = False
    if imported or updated:
        models["profiles"] = profiles
        previous_active_profile = str(models.get("active_profile", "") or "").strip()
        models["active_profile"] = _resolve_active_profile_after_import(
            models,
            profiles,
            touched_profile_ids,
        )
        active_profile_switched = models["active_profile"] != previous_active_profile
        config["models"] = models
        save_config(config)
    return {
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "active_profile": str(models.get("active_profile", "") or "").strip(),
        "active_profile_switched": active_profile_switched,
    }


def remove_model_profile(profile_id):
    config = load_config()
    schema_version = get_config_schema_version(config=config)
    models = config.get("models")
    if schema_version < 2:
        # Profiles already present means the install is operable; stamp v2 instead of hard-failing.
        if isinstance(models, dict) and isinstance(models.get("profiles"), list):
            config["schema_version"] = 2
            schema_version = 2
        else:
            raise RuntimeError("Model profile removal requires config schema v2")
    if not isinstance(models, dict):
        raise RuntimeError("Missing models section in config")
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        raise RuntimeError("Missing models.profiles in config")
    profile_id = str(profile_id or "").strip()
    if not profile_id:
        raise RuntimeError("Profile id is required")

    target_index = -1
    target_profile = None
    for idx, item in enumerate(profiles):
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "") or "").strip() == profile_id:
            target_index = idx
            target_profile = dict(item)
            break
    if target_profile is None:
        raise RuntimeError(f"Model profile not found: {profile_id}")

    removed_resource_dir = _resolve_profile_resource_dir(target_profile)
    removed_asset_dir = _resolve_profile_asset_base_dir(config, target_profile)
    # Release file locks before mutating config / deleting directories.
    _release_profile_runtime_locks(removed_asset_dir, removed_resource_dir)
    removed_profile = profiles.pop(target_index)

    active_profile_id = str(models.get("active_profile", "") or "").strip()
    if active_profile_id == profile_id:
        fallback_profiles = [item for item in profiles if isinstance(item, dict) and str(item.get("id", "") or "").strip()]
        models["active_profile"] = str(fallback_profiles[0].get("id", "") or "").strip() if fallback_profiles else ""
    models["profiles"] = profiles
    config["models"] = models
    save_config(config)

    removed_resource = False
    removed_asset = False
    removed_empty_parents = []
    delete_warnings = []
    if removed_resource_dir and os.path.exists(removed_resource_dir):
        ok, error = _rmtree_with_retry(removed_resource_dir)
        removed_resource = ok or not os.path.exists(removed_resource_dir)
        if not removed_resource and error:
            delete_warnings.append(error)
        elif removed_resource:
            resource_parent = os.path.dirname(removed_resource_dir)
            if _remove_empty_dir_if_possible(resource_parent):
                removed_empty_parents.append(resource_parent)
    if removed_asset_dir and os.path.exists(removed_asset_dir):
        ok, error = _rmtree_with_retry(removed_asset_dir)
        removed_asset = ok or not os.path.exists(removed_asset_dir)
        if not removed_asset and error:
            delete_warnings.append(error)
        elif removed_asset:
            asset_parent = os.path.dirname(removed_asset_dir)
            if _remove_empty_dir_if_possible(asset_parent):
                removed_empty_parents.append(asset_parent)

    return {
        "removed_profile_id": profile_id,
        "removed_profile": removed_profile,
        "active_profile": str(models.get("active_profile", "") or "").strip(),
        "removed_resource_dir": removed_resource_dir,
        "removed_asset_dir": removed_asset_dir,
        "removed_resource": removed_resource,
        "removed_asset": removed_asset,
        "removed_empty_parent_dirs": removed_empty_parents,
        "delete_warnings": delete_warnings,
    }


def ensure_default_clip_manifest(config=None):
    """
    Backfill a default model_manifest.json for the legacy/default CLIP profile
    under <model_dir>/openai-clip/<variant>/model_manifest.json.

    Only writes when required ONNX/vocab files are already present — otherwise a
    ghost manifest makes the UI show a non-working OpenAI CLIP profile.
    """
    cfg = dict(config or load_config())
    models = cfg.get("models")
    if not isinstance(models, dict):
        return ""
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        return ""

    target_profile = None
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if str(profile.get("provider", "") or "").strip() != "clip_onnx":
            continue
        target_profile = profile
        if str(profile.get("id", "") or "").strip() == "clip_onnx_default":
            break
    if not isinstance(target_profile, dict):
        return ""

    runtime = dict(target_profile.get("runtime") or {})
    model_root = str(runtime.get("model_dir", "") or "").strip()
    if not model_root:
        model_root = str(cfg.get("model_dir", "") or "").strip()
    if not model_root:
        return ""
    model_root = os.path.normpath(os.path.abspath(os.fspath(model_root)))

    variant = str(runtime.get("model_variant", "") or target_profile.get("model_variant", "") or "").strip() or "vit-base-patch32"
    target_dir = os.path.join(model_root, "openai-clip", variant)
    required_files = _profile_required_files(target_profile) or list(REQUIRED_MODEL_FILES)
    if not all(os.path.isfile(os.path.join(target_dir, name)) for name in required_files):
        return ""
    os.makedirs(target_dir, exist_ok=True)
    manifest_file = os.path.join(target_dir, "model_manifest.json")
    if os.path.exists(manifest_file):
        return manifest_file

    payload = {
        "id": str(target_profile.get("id", "") or "clip_onnx_default"),
        "provider": "clip_onnx",
        "variant": variant,
        "display_name": str(target_profile.get("display_name", "") or "OpenAI CLIP"),
        "prefer_gpu": bool(runtime.get("prefer_gpu", True)),
        "required_files": list(required_files),
        "files": dict(target_profile.get("files") or {}),
    }
    with open(manifest_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return manifest_file


def prune_incomplete_model_profiles(config=None) -> dict:
    """Drop config profiles whose required model files are missing on disk."""
    cfg = dict(config or load_config())
    models = cfg.get("models")
    if not isinstance(models, dict):
        return {"removed": [], "active_profile": "", "changed": False}
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        return {"removed": [], "active_profile": "", "changed": False}

    kept = []
    removed = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id", "") or "").strip()
        if _profile_files_ready(profile):
            kept.append(profile)
            continue
        removed.append(profile_id or "(unnamed)")

    active = str(models.get("active_profile", "") or "").strip()
    changed = len(removed) > 0 or (active and not _find_profile_by_id(kept, active))
    if not changed and len(kept) == len(profiles):
        return {"removed": [], "active_profile": active, "changed": False}

    models["profiles"] = kept
    if kept:
        if not _find_profile_by_id(kept, active) or not _profile_files_ready(_find_profile_by_id(kept, active) or {}):
            models["active_profile"] = _pick_ready_profile_id(kept, [str(p.get("id") or "") for p in kept]) or str(
                kept[0].get("id") or ""
            )
    else:
        models["active_profile"] = ""
    cfg["models"] = models
    save_config(cfg)
    return {
        "removed": removed,
        "active_profile": str(models.get("active_profile", "") or "").strip(),
        "changed": True,
    }


def rediscover_model_profiles(model_root: str | None = None) -> dict:
    """Rescan ``model_dir`` manifests, register complete packs, drop incomplete ghosts.

    Fault-tolerance for lost/corrupt ``models.profiles`` in config.json: as long as
    ONNX packs remain under the model root, one click (or startup auto-scan) restores them.
    """
    cfg = load_config()
    root = str(model_root or "").strip()
    if not root:
        root = str(cfg.get("model_dir", "") or "").strip()
    if not root:
        try:
            from src.storage.config_store import get_effective_model_dir

            root = str(get_effective_model_dir(config=cfg) or "").strip()
        except Exception:
            root = ""
    if not root:
        return {
            "imported": 0,
            "updated": 0,
            "removed": [],
            "errors": ["model_dir is empty"],
            "active_profile": "",
            "active_profile_switched": False,
            "manifests_found": 0,
        }

    root = os.path.normpath(os.path.abspath(os.fspath(root)))
    # Trim accidental provider/variant leaf paths back to the models root.
    try:
        from src.storage.config_store import get_active_model_profile

        profile = get_active_model_profile(config=cfg)
        provider = str(profile.get("provider", "") or "").strip()
        runtime = dict(profile.get("runtime") or {})
        variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
        if provider and variant:
            for provider_dir in iter_provider_resource_dir_candidates(provider):
                expected_tail = os.path.normcase(os.path.normpath(os.path.join(provider_dir, variant)))
                if os.path.normcase(root).endswith(expected_tail):
                    parent = os.path.dirname(os.path.dirname(root))
                    if parent:
                        root = parent
                    break
    except Exception:
        pass

    manifests = _discover_manifest_files(root)
    import_result = import_model_packages(root, manifest_files=manifests or None)
    prune_result = prune_incomplete_model_profiles()
    active_before = str(import_result.get("active_profile", "") or "").strip()
    active_after = str(prune_result.get("active_profile", "") or active_before).strip()
    return {
        "imported": int(import_result.get("imported", 0) or 0),
        "updated": int(import_result.get("updated", 0) or 0),
        "removed": list(prune_result.get("removed") or []),
        "errors": list(import_result.get("errors") or []),
        "active_profile": active_after,
        "active_profile_switched": bool(import_result.get("active_profile_switched")) or (active_before != active_after),
        "manifests_found": len(manifests),
        "model_root": root,
    }

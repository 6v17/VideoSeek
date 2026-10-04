"""Import local model zips and ffmpeg.exe into the VideoSeek data directory.

Same write path as the in-app 「导入并解析」 action. Does not download files.
Does not need a git checkout. An installed VideoSeek is enough: config lives in
%LOCALAPPDATA%\\VideoSeek\\config.json. Close VideoSeek first so it is not
writing that file at the same time.

Default layout (when config.json has not moved these paths):

  %LOCALAPPDATA%\\VideoSeek\\config.json
  %LOCALAPPDATA%\\VideoSeek\\models\\<provider>\\<variant>\\
  %LOCALAPPDATA%\\VideoSeek\\bin\\ffmpeg.exe

  import_runtime_resources.bat --status
  import_runtime_resources.bat D:\\downloads\\openai-clip.zip D:\\downloads\\ffmpeg.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile


def _find_repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    starts = [os.path.dirname(here), here, os.getcwd()]
    seen: set[str] = set()
    for start in starts:
        current = os.path.abspath(start)
        for _ in range(8):
            if current in seen:
                break
            seen.add(current)
            marker = os.path.join(current, "src", "app", "config.py")
            if os.path.isfile(marker):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return ""


def _ensure_repo_on_path() -> bool:
    root = _find_repo_root()
    if not root:
        return False
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def _app_data_dir() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, "VideoSeek")
    return os.path.join(os.path.expanduser("~"), ".videoseek")


def _provider_dir(provider: str) -> str:
    if provider == "clip_onnx":
        return "openai-clip"
    if provider == "siglip2_onnx":
        return "siglip2"
    if provider == "chinese_clip_onnx":
        return "chinese-clip"
    return provider.replace("_", "-")


def _sanitize_profile_id(raw_value: str) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "_", str(raw_value or "").strip().lower()).strip("_")
    return text or "model_profile"


def _load_app_config(config_path: str) -> dict:
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RuntimeError(f"config.json must be a JSON object: {config_path}")
        return payload
    return {"schema_version": 2, "models": {"active_profile": "", "profiles": []}}


def _model_root_from_config(config: dict, app_data: str) -> str:
    root = str(config.get("model_dir") or "").strip()
    if not root:
        root = os.path.join(app_data, "models")
    root = os.path.abspath(root)
    provider_leaf = os.path.basename(os.path.dirname(root)).strip().lower()
    if provider_leaf in {"openai-clip", "siglip2", "chinese-clip", "chinese-clip-onnx"}:
        parent = os.path.dirname(os.path.dirname(root))
        if parent:
            root = parent
    config["model_dir"] = root
    return root


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _matching_sha(zip_path: str, sha_files: list[str]) -> str:
    expected_name = f"{os.path.basename(zip_path)}.sha256".lower()
    for candidate in sha_files:
        if os.path.basename(candidate).lower() == expected_name:
            return candidate
    sibling = f"{zip_path}.sha256"
    if os.path.isfile(sibling):
        return sibling
    return ""


def _verify_sha256(zip_path: str, sha_file: str) -> bool:
    if not sha_file:
        return False
    with open(sha_file, "r", encoding="utf-8") as handle:
        text = handle.read().strip()
    token = text.split()[0].upper() if text else ""
    if not re.fullmatch(r"[0-9A-F]{64}", token):
        raise RuntimeError(f"Invalid checksum file: {sha_file}")
    actual = _sha256_file(zip_path)
    if actual != token:
        raise RuntimeError(f"Checksum mismatch for {os.path.basename(zip_path)}")
    return True


def _safe_extract(zip_path: str, dest: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            normalized = os.path.normpath(member)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise RuntimeError(f"Unsafe zip entry: {member}")
        archive.extractall(dest)


def _default_files_map(provider: str, manifest: dict) -> dict:
    files_map = manifest.get("files")
    if isinstance(files_map, dict) and files_map:
        return files_map
    if provider == "clip_onnx":
        return {
            "visual_model": "clip_visual.onnx",
            "text_model": "clip_text.onnx",
            "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
        }
    if provider == "siglip2_onnx":
        return {
            "vision_model": "vision_model.onnx",
            "text_model": "text_model.onnx",
            "tokenizer_json": "tokenizer.json",
            "tokenizer_config": "tokenizer_config.json",
        }
    if provider == "chinese_clip_onnx":
        return {
            "image_model": "chinese_clip_image.onnx",
            "text_model": "chinese_clip_text.onnx",
            "tokenizer_vocab": "vocab.txt",
            "preprocessor_config": "preprocessor_config.json",
            "model_config": "config.json",
        }
    return {}


def _install_search_tree(extracted_root: str, model_root: str, config: dict) -> dict:
    manifests = []
    for current, _dirs, files in os.walk(extracted_root):
        if "model_manifest.json" in files:
            manifests.append(os.path.join(current, "model_manifest.json"))
    if not manifests:
        raise RuntimeError("No model_manifest.json in zip")
    models = config.get("models")
    if not isinstance(models, dict):
        models = {}
        config["models"] = models
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        profiles = []
        models["profiles"] = profiles
    existing = {}
    for index, profile in enumerate(profiles):
        if isinstance(profile, dict) and str(profile.get("id") or "").strip():
            existing[str(profile.get("id")).strip()] = index
    imported = 0
    updated = 0
    for manifest_file in manifests:
        with open(manifest_file, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise RuntimeError(f"Invalid manifest: {manifest_file}")
        provider = str(manifest.get("provider") or "").strip()
        variant = str(manifest.get("variant") or manifest.get("model_variant") or "").strip()
        if not provider or not variant:
            raise RuntimeError(f"Manifest missing provider/variant: {manifest_file}")
        target_dir = os.path.join(model_root, _provider_dir(provider), variant)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.copytree(os.path.dirname(manifest_file), target_dir)
        profile_id = _sanitize_profile_id(str(manifest.get("id") or f"{provider}_{variant}"))
        runtime = {
            "prefer_gpu": bool(manifest.get("prefer_gpu", True)),
            "model_dir": model_root,
            "model_variant": variant,
        }
        dimension = manifest.get("embedding_dimension", manifest.get("dimension"))
        try:
            dimension_int = int(dimension)
        except (TypeError, ValueError):
            dimension_int = 0
        if dimension_int > 0:
            runtime["embedding_dimension"] = dimension_int
        new_profile = {
            "id": profile_id,
            "provider": provider,
            "display_name": str(manifest.get("display_name") or "").strip() or f"{_provider_dir(provider)} / {variant}",
            "enabled": True,
            "runtime": runtime,
            "files": _default_files_map(provider, manifest),
            "capabilities": {
                "text_query": True,
                "image_query": True,
                "video_embedding": True,
                "cross_modal_search": True,
            },
        }
        if dimension_int > 0:
            new_profile["embedding_dimension"] = dimension_int
            new_profile["capabilities"]["embedding_dimension"] = dimension_int
        if profile_id in existing:
            profiles[existing[profile_id]] = new_profile
            updated += 1
        else:
            profiles.append(new_profile)
            existing[profile_id] = len(profiles) - 1
            imported += 1
        if not str(models.get("active_profile") or "").strip():
            models["active_profile"] = profile_id
    return {"imported": imported, "updated": updated}


def _install_understanding_tree(extracted_root: str, model_root: str) -> str:
    manifest_path = os.path.join(extracted_root, "understanding_manifest.json")
    if not os.path.isfile(manifest_path):
        children = [name for name in os.listdir(extracted_root) if os.path.isdir(os.path.join(extracted_root, name))]
        if len(children) == 1:
            nested = os.path.join(extracted_root, children[0], "understanding_manifest.json")
            if os.path.isfile(nested):
                extracted_root = os.path.join(extracted_root, children[0])
                manifest_path = nested
    if not os.path.isfile(manifest_path):
        raise RuntimeError("Zip must contain understanding_manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise RuntimeError("Invalid understanding_manifest.json")
    relpath = str(manifest.get("install_relpath") or "").strip().replace("\\", "/")
    component_id = str(manifest.get("id") or "").strip()
    if not relpath or not component_id:
        raise RuntimeError("understanding_manifest.json missing id or install_relpath")
    target_dir = os.path.join(model_root, "understanding", relpath.replace("/", os.sep))
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    for name in os.listdir(extracted_root):
        source = os.path.join(extracted_root, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(target_dir, name))
    return component_id


def _classify_extracted(extracted_root: str) -> str:
    for current, _dirs, files in os.walk(extracted_root):
        if "understanding_manifest.json" in files and current == extracted_root:
            return "understanding"
        if "understanding_manifest.json" in files:
            return "understanding"
        if "model_manifest.json" in files:
            return "search"
    return "unknown"


def import_runtime_resources_standalone(paths: list[str], *, app_data_dir: str | None = None) -> dict:
    """Import into the installed app data directory. Standard library only."""
    app_data = os.path.abspath(app_data_dir or _app_data_dir())
    config_path = os.path.join(app_data, "config.json")
    os.makedirs(app_data, exist_ok=True)
    config = _load_app_config(config_path)
    model_root = _model_root_from_config(config, app_data)
    os.makedirs(model_root, exist_ok=True)

    files = [os.path.abspath(os.fspath(path)) for path in paths if str(path or "").strip()]
    ffmpeg_files = []
    zip_files = []
    sha_files = []
    rejected = []
    for path in files:
        name = os.path.basename(path).lower()
        if name == "ffmpeg.exe":
            ffmpeg_files.append(path)
        elif name.endswith(".zip"):
            zip_files.append(path)
        elif name.endswith(".sha256"):
            sha_files.append(path)
        else:
            rejected.append(os.path.basename(path))
    if rejected:
        raise RuntimeError(f"Unsupported runtime file(s): {', '.join(rejected)}")
    if len(ffmpeg_files) > 1:
        raise RuntimeError("Pass one ffmpeg.exe.")
    if sha_files and not zip_files:
        raise RuntimeError("A .sha256 file needs the matching .zip beside it.")

    ffmpeg_result = None
    if ffmpeg_files:
        source = ffmpeg_files[0]
        if not os.path.isfile(source):
            raise RuntimeError(f"FFmpeg file not found: {source}")
        target = str(config.get("ffmpeg_path") or "").strip() or os.path.join(app_data, "bin", "ffmpeg.exe")
        target = os.path.abspath(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        config["ffmpeg_path"] = target
        ffmpeg_result = {"source": source, "target_path": target}

    imported = 0
    updated = 0
    understanding_imported = []
    errors = []
    checksum_verified_count = 0
    for zip_path in zip_files:
        if not os.path.isfile(zip_path) or not zipfile.is_zipfile(zip_path):
            errors.append(f"{os.path.basename(zip_path)}: not a zip")
            continue
        try:
            sha_file = _matching_sha(zip_path, sha_files)
            if _verify_sha256(zip_path, sha_file):
                checksum_verified_count += 1
            os.makedirs(model_root, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="videoseek-import-", dir=model_root) as temp_dir:
                extracted = os.path.join(temp_dir, "extracted")
                os.makedirs(extracted, exist_ok=True)
                _safe_extract(zip_path, extracted)
                kind = _classify_extracted(extracted)
                if kind == "understanding":
                    understanding_imported.append(_install_understanding_tree(extracted, model_root))
                    imported += 1
                elif kind == "search":
                    result = _install_search_tree(extracted, model_root, config)
                    imported += int(result["imported"])
                    updated += int(result["updated"])
                else:
                    errors.append(f"{os.path.basename(zip_path)}: unrecognized package")
        except Exception as exc:
            errors.append(f"{os.path.basename(zip_path)}: {exc}")

    if ffmpeg_files or zip_files:
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    return {
        "config_file": config_path,
        "model_root": model_root,
        "ffmpeg": ffmpeg_result,
        "packages": {
            "imported": imported,
            "updated": updated,
            "understanding_imported": understanding_imported,
            "errors": errors,
            "checksum_verified_count": checksum_verified_count,
        },
        "mode": "installed-app",
    }


def _print_payload(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import model zips and ffmpeg.exe into VideoSeek's data directory and config.json.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Local model .zip (optional sibling .sha256) and/or ffmpeg.exe.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print whether models and FFmpeg are already in place. Does not import.",
    )
    args = parser.parse_args(argv)
    if not args.status and not args.files:
        parser.error("pass at least one zip or ffmpeg.exe, or use --status")

    if _ensure_repo_on_path():
        from src.app.config import CONFIG_FILE, load_config
        from src.services.runtime_resource_service import (
            _resolve_runtime_model_root_dir,
            get_runtime_resource_status,
            import_runtime_resources,
        )

        if args.status and not args.files:
            config = load_config()
            _print_payload(
                {
                    "config_file": CONFIG_FILE,
                    "model_root": _resolve_runtime_model_root_dir(config),
                    "status": get_runtime_resource_status(),
                }
            )
            return 0
        try:
            payload = import_runtime_resources(args.files)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _print_payload(payload)
        packages = payload.get("packages") or {}
        errors = [str(item) for item in packages.get("errors", []) if str(item).strip()]
        return 1 if errors else 0

    try:
        if args.status and not args.files:
            payload = import_runtime_resources_standalone([])
            payload["packages"] = None
        else:
            payload = import_runtime_resources_standalone(args.files)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_payload(payload)
    packages = payload.get("packages") or {}
    errors = [str(item) for item in packages.get("errors", []) if str(item).strip()]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

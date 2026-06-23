from __future__ import annotations

import json
import os
import re
import hashlib
import shutil
import tempfile
import zipfile

from src.services.understanding_paths import get_understanding_root
from src.services.understanding_resource_service import (
    SEARCH_MODEL_MANIFEST_FILENAME,
    UNDERSTANDING_MANIFEST_FILENAME,
    scan_understanding_components,
    validate_component_manifest,
)


def _normalize_zip_member_path(member: str) -> str:
    return os.path.normpath(str(member or "").replace("\\", "/")).replace("\\", "/")


def zip_has_root_file(zip_path: str, filename: str) -> bool:
    target = str(filename or "").strip().replace("\\", "/")
    if not target:
        return False
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            normalized = _normalize_zip_member_path(member).lstrip("./")
            if normalized == target:
                return True
    return False


def zip_contains_file_suffix(zip_path: str, suffix: str) -> bool:
    normalized_suffix = str(suffix or "").strip().replace("\\", "/")
    if not normalized_suffix:
        return False
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            normalized = _normalize_zip_member_path(member).lstrip("./")
            if normalized.endswith(normalized_suffix):
                return True
    return False


def classify_package_zip(zip_path: str) -> str:
    if zip_has_root_file(zip_path, UNDERSTANDING_MANIFEST_FILENAME):
        if zip_contains_file_suffix(zip_path, SEARCH_MODEL_MANIFEST_FILENAME):
            raise RuntimeError(
                f"Package {os.path.basename(zip_path)} contains both "
                f"{UNDERSTANDING_MANIFEST_FILENAME} and {SEARCH_MODEL_MANIFEST_FILENAME}"
            )
        return "understanding"
    if zip_contains_file_suffix(zip_path, SEARCH_MODEL_MANIFEST_FILENAME):
        return "search"
    return "unknown"

_SHA256_PATTERN = re.compile(r"^[0-9A-F]{64}$")


def _sha256_file(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _parse_sha256_text(text: str) -> str:
    line = str(text or "").strip()
    if not line:
        return ""
    token = line.split()[0].strip().upper()
    if len(token) != 64 or _SHA256_PATTERN.fullmatch(token) is None:
        return ""
    return token


def _read_expected_sha256(zip_path: str, sha256_file: str | None = None) -> str:
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


def _safe_extract_zip(zip_path: str, output_dir: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            normalized = os.path.normpath(member)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise RuntimeError(f"Unsafe zip entry detected: {member}")
        archive.extractall(output_dir)


def _validate_extracted_component_package(extract_dir: str) -> dict:
    extract_dir = os.path.normpath(extract_dir)
    root_manifest_path = os.path.join(extract_dir, UNDERSTANDING_MANIFEST_FILENAME)
    if not os.path.isfile(root_manifest_path):
        raise RuntimeError("Zip must contain understanding_manifest.json at root")

    nested_manifests: list[str] = []
    for current_root, _dirs, files in os.walk(extract_dir):
        if current_root == extract_dir:
            continue
        if UNDERSTANDING_MANIFEST_FILENAME in files:
            nested_manifests.append(os.path.join(current_root, UNDERSTANDING_MANIFEST_FILENAME))
    if nested_manifests:
        raise RuntimeError("Nested understanding_manifest.json is not allowed")

    root_entries = os.listdir(extract_dir)
    if "components" in root_entries and os.path.isdir(os.path.join(extract_dir, "components")):
        raise RuntimeError("Zip must not contain a components/ directory tree")

    payload_files = [
        name
        for name in root_entries
        if name != UNDERSTANDING_MANIFEST_FILENAME and os.path.isfile(os.path.join(extract_dir, name))
    ]
    if not payload_files:
        raise RuntimeError("Zip must include model files besides understanding_manifest.json")

    with open(root_manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    try:
        return validate_component_manifest(manifest)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _install_extracted_component(extract_dir: str, model_root: str, manifest: dict) -> str:
    install_relpath = str(manifest.get("install_relpath", "") or "").strip().replace("\\", "/")
    if not install_relpath:
        raise RuntimeError("Manifest missing install_relpath")

    target_dir = os.path.join(get_understanding_root(model_root), install_relpath.replace("/", os.sep))
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    for name in os.listdir(extract_dir):
        source_path = os.path.join(extract_dir, name)
        if os.path.isfile(source_path):
            shutil.copy2(source_path, os.path.join(target_dir, name))

    validate_component_manifest(manifest, component_dir=target_dir)
    return str(manifest.get("id", "") or "").strip()


def import_understanding_component_zip(
    model_dir: str,
    zip_path: str,
    *,
    sha256_file: str | None = None,
    require_checksum: bool = False,
) -> dict:
    root = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
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

    existed_before = {
        str(item.get("id", "") or "").strip()
        for item in scan_understanding_components(model_dir=root)
        if item.get("installed")
    }

    with tempfile.TemporaryDirectory(prefix="videoseek-understanding-pack-") as temp_dir:
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _safe_extract_zip(zip_path, extract_dir)
        manifest = _validate_extracted_component_package(extract_dir)
        component_id = _install_extracted_component(extract_dir, root, manifest)

    if not component_id:
        raise RuntimeError("Installed component is missing id")

    return {
        "component_id": component_id,
        "install_dir": os.path.join(
            get_understanding_root(root),
            str(manifest.get("install_relpath", "") or "").replace("\\", "/").replace("/", os.sep),
        ),
        "updated": component_id in existed_before,
        "imported": component_id not in existed_before,
        "checksum_verified": bool(expected_sha256),
        "components": scan_understanding_components(model_dir=root),
    }


def import_understanding_component_zips(
    model_dir: str,
    zip_paths: list[str],
    *,
    sha256_files: list[str] | None = None,
    continue_on_error: bool = True,
) -> dict:
    root = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
    zip_items = [str(path or "").strip() for path in (zip_paths or []) if str(path or "").strip()]
    sha_items = [str(path or "").strip() for path in (sha256_files or []) if str(path or "").strip()]

    imported: list[str] = []
    updated: list[str] = []
    errors: list[str] = []
    checksum_verified_count = 0

    for zip_path in zip_items:
        if not zip_path.lower().endswith(".zip"):
            continue
        matching_sha = ""
        expected_name = f"{os.path.basename(zip_path)}.sha256".lower()
        for candidate in sha_items:
            if os.path.basename(candidate).lower() == expected_name:
                matching_sha = candidate
                break
        try:
            result = import_understanding_component_zip(root, zip_path, sha256_file=matching_sha or None)
            component_id = str(result.get("component_id", "") or "").strip()
            if result.get("updated"):
                updated.append(component_id)
            else:
                imported.append(component_id)
            if result.get("checksum_verified"):
                checksum_verified_count += 1
        except Exception as exc:
            errors.append(f"{os.path.basename(zip_path)}: {exc}")
            if not continue_on_error:
                break

    return {
        "imported": imported,
        "updated": updated,
        "errors": errors,
        "checksum_verified_count": checksum_verified_count,
        "components": scan_understanding_components(model_dir=root),
    }

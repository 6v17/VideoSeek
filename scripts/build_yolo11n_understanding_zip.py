"""Build VideoSeek understanding component zip for YOLO11n."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

SOURCE_DIR = Path(r"C:\Users\LiuWei\Desktop\yolo11n")
OUTPUT_ZIP = Path(r"C:\Users\LiuWei\Desktop\vision-object-detection-yolo11n.zip")
MANIFEST_NAME = "understanding_manifest.json"
MODEL_NAME = "yolo11n.onnx"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_id = str(manifest.get("model_id", "")).strip()
    modality = str(manifest.get("modality", "")).strip()
    task = str(manifest.get("task", "")).strip()
    expected_id = f"{modality}/{task}/{model_id}"
    expected_relpath = f"components/{modality}/{task}/{model_id}"

    if manifest.get("kind") != "understanding_component":
        raise ValueError("kind must be understanding_component")
    if manifest.get("id") != expected_id:
        raise ValueError(f"id must be {expected_id!r}, got {manifest.get('id')!r}")
    if manifest.get("install_relpath") != expected_relpath:
        raise ValueError(
            f"install_relpath must be {expected_relpath!r}, got {manifest.get('install_relpath')!r}"
        )

    required_files = list(manifest.get("required_files") or [])
    for name in required_files:
        file_path = manifest_path.parent / name
        if not file_path.is_file() or file_path.stat().st_size <= 0:
            raise ValueError(f"required file missing or empty: {name}")

    return manifest


def build_zip() -> None:
    manifest_path = SOURCE_DIR / MANIFEST_NAME
    model_path = SOURCE_DIR / MODEL_NAME
    validate_manifest(manifest_path)

    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, MANIFEST_NAME)
        archive.write(model_path, MODEL_NAME)

    checksum = sha256_file(OUTPUT_ZIP)
    checksum_path = OUTPUT_ZIP.with_suffix(".zip.sha256")
    checksum_path.write_text(f"{checksum}  {OUTPUT_ZIP.name}\n", encoding="utf-8")

    print(f"Created: {OUTPUT_ZIP}")
    print(f"SHA256:  {checksum_path}")
    print(f"Files:   {MANIFEST_NAME}, {MODEL_NAME}")


if __name__ == "__main__":
    build_zip()

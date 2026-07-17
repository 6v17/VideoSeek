#!/usr/bin/env python3
"""Download Faster-Whisper medium and pack an understanding import zip.

Examples:
  python scripts/pack_faster_whisper_understanding_zip.py --mirror

Defaults (Desktop, fixed):
  - download/cache: ~/Desktop/faster-whisper-medium/
  - output zip:     ~/Desktop/faster-whisper-medium-understanding.zip

Notes:
  - Reuses the Desktop cache if files are already complete (no re-download).
  - model.bin is stored uncompressed in the zip (saves peak disk use).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "resources"
    / "understanding_packages"
    / "audio-speech-to-text-faster-whisper-medium"
    / "understanding_manifest.json"
)
DEFAULT_CACHE_DIR = DESKTOP / "faster-whisper-medium"
DEFAULT_OUTPUT_ZIP = DESKTOP / "faster-whisper-medium-understanding.zip"
DEFAULT_HF_REPO = "Systran/faster-whisper-medium"
DEFAULT_MIRROR = "https://hf-mirror.com"
REQUIRED = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def _apply_endpoint(endpoint: str) -> None:
    value = str(endpoint or "").strip().rstrip("/")
    if not value:
        return
    os.environ["HF_ENDPOINT"] = value
    print(f"Using HF endpoint: {value}", flush=True)


def _disk_free_bytes(path: Path) -> int | None:
    try:
        usage = shutil.disk_usage(str(path if path.exists() else path.parent))
        return int(usage.free)
    except Exception:
        return None


def _fmt_gb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 ** 3):.2f} GB"


def _ensure_space(path: Path, need_bytes: int, label: str) -> None:
    free = _disk_free_bytes(path)
    if free is None:
        return
    if free < need_bytes:
        raise SystemExit(
            f"Not enough free space for {label}.\n"
            f"Need about {_fmt_gb(need_bytes)}, free on {path.drive or path}: {_fmt_gb(free)}.\n"
            "Free disk space, or pass --output / --cache-dir on a roomier drive."
        )


def _model_ready(model_dir: Path) -> bool:
    return all((model_dir / name).is_file() and (model_dir / name).stat().st_size > 0 for name in REQUIRED)


def _download_model(repo_id: str, target_dir: Path, *, max_retries: int = 3) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required. Install with: pip install huggingface_hub"
        ) from exc

    target_dir.mkdir(parents=True, exist_ok=True)
    last_error: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Downloading {repo_id} (attempt {attempt}/{max_retries}) ...", flush=True)
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(target_dir),
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Download failed: {exc}", flush=True)
    assert last_error is not None
    hint = (
        "\nHugging Face download failed (network / reset).\n"
        "Try:\n"
        f"  1) python scripts/pack_faster_whisper_understanding_zip.py --mirror\n"
        f"  2) set HF_ENDPOINT={DEFAULT_MIRROR}\n"
        "  3) Manual download, then --model-dir <folder>\n"
        f"     {DEFAULT_MIRROR}/{DEFAULT_HF_REPO}\n"
    )
    raise SystemExit(hint + f"\nLast error: {last_error}") from last_error


def _validate_files(model_dir: Path) -> None:
    missing = [name for name in REQUIRED if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit(f"Model folder missing required files: {', '.join(missing)}\nDir: {model_dir}")


def _write_zip(model_dir: Path, manifest_path: Path, output_zip: Path) -> None:
    output_zip = output_zip.resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    # model.bin ~1.5GB and barely compresses; STORED avoids a second huge temp write.
    total_src = sum((model_dir / name).stat().st_size for name in REQUIRED if (model_dir / name).is_file())
    total_src += manifest_path.stat().st_size
    _ensure_space(output_zip.parent, int(total_src * 1.05) + (64 * 1024 * 1024), "writing zip")

    if output_zip.exists():
        output_zip.unlink()

    print(f"Writing zip -> {output_zip}", flush=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.write(manifest_path, arcname="understanding_manifest.json")
        for path in sorted(model_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.name in {"README.md", ".gitattributes"}:
                continue
            print(f"  + {path.name} ({_fmt_gb(path.stat().st_size)})", flush=True)
            archive.write(path, arcname=path.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_HF_REPO, help=f"HF repo id (default: {DEFAULT_HF_REPO})")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="understanding_manifest.json template")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_ZIP),
        help=f"Output zip path (default: {DEFAULT_OUTPUT_ZIP})",
    )
    parser.add_argument(
        "--model-dir",
        default="",
        help="Existing local model directory (skip download)",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help=f"Download cache dir (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument("--mirror", action="store_true", help=f"Use {DEFAULT_MIRROR}")
    parser.add_argument("--endpoint", default="", help="Custom HF endpoint")
    parser.add_argument("--retries", type=int, default=3, help="Download retries")
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download even if cache already has required files",
    )
    args = parser.parse_args(argv)

    if args.mirror and not args.endpoint:
        _apply_endpoint(DEFAULT_MIRROR)
    elif args.endpoint:
        _apply_endpoint(args.endpoint)
    elif os.environ.get("HF_ENDPOINT"):
        print(f"Using existing HF_ENDPOINT={os.environ['HF_ENDPOINT']}", flush=True)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("kind") != "understanding_component":
        raise SystemExit("Manifest kind must be understanding_component")

    output_zip = Path(args.output)
    if args.model_dir:
        model_dir = Path(args.model_dir)
        if not model_dir.is_dir():
            raise SystemExit(f"Model dir not found: {model_dir}")
        _validate_files(model_dir)
        _write_zip(model_dir, manifest_path, output_zip)
    else:
        model_dir = Path(args.cache_dir)
        if _model_ready(model_dir) and not args.force_download:
            print(f"Using cached model dir: {model_dir}", flush=True)
        else:
            # ~1.6GB download + slack
            _ensure_space(model_dir if model_dir.exists() else model_dir.parent, int(1.8 * 1024**3), "download cache")
            _download_model(args.repo, model_dir, max_retries=max(1, int(args.retries)))
        _validate_files(model_dir)
        _write_zip(model_dir, manifest_path, output_zip)

    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"Wrote {output_zip} ({size_mb:.1f} MB)")
    print("Import in VideoSeek: Understanding / Settings → Import Model")
    print(f"Cache kept at: {args.model_dir or args.cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

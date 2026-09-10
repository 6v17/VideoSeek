"""Zip a prepared provider/variant model directory for VideoSeek import.

Expects ``model_manifest.json`` plus required ONNX/sidecars already present.

Examples:
    python scripts/pack_vision_model_zip.py --pack vit-large-patch14
    python scripts/pack_vision_model_zip.py --dir models/siglip2/so400m-patch14-224 \\
        --out dist/models/siglip2-so400m-patch14-224.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.vision_model_pack_specs import LARGE_224_PACKS, get_pack_spec  # noqa: E402


def _load_manifest(model_dir: Path) -> dict:
    manifest_path = model_dir / "model_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Missing model_manifest.json under {model_dir}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid manifest JSON: {manifest_path}")
    return payload


def _required_files(manifest: dict) -> list[str]:
    required = manifest.get("required_files")
    if isinstance(required, list) and required:
        return [str(item).strip() for item in required if str(item).strip()]
    provider = str(manifest.get("provider", "") or "").strip()
    from src.services.model_package_service import PROVIDER_REQUIRED_MODEL_FILES

    return list(PROVIDER_REQUIRED_MODEL_FILES.get(provider, []))


def _zip_model_dir(model_dir: Path, provider_dir: str, variant: str, out_path: Path) -> None:
    manifest = _load_manifest(model_dir)
    missing = [name for name in _required_files(manifest) if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit(f"Missing required files under {model_dir}: {', '.join(missing)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    arc_prefix = f"{provider_dir}/{variant}"
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(model_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(model_dir).as_posix()
            archive.write(path, f"{arc_prefix}/{relative}")
    print(f"wrote zip -> {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack a vision model directory into an import zip.")
    parser.add_argument("--pack", type=str, default="", help="Pack key/variant from vision_model_pack_specs")
    parser.add_argument("--dir", type=Path, default=None, help="Prepared model directory")
    parser.add_argument("--out", type=Path, default=None, help="Output zip path")
    parser.add_argument("--list", action="store_true", help="List known large-224 packs and exit")
    args = parser.parse_args()

    if args.list:
        for item in LARGE_224_PACKS:
            print(
                f"{item['key']}: provider={item['provider']} variant={item['variant']} "
                f"dim={item['embedding_dimension']} hf={item['hf_id']}"
            )
        return 0

    if args.pack:
        spec = get_pack_spec(args.pack)
        model_dir = args.dir or (ROOT / "models" / spec["provider_dir"] / spec["variant"])
        out_path = args.out or (
            ROOT / "dist" / "models" / f"{spec['provider_dir']}-{spec['variant']}.zip"
        )
        _zip_model_dir(model_dir.resolve(), spec["provider_dir"], spec["variant"], out_path.resolve())
        return 0

    if args.dir is None:
        raise SystemExit("Provide --pack or --dir")
    model_dir = args.dir.resolve()
    manifest = _load_manifest(model_dir)
    provider = str(manifest.get("provider", "") or "").strip()
    variant = str(manifest.get("variant", "") or "").strip()
    if not provider or not variant:
        raise SystemExit("manifest must include provider and variant")
    from src.storage.config_store import resolve_provider_dir

    provider_dir = resolve_provider_dir(provider)
    out_path = (args.out or (ROOT / "dist" / "models" / f"{provider_dir}-{variant}.zip")).resolve()
    _zip_model_dir(model_dir, provider_dir, variant, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

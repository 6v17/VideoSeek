"""Import existing per-video *_vectors.npy into LanceDB (no search switch, no deletion).

Run with conda VideoSeek env:

  conda activate VideoSeek
  python scripts/import_npy_to_lance.py
  python scripts/import_npy_to_lance.py --profile "C:/Users/.../model_assets/clip_onnx/vit-base-patch32"
  python scripts/import_npy_to_lance.py --all-profiles
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import load_config
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.lance_store import import_all_model_profiles_to_lance, import_npy_to_lance


def _print_summary(summary: dict) -> None:
    label = summary.get("label")
    if label:
        print(f"\n=== profile: {label} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import VideoSeek npy vectors into LanceDB.")
    parser.add_argument(
        "--profile",
        help="Model profile base dir (contains meta.json, vector/, index/). Defaults to active profile.",
    )
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Import every on-disk model profile under data/model_assets/.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Do not drop existing Lance tables; upsert per video.",
    )
    args = parser.parse_args(argv)

    replace_existing = not args.incremental

    if args.all_profiles:
        summaries = import_all_model_profiles_to_lance(
            config=load_config(),
            replace_existing=replace_existing,
            progress_callback=lambda percent, message: print(f"[{percent:3d}%] {message}"),
        )
        for summary in summaries:
            _print_summary(summary)
        failed = sum(int(item.get("videos_failed", 0)) for item in summaries)
        return 1 if failed else 0

    if args.profile:
        profile_base_dir = os.path.normpath(args.profile)
    else:
        profile_base_dir = get_local_model_asset_dirs(config=load_config())["base_dir"]

    if not os.path.isdir(profile_base_dir):
        print(f"Profile base dir not found: {profile_base_dir}", file=sys.stderr)
        return 2

    summary = import_npy_to_lance(
        profile_base_dir,
        replace_existing=replace_existing,
        progress_callback=lambda percent, message: print(f"[{percent:3d}%] {message}"),
    )
    _print_summary(summary)
    return 1 if summary.get("videos_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())

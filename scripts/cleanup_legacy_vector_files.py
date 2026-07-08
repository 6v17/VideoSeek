"""Remove legacy npy/faiss vector files after Lance migration.

Run only when Lance search is verified working:

  conda activate VideoSeek
  python scripts/cleanup_legacy_vector_files.py --dry-run
  python scripts/cleanup_legacy_vector_files.py --yes
"""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import load_config
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.lance_migration_runner import (
    cleanup_legacy_vector_paths,
    collect_legacy_vector_paths,
)
from src.storage.lance_store import should_use_lance_storage
from src.storage.video_id_migration import iter_model_asset_storage_roots


def _path_size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete legacy npy/faiss assets when Lance is active.")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be deleted.")
    parser.add_argument("--yes", action="store_true", help="Perform deletion without interactive prompt.")
    args = parser.parse_args(argv)

    config = load_config()
    if not should_use_lance_storage(config):
        print("Lance storage is not active for the current profile. Aborting.", file=sys.stderr)
        return 2

    active_dirs = get_local_model_asset_dirs(config=config)
    profiles = list(iter_model_asset_storage_roots(config=config))
    if not profiles:
        profiles = [{"label": "active", "base_dir": active_dirs["base_dir"]}]

    total_bytes = 0
    planned: list[tuple[str, list[str]]] = []
    for profile in profiles:
        base_dir = profile["base_dir"]
        if not should_use_lance_storage(config, profile_base_dir=base_dir):
            continue
        targets = collect_legacy_vector_paths(base_dir)
        if targets:
            planned.append((str(profile.get("label", base_dir)), targets))
            total_bytes += sum(_path_size(path) for path in targets)

    if not planned:
        print("No legacy vector files found to clean up.")
        return 0

    print(f"Profiles to clean: {len(planned)}")
    print(f"Estimated reclaim: {total_bytes / (1024 * 1024):.1f} MB")
    for label, targets in planned:
        print(f"\n[{label}] {len(targets)} path(s)")
        for path in targets[:10]:
            print(f"  - {path}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more")

    if args.dry_run:
        print("\nDry run only; nothing deleted.")
        return 0
    if not args.yes:
        print("\nRe-run with --yes to delete.", file=sys.stderr)
        return 1

    removed = 0
    for _label, targets in planned:
        removed += cleanup_legacy_vector_paths(targets)
    print(f"\nRemoved {removed} legacy path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

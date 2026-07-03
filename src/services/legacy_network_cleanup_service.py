"""Scan and remove legacy remote / network-library assets."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from src.app.config import get_data_storage_paths, load_config


@dataclass
class LegacyNetworkScan:
    paths: list[str] = field(default_factory=list)
    total_bytes: int = 0
    groups: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class LegacyNetworkCleanupResult:
    deleted_count: int = 0
    freed_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def scan_legacy_network_assets(config=None) -> LegacyNetworkScan:
    cfg = dict(config or load_config())
    storage = get_data_storage_paths(cfg)
    data_dir = storage["data_dir"]
    groups: dict[str, list[str]] = {
        "model_remote": [],
        "legacy_flat": [],
        "cache": [],
    }
    paths: list[str] = []

    model_assets_root = os.path.join(data_dir, "model_assets")
    if os.path.isdir(model_assets_root):
        for root, dirs, _files in os.walk(model_assets_root):
            if os.path.basename(root).lower() == "remote":
                groups["model_remote"].append(root)
            for name in dirs:
                if name.lower() == "remote":
                    candidate = os.path.join(root, name)
                    if candidate not in groups["model_remote"]:
                        groups["model_remote"].append(candidate)

    for rel in ("remote",):
        flat = os.path.join(data_dir, rel)
        if os.path.isdir(flat):
            groups["legacy_flat"].append(flat)

    for rel in ("remote_build_cache", "link_cache"):
        cache_dir = os.path.join(data_dir, rel)
        if os.path.isdir(cache_dir):
            groups["cache"].append(cache_dir)

    for bucket in groups.values():
        for path in bucket:
            if path not in paths:
                paths.append(path)

    total_bytes = sum(_dir_size(path) for path in paths)
    return LegacyNetworkScan(paths=paths, total_bytes=total_bytes, groups=groups)


def clear_legacy_network_assets(config=None) -> LegacyNetworkCleanupResult:
    scan = scan_legacy_network_assets(config=config)
    deleted = 0
    freed = 0
    errors: list[str] = []
    for path in scan.paths:
        if not os.path.exists(path):
            continue
        size = _dir_size(path)
        try:
            shutil.rmtree(path)
            deleted += 1
            freed += size
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return LegacyNetworkCleanupResult(deleted_count=deleted, freed_bytes=freed, errors=errors)


def _dir_size(path: str) -> int:
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total

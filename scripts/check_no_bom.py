#!/usr/bin/env python3
"""Fail if any git-tracked file starts with a UTF-8 BOM.

BOM in ``pyproject.toml`` breaks tomllib / pip / pytest collection while Ruff
may still pass — keep this check in CI and run locally before push.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

_BOM = b"\xef\xbb\xbf"


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [name for name in result.stdout.decode("utf-8", errors="replace").split("\0") if name]


def main() -> int:
    bad: list[str] = []
    for name in _tracked_files():
        path = pathlib.Path(name)
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            print(f"skip unreadable {name}: {exc}", file=sys.stderr)
            continue
        if raw.startswith(_BOM):
            bad.append(name)
    if bad:
        print("UTF-8 BOM found in tracked files (save as UTF-8 without BOM):")
        for name in bad:
            print(f"  {name}")
        return 1
    print("No UTF-8 BOM in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

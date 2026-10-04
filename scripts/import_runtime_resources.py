"""Import local model zips and ffmpeg.exe into the VideoSeek data directory.

Same write path as the in-app 「导入并解析」 action. Does not download files.
Close VideoSeek first so it is not writing config.json at the same time.

Default layout (when config.json has not moved these paths):

  %LOCALAPPDATA%\\VideoSeek\\config.json
  %LOCALAPPDATA%\\VideoSeek\\models\\<provider>\\<variant>\\
  %LOCALAPPDATA%\\VideoSeek\\bin\\ffmpeg.exe

  import_runtime_resources.bat --status
  import_runtime_resources.bat D:\\downloads\\openai-clip.zip D:\\downloads\\ffmpeg.exe
"""
from __future__ import annotations

import argparse
import json
import os
import sys


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
        print(
            "VideoSeek source was not found. Keep this script beside a checkout "
            "of https://github.com/6v17/VideoSeek (the scripts directory, or any "
            "folder inside that checkout) and run it again.",
            file=sys.stderr,
        )
        return False
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


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
    if not _ensure_repo_on_path():
        return 1

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

    if not args.files:
        parser.error("pass at least one zip or ffmpeg.exe, or use --status")

    try:
        payload = import_runtime_resources(args.files)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _print_payload(payload)
    packages = payload.get("packages") or {}
    errors = [str(item) for item in packages.get("errors", []) if str(item).strip()]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

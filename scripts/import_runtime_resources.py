"""Import local model zips and ffmpeg.exe into the VideoSeek data directory.

Same write path as the in-app 「导入并解析」 action. Does not download files.
Close VideoSeek first so it is not writing config.json at the same time.

Default layout (when config.json has not moved these paths):

  %LOCALAPPDATA%\\VideoSeek\\config.json
  %LOCALAPPDATA%\\VideoSeek\\models\\<provider>\\<variant>\\
  %LOCALAPPDATA%\\VideoSeek\\bin\\ffmpeg.exe

  scripts\\import_runtime_resources.bat --status
  scripts\\import_runtime_resources.bat D:\\downloads\\openai-clip.zip D:\\downloads\\ffmpeg.exe
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import CONFIG_FILE, load_config
from src.services.runtime_resource_service import (
    _resolve_runtime_model_root_dir,
    get_runtime_resource_status,
    import_runtime_resources,
)


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

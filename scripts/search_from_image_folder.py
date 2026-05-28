#!/usr/bin/env python3
"""Batch image search via VideoSeek Agent API → cuts.json.

Usage:
  python scripts/search_from_image_folder.py "C:\\Users\\LiuWei\\Pictures\\Screenshots"
  python scripts/search_from_image_folder.py "C:\\path\\to\\folder" --top-k 5 --mode chunk
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:8765/api/v1"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _request(method: str, url: str, body: dict | None = None, timeout: float = 600.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")
    files = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Image folder → VideoSeek batch search → cuts.json")
    parser.add_argument("image_folder", type=Path, help="Folder of reference screenshots")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Agent API base (default: %(default)s)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mode", choices=("chunk", "frame"), default="chunk")
    parser.add_argument("--keep", type=int, default=2, help="Max hits to keep per image")
    parser.add_argument("--pad-before", type=float, default=3.0)
    parser.add_argument("--pad-after", type=float, default=3.0)
    parser.add_argument("-o", "--output", type=Path, default=Path("cuts-from-screenshots.json"))
    parser.add_argument("--project", default="screenshots-rough")
    args = parser.parse_args()

    folder = args.image_folder.expanduser().resolve()
    images = _list_images(folder)
    if not images:
        print(f"No images ({', '.join(sorted(IMAGE_EXTS))}) in: {folder}", file=sys.stderr)
        return 1

    print(f"Found {len(images)} image(s) in {folder}")
    for p in images:
        print(f"  - {p.name}")

    health_url = f"{args.base_url.rstrip('/')}/health?mode={args.mode}"
    try:
        health = _request("GET", health_url, timeout=10.0)
    except urllib.error.URLError as exc:
        print(
            "Cannot reach Agent API. Is VideoSeek running with Agent API enabled?\n"
            "  Settings → General → Agent API (localhost) → On\n"
            f"  URL: {health_url}\n"
            f"  Error: {exc}",
            file=sys.stderr,
        )
        return 2

    if not health.get("index_ready"):
        print(
            "Index not ready. Open VideoSeek and sync the library first.\n"
            f"  health: {json.dumps(health, ensure_ascii=False, indent=2)}",
            file=sys.stderr,
        )
        return 3

    print(f"Index OK: {health.get('video_count')} videos, mode={args.mode}")

    batch_url = f"{args.base_url.rstrip('/')}/search/batch"
    payload = {
        "image_folder": str(folder),
        "top_k": args.top_k,
        "mode": args.mode,
        "continue_on_error": True,
    }
    print("Searching (may take a while)...")
    try:
        batch = _request("POST", batch_url, payload, timeout=600.0)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Batch search failed HTTP {exc.code}: {body}", file=sys.stderr)
        return 4

    results = batch.get("results") or []
    succeeded = sum(1 for r in results if r.get("ok"))
    failed = len(results) - succeeded
    print(f"Done: {succeeded} ok, {failed} failed, elapsed_ms={batch.get('meta', {}).get('elapsed_ms')}")

    for block in results:
        cid = block.get("client_request_id", "?")
        if block.get("ok"):
            n = len(block.get("hits") or [])
            top = (block.get("hits") or [{}])[0]
            print(
                f"  [ok] {cid}: {n} hit(s)"
                + (
                    f" → {top.get('video_path')} @ {top.get('start_timecode', top.get('start_sec'))}-{top.get('end_timecode', top.get('end_sec'))}"
                    if n
                    else " (empty)"
                )
            )
        else:
            err = block.get("error") or {}
            print(f"  [fail] {cid}: {err.get('code')} — {err.get('message')}")

    manifest_url = f"{args.base_url.rstrip('/')}/export/manifest"
    manifest_payload = {
        "project": args.project,
        "sources": results,
        "keep_per_source": args.keep,
        "dedupe": True,
        "write_path": str(args.output.resolve()),
    }
    try:
        manifest = _request("POST", manifest_url, manifest_payload, timeout=30.0)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Manifest export failed HTTP {exc.code}: {body}", file=sys.stderr)
        return 5

    items = (manifest.get("manifest") or {}).get("items") or []
    print(f"Wrote {len(items)} clip(s) → {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

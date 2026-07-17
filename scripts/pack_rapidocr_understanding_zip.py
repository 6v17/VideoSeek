#!/usr/bin/env python3
"""Download PP-OCRv4 Chinese ONNX models and pack an understanding zip for RapidOCR.

Default output: Desktop/rapidocr-zh-understanding.zip
Models cached under Desktop/rapidocr-zh/ unless --cache is set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile

MODEL_FILES = {
    "ch_PP-OCRv4_det_infer.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.4.0/"
        "onnx/PP-OCRv4/det/ch_PP-OCRv4_det_infer.onnx"
    ),
    "ch_PP-OCRv4_rec_infer.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.4.0/"
        "onnx/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer.onnx"
    ),
    "ch_ppocr_mobile_v2.0_cls_infer.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.4.0/"
        "onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx"
    ),
}


def _desktop() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _download(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest) and os.path.getsize(dest) > 1024:
        print(f"reuse {dest}")
        return
    print(f"download {url}")
    tmp = f"{dest}.tmp"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=os.path.join(_desktop(), "rapidocr-zh"))
    parser.add_argument("--out", default=os.path.join(_desktop(), "rapidocr-zh-understanding.zip"))
    parser.add_argument(
        "--manifest",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "resources",
            "understanding_packages",
            "vision-ocr-rapidocr-zh",
            "understanding_manifest.json",
        ),
    )
    args = parser.parse_args()

    cache = os.path.abspath(args.cache)
    os.makedirs(cache, exist_ok=True)
    for name, url in MODEL_FILES.items():
        try:
            _download(url, os.path.join(cache, name))
        except Exception as exc:
            print(f"WARN skip {name}: {exc}", file=sys.stderr)

    det = os.path.join(cache, "ch_PP-OCRv4_det_infer.onnx")
    rec = os.path.join(cache, "ch_PP-OCRv4_rec_infer.onnx")
    if not (os.path.isfile(det) and os.path.isfile(rec)):
        print("det/rec models missing; abort", file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    staging = os.path.join(cache, "_stage")
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    for name in MODEL_FILES:
        src = os.path.join(cache, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(staging, name))
    with open(os.path.join(staging, "understanding_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(staging):
            for name in files:
                path = os.path.join(root, name)
                arc = os.path.relpath(path, staging).replace("\\", "/")
                zf.write(path, arcname=arc)
    print(f"wrote {out}")
    print(f"sha256 {hashlib.sha256(open(out, 'rb').read()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

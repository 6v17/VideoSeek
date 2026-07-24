"""Scan site-packages for non-Python data our Nuitka bundle may omit."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

PACKAGES = [
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "faiss",
    "lancedb",
    "pyarrow",
    "yt_dlp",
    "fastapi",
    "uvicorn",
    "starlette",
    "multipart",
    "rookiepy",
    "qrcode",
    "pillow_heif",
    "tokenizers",
    "vlc",
    "certifi",
    "yaml",
    "ftfy",
    "scenedetect",
    "numpy",
]

DATA_EXTS = {
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".onnx",
    ".bin",
    ".dat",
    ".csv",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".pem",
    ".crt",
    ".dll",
    ".pyd",
    ".so",
    ".dylib",
    ".npy",
    ".npz",
    ".proto",
    ".ini",
    ".cfg",
    ".toml",
    ".model",
    ".tiktoken",
}

CRITICAL = {
    "rapidocr_onnxruntime": ["config.yaml"],
    "certifi": ["cacert.pem"],
}


def _package_root(mod) -> Path | None:
    f = getattr(mod, "__file__", None)
    if not f:
        return None
    root = Path(f).resolve().parent
    if root.name == "__pycache__":
        root = root.parent
    return root


def main() -> None:
    print(f"{'package':28} {'status':14} summary")
    print("-" * 110)
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:
            print(f"{name:28} {'IMPORT_FAIL':14} {exc}")
            continue
        root = _package_root(mod)
        if root is None:
            print(f"{name:28} {'NO_FILE':14}")
            continue

        data_files: list[str] = []
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if any(part in {"__pycache__", ".git", "tests", "test"} for part in p.parts):
                    continue
                if p.suffix.lower() in DATA_EXTS or p.name.lower() in {"cacert.pem", "config.yaml"}:
                    data_files.append(p.relative_to(root).as_posix())
        except Exception as exc:
            print(f"{name:28} {'SCAN_FAIL':14} {exc}")
            continue

        by_ext: dict[str, int] = {}
        for rel in data_files:
            ext = Path(rel).suffix.lower() or Path(rel).name
            by_ext[ext] = by_ext.get(ext, 0) + 1

        crit = CRITICAL.get(name, [])
        missing_crit = [c for c in crit if not (root / c).is_file()]
        if missing_crit:
            status = "MISSING_CRIT"
        elif data_files:
            status = "HAS_DATA"
        else:
            status = "PY_ONLY"

        print(f"{name:28} {status:14} n={len(data_files)} {by_ext}")
        sample = "; ".join(sorted(data_files)[:10])
        if sample:
            print(f"{'':28} {'':14} sample: {sample}")
        if missing_crit:
            print(f"{'':28} {'':14} MISSING: {missing_crit}")

    print("\n=== Critical probes ===")
    try:
        import onnxruntime as ort

        capi = Path(ort.__file__).resolve().parent / "capi"
        dlls = sorted(capi.glob("*.dll")) if capi.is_dir() else []
        print(f"onnxruntime/capi dlls: {len(dlls)} -> {[d.name for d in dlls[:12]]}")
    except Exception as exc:
        print("onnxruntime probe failed:", exc)

    try:
        import rapidocr_onnxruntime as r

        root = Path(r.__file__).resolve().parent
        models = root / "models"
        print(
            "rapidocr config:",
            (root / "config.yaml").is_file(),
            "models_dir:",
            models.is_dir(),
            "model_files:",
            len(list(models.rglob("*"))) if models.is_dir() else 0,
        )
    except Exception as exc:
        print("rapidocr probe failed:", exc)

    try:
        import certifi

        where = certifi.where()
        print("certifi cacert:", where, "exists:", os.path.isfile(where))
    except Exception as exc:
        print("certifi probe failed:", exc)

    for name in ("pyarrow", "lancedb", "cv2", "faiss"):
        try:
            mod = importlib.import_module(name)
            root = _package_root(mod)
            if root is None:
                continue
            top = sorted(p.name for p in root.iterdir())[:24]
            print(f"{name} top entries: {top}")
        except Exception as exc:
            print(name, "probe failed:", exc)


if __name__ == "__main__":
    main()

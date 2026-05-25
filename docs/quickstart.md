# VideoSeek Quickstart

This guide contains detailed setup, runtime resources, and troubleshooting notes for local development and daily use.

## 1) Environment

- OS: Windows recommended for current packaged runtime layout.
- Python: Use a recent Python 3.x environment.
- Install dependencies:

```bash
pip install -r requirements.txt
```

Or explicitly (Windows):

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

On Linux or macOS, replace `onnxruntime-directml` with `onnxruntime`.

## 2) Run

```bash
python main.py
```

Models and FFmpeg are **not** shipped with the repo. Expect the runtime-resources dialog on first launch unless everything is already configured.

## 3) Runtime resources (models & FFmpeg)

**Primary workflow:** download the official **zip** from the maintainer cloud folder (see README link), then **import inside the app** (§ 3.1). Use manual file layout (§ 3.2) only for custom setups.

**Note on `src/app/app_meta.py`:** URLs there drive **notice / version / about** JSON and the **「Go to download」** browser shortcut; they may also point at the same cloud folder. Optional HTTP-based download of weights exists in code **only when** `model_manifest_url` returns a **JSON manifest**—many distributions use that field as a **human download page** instead, in which case rely on the zip import flow below.

### 3.1 Bundled model zip from 123 pan (recommended for contributors)

The folder linked in the README as **[123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA)** is maintained by the project: it holds **ready-made archives**, not a loose pile of weight files you must wire up by hand. Downloads typically include a **PDF tutorial** (often Chinese) that walks through the **intended user flow**:

1. Start the app (`python main.py`).
2. When the runtime-resources dialog appears (or open **Import runtime resources** from the banner / menu), use the **drop zone** or **Add files** to add the model `.zip`.
3. Optionally add a sibling **`*.sha256`** next to the zip if the bundle ships one (checksum verification).
4. Click **Import and Parse** (`导入并解析`). The app extracts the zip under your model directory and merges **`model_manifest.json`** entries into Settings (field reference: **§ 3.3**). You should **not** need to unpack manually into `%LOCALAPPDATA%\VideoSeek\models\` first.
5. If several model profiles are registered, pick the **active model profile** under Settings.

For FFmpeg, you can add **`ffmpeg.exe`** in the **same file list** and run **Import and Parse** so it is copied to the app-managed FFmpeg location.

This matches how end users are expected to install models; contributors validating releases should follow the same path before diving into manual layouts.

### 3.2 Model files — manual layout (advanced)

Use this only when you are **not** using the official zip flow—for example custom builds or debugging.

Place files under one of:
- `%LOCALAPPDATA%\VideoSeek\models\`
- `models/` under project root

You must mirror the **active model profile** layout (manifest + weights next to each other). Default `clip_onnx` example filenames:

- `clip_visual.onnx`
- `clip_text.onnx`
- `bpe_simple_vocab_16e6.txt.gz`

If you switch to another provider/profile (for example `siglip2_onnx`), file requirements change with that profile. Runtime checks follow the active profile configuration.

Implementation reference for zip/import behavior: `src/services/model_package_service.py`.

### 3.3 `model_manifest.json` (pack layout / custom bundles)

Official zips from the 123 pan folder already include this file—**you only need this section when authoring or inspecting a custom package.**

- **Filename:** **`model_manifest.json`** (not `manifest.json`).
- **Placement:** In the zip (or on disk after import), the manifest must sit **in the same folder** as the model weight files. After import, that folder is under  
  `<model_dir>/<provider_folder>/<variant>/`  
  where **`provider_folder`** is derived from `provider`, e.g. `openai-clip` for `clip_onnx`, `siglip2` for `siglip2_onnx` (see `_provider_dir` in `src/services/model_package_service.py`).

**Required fields**

| Field | Meaning |
|-------|--------|
| `provider` | Inference backend id, e.g. `clip_onnx`, `siglip2_onnx`. |
| `variant` **or** `model_variant` | Subfolder name for that provider, e.g. `vit-base-patch32`. |

**Optional fields**

| Field | Meaning |
|-------|--------|
| `id` | Profile id in Settings; if omitted, derived from `provider` + `variant`. |
| `display_name` | Shown in the model profile UI. |
| `prefer_gpu` | Boolean; default `true`. |
| `required_files` | List of filenames that must exist beside the manifest. If omitted, defaults are used per `provider` (CLIP vs SigLIP2 file lists in code). |
| `files` | Map of logical keys → filenames for config; if omitted, built-in defaults apply for known providers. |

**Minimal example (`clip_onnx`):**

```json
{
  "provider": "clip_onnx",
  "variant": "vit-base-patch32",
  "display_name": "CLIP ONNX (example)"
}
```

Authoritative validation and defaults: `import_model_packages` / `_install_extracted_packages` in `src/services/model_package_service.py`.

### 3.4 FFmpeg

Either:
- Put `ffmpeg.exe` into `%LOCALAPPDATA%\VideoSeek\bin\`
- Or keep `ffmpeg` accessible from `PATH`

**Experimental hardware decode (Windows):** In Settings → Model/GPU, enable **Experimental: hardware decode (D3D11VA)**. Default is off (CPU decode). When on, indexing tries GPU decode with automatic fallback to CPU; 10-bit HEVC on NVIDIA may use a `p010` filter chain. See **`docs/ai/pipelines.md`** (Pipeline 1) for backend matrix and limits.

### 3.5 VLC Runtime for In-App Preview

Install `python-vlc` and ensure runtime binaries are available.

Project-local layout on Windows:
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/` (complete plugin directory)

`ui/playback/vlc_player.py` automatically:
- Prepends `vlc_lib/` to `PATH`
- Sets `VLC_PLUGIN_PATH` when `vlc_lib/plugins/` exists

If VLC runtime is missing/incomplete, search and indexing can still work, but in-app preview playback may not.

## 4) Tests

**Focused subset** (fast smoke checks):

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

**Full suite** (all modules under `tests/`):

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 5) Common Issues

### Unsupported URL

- Typically caused by search/list/channel pages instead of video detail pages.
- Use direct video detail URLs.

### Fresh cookies needed

- Usually due to source-site anti-bot or auth limits.
- Refresh browser cookies and retry link extraction.

### Build finished with 0 new vectors

- Links may have been blocked by precheck or recognized as duplicates.
- Source videos may fail extraction/parsing; inspect build status summary in UI.

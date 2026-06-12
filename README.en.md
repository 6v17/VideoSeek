# VideoSeek

[中文说明](./README.md) | **English**

Desktop semantic video search built with PySide6, ONNX Runtime, FAISS, and FFmpeg.

## Download

End users: get the installer from **[Releases](https://www.lv17.top/)**. Model zips are still on [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) — import inside the app (`docs/quickstart.md` § 3.1).

**Quick Start** below is for **running from source** in this repo.

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

Or install explicitly (Windows; includes mobile bridge and QR):

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

On Linux or macOS, use `onnxruntime` instead of `onnxruntime-directml` (this project’s GPU path targets Windows DirectML; inference falls back to CPU elsewhere).

2. Start the app:

```bash
python main.py
```

3. First launch — **models and FFmpeg are not bundled.** Recommended: download the official **zip** from [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA), run `python main.py`, open **Import runtime resources**, add the `.zip`, then **Import and Parse** (details in **`docs/quickstart.md` § 3.1**). Advanced manual layout is in § 3.2.

## Runtime Requirements

- Model files depend on the **active model profile** (default `clip_onnx`; also supports e.g. `siglip2_onnx`, `chinese_clip_onnx` via imported `model_manifest.json`). **Primary workflow:** get the maintainer-built zip from [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) and **import it in the app** (same steps as quickstart § 3.1). `src/app/app_meta.py` still holds URLs for **release notes / version / about** and may point **「Go to download」** at the cloud folder; it is **not** assumed that ONNX files are fetched automatically without that zip flow.
- Default `clip_onnx` example files:
  - `clip_visual.onnx`
  - `clip_text.onnx`
  - `bpe_simple_vocab_16e6.txt.gz`
- `ffmpeg.exe` for frame extraction and preview.
- `python-vlc` plus VLC runtime for in-app preview playback.

Windows VLC runtime layout (project-local):
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/`

If `vlc_lib/` is missing or incomplete, search/indexing may still work but preview playback may be unavailable.

## Upgrading from older builds (≥ 1.0.82)

- First launch runs **schema** and **video index ID** migration (no re-encode: renames files under `vector/` / `index/` and updates `meta.json`).
- If the startup dialog shows **[Video index IDs (no re-encode)]**, IDs are aligned; library sync logs should mention `reuse_cached_vectors`, not a full re-index.
- If migration is still pending, **restart once**; see `docs/migration_forced_upgrade_checklist.md` §4.1.
- Close action: **exit** or **minimize to tray** (settings); indexing in progress prompts separately.

## Tests

Focused subset:

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

Full suite: `python -m unittest discover -s tests -p "test_*.py"` (see `docs/quickstart.md`).

## More Docs

- Detailed setup and troubleshooting: `docs/quickstart.md` (Chinese)
- Architecture and module map: `docs/architecture.md`
- Agent HTTP API: `docs/for-agents.md`

## License

MIT

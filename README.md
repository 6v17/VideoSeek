# VideoSeek

[中文说明](./README.zh-CN.md) | **English**

Desktop semantic video search built with `PySide6`, `ONNX Runtime`, `FAISS`, and `FFmpeg`.

## Tech Stack

- Language: `Python`
- Desktop UI: `PySide6` (Qt for Python)
- Embedding inference: `ONNX Runtime`
- Vector index/search: `FAISS`
- Video processing: `FFmpeg`
- Media extraction from links: `yt-dlp`

## What It Does

- Search local video libraries with text or an image
- Build frame-level embeddings with CLIP
- Store and query vectors with FAISS
- Preview matched clips inside the desktop app
- Build and search a remote library from online links
- Inspect local vector paths and remote source-link details in-app

## Run Locally

1. Clone the repo.
2. Install dependencies:

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow ftfy regex yt-dlp
```

3. Start the app:

```bash
python main.py
```

On first launch, the app can prepare runtime resources automatically from the remote manifest configured in `src/app/app_meta.py`.

Manual fallback:

- Put these model files into `%LOCALAPPDATA%\\VideoSeek\\models\\` or `models/`:

- `clip_visual.onnx`
- `clip_text.onnx`
- `bpe_simple_vocab_16e6.txt.gz`

- Put `ffmpeg.exe` into `%LOCALAPPDATA%\\VideoSeek\\bin\\` or make sure `ffmpeg` is available on `PATH`

## Project Structure

```text
main.py
src/
  app/
    app_meta.py        built-in product metadata and remote endpoints
    config.py          user config loading and app version access
    i18n.py            zh/en text resources
  core/
    core.py            compatibility entry for search
    clip_embedding.py  CLIP embedding and per-video indexing
    extract_frames.py  frame extraction helpers
    faiss_index.py     vector persistence and FAISS helpers
    tokenizer.py       CLIP tokenizer helpers
  services/
    search_service.py  search loading and query embedding
    library_service.py library metadata operations
    indexing_service.py scan, reuse, merge, and index helpers
    remote_library_service.py remote link build/export/import helpers
    remote_search_service.py remote vector search helpers
    link_search_service.py local-link-to-local-library match helpers
    model_service.py   model manifest parsing and download helpers
    ffmpeg_service.py  ffmpeg manifest parsing and download helpers
    runtime_resource_service.py runtime resource status and directory helpers
    notice_service.py  remote/local notice loading
    version_service.py remote version comparison
  workflows/
    update_video.py    indexing workflow entry
  utils.py             shared utility helpers
ui/
  gui.py               main window shell and UI wiring
  runtime_resource_controller.py runtime resource dialog/download flow
  app_meta_controller.py version and notice refresh flow
  search_controller.py search and thumbnail flow
  network_search_controller.py remote library search/build flow
  link_search_controller.py link-to-local-library match flow
  indexing_controller.py indexing workflow UI flow
  preview_controller.py preview playback flow
  components.py        reusable UI widgets
  table_views.py       table population helpers
  workers.py           background workers
tests/
  test_runtime_resource_service.py runtime resource service tests
  test_notice_version_utils.py notice, version, and config sync tests
  test_download_services.py model and ffmpeg manifest/download tests
  test_controllers.py lightweight controller tests
```

## Architecture

- `ui/gui.py` is now mainly the shell: page wiring, text refresh, and cross-controller coordination.
- `ui/*_controller.py` files own workflow-heavy UI logic that previously lived in the main window.
- `ui/workers.py` isolates long-running background jobs.
- `src/services/` owns business logic, remote metadata parsing, and runtime resource state.
- `src/workflows/` keeps higher-level indexing orchestration.
- `src/utils.py` keeps shared filesystem, FFmpeg, preview, and config sync helpers.

## Agent Notes

This repository includes agent guidance in:

- `AGENTS.md`
- `AGENTS.zh-CN.md`

These files document project structure, testing expectations, and high-risk areas.

In particular, changes touching the local-library sync/indexing path should be treated conservatively:

- Avoid broad refactors in `src/services/indexing_service.py`, `src/workflows/update_video.py`, `src/core/extract_frames.py`, `src/core/clip_embedding.py`, `src/core/faiss_index.py`, `ui/workers.py`, and `ui/indexing_controller.py`.
- Prefer minimal fixes or narrowly scoped feature changes.
- Run syntax checks plus `tests.test_services` after changes in the indexing path.
- Also run `tests.test_controllers` when UI start/stop/progress flow changes.

## Configuration Layers

- User config: `config.json`
- Controls local runtime behavior such as theme, language, FPS, preview size, thumbnail size, and FFmpeg path.
- Safe for end users to modify.

Remote build related config:

- `fps`: shared sampling rate used by both local indexing and remote library build.
- `remote_max_frames`: advanced safety cap for sampled frames per remote source video.
  This cap only applies when video duration is very long and `fps` would produce too many frames.

- App metadata: `src/app/app_meta.py`
- Controls built-in app version plus remote notice, version, and download endpoints.
- Intended for product/distribution control and should not be exposed to end users.

Example split:

```text
config.json
  theme
  language
  fps
  remote_max_frames
  preview_seconds
  ffmpeg_path
  model_dir

src/app/app_meta.py
  version
  notice_url
  version_url
  model_manifest_url
  remote_timeout
```

## Models Used

Core embedding resources:

- `clip_visual.onnx`: CLIP image encoder
- `clip_text.onnx`: CLIP text encoder
- `bpe_simple_vocab_16e6.txt.gz`: tokenizer vocabulary for CLIP text encoder

Default model lookup locations:

- `%LOCALAPPDATA%\\VideoSeek\\models\\`
- `models/` in project directory

Runtime video tool:

- `ffmpeg.exe` (for frame extraction and preview)

## Remote Library Notes

- The Remote Library page is split into two sections:
  - `Build Remote Library`: link input, build mode, build/import/export tools, and build progress/status.
  - `Search Remote Library`: text/image query, search actions, and search status.
- Link input is now inline on the page (multi-line). Paste one or more URLs and click build directly.
- Precheck no longer opens a blocking popup. It reports summary in build status and continues automatically when buildable links exist.
- Build modes:
  - `Download then match`: higher compatibility across sites.
  - `Stream URL match`: faster when a site exposes stable stream URLs.
- Duplicate links are pre-checked before heavy processing to avoid unnecessary re-download/re-embedding when possible.
- Build status now reports staged progress (`resolve/download -> extract -> embed -> merge -> index`) and completion summary (`success/failed/skipped`).
- In-app tools on the Remote Library page:
  - `View Link List`: inspect grouped source-link records.
  - `Open Download Folder`: open remote build cache folders quickly.
- Some sites may still require fresh browser cookies for extraction (for example, certain Douyin pages), and unsupported pages (search/list pages) should be skipped.

## Tests

Run the focused lightweight test suite with:

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

These tests intentionally focus on services/controllers and avoid heavy runtime dependencies where possible.

## Build Remote Library Pack

Use this script to build a distributable remote vector library from online links:

```bash
python scripts/build_remote_index.py --links-file docs/remote_links.txt --base-url https://your-cdn/videoseek/remote --incremental
```

Outputs:

- `remote_index.faiss`
- `remote_vectors.npy` (includes `timestamps`, `source_links`, `titles`)
- `manifest.json`

Then set `remote_index_manifest_url` in `src/app/app_meta.py` to your published manifest URL.

Incremental behavior:

- With `--incremental`, the script loads existing `remote_vectors.npy` and only appends new items.
- Dedup key is `source_id + timestamp(ms)`.
- If no new vectors are appended, it skips rebuild by default.
- Use `--force-rebuild` to rebuild files even when no new vectors are detected.

## Packaging

Example Nuitka command:

```powershell
python -m nuitka --standalone `
--plugin-enable=pyside6 `
--include-qt-plugins=multimedia `
--windows-console-mode=disable `
--output-dir=dist `
--output-filename=VideoSeek `
--windows-icon-from-ico=icon.ico `
--include-data-file=config.json=config.json `
--include-data-dir=vlc_lib=vlc_lib `
--include-package=yt_dlp `
--nofollow-import-to=yt_dlp.extractor.lazy_extractors `
--show-progress `
--verbose `
main.py
```

If you bundle `config.json`, keep machine-local runtime fields empty:

- `model_dir`
- `ffmpeg_path`

Otherwise the first launch on another machine may inherit invalid absolute paths from the build machine before the app migrates settings into `%LOCALAPPDATA%\\VideoSeek\\config.json`.

VLC packaging note:

- `vlc_lib` is required for local VLC preview playback in packaged builds.
- In practice, some VLC runtime DLLs may still be missed by Nuitka data inclusion depending on file type handling.
- If the packaged app cannot play through VLC, copy the whole `vlc_lib` folder into `dist/main.dist\vlc_lib` after packaging and verify `libvlc.dll`, `libvlccore.dll`, and the `plugins` directory are present.
## Download

Runtime resource packaging note:

- The app prefers external runtime resources over bundling large files into every release.
- Default external model directory on Windows is `%LOCALAPPDATA%\\VideoSeek\\models`.
- Default managed FFmpeg path is `%LOCALAPPDATA%\\VideoSeek\\bin\\ffmpeg.exe`.
- If `model_manifest_url` is configured in `src/app/app_meta.py`, the app can prepare both models and FFmpeg from one remote manifest.
- The manifest can define a primary source plus mirror sources, and the app will automatically try the next source if one fails.


## License

MIT

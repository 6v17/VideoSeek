# VideoSeek

Desktop semantic video search built with `PySide6`, `ONNX Runtime`, `FAISS`, and `FFmpeg`.

## What It Does

- Search local video libraries with text or an image
- Build frame-level embeddings with CLIP
- Store and query vectors with FAISS
- Preview matched clips inside the desktop app

## Run Locally

1. Clone the repo.
2. Install dependencies:

```bash
pip install onnxruntime-gpu opencv-python PySide6 faiss-cpu numpy pillow ftfy regex
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

## Configuration Layers

- User config: `config.json`
- Controls local runtime behavior such as theme, language, FPS, preview size, thumbnail size, and FFmpeg path.
- Safe for end users to modify.

- App metadata: `src/app/app_meta.py`
- Controls built-in app version plus remote notice, version, and download endpoints.
- Intended for product/distribution control and should not be exposed to end users.

Example split:

```text
config.json
  theme
  language
  fps
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

## Packaging

Example Nuitka command:

```bash
python -m nuitka --standalone ^
--plugin-enable=pyside6 ^
--include-qt-plugins=multimedia ^
--windows-console-mode=disable ^
--output-dir=dist ^
--output-filename=VideoSeek ^
--windows-icon-from-ico=icon.ico ^
--include-data-file=config.json=config.json ^
main.py
```
## Download

Runtime resource packaging note:

- The app prefers external runtime resources over bundling large files into every release.
- Default external model directory on Windows is `%LOCALAPPDATA%\\VideoSeek\\models`.
- Default managed FFmpeg path is `%LOCALAPPDATA%\\VideoSeek\\bin\\ffmpeg.exe`.
- If `model_manifest_url` is configured in `src/app/app_meta.py`, the app can prepare both models and FFmpeg from one remote manifest.
- The manifest can define a primary source plus mirror sources, and the app will automatically try the next source if one fails.


## License

MIT

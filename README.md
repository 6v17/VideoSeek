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

3. Put these model files into `models/`:

- `clip_visual.onnx`
- `clip_text.onnx`
- `bpe_simple_vocab_16e6.txt.gz`

4. Put `ffmpeg.exe` in the project root.
5. Start the app:

```bash
python main.py
```

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
    notice_service.py  remote/local notice loading
    version_service.py remote version comparison
  workflows/
    update_video.py    indexing workflow entry
  utils.py             shared utility helpers
ui/
  gui.py               main window orchestration
  components.py        reusable UI widgets
  table_views.py       table population helpers
  workers.py           background workers
tests/
  test_services.py     lightweight service-layer tests
```

## Architecture

- `ui/gui.py` coordinates user actions and worker threads.
- `ui/workers.py` isolates long-running search, indexing, and thumbnail jobs.
- `src/app/` owns product metadata, user config, and i18n text resources.
- `src/core/` owns lower-level search, embedding, tokenization, and FAISS helpers.
- `src/services/` owns business-facing library, search, indexing, notice, and version services.
- `src/workflows/` owns higher-level indexing workflow orchestration.
- `src/utils.py` keeps shared filesystem, FFmpeg, and metadata helpers.

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

src/app/app_meta.py
  version
  notice_url
  version_url
  download_url
  remote_timeout
```

## Tests

The repo now includes a small `unittest` suite for service-layer behavior:

```bash
python -m unittest tests.test_services
```

Current environment note: I could not run the tests here because no Python interpreter is available in the shell.

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
--include-data-dir=models=models ^
--include-data-file=config.json=config.json ^
--include-data-file=ffmpeg.exe=ffmpeg.exe ^
main.py
```
## Download
```bash
 1、Gitee Release: [https://gitee.com/lIlIlIlIlIlIlIlIlIlIlIlIl/VideoSeek/releases](https://gitee.com/lIlIlIlIlIlIlIlIlIlIlIlIl/VideoSeek/releases)
 2、GitHub Release: [https://gitee.com/O-O-O-O-O-O-O-O-O-O-O-O-O-O-O-O//VideoSeek/releases](https://gitee.com/O-O-O-O-O-O-O-O-O-O-O-O-O-O-O-O//VideoSeek/releases)
```
## License

MIT

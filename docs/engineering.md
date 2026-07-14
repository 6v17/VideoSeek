# Engineering conventions

Short rules for keeping VideoSeek maintainable. Architecture overview: [`architecture.md`](architecture.md).

## Hard rules

1. **New features go through `src/services/`** — UI and Agent HTTP only schedule; they do not copy business logic.
2. **Do not extend legacy npy / FAISS index paths** — Lance is the write/read path. Legacy code is maintenance-only until removed.
3. **Indexing/search reads are Lance-only** — `_load_vectors_from_disk` / search assets do not load `*_vectors.npy`. Startup migration still imports npy → Lance; leftover npy is cleaned after `lance_migration.completed`. Library details mark npy-only videos as `broken_asset`, not `ready`.
4. **Do not import private (`_foo`) symbols across packages** — if another module needs it, make a public helper or move it.
5. **Prefer new modules under ~400 lines** — when touching a god file, extract the piece you need instead of growing it.

## `src.utils` migration

`src/utils.py` is a compatibility facade. Prefer:

| Concern | Module |
|---------|--------|
| App / resource paths | `src.infra.paths` |
| FFmpeg / ffprobe paths | `src.infra.ffmpeg_paths` |
| Model directory / asset paths | `src.infra.model_paths` |
| Meta JSON I/O | `src.storage.meta_io` |
| Library path / video hash | `src.storage.video_identity` |
| Duration / stream probe | `src.media.probe` |
| Preview / export clips | `src.media.export_clip` |
| Sampling FPS rules | `src.media.sampling_fps` |
| Thumbnails | `src.media.thumbnail` |

Existing `from src.utils import …` imports stay valid while callers migrate.

## `src.web.agent_api` package

The former monolith `src/web/agent_api.py` is split into `src/web/agent_api/` (`health`, `search`, `export_ops`, `service`, …). Public imports remain `from src.web.agent_api import …`.

## Lint / CI

- Ruff config lives in `pyproject.toml` (narrow rule set on purpose).
- CI runs `ruff check` then `pytest`.
- Expand Ruff rules gradually; do not dump a repo-wide style rewrite in one PR.
- Former megafile `tests/test_services.py` is split into `tests/test_services_*.py` (+ `services_test_support.py`).

## What not to do

- Do not rewrite the PySide6 UI “to clean the codebase.”
- Do not start a second storage format alongside Lance.
- Do not open a “full MainWindow refactor” without a feature-driven reason.

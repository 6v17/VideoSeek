# Engineering conventions

Short rules for keeping VideoSeek maintainable. Architecture overview: [`architecture.md`](architecture.md).

## Hard rules

1. **New features go through `src/services/`** — UI and Agent HTTP only schedule; they do not copy business logic.
2. **Do not extend legacy npy / FAISS index paths** — Lance is the write/read path. Legacy code is maintenance-only until removed.
3. **Indexing/search reads are Lance-only** — `_load_vectors_from_disk` / search assets do not load `*_vectors.npy`. Users import npy → Lance from **Settings → Paths** (not auto on launch); after `lance_migration.completed`, startup gates trust that flag and skip vector-dir listdir (sidecar npy may remain). Library details mark npy-only videos as `broken_asset`, not `ready`.
4. **Do not import private (`_foo`) symbols across packages** — if another module needs it, make a public helper or move it.
5. **Prefer new modules under ~400 lines** — when touching a god file, extract the piece you need instead of growing it.
6. **Broad `except` must not hide a failure** — `except Exception` / bare `except` that still returns `[]` / `0` / `None` / `""` must call `note_swallowed` (or log / raise). Narrow parse catches may keep a quiet fallback. `tests/test_silent_failure_ratchet.py` fails if a new silent one appears.
7. **Recap knobs / prompts / VO budget stay out of the runner** — stage knobs in `recap_constants.py`, prompts in `recap_prompts.py`, VO timing math in `recap_vo_budget.py`; `recap_service` re-exports them. Next splits should follow plan / voiceover / match / export, not a rewrite.

## AI-assisted edit stops

AI will keep patching a file until someone stops it. Treat these as hard stops (human or agent), not soft style tips:

| Trigger | Stop and do this instead |
|---------|--------------------------|
| Single file grows past **500 lines** while you are editing it | Split (or extract the piece you touched). Do not keep appending. |
| A module gains more than **10 top-level magic knobs** | Move them to a constants / config module (see rule 7 for recap). |
| A third `fit_X_to_Y` / `stretch_X_for_Y` / similar patch helper appears in the same pipeline | Redesign the stage boundary; do not add another parameter or sibling helper. |
| You split a module | Define the **public** surface in the same change (`name = _name` aliases or a small facade). Cross-package `from … import _foo` is a failed split (rule 4). |

Legacy god files already over these lines are exempt until touched; once you touch them, leave them closer to the table than you found them.

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

- Ruff config lives in `pyproject.toml` (`F` + `E4`/`E7`/`E9`; `E402` ignored for lazy imports).
- CI runs `ruff check` then `pytest`.
- Expand Ruff rules gradually; do not dump a repo-wide style rewrite in one PR.
- Former megafile `tests/test_services.py` is split into `tests/test_services_*.py` (+ `services_test_support.py`).

## What not to do

- Do not rewrite the PySide6 UI “to clean the codebase.”
- Do not start a second storage format alongside Lance.
- Do not open a “full MainWindow refactor” without a feature-driven reason.

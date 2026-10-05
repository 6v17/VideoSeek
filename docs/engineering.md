# Engineering conventions

Short rules for keeping VideoSeek maintainable. Architecture overview: [`architecture.md`](architecture.md).

## Hard rules

1. **New features go through `src/services/`** — UI and Agent HTTP only schedule; they do not copy business logic.
2. **Do not extend legacy npy / FAISS index paths** — Lance is the write/read path. Legacy code is maintenance-only until removed.
3. **Indexing/search reads are Lance-only** — `_load_vectors_from_disk` / search assets do not load `*_vectors.npy`. Users import npy → Lance from **Settings → Paths** (not auto on launch); after `lance_migration.completed`, startup gates trust that flag and skip vector-dir listdir (sidecar npy may remain). Library details mark npy-only videos as `broken_asset`, not `ready`.
4. **Do not import private (`_foo`) symbols across packages** — if another module needs it, make a public helper or move it. Stage→stage `from … import _foo` is a failed split.
5. **Split on stage boundaries, not line quotas** — extract a coherent stage / concern when the boundary is clear. ~400–500 lines is a **smell / pause**, not a hard force-split. Prefer one coherent module over many tiny ones that only exist to game a count.
6. **Broad `except` must not hide a failure** — `except Exception` / bare `except` that still returns `[]` / `0` / `None` / `""` must call `note_swallowed` (or log / raise). Narrow parse catches may keep a quiet fallback. `tests/test_silent_failure_ratchet.py` fails if a new silent one appears.
7. **Recap stage modules stay out of the runner** — knobs in `recap_constants.py`, prompts in `recap_prompts.py`, VO timing in `recap_vo_budget.py`, match QC in `recap_match.py`, captions in `recap_captions.py`, cut coalesce/fit/pad/build in `recap_cuts.py` / `recap_cut_fit.py` / `recap_cut_pad.py` / `recap_cut_build.py`, sidecar I/O in `recap_io.py`, soft focus in `recap_focus.py`, rematch helpers+jobs in `recap_rematch.py`, motion in `recap_motion.py`, OCR/spine in `recap_spine.py`, LLM JSON in `recap_llm_json.py`, plan cover/acts/gaps/merge/normalize in `recap_plan_*.py`, act plan LLM+finalize in `recap_plan_pipeline.py`, match waves+prompts in `recap_match_waves.py`, VO scrub/draft/units/edit/post/pipeline in `recap_vo_*.py`, clocks in `recap_clock.py`, caption prompts in `recap_caption_prompt.py`, runtime+export in `recap_runtime.py`, pack+dialogue in `recap_pack.py`; `recap_service` re-exports them and keeps `generate_recap_timeline`. LLM stages look up `call_remote_llm` / `build_recap_pack` (and other patch points) on the runner so tests can still patch there.

## AI-assisted edit stops

AI will keep patching a file until someone stops it. These are **required behaviors**, not a line-count beauty contest:

| Trigger | Stop and do this instead |
|---------|--------------------------|
| You are about to append yet another concern into an already mixed module | Extract the **stage boundary** you need (or stop and ask). Do not keep bolting features onto a god file. |
| A file past ~500 lines keeps growing with **no clear stage** | Pause and name the boundary before more edits. Split only when the cut is coherent — do **not** shatter a working orchestration just to undercut 500. |
| A module gains more than **10 top-level magic knobs** | Move them to a constants / config module (see rule 7 for recap). |
| A third `fit_X_to_Y` / `stretch_X_for_Y` / similar patch helper appears in the same pipeline | Redesign the stage boundary; do not add another parameter or sibling helper. |
| You split a module | Define the **public** surface in the same change (`name = _name` aliases or a small facade). No new stage→stage `from … import _foo` (rule 4). |

Facade barrels that mostly re-export (e.g. `recap_service`) are fine to be long; do not grow their non-import body without reason. Leftover private re-exports on a facade are compatibility debt, not permission for new `_` cross-imports.

Legacy god files are exempt until touched; when you touch them, leave boundaries clearer than you found them — not necessarily fewer lines.

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

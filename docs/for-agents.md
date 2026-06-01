# VideoSeek — Agent Integration Guide

This document is for **external agents** (Cursor, Claude Code, custom scripts, MCP tools) that help users turn **scripts / copy** into **rough-cut material lists** using VideoSeek’s **visual semantic search**.

> **Status:** **In development** — on `http://127.0.0.1:8765` when the desktop app is running **and** **Settings → General → 本机搜索接口** is enabled (`src/web/agent_api.py`). Default: **off**.
>
> Endpoints: `GET /api/v1/health` · `GET /api/v1/agent-starter` · `GET /api/v1/libraries` · `GET /api/v1/libraries/videos` · `GET /api/v1/search/presets` · `GET /api/v1/search/presets/{id}` · `POST /api/v1/search` · `POST /api/v1/search/batch` · `GET /api/v1/search/telemetry` · `POST /api/v1/export/manifest` · `POST /api/v1/export/clip`
>
> Request/response fields may still change before a public freeze. Treat this doc as the current draft, not a permanent contract.

---

## 0. Protocol notes (draft)

The Agent API is a thin HTTP layer over **`search_service`** (same pipeline as the desktop Search button). Request normalization is shared with the GUI via **`search_request_service`** (preset/inline query, image precision) and **`search_scope`** (effective scope: request → preset videos → desktop picker). When the API stabilizes for external tools, these shapes are the intended baseline:

### Hit fields (minimum stable subset)

Production search responses include **additional fields** — see §5.2 (`duration_sec`, `start_timecode`, `clip_window`, etc.). Do not parse §0 alone.

```json
{
  "rank": 1,
  "video_path": "...",
  "start_sec": 0.0,
  "end_sec": 0.0,
  "score": 0.0
}
```

### Error envelope (target shape)

```json
{
  "api_version": "1",
  "ok": false,
  "error": { "code": "index_not_ready", "message": "..." }
}
```

Stable codes today: `invalid_request`, `index_not_ready`, `query_failed`, `export_failed`, `engine_busy`.

Responses include **`api_version": "1"`**; bump only when breaking shapes intentionally.

---

## 1. What VideoSeek Is Good At

VideoSeek indexes local videos with **CLIP / SigLIP / Chinese CLIP** (and other registered ONNX profile) embeddings and retrieves **time ranges** by:

- **Text** — “red jersey celebration”, “product close-up on desk”
- **Image** — find shots similar to a reference frame

Each successful search returns **where** (file path + seconds), not a finished edit.

| Suitable for | Not suitable for (unless you add ASR/subtitles elsewhere) |
|--------------|-------------------------------------------------------------|
| Visible scenes, objects, actions, camera feel, color, mood | Exact dialogue lines, plot logic, “what he said about price” |
| B-roll picking, sports highlights, product shots | Speaker identity from voice alone |
| Rough assembly: “candidate clips per script line” | Final pacing, transitions, legal/music clearance |

**Mental model:** VideoSeek is a **visual spotter**; the agent is the **editor** (pick, order, trim, export).

---

## 2. Query label on hits (not video tags, not saved presets)

**Terminology (avoid confusion):**

| Term | Meaning | Status |
|------|---------|--------|
| **Query label** | The `query` string on a search request; copied into each hit / manifest row as *why this clip was chosen* | **Today** — use on every `/search` |
| **Search preset** | A **named, saved bundle** created in the desktop app (text and/or reference images, optional fusion weights). Run via `preset_id` on `/search` — same vectors and filters as clicking a chip in the GUI | **Today** — §5.1 |
| **Video metadata tag** | Permanent `tags: ["高燃"]` on each file/segment in the library | **Out of scope** — not this product direction |

For Agent API v1 you do **not** need a separate tagging database or full-library auto-labeling.

- Every `search` call returns a **query label** in the top-level `query` field (preset name when using `preset_id`).
- Copy that string into each manifest row so downstream steps know *why* this segment was chosen.
- Agents may pass **`preset_id`** (§5.1–5.2) for user-saved conditions, or inline `query` / `query_type` for ad-hoc searches.

Example row:

```json
{
  "query": "football goal celebration hug",
  "video_path": "D:/library/match_01.mp4",
  "start_sec": 120.5,
  "end_sec": 125.0,
  "score": 0.82,
  "rank": 1
}
```

---

## 3. How to Rewrite User Copy Into Queries

Agents **must** rewrite user script lines into **short, visible descriptions** before calling search.

### Rules

1. **One query ≈ one visible shot** (roughly 4–20 Chinese characters or 3–12 English words).
2. **Keep what a camera sees**; drop story glue, inner thoughts, and dialogue content unless you also have subtitles.
3. **Prefer concrete nouns + action + framing** over abstract mood words alone.
4. **Do not** paste an entire paragraph as a single query.
5. If the user gives **dialogue-only** lines, infer the likely **shot coverage** (e.g. interview close-up, wide room) or ask the user — do not search the literal quote.

### Examples (Chinese copy)

| User script line | Bad query | Good query |
|------------------|-----------|------------|
| 他进球后激动地拥抱队友 | 他进球后激动地拥抱队友 | 足球进球 庆祝 球员拥抱 |
| 产品在桌上特写，光线柔和 | 产品在桌上特写，光线柔和 | 产品特写 桌面 柔光 |
| 主持人说到本期主题 | 主持人说到本期主题 | 主持人 半身 访谈 面对镜头 |
| 航拍整个球场 | 航拍整个球场 | 足球场 航拍 全景 |

### Examples (English copy)

| User script line | Bad query | Good query |
|------------------|-----------|------------|
| He hugs his teammates after scoring | He hugs his teammates after scoring | soccer goal celebration team hug |
| Soft light product hero on desk | Soft light product hero on desk | product close-up desk soft lighting |

### When to split one script line into multiple queries

- The line mentions **two different shots** (“wide stadium, then close-up face”) → 2 queries.
- The line spans **time** (“first half vs second half”) → separate queries with disambiguating words.
- You need **fallback coverage** → optional alternate query with synonyms (max 2 retries per script line).

---

## 4. Recommended Agent Workflow (Rough Cut)

```
User script / screenshot folder
    → GET /libraries (discover library_path — do not guess folders)
    → split into beats OR batch image_folder
    → for each beat: rewrite to visual query (§3)
    → POST /search or POST /search/batch (expand_frame_hits: true; scope.library_paths from /libraries)
    → keep top 1–3 hits per beat
    → POST /export/manifest (sources=results, dedupe: true) → cuts.json
    → POST /export/clip per item (preferred) or shell ffmpeg using health.ffmpeg.ffmpeg_path
```

### 4.1 Frame mode vs chunk mode

Controlled by `mode` (see §5). Desktop default is often `frame` (`config.json` → `search_mode`).

| `mode` | `start_sec` / `end_sec` | Agent handling |
|--------|-------------------------|----------------|
| `chunk` | Real interval from semantic chunking | Use as-is for rough cuts |
| `frame` | Often **equal** (single timestamp) | Server pads by default (`expand_frame_hits: true`) |

**Default:** leave `expand_frame_hits: true` (pad **3 s** before / **3 s** after; clamped to `video_duration_sec` when known). Hits include `clip_window.raw_*` for the original point.

**Only if** `expand_frame_hits: false`, apply manual padding per below:

- `pad_before_sec`: **3**
- `pad_after_sec`: **3**

Or set `end_sec = start_sec + preview_seconds` (desktop default **6**). Clamp to `[0, video_duration]`.

### 4.2 Choosing hits per query

1. Sort by `rank` ascending (1 = best).
2. Drop hits below `min_score` if set (§5.5 — calibrate per library).
3. Prefer **diverse** files: do not take five hits from the same minute unless the script asks for it.
4. For rough cut, **`top_k` request 3–5**, keep **1–2** per script line.

### 4.3 Deduplication

Merge when:

- Same `video_path`, and
- Intervals overlap more than **50%** of the shorter segment, or start times within **2 s** in frame mode.

Keep the higher rank (lower `rank` number). **`POST /export/manifest` with `dedupe: true` applies the same rules server-side** (§5.4).

### 4.4 Screenshot folder workflow (end-to-end)

1. `GET /api/v1/health` — check `index_ready`, read `capabilities.export_clip` and `ffmpeg.ffmpeg_path`
2. `GET /api/v1/libraries` — pick `library_path` values for `scope.library_paths` (no directory guessing)
3. `POST /api/v1/search/batch` — e.g. `{ "image_folder": "C:/shots", "top_k": 3, "mode": "chunk", "scope": { "library_paths": ["D:/film_lib"] } }`
4. `POST /api/v1/export/manifest` — `{ "sources": <batch.results>, "keep_per_source": 2, "dedupe": true, "write_path": "D:/cuts.json" }`
5. `POST /api/v1/export/clip` per manifest row — or shell out to `ffmpeg.ffmpeg_path` if `export_clip` is false

Or run: `python scripts/search_from_image_folder.py "C:/shots"` (steps 2–3 in one script).

---

## 5. API Contract (v1)

**Base URL:** `http://127.0.0.1:8765` (default; override with env, see §8)  
**Prefix:** `/api/v1`  
**Binding:** localhost only by default — not exposed to LAN.  
**Auth:** none in v1 (local trust boundary).

**Safety boundary:** no index rebuild, no library/config mutation. Search is read-only against the index. **`export/manifest` may write a JSON file only when you pass `write_path`**. **`export/clip` writes the mp4/mkv/mov at `output_path`** (explicit agent side effect; rejected if output falls inside an indexed library root).

**Concurrency:** up to **2** concurrent searches; additional requests wait on a queue. **Per-search timeout:** read `search_timeout_sec` / `search_timeout_precise_sec` from `/health` (defaults **90s** fast, **180s** precise) → HTTP 503 `engine_busy` if exceeded. Response `meta.search_timeout_sec` echoes the budget used.

### 5.0 `GET /api/v1/health` (call before batch search)

Optional query: `?mode=frame` or `?mode=chunk` (which index to probe; default follows app `search_mode`).

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "service": "videoseek-agent-api",
  "index_ready": true,
  "index_stale": false,
  "global_index_state": "fresh",
  "search_mode_default": "frame",
  "search_mode_checked": "frame",
  "model": "clip_onnx_default",
  "provider": "clip_onnx",
  "embedding_space": "clip_onnx_default",
  "dimension": 512,
  "metric": "ip",
  "video_count": 42,
  "vector_count": 12040,
  "frame_vector_count": 9800,
  "chunk_vector_count": 2240,
  "indexed_video_paths": 18,
  "index_id": "clip_onnx_default_512_ip_fresh",
  "capabilities": {
    "text_search": true,
    "image_search": true,
    "frame_search": true,
    "chunk_search": true,
    "batch_search": true,
    "search_presets": true,
    "search_precision": true,
    "export_manifest": true,
    "export_clip": true,
    "library_discovery": true,
    "local_ffmpeg_clip": true
  },
  "ffmpeg": {
    "ffmpeg_available": true,
    "ffmpeg_path": "C:/Users/you/AppData/Local/VideoSeek/bin/ffmpeg.exe",
    "ffmpeg_source": "managed"
  },
  "max_concurrent_searches": 2,
  "search_timeout_sec": 90,
  "search_timeout_precise_sec": 180,
  "agent_api_default_image_precision": "fast",
  "max_batch_queries": 64,
  "batch_timeout_sec": 1200,
  "search_index_schema_version": 2,
  "library_indexes_upgrade_needed": false,
  "library_index_count": 3,
  "library_indexes_ready": 3,
  "library_indexes_stale": 0,
  "saved_search_scope_mode": "all"
}
```

| Field | Agent use |
|-------|-----------|
| `index_ready` | If `false`, do not spam `/search` — ask user to sync index in VideoSeek |
| `index_stale` | If `true`, results may be outdated until user rebuilds global index |
| `index_id` | Cache key — confirm later searches use the same index snapshot / model |
| `model` / `provider` / `dimension` | Reflect the **active model profile** (e.g. `chinese_clip_vit_base_patch16`, `chinese_clip_onnx`, `512`) — not always `clip_onnx` |
| `embedding_space` | Embedding namespace in `index_id`; useful when comparing snapshots across runs |
| `capabilities` | Skip unsupported modes (e.g. `chunk_search: false` → use `frame`; `search_presets: false` → use inline `query` only; `search_precision: false` → omit `search_precision_mode`; `library_discovery: false` → ask user for paths; `export_clip: false` → shell ffmpeg manually) |
| `capabilities.library_discovery` | If `true`, call `GET /libraries` before search — do not scan disk for library folders |
| `capabilities.export_clip` | If `true`, prefer `POST /export/clip` over hand-built ffmpeg commands |
| `ffmpeg.ffmpeg_path` | Returned on `/health` and `/export/clip` responses — use for manual ffmpeg fallback only |
| `ffmpeg.ffmpeg_available` | If `false`, ask user to install/import FFmpeg in VideoSeek settings |
| `ffmpeg.ffmpeg_source` | `configured` / `managed` / `bundled` / `system` / `missing` (debug) |
| `capabilities.local_ffmpeg_clip` | If `true`, agent may shell out to `ffmpeg.ffmpeg_path` after search |
| `video_count` | Files tracked in library metadata |
| `vector_count` | Vectors in the active global index for `search_mode_checked` |
| `frame_vector_count` / `chunk_vector_count` | Per-mode vector totals (even when only one mode is checked) |
| `search_index_schema_version` | `1` = global-only search; `2` = per-library indexes available |
| `library_indexes_upgrade_needed` | If `true`, per-library indexes are still building — restart VideoSeek and wait for startup migration |
| `library_indexes_ready` / `library_indexes_stale` | Count of per-library indexes ready vs stale (v2 only) |
| `saved_search_scope_mode` | Desktop setting: `all` or `selected`. When you **omit** `scope` on `/search`, the server mirrors this saved picker (same as the desktop Search button) |
| `max_batch_queries` / `batch_timeout_sec` | Batch limits — size `queries[]` and expect HTTP 503 if exceeded. Batch timeout scales with item count × per-item timeout (fast vs precise), capped at 7200s |
| `search_timeout_sec` | Per-request timeout for **fast** searches (text or image). Default **90s** |
| `search_timeout_precise_sec` | Per-request timeout when `search_precision_mode: "precise"` (image / preset ref-image / crop locate). Default **180s** |
| `search_telemetry_enabled` | Local screenshot metrics (default **true**); same JSON as desktop **Settings → 截图搜索诊断** |
| `agent_api_default_image_precision` | Default when image queries omit `search_precision_mode`: `"fast"` or `"precise"`. Text-only always `"fast"` |

### 5.0.1 `GET /api/v1/agent-starter` (paste onboarding)

Optional query: `?locale=zh|en` (default `zh`), `?mode=frame|chunk` (same as `/health` index probe).

Returns a **short paste block** (~80 lines): intro + live `/health` snapshot + 7-step workflow. Does **not** embed the full `for-agents.md`.

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "starter_text": "你是本机 VideoSeek 的粗剪编排助手。\n...",
  "full_doc_rel": "docs/for-agents.md",
  "full_doc_path": "D:/Release/VideoSeek/docs/for-agents.md",
  "meta": {
    "locale": "zh",
    "line_count": 52,
    "doc_on_disk": true
  }
}
```

| Field | Agent use |
|-------|-----------|
| `starter_text` | Paste into Cursor / Claude as system context |
| `full_doc_rel` | **Preferred** — relative to VideoSeek install root; works across machines |
| `full_doc_path` | Absolute path when the file exists on disk (`null` if missing); for “open in editor” only |
| `meta.doc_on_disk` | If `false`, full contract file was not shipped beside the app |

Settings UI **「复制接入说明」** uses the same `starter_text` builder (locale follows app language).

**Packaged (Nuitka) layout:** ship `docs/for-agents.md` next to the executable (same rule as `vlc_lib/`). After build:

```powershell
New-Item -ItemType Directory -Force -Path .\dist\main.dist\docs | Out-Null
Copy-Item -Force .\docs\for-agents.md .\dist\main.dist\docs\for-agents.md
```

Resolution uses `get_resource_path("docs/for-agents.md")` → `dirname(VideoSeek.exe)` when launched as a packaged `.exe` (Nuitka does not always set `sys.frozen`).

### 5.1 Search presets (`GET`)

Presets are **shared with the desktop app** (same JSON store). They can be text-only, image-only, or mixed (text + helper images with optional fusion weights). Reference image files stay on disk — the API exposes counts and summaries, not absolute ref paths.

#### `GET /api/v1/search/presets`

List all presets (newest order follows desktop storage).

```json
{
  "api_version": "1",
  "ok": true,
  "presets": [
    {
      "id": "a1b2c3d4e5f6",
      "name": "Night City",
      "query": "anime night skyline",
      "reference_image_count": 2,
      "summary": "anime night skyline + [2 image(s)] + (50:50)",
      "fusion": { "text_weight": 0.5, "image_weight": 0.5 }
    }
  ],
  "meta": { "count": 1 }
}
```

#### `GET /api/v1/search/presets/{preset_id}`

```json
{
  "api_version": "1",
  "ok": true,
  "preset": {
    "id": "a1b2c3d4e5f6",
    "name": "Night City",
    "query": "anime night skyline",
    "reference_image_count": 2,
    "summary": "anime night skyline + [2 image(s)] + (50:50)"
  }
}
```

| HTTP | Meaning |
|------|---------|
| 404 | Unknown `preset_id` |

**Agent workflow:** `GET /presets` → let user pick a name → `POST /search` with `preset_id`. Or skip listing if the user already gave you an id from the desktop UI.

**Live settings (same as GUI Search button / preset chip):**

| Setting | Preset / inline search behavior |
|---------|----------------------------------|
| **Search mode** (`frame` / `chunk`) | Uses request `mode` if set; otherwise desktop `search_mode` at request time — **not** frozen inside the preset |
| **Search scope** | If `scope` is **omitted**, mirrors desktop **Search scope** (selected videos first, else selected libraries, else all indexed). Preset-owned `video_paths` apply before the desktop picker. Pass `scope` to override |
| **Image precision** | Request `search_precision_mode: "precise"` for image / preset-with-ref-image searches (same pipeline as desktop **精搜**). Agent default when omitted: `agent_api_default_image_precision` from `/health` — **not** the live desktop toggle. Text-only always `"fast"` |
| **Reference-image rerank** | Preset searches pass `pixel_query_data` internally (same as GUI preset chip) — no extra request field |
| **top_k / min_score** | Request fields override; otherwise preset defaults, then app defaults |

### 5.2 `POST /api/v1/search`

Find segments in the **currently indexed local library** on the machine where VideoSeek is running.

Provide **`preset_id` or `query`**, not both.

#### Request (inline text query)

```json
{
  "query": "足球进球 庆祝",
  "query_type": "text",
  "top_k": 5,
  "mode": "chunk",
  "min_score": null,
  "client_request_id": "beat-03",
  "scope": { "library_paths": ["D:/Videos/MyLibrary"] },
  "expand_frame_hits": true,
  "pad_before_sec": 3,
  "pad_after_sec": 3
}
```

#### Request (saved preset)

```json
{
  "preset_id": "a1b2c3d4e5f6",
  "mode": "chunk",
  "top_k": 10,
  "client_request_id": "beat-03"
}
```

#### Request (image + precise mode)

```json
{
  "query": "D:/refs/hero_frame.png",
  "query_type": "image_path",
  "search_precision_mode": "precise",
  "top_k": 8,
  "mode": "frame",
  "expand_frame_hits": true
}
```

Omit `scope` to follow the desktop **Search scope** picker automatically.

When `preset_id` is set, omit `query` and `query_type`. The server uses the preset’s cached query vector (including mixed text+image fusion). Response `query` is the **preset name** (query label for manifests).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `preset_id` | string | yes* | Id from `GET /api/v1/search/presets`. Mutually exclusive with `query`. |
| `query` | string | yes* | Visual search text or image path; also echoed as the **query label** on hits / manifest rows (§2). |
| `query_type` | `"text"` \| `"image_path"` | no | Required semantics when using `query` (default `text`). Ignored when `preset_id` is set. |
| `top_k` | integer | no | Max hits to return. Bounds **1–200** (app config). Default: preset `top_k`, else desktop `search_top_k` (**20**). |
| `mode` | `"frame"` \| `"chunk"` | no | Override desktop `search_mode`. Default: follow app settings at request time. |
| `min_score` | number \| null | no | Optional post-filter; implementation may compare against inner-product style scores. When unsure, omit and filter by rank only. |
| `search_precision_mode` | `"fast"` \| `"precise"` | no | Image-search precision (same as desktop **精搜** pipeline). Default: `agent_api_default_image_precision` from `/health` when omitted — Agent does **not** read the desktop toggle per request. Ignored for text-only. Preset ref-image searches honor `"precise"` |
| `client_request_id` | string | no | Echoed back for correlating script beats. |
| `scope` | object | no | Optional override. **When omitted**, server mirrors desktop **Search scope** (same as GUI Search button). See scope fields below |
| `scope.video_paths` | string[] | no | Limit hits to these absolute video paths (global index over-fetch then filter). |
| `scope.library_paths` | string[] | no | Limit hits to videos under these library root folders. With v2 per-library indexes, queries those indexes directly (same as desktop **Selected libraries**). |
| `scope.use_saved_scope` | boolean | no | Default `false`. Set `true` (with an otherwise empty `scope` object) to **explicitly** read desktop saved scope from config. Usually unnecessary — omitting `scope` already mirrors the desktop picker |
| `expand_frame_hits` | boolean | no | Default `true`. Pad frame point hits by `pad_*`. |
| `pad_before_sec` / `pad_after_sec` | number | no | Default **3** / **3** when expanding frame hits. |
| `preview_anchor_sec` | number | no | **Screenshot locate-in-video** (same as desktop **定位镜头**). Requires image query + `scope.video_paths` with **exactly one** video. Server forces `search_precision_mode: "precise"`. Refines around this anchor (±5s CLIP, anchor stability); returns up to 1 crop hit. Omit for normal fast/precise search. |

\* Provide **`preset_id` or `query`**, not both.

For `query_type: "image_path"`, `query` is the file path.

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "query": "足球进球 庆祝",
  "query_type": "text",
  "mode": "chunk",
  "client_request_id": "beat-03",
  "preset_id": "a1b2c3d4e5f6",
  "preset_name": "Night City",
  "hits": [
    {
      "rank": 1,
      "video_path": "D:/Videos/library/match_01.mp4",
      "start_sec": 120.5,
      "end_sec": 125.0,
      "score": 0.82,
      "duration_sec": 4.5,
      "start_timecode": "00:02:00",
      "end_timecode": "00:02:05",
      "clip_window": {
        "start_sec": 120.5,
        "end_sec": 125.0,
        "padding_applied": false,
        "raw_start_sec": 120.5,
        "raw_end_sec": 125.0
      }
    }
  ],
  "meta": {
    "returned": 1,
    "top_k": 5,
    "fetch_top_k": 15,
    "search_precision_mode": "fast",
    "search_timeout_sec": 90,
    "scope_applied": true,
    "index_ready": true,
    "elapsed_ms": 240
  }
}
```

| Field | Description |
|-------|-------------|
| `preset_id` / `preset_name` | Present when the request used `preset_id` |
| `hits[].rank` | 1-based order after server-side ranking |
| `hits[].video_path` | Absolute path to source media |
| `hits[].start_sec` / `end_sec` | Clip window (after pad when `expand_frame_hits: true`) |
| `hits[].score` | Similarity score (higher = better for dot-product style metrics) |
| `hits[].duration_sec` | `end_sec - start_sec` |
| `hits[].start_timecode` / `end_timecode` | `HH:MM:SS` for human review |
| `hits[].clip_window` | `raw_start_sec`, `raw_end_sec`, `padding_applied` |
| `hits[].video_duration_sec` | Present when container duration is known |
| `meta.fetch_top_k` | Over-fetch size for global+filter scope; equals `top_k` when `scope_uses_per_library_indexes` |
| `meta.search_precision_mode` | `"fast"` or `"precise"` actually used (`"fast"` for text-only) |
| `meta.search_timeout_sec` | Per-request timeout budget applied by the server (fast vs precise); present on **`POST /search`** only |
| `meta.batch_timeout_sec` | Total timeout budget for **`POST /search/batch`** (may exceed `/health` `batch_timeout_sec` when scaled by query count) |
| `meta.scope_applied` | `true` when any scope limit was applied |
| `meta.scope_video_paths` | Resolved video paths (explicit, preset-owned, or from desktop picker) |
| `meta.scope_library_paths` | Resolved library roots (explicit or from desktop picker) |
| `meta.scope_uses_per_library_indexes` | `true` when v2 per-library indexes were queried directly |
| `meta.scope_use_saved_scope` | Echo of `scope.use_saved_scope` |
| `meta.saved_search_scope_mode` | Desktop `all` / `selected` at request time |
| `meta.preview_anchor_sec` | Echo when crop locate was requested |
| `meta.crop_locate` | `true` when `preview_anchor_sec` was used (screenshot locate-in-video pipeline) |

#### Screenshot locate workflow (`preview_anchor_sec`)

Same two-step semantics as the desktop **定位镜头** button:

1. **Fast recall** — image search without `preview_anchor_sec` → get `video_path` + `start_sec` (anchor).
2. **Locate** — same image + `scope.video_paths: [that video]` + `preview_anchor_sec: <anchor>` + forced precise mode.

```json
{
  "query": "D:/refs/crop.png",
  "query_type": "image_path",
  "scope": { "video_paths": ["D:/Videos/library/match_01.mp4"] },
  "preview_anchor_sec": 64.0,
  "top_k": 1,
  "mode": "frame",
  "expand_frame_hits": true
}
```

Crop screenshots skip pixel rerank; anchor moves only when CLIP gain ≥ 0.03 over the nearest anchor frame. Agent crop searches increment **confidence** telemetry; locate calls also increment **anchor retention** (via shared `search_service`).

**Playback bias** (user scrub vs suggested time) is recorded from the **desktop preview UI only** — agents do not have a playback surface. Use `GET /search/telemetry` to read aggregated stats after the user reviews hits in VideoSeek.

#### `GET /api/v1/search/telemetry`

Read-only local screenshot-search diagnostics (same counters as desktop Settings panel).

Optional query: `?locale=zh|en` (default `zh`).

```json
{
  "api_version": "1",
  "ok": true,
  "enabled": true,
  "file_path": "C:/Users/.../VideoSeek/telemetry/search_telemetry.json",
  "panel_text": "Anchor 保留率\n92.4%\n\n播放平均绝对偏差\n0.8s\n...",
  "summary": {
    "crop_locate": { "total": 10, "anchor_kept": 9, "anchor_moved": 1, "retention_rate": 0.9 },
    "confidence_tiers": { "clip_confidence_very_high": 6, "clip_confidence_high": 3 },
    "playback_bias": {
      "samples": 5,
      "mean_abs_delta_sec": 0.8,
      "within_1s_rate": 0.8,
      "p50_abs_delta_sec": 0.6,
      "p90_abs_delta_sec": 2.1,
      "p95_abs_delta_sec": 3.4
    }
  }
}
```

| Field | Agent use |
|-------|-----------|
| `enabled` | Respects `search_telemetry_enabled` in config (default on) |
| `summary.playback_bias` | **Primary accuracy signal** when user previews in desktop UI |
| `summary.crop_locate.retention_rate` | Validates “fast anchor is already good” design |
| `summary.confidence_tiers` | Health monitor for CLIP / screenshot quality |
| `panel_text` | Human-readable block for support tickets |

#### Error responses

All errors use the same JSON body (§0):

```json
{
  "api_version": "1",
  "ok": false,
  "error": {
    "code": "index_not_ready",
    "message": "Search index is not ready. Sync the library in VideoSeek first."
  }
}
```

| HTTP | `error.code` | Meaning | Agent action |
|------|----------------|---------|--------------|
| 400 | `invalid_request` | Bad JSON or missing fields | Fix request |
| 409 | `index_not_ready` | Library index missing or empty | Ask user to sync index in VideoSeek |
| 422 | `query_failed` | Model/runtime failure | Retry once; then report |
| 503 | `engine_busy` | Timeout or saturated GPU queue | Back off and retry |

Empty `hits` is **not** an error — try a more visual query (§3).

### 5.3 `POST /api/v1/search/batch`

Run many searches in one HTTP call (screenshot folders, storyboard beats). **Limit:** 64 items per request. **Timeout:** at least `batch_timeout_sec` from `/health` (default **1200s**), or `query_count × per_item_timeout × 1.1` when larger (per-item timeout is **180s** if any item uses precise mode, else **90s**). Each item still respects the global search concurrency cap (2).

#### Request (screenshot folder)

```json
{
  "image_folder": "D:/storyboard/beat03",
  "top_k": 3,
  "mode": "chunk",
  "scope": { "library_paths": ["D:/Videos/MyLibrary"] },
  "expand_frame_hits": true,
  "pad_before_sec": 3,
  "pad_after_sec": 3,
  "continue_on_error": true
}
```

`image_folder` scans `*.png`, `*.jpg`, `*.jpeg`, `*.webp`, `*.bmp`, `*.gif` (sorted by filename). Each file becomes one search; `client_request_id` defaults to the filename. Image-folder items inherit batch `search_precision_mode` when set; otherwise they follow `agent_api_default_image_precision` from `/health` (same as inline `image_path` searches).

Batch-level **`top_k`, `mode`, `min_score`, `search_precision_mode`, `scope`, `expand_frame_hits`, `pad_*`** apply to every item (including folder-expanded images) unless an entry in `queries` overrides (scope per-item only).

#### Request (explicit list)

```json
{
  "queries": [
    {
      "query": "D:/refs/a.png",
      "query_type": "image_path",
      "client_request_id": "a"
    },
    {
      "preset_id": "a1b2c3d4e5f6",
      "client_request_id": "night-city"
    },
    {
      "query": "黄衣 男孩 拖行",
      "query_type": "text",
      "client_request_id": "b"
    }
  ],
  "top_k": 5,
  "mode": "chunk",
  "continue_on_error": true
}
```

Batch-level `top_k`, `mode`, `min_score`, `search_precision_mode`, `scope`, `expand_frame_hits`, `pad_*` apply to all items unless overridden in `queries`. You may combine `queries` + `image_folder` in one request.

| Field | Description |
|-------|-------------|
| `queries` | List of single-search bodies (same shape as §5.2). Each entry may use `preset_id` **or** `query`. |
| `image_folder` | Optional directory of reference images (agent does not need to list files) |
| `scope` / `expand_frame_hits` / `pad_*` | Batch defaults inherited by all items (see folder example above) |
| `continue_on_error` | If `true` (default), one bad path does not stop the rest |

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "results": [
    {
      "ok": true,
      "client_request_id": "a.png",
      "query": "D:/storyboard/beat03/a.png",
      "query_type": "image_path",
      "mode": "chunk",
      "hits": [ { "rank": 1, "video_path": "...", "start_sec": 0, "end_sec": 5, "score": 0.8 } ]
    },
    {
      "ok": false,
      "client_request_id": "missing.png",
      "query": "D:/storyboard/beat03/missing.png",
      "query_type": "image_path",
      "hits": [],
      "error": { "code": "invalid_request", "message": "image_path does not exist: ..." }
    }
  ],
  "meta": {
    "total": 2,
    "processed": 2,
    "succeeded": 1,
    "failed": 1,
    "elapsed_ms": 1200,
    "batch_timeout_sec": 1200
  }
}
```

Top-level `ok` is `false` if any item failed, but `results` still contains per-item payloads.

### 5.4 `POST /api/v1/export/manifest`

Turn search/batch results into a standard `cuts.json` (dedupe + optional write to disk). **`dedupe: true` uses §4.3 rules server-side.**

```json
{
  "project": "screenshots-rough",
  "sources": [ { "ok": true, "hits": [ "..." ], "query": "..." } ],
  "keep_per_source": 2,
  "dedupe": true,
  "write_path": "D:/cuts-from-screenshots.json",
  "mode": "chunk",
  "expand_frame_hits": true,
  "pad_before_sec": 3,
  "pad_after_sec": 3
}
```

| Field | Description |
|-------|-------------|
| `sources` | List of `/search` or batch result blocks — pass the **`results` array from a batch response as JSON objects**, not a string placeholder or serialized JSON string |
| `items` | Alternative: explicit manifest rows (skip `sources`) |
| `keep_per_source` | Max hits per source block when building from `sources` |
| `dedupe` | Apply §4.3 overlap rules |
| `write_path` | Optional absolute path to write JSON; omit to return body only |
| `mode` / `expand_frame_hits` / `pad_*` | Used when expanding raw items (usually hits are already enriched from search) |

Or pass explicit `items` (same shape as manifest rows). Response:

```json
{
  "api_version": "1",
  "ok": true,
  "manifest": { "version": 1, "project": "...", "items": [ ... ] },
  "meta": { "item_count": 4, "dedupe": true, "write_path": "..." }
}
```

`write_path` is optional — omit to receive JSON only.

### 5.5 `GET /api/v1/libraries` (call before search)

Lists indexed library roots registered in VideoSeek. Use returned `library_path` values in `scope.library_paths` — **do not guess or scan the user's disk**.

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "libraries": [
    {
      "library_path": "D:/Videos/AnimeS1",
      "display_name": "AnimeS1",
      "index_state": "ready",
      "video_count_total": 120,
      "video_count_indexed_ready": 118,
      "video_count_missing_source": 2,
      "per_library_index_ready": true,
      "offline": false
    }
  ],
  "meta": {
    "count": 1,
    "search_index_schema_version": 2,
    "saved_search_scope_mode": "selected"
  }
}
```

| Field | Agent use |
|-------|-----------|
| `library_path` | Pass to `scope.library_paths` on `/search` and `/search/batch` |
| `video_count_indexed_ready` | How many files are searchable (`asset_state=ready` and source exists) |
| `per_library_index_ready` | v2 per-library FAISS ready — scoped search is faster when `true` |
| `offline` | Root folder missing on disk — warn user before searching |

### 5.6 `GET /api/v1/libraries/videos`

Paginated video inventory for one library. Query parameters:

| Param | Default | Notes |
|-------|---------|-------|
| `library_path` | — | **Required** — absolute root from `GET /libraries` |
| `ready_only` | `true` | When `true`, only `asset_state=ready` with existing source file |
| `limit` | `500` | Max **2000** |
| `offset` | `0` | Page offset |

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "library_path": "D:/Videos/AnimeS1",
  "videos": [
    {
      "video_path": "D:/Videos/AnimeS1/ep01.mp4",
      "video_rel_path": "ep01.mp4",
      "video_id": "abc123",
      "asset_state": "ready",
      "source_exists": true
    }
  ],
  "meta": {
    "returned": 1,
    "total_listed": 118,
    "total_ready": 118,
    "offset": 0,
    "limit": 500,
    "ready_only": true
  }
}
```

Use `video_path` directly in `scope.video_paths` when you need single-file scope. Unknown library → HTTP **404** `invalid_request`.

### 5.7 `POST /api/v1/export/clip`

Server-side FFmpeg subclip — same window rules and **libx264 re-encode** as desktop preview export (`export_original_clip`). **One clip at a time** (semaphore=1); concurrent requests may get HTTP **503** `engine_busy`.

#### Request

```json
{
  "video_path": "D:/Videos/library/match_01.mp4",
  "start_sec": 120.5,
  "end_sec": 125.0,
  "output_path": "D:/exports/beat-03-take-1.mp4",
  "client_request_id": "beat-03",
  "silent": false
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `video_path` | yes | Absolute path; must exist |
| `start_sec` / `end_sec` | yes | From search hit; `end_sec > start_sec` |
| `output_path` | yes | Destination `.mp4`, `.mkv`, or `.mov` — must **not** lie inside any indexed `library_path` |
| `client_request_id` | no | Echoed in response for your manifest correlation |
| `silent` | no | Default follows app `export_video_silent` |

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "output_path": "D:/exports/beat-03-take-1.mp4",
  "video_path": "D:/Videos/library/match_01.mp4",
  "start_sec": 120.5,
  "end_sec": 125.0,
  "duration_sec": 4.5,
  "ffmpeg_path": "C:/Users/you/AppData/Local/VideoSeek/bin/ffmpeg.exe",
  "client_request_id": "beat-03",
  "meta": { "elapsed_ms": 820, "encode_mode": "libx264_crf18", "silent": false }
}
```

| HTTP | code | When |
|------|------|------|
| 400 | `invalid_request` | Bad times, bad extension, output inside library root |
| 404 | `invalid_request` | Source video missing |
| 422 | `export_failed` | FFmpeg non-zero exit (stderr summary in `message`) |
| 503 | `engine_busy` | Timeout (**120s**) or export queue busy |

Check `capabilities.export_clip` on `/health` first. If `false`, fall back to manual ffmpeg (§6).

### 5.8 Suggested request parameters (copy into agent config)

**Rough-cut material pass (recommended starting point)**

```json
{
  "top_k": 5,
  "mode": "chunk",
  "min_score": null
}
```

Keep **1–2** hits per script beat.

**Precise single-moment lookup**

```json
{
  "top_k": 8,
  "mode": "frame",
  "min_score": null,
  "search_precision_mode": "precise",
  "expand_frame_hits": true
}
```

Use with `query_type: "image_path"` or a preset that includes reference images. Server pads frame points by default; set `expand_frame_hits: false` only if you pad manually (§4.1).

---

## 6. `cuts.json` Manifest (shape reference)

**Preferred:** `POST /api/v1/export/manifest` (§5.4) after search/batch.  
**Fallback:** build the same JSON yourself if the API is unavailable.

```json
{
  "version": 1,
  "project": "episode-01-rough",
  "items": [
    {
      "id": "beat-03-take-1",
      "query": "足球进球 庆祝",
      "video_path": "D:/Videos/library/match_01.mp4",
      "start_sec": 120.5,
      "end_sec": 125.0,
      "score": 0.82,
      "rank": 1,
      "notes": ""
    }
  ]
}
```

**FFmpeg example** (manual fallback when `export_clip` is false) — read `ffmpeg.ffmpeg_path` from `/health` first:

**Preferred:** loop manifest items through `POST /api/v1/export/clip` (§5.7) when `capabilities.export_clip` is true.

```bash
"C:/Users/you/AppData/Local/VideoSeek/bin/ffmpeg.exe" -y -ss 120.5 -to 125.0 -i "D:/Videos/library/match_01.mp4" -c copy "beat-03-take-1.mp4"
```

On Windows, quote paths with spaces. Use re-encode if `-c copy` breaks on non-keyframe cuts.

---

## 7. System Prompt Template (copy for Cursor / Claude)

```text
You are a rough-cut assistant using VideoSeek on the user's PC.

VideoSeek finds video shots by VISUAL meaning, not dialogue.
Default pipeline:
1. Rewrite each script beat into a short visual query (§3). Never search literal dialogue.
2. GET http://127.0.0.1:8765/api/v1/health — stop if index_ready is false; note export_clip and ffmpeg.ffmpeg_path.
3. GET http://127.0.0.1:8765/api/v1/libraries — use library_path for scope; never guess library folders.
4. Optional: GET /api/v1/search/presets if the user maintains named presets in VideoSeek.
5. POST /api/v1/search or /search/batch — use preset_id for saved conditions, or inline query; expand_frame_hits=true, mode=chunk, top_k=5. scope.library_paths from step 3 when narrowing; omit scope to mirror desktop picker. For image queries, set search_precision_mode=precise, or rely on agent_api_default_image_precision from /health.
6. POST /api/v1/export/manifest with sources=<results>, dedupe=true, keep_per_source=2 (optional write_path).
7. POST /api/v1/export/clip per kept hit (output_path outside library roots), or ffmpeg fallback if export_clip is false.

Do not manually pad frame hits unless expand_frame_hits=false.
Do not rebuild indexes or change VideoSeek settings unless the user asks.
If search returns empty hits, rephrase visually at most twice.
Run API calls in the user's local terminal when the IDE cannot reach 127.0.0.1:8765.
```

---

## 8. Runtime & Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `agent_api_enabled` (config) | `false` | Persistent toggle in Settings UI |
| `agent_api_search_timeout_fast_sec` (config) | `90` | Per-search timeout for fast / text queries (seconds) |
| `agent_api_search_timeout_precise_sec` (config) | `180` | Per-search timeout when precise image mode is used |
| `agent_api_batch_timeout_sec` (config) | `1200` | Minimum batch timeout floor (seconds); actual batch budget may scale up |
| `agent_api_default_image_precision` (config) | `"fast"` | Default for image queries when `search_precision_mode` is omitted |
| `search_telemetry_enabled` (config) | `true` | Local screenshot metrics; disable only if you must stop counter writes |
| `VIDEOSEEK_AGENT_API` | *(unset)* | `0` = force off; `1` = force on (overrides config) |
| `VIDEOSEEK_AGENT_API_HOST` | `127.0.0.1` | Bind address |
| `VIDEOSEEK_AGENT_API_PORT` | `8765` | TCP port |

Enable in the app: **Settings → General → 本机搜索接口 → On → Save**. Service applies after save (and on next startup if already enabled).

### Packaged app (Nuitka)

Ship these **relative to the executable directory** (same as `get_resource_path()`):

```
VideoSeek.exe
docs/for-agents.md    ← Agent full contract + this guide
vlc_lib/
```

The Agent API exposes `full_doc_rel: "docs/for-agents.md"` on `/agent-starter`; `full_doc_path` is the resolved absolute path when the file exists.

### Prerequisites checklist

Before batch searching:

- [ ] VideoSeek desktop is **running**
- [ ] `GET /api/v1/health` → `index_ready: true`
- [ ] Active model profile matches indexed vectors
- [ ] Agent uses **visual rewrite** (§3), not literal script lines

---

## 9. Safety Scope (Why This Is Low Risk)

v1 Agent API is designed for **orchestration, not library administration**:

- No file deletion, no index rebuild, no writes to `config.json`
- Search reads the existing index only
- **`export/manifest` may write one JSON file** when you explicitly set `write_path` (cuts list, not source media)
- Worst case from search: irrelevant hits — same as a bad query in the GUI

---

## 10. Mapping to Code (for maintainers)

| Doc concept | Code |
|-------------|------|
| HTTP server | `src/web/agent_api.py` → `AgentApiService` |
| GUI lifecycle | `ui/controllers/agent_api_controller.py` → start after startup |
| Search execution | `src/services/search_service.py` → `run_search` / `run_chunk_search` |
| Query + preset resolution | `src/services/search_request_service.py` → `resolve_search_query_inputs` |
| Scope parity (GUI + Agent) | `src/services/search_scope.py` → `resolve_effective_search_scope`, `resolve_default_active_search_scope` |
| Image precision default | `search_request_service.normalize_search_precision_mode` + `agent_api_default_image_precision` in config |
| Hit shape | `src/domain/search_hit.py` → `SearchHit` → JSON in `_hits_to_payload` |
| Enriched hit fields | `src/web/agent_api.py` → `_enrich_hit_payload` |
| `POST /export/manifest` | `src/web/agent_api.py` → `execute_export_manifest` |
| Library discovery | `src/services/agent_library_service.py` → `list_agent_libraries`, `list_agent_library_videos` |
| Agent starter paste | `src/services/agent_starter_service.py` → `build_agent_starter_text` (`get_resource_path` for doc lookup) |
| `POST /export/clip` | `src/services/agent_clip_service.py` → `execute_agent_export_clip` |
| Crop locate (`preview_anchor_sec`) | `src/web/agent_api.py` → `execute_agent_search` → `run_search(..., preview_anchor_sec=…)` |
| Screenshot telemetry | `src/services/search_telemetry.py` — shared by GUI + Agent; `GET /search/telemetry` → `get_agent_search_telemetry` |

---

## 11. Changelog

| Date | Change |
|------|--------|
| 2026-05-25 | Initial agent guide |
| 2026-05-25 | v1 API shipped (`health` + `search`); §0 draft protocol notes |
| 2026-05-25 | P0: scope filter, enriched hits, `export/manifest` |
| 2026-05-25 | Doc sync: Status, §4–§9, batch/manifest params, screenshot workflow |
| 2026-05-25 | §5 numbering, `/health` contract fields, manifest `sources` note, §10 mapping |
| 2026-05-26 | v2: `scope.library_paths`, `scope.use_saved_scope`, per-library index health fields |
| 2026-05-26 | §2: clarify query label vs search presets vs video metadata tags; §5.5 preset sketch; plan in `docs/planned_features.md` |
| 2026-05-27 | Search presets API: `GET /search/presets`, `GET /search/presets/{id}`, `POST /search` + `preset_id`; §5 renumbered; `capabilities.search_presets` |
| 2026-05-31 | GUI parity: default scope mirrors desktop picker (omit `scope`); preset `video_paths`; `search_precision_mode`; preset `pixel_query_data` rerank; `capabilities.search_precision` |
| 2026-05-31 | Agent timeouts: fast **90s** / precise **180s** per search; batch **1200s** floor with dynamic scaling; `search_timeout_precise_sec` + `agent_api_default_image_precision` on `/health`; `meta.search_timeout_sec` / `meta.batch_timeout_sec` on responses |
| 2026-05-31 | Doc/code alignment: shared `search_request_service` + `search_scope`; fix stale **120s** timeout text; §8 config keys; §10 mapping |
| 2026-05-31 | v1.1: `GET /libraries`, `GET /libraries/videos`, `POST /export/clip`; `library_discovery` + `export_clip` capabilities; workflow §4 uses library discovery before search |
| 2026-05-31 | `GET /agent-starter` + Settings「复制 Agent 说明」— short paste onboarding (not full for-agents.md) |
| 2026-05-31 | `full_doc_rel` + Nuitka-friendly doc lookup via `get_resource_path("docs/for-agents.md")` |
| 2026-06-01 | Screenshot locate: `preview_anchor_sec` on `POST /search`; `GET /search/telemetry`; shared `search_telemetry` with desktop; `capabilities.crop_locate` + `search_telemetry` |

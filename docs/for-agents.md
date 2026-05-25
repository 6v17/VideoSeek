# VideoSeek — Agent Integration Guide

This document is for **external agents** (Cursor, Claude Code, custom scripts, MCP tools) that help users turn **scripts / copy** into **rough-cut material lists** using VideoSeek’s **visual semantic search**.

> **Status:** **In development** — on `http://127.0.0.1:8765` when the desktop app is running **and** Agent API is enabled in **Settings → General → Agent API (localhost)** (`src/web/agent_api.py`). Default: **off**.
>
> Endpoints: `GET /api/v1/health` · `POST /api/v1/search` · `POST /api/v1/search/batch` · `POST /api/v1/export/manifest`
>
> Request/response fields may still change before a public freeze. Treat this doc as the current draft, not a permanent contract.

---

## 0. Protocol notes (draft)

The Agent API is a thin wrapper over `search_service` (not GUI automation). When the API stabilizes for external tools, these shapes are the intended baseline:

### Hit fields (minimum stable subset)

Production search responses include **additional fields** — see §5.1 (`duration_sec`, `start_timecode`, `clip_window`, etc.). Do not parse §0 alone.

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

Stable codes today: `invalid_request`, `index_not_ready`, `query_failed`, `engine_busy`.

Responses include **`api_version": "1"`**; bump only when breaking shapes intentionally.

---

## 1. What VideoSeek Is Good At

VideoSeek indexes local videos with **CLIP / SigLIP-style embeddings** and retrieves **time ranges** by:

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

## 2. Tags = Search Queries

You do **not** need a separate tagging system for v1.

- Every `search` call includes a `query` string.
- That string is the **tag name** for all hits returned in that call.
- When exporting a cut list, copy `query` into each row so downstream steps know *why* this segment was chosen.

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
    → split into beats OR batch image_folder
    → for each beat: rewrite to visual query (§3)
    → POST /search or POST /search/batch (expand_frame_hits: true; scope if single film)
    → keep top 1–3 hits per beat
    → POST /export/manifest (sources=results, dedupe: true) → cuts.json
    → ffmpeg using health.ffmpeg.ffmpeg_path
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
2. Drop hits below `min_score` if set (§5.4 presets — calibrate per library).
3. Prefer **diverse** files: do not take five hits from the same minute unless the script asks for it.
4. For rough cut, **`top_k` request 3–5**, keep **1–2** per script line.

### 4.3 Deduplication

Merge when:

- Same `video_path`, and
- Intervals overlap more than **50%** of the shorter segment, or start times within **2 s** in frame mode.

Keep the higher rank (lower `rank` number). **`POST /export/manifest` with `dedupe: true` applies the same rules server-side** (§5.3).

### 4.4 Screenshot folder workflow (end-to-end)

1. `GET /api/v1/health` — check `index_ready`, read `ffmpeg.ffmpeg_path`
2. `POST /api/v1/search/batch` — e.g. `{ "image_folder": "C:/shots", "top_k": 3, "mode": "chunk", "scope": { "video_paths": ["D:/film.mp4"] } }`
3. `POST /api/v1/export/manifest` — `{ "sources": <batch.results>, "keep_per_source": 2, "dedupe": true, "write_path": "D:/cuts.json" }`
4. Shell out to `ffmpeg.ffmpeg_path` per manifest item

Or run: `python scripts/search_from_image_folder.py "C:/shots"` (steps 2–3 in one script).

---

## 5. API Contract (v1)

**Base URL:** `http://127.0.0.1:8765` (default; override with env, see §8)  
**Prefix:** `/api/v1`  
**Binding:** localhost only by default — not exposed to LAN.  
**Auth:** none in v1 (local trust boundary).

**Safety boundary:** no index rebuild, no library/config mutation, no video export via API. Search is read-only against the index. **`export/manifest` may write a JSON file only when you pass `write_path`** (user/agent explicit).

**Concurrency:** up to **2** concurrent searches; additional requests wait on a queue. **Timeout:** 120s per search → HTTP 503 `engine_busy`.

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
    "export_manifest": true,
    "export_clip": false,
    "local_ffmpeg_clip": true
  },
  "ffmpeg": {
    "ffmpeg_available": true,
    "ffmpeg_path": "C:/Users/you/AppData/Local/VideoSeek/bin/ffmpeg.exe",
    "ffmpeg_source": "managed"
  },
  "max_concurrent_searches": 2,
  "search_timeout_sec": 120,
  "max_batch_queries": 64,
  "batch_timeout_sec": 600
}
```

| Field | Agent use |
|-------|-----------|
| `index_ready` | If `false`, do not spam `/search` — ask user to sync index in VideoSeek |
| `index_stale` | If `true`, results may be outdated until user rebuilds global index |
| `index_id` | Cache key — confirm later searches use the same index snapshot / model |
| `embedding_space` | Embedding namespace in `index_id`; useful when comparing snapshots across runs |
| `capabilities` | Skip unsupported modes (e.g. `chunk_search: false` → use `frame`; `batch_search: false` → loop `/search`) |
| `ffmpeg.ffmpeg_path` | **Do not search the disk** — use this executable for `-ss/-to` clip export |
| `ffmpeg.ffmpeg_available` | If `false`, ask user to install/import FFmpeg in VideoSeek settings |
| `ffmpeg.ffmpeg_source` | `configured` / `managed` / `bundled` / `system` / `missing` (debug) |
| `capabilities.local_ffmpeg_clip` | If `true`, agent may shell out to `ffmpeg.ffmpeg_path` after search |
| `video_count` | Files tracked in library metadata |
| `vector_count` | Vectors in the active global index for `search_mode_checked` |
| `frame_vector_count` / `chunk_vector_count` | Per-mode vector totals (even when only one mode is checked) |
| `max_batch_queries` / `batch_timeout_sec` | Batch limits — size `queries[]` and expect HTTP 503 if exceeded |

### 5.1 `POST /api/v1/search`

Find segments in the **currently indexed local library** on the machine where VideoSeek is running.

#### Request

```json
{
  "query": "足球进球 庆祝",
  "query_type": "text",
  "top_k": 5,
  "mode": "chunk",
  "min_score": null,
  "client_request_id": "beat-03",
  "scope": { "video_paths": ["D:/library/it2017.mp4"] },
  "expand_frame_hits": true,
  "pad_before_sec": 3,
  "pad_after_sec": 3
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes* | Visual search text; also used as the **tag** for these hits. |
| `query_type` | `"text"` \| `"image_path"` | yes | `text` for language queries; `image_path` for absolute path to a reference image on the same machine. |
| `top_k` | integer | no | Max hits to return. Bounds **1–200** (app config). Default: desktop `search_top_k` (**20**). |
| `mode` | `"frame"` \| `"chunk"` | no | Override desktop `search_mode`. Default: follow app settings (`frame` in fresh installs). |
| `min_score` | number \| null | no | Optional post-filter; implementation may compare against inner-product style scores. When unsure, omit and filter by rank only. |
| `client_request_id` | string | no | Echoed back for correlating script beats. |
| `scope.video_paths` | string[] | no | Limit hits to these absolute video paths (over-fetch then filter). |
| `expand_frame_hits` | boolean | no | Default `true`. Pad frame point hits by `pad_*`. |
| `pad_before_sec` / `pad_after_sec` | number | no | Default **3** / **3** when expanding frame hits. |

\* For `query_type: "image_path"`, `query` is the file path.

#### Response `200`

```json
{
  "api_version": "1",
  "ok": true,
  "query": "足球进球 庆祝",
  "query_type": "text",
  "mode": "chunk",
  "client_request_id": "beat-03",
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
    "scope_applied": true,
    "index_ready": true,
    "elapsed_ms": 240
  }
}
```

| Field | Description |
|-------|-------------|
| `hits[].rank` | 1-based order after server-side ranking |
| `hits[].video_path` | Absolute path to source media |
| `hits[].start_sec` / `end_sec` | Clip window (after pad when `expand_frame_hits: true`) |
| `hits[].score` | Similarity score (higher = better for dot-product style metrics) |
| `hits[].duration_sec` | `end_sec - start_sec` |
| `hits[].start_timecode` / `end_timecode` | `HH:MM:SS` for human review |
| `hits[].clip_window` | `raw_start_sec`, `raw_end_sec`, `padding_applied` |
| `hits[].video_duration_sec` | Present when container duration is known |
| `meta.fetch_top_k` | Internal over-fetch size when `scope` is set (then trimmed to `top_k`) |
| `meta.scope_applied` | `true` when `scope.video_paths` filtered results |

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

### 5.2 `POST /api/v1/search/batch`

Run many searches in one HTTP call (screenshot folders, storyboard beats). **Limit:** 64 items per request; **timeout:** 600s for the whole batch. Each item still respects the global search concurrency cap (2).

#### Request (screenshot folder)

```json
{
  "image_folder": "D:/storyboard/beat03",
  "top_k": 3,
  "mode": "chunk",
  "scope": { "video_paths": ["D:/library/it2017.mp4"] },
  "expand_frame_hits": true,
  "pad_before_sec": 3,
  "pad_after_sec": 3,
  "continue_on_error": true
}
```

`image_folder` scans `*.png`, `*.jpg`, `*.jpeg`, `*.webp`, `*.bmp`, `*.gif` (sorted by filename). Each file becomes one search; `client_request_id` defaults to the filename.

Batch-level **`top_k`, `mode`, `min_score`, `scope`, `expand_frame_hits`, `pad_*`** apply to every item (including folder-expanded images) unless an entry in `queries` overrides (scope per-item only).

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

Batch-level `top_k`, `mode`, `min_score`, `scope`, `expand_frame_hits`, `pad_*` apply to all items unless overridden in `queries`. You may combine `queries` + `image_folder` in one request.

| Field | Description |
|-------|-------------|
| `queries` | List of single-search bodies (same shape as §5.1) |
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
    "elapsed_ms": 1200
  }
}
```

Top-level `ok` is `false` if any item failed, but `results` still contains per-item payloads.

### 5.3 `POST /api/v1/export/manifest`

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

### 5.4 Presets (copy into agent config)

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
  "expand_frame_hits": true
}
```

Server pads frame points by default; set `expand_frame_hits: false` only if you pad manually (§4.1).

### 5.5 Planned follow-ups (v1.1+)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/export/clip` | FFmpeg subclip (side effect — gate carefully) |

---

## 6. `cuts.json` Manifest (shape reference)

**Preferred:** `POST /api/v1/export/manifest` (§5.3) after search/batch.  
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

**FFmpeg example** (one item) — read `ffmpeg.ffmpeg_path` from `/health` first:

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
2. GET http://127.0.0.1:8765/api/v1/health — stop if index_ready is false; save ffmpeg.ffmpeg_path.
3. POST /api/v1/search or /search/batch with expand_frame_hits=true, mode=chunk, top_k=5; add scope.video_paths when working on one film.
4. POST /api/v1/export/manifest with sources=<results>, dedupe=true, keep_per_source=2 (optional write_path).
5. To render clips, use health.ffmpeg.ffmpeg_path with -ss/-to from manifest items (never bare "ffmpeg").

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
| `VIDEOSEEK_AGENT_API` | *(unset)* | `0` = force off; `1` = force on (overrides config) |
| `VIDEOSEEK_AGENT_API_HOST` | `127.0.0.1` | Bind address |
| `VIDEOSEEK_AGENT_API_PORT` | `8765` | TCP port |

Enable in the app: **Settings → General → Agent API (localhost) → On → Save**. Service applies after save (and on next startup if already enabled).

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
| Search | `src/services/search_service.py` → `run_search(..., search_mode=...)` / `run_chunk_search` |
| Hit shape | `src/domain/search_hit.py` → `SearchHit` → JSON in `_hits_to_payload` |
| Enriched hit fields | `src/web/agent_api.py` → `_enrich_hit_payload` (time range, paths, scores on each hit) |
| `POST /export/manifest` | `src/web/agent_api.py` → `execute_export_manifest` |

---

## 11. Changelog

| Date | Change |
|------|--------|
| 2026-05-25 | Initial agent guide |
| 2026-05-25 | v1 API shipped (`health` + `search`); §0 draft protocol notes |
| 2026-05-25 | P0: scope filter, enriched hits, `export/manifest` |
| 2026-05-25 | Doc sync: Status, §4–§9, batch/manifest params, screenshot workflow |
| 2026-05-25 | §5 numbering, `/health` contract fields, manifest `sources` note, §10 mapping |

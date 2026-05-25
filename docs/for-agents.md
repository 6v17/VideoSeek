# VideoSeek — Agent Integration Guide

This document is for **external agents** (Cursor, Claude Code, custom scripts, MCP tools) that help users turn **scripts / copy** into **rough-cut material lists** using VideoSeek’s **visual semantic search**.

> **Status:** **In development** — `GET /api/v1/health` and `POST /api/v1/search` on `http://127.0.0.1:8765` when the desktop app is running **and** Agent API is enabled in **Settings → General → Agent API (localhost)** (`src/web/agent_api.py`). Default: **off**.
>
> Request/response fields may still change before a public freeze. Treat this doc as the current draft, not a permanent contract.

---

## 0. Protocol notes (draft)

The Agent API is a thin wrapper over `search_service` (not GUI automation). When the API stabilizes for external tools, these shapes are the intended baseline:

### Hit fields (target shape)

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
User script
    → split into lines / beats
    → for each beat: rewrite to visual query
    → POST /search (or CLI) per query
    → keep top 1–3 hits per query (by rank / score threshold)
    → dedupe (same file + overlapping time)
    → optionally expand frame hits to short intervals (§4.1)
    → emit cuts.json (and/or call export_clip later)
    → ffmpeg or NLE to assemble
```

### 4.1 Frame mode vs chunk mode

Controlled by `mode` (see §5). Desktop default is often `frame` (`config.json` → `search_mode`).

| `mode` | `start_sec` / `end_sec` | Agent handling |
|--------|-------------------------|----------------|
| `chunk` | Real interval from semantic chunking | Use as-is for rough cuts |
| `frame` | Often **equal** (single timestamp) | Expand to a clip window before export |

For **frame** hits where `start_sec == end_sec`, expand symmetrically (recommended defaults):

- `pad_before_sec`: **3**
- `pad_after_sec`: **3**

Or set `end_sec = start_sec + preview_seconds` if the API exposes desktop `preview_seconds` (default **6** in app config). Clamp to `[0, video_duration]` if duration is known.

### 4.2 Choosing hits per query

1. Sort by `rank` ascending (1 = best).
2. Drop hits below `min_score` if set (§5.2 — calibrate per library; start around **0.2–0.35** only after you inspect real scores).
3. Prefer **diverse** files: do not take five hits from the same minute unless the script asks for it.
4. For rough cut, **`top_k` request 3–5**, keep **1–2** per script line.

### 4.3 Deduplication

Merge when:

- Same `video_path`, and
- Intervals overlap more than **50%** of the shorter segment, or start times within **2 s** in frame mode.

Keep the higher rank (lower `rank` number).

---

## 5. API Contract (v1)

**Base URL:** `http://127.0.0.1:8765` (default; override with env, see §8)  
**Prefix:** `/api/v1`  
**Binding:** localhost only by default — not exposed to LAN.  
**Auth:** none in v1 (local trust boundary).

Only **read-only search** in v1 — no index rebuild, no delete, no config writes.

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
  "dimension": 512,
  "metric": "ip",
  "video_count": 42,
  "vector_count": 12040,
  "indexed_video_paths": 18,
  "index_id": "clip_onnx_default_512_ip_fresh",
  "capabilities": {
    "text_search": true,
    "image_search": true,
    "frame_search": true,
    "chunk_search": true,
    "export_manifest": false,
    "export_clip": false,
    "local_ffmpeg_clip": true
  },
  "ffmpeg": {
    "ffmpeg_available": true,
    "ffmpeg_path": "C:/Users/you/AppData/Local/VideoSeek/bin/ffmpeg.exe",
    "ffmpeg_source": "managed"
  },
  "max_concurrent_searches": 2,
  "search_timeout_sec": 120
}
```

| Field | Agent use |
|-------|-----------|
| `index_ready` | If `false`, do not spam `/search` — ask user to sync index in VideoSeek |
| `index_stale` | If `true`, results may be outdated until user rebuilds global index |
| `index_id` | Cache key — confirm later searches use the same index snapshot / model |
| `capabilities` | Skip unsupported modes (e.g. `chunk_search: false` → use `frame`) |
| `ffmpeg.ffmpeg_path` | **Do not search the disk** — use this executable for `-ss/-to` clip export |
| `ffmpeg.ffmpeg_available` | If `false`, ask user to install/import FFmpeg in VideoSeek settings |
| `ffmpeg.ffmpeg_source` | `configured` / `managed` / `bundled` / `system` / `missing` (debug) |
| `capabilities.local_ffmpeg_clip` | If `true`, agent may shell out to `ffmpeg.ffmpeg_path` after search |
| `video_count` | Files tracked in library metadata |
| `vector_count` | Vectors in the active global index for `mode` |

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
  "client_request_id": "beat-03"
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
      "score": 0.82
    }
  ],
  "meta": {
    "returned": 1,
    "top_k": 5,
    "index_ready": true,
    "elapsed_ms": 240
  }
}
```

| Field | Description |
|-------|-------------|
| `hits[].rank` | 1-based order after server-side ranking |
| `hits[].video_path` | Absolute path to source media |
| `hits[].start_sec` / `end_sec` | Seconds; see §4.1 for frame mode |
| `hits[].score` | Similarity score from retrieval (higher = better match for dot-product style metrics used in frame rerank paths) |

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

### 5.2 Presets (copy into agent config)

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
  "min_score": null
}
```

Apply §4.1 padding before any cut/export.

### 5.3 Planned follow-ups (v1.1+, fields frozen in §0)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/export/manifest` | Write `cuts.json` from hit list |
| `POST /api/v1/export/clip` | FFmpeg subclip (side effect — gate carefully) |

---

## 6. `cuts.json` Manifest (Agent → FFmpeg)

When the HTTP export endpoint does not exist yet, agents should write this file themselves after search.

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

VideoSeek finds video shots by VISUAL meaning, not dialogue. Before every search:
1. Rewrite each script beat into a short visual query (objects, action, framing).
2. Never search literal dialogue or abstract plot summaries.
3. Call GET http://127.0.0.1:8765/api/v1/health; if index_ready is false, stop and ask the user to sync the library.
4. Remember health.ffmpeg.ffmpeg_path for clipping; never guess ffmpeg location on disk.
5. Call POST http://127.0.0.1:8765/api/v1/search with query_type=text.
6. Use mode=chunk, top_k=5 for rough material; keep 1-2 hits per beat.
7. Tag each hit with the query string used.
8. If mode=frame and start_sec equals end_sec, pad about 3s before and after.
9. Dedupe overlapping hits from the same file.
10. Output cuts.json; to render clips use health.ffmpeg.ffmpeg_path with -ss/-to (not bare "ffmpeg").

If search returns empty hits, rephrase visually (synonyms, simpler nouns) at most twice.
Do not rebuild indexes or change VideoSeek settings unless the user explicitly asks.
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

v1 agent integration should expose **search only**:

- No file deletion
- No index rebuild
- No writes to `config.json`
- Worst case: irrelevant search results — same as typing a bad query in the UI

---

## 10. Mapping to Code (for maintainers)

| Doc concept | Code |
|-------------|------|
| HTTP server | `src/web/agent_api.py` → `AgentApiService` |
| GUI lifecycle | `ui/controllers/agent_api_controller.py` → start after startup |
| Search | `src/services/search_service.py` → `run_search(..., search_mode=...)` / `run_chunk_search` |
| Hit shape | `src/domain/search_hit.py` → `SearchHit` → JSON in `_hits_to_payload` |

---

## 11. Changelog

| Date | Change |
|------|--------|
| 2026-05-25 | Initial agent guide |
| 2026-05-25 | v1 API shipped (`health` + `search`); §0 draft protocol notes |

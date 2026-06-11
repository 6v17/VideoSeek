# VideoSeek 架构概览

**VideoSeek 是围绕「视频素材检索」打造的本地化平台：索引管理、搜索编排、定位预览、导出与 Agent 集成为一条工作流；CLIP 系模型只是底层 embedding，真正的价值在视频工程与闭环。**

它不是 AI 自动剪辑器，也不是「三十行 open_clip + faiss」的 Demo。Agent API（`127.0.0.1` 本机 HTTP）是附属编排面，不是云端 SaaS。产品聚焦在：

```text
建索引 → 语义检索 → 定位 / 预览 → 导出片段 →（可选）Agent 批量编排
```

**工程化才是主体**（比换哪个 CLIP 变体更重要）：抽帧与时间戳、向量缓存与增量同步、按模型 profile 隔离的 `data/model_assets/`、v2 分库索引与 scope、全局索引重建、远程库、迁移与 `asset_state` 诊断。这些叠在一起，才构成可用的素材检索平台。

**运行热点**不在理论分层图上的每个方框，而在三条链：

| 模块 | 实际角色 |
|------|----------|
| `search_service.py` | **搜索编排引擎**（frame/chunk 双路、scope、rerank、预设融合、去重合并等；未来能力会继续堆在这里） |
| `indexing_service.py` | 索引构建、复用、全局/分库合并 |
| `clip_embedding.py` | 统一 ONNX 推理后端（`clip_onnx` / `siglip2_onnx` / `chinese_clip_onnx`；换模型须重建索引） |

UI 与 `src/web/agent_api.py` 是薄控制器与调用入口，不在 FastAPI 层复制搜索逻辑。

**产品收敛**：混剪回源（Remix）、Trace 溯源等已移除；见 `docs/planned_features.md` §4。刻意不做索引重建、改用户配置、暴露 LAN 管理面——Agent 是编排者，不是库管理员。

下文描述 **代码实际怎么跑**，不是理想的「企业七层蛋糕」。若架构图有七个框而热路径只碰三个模块，以 [Reality check](#reality-check) 为准。

---

# VideoSeek Architecture

This document describes **how the code actually runs**, not an idealized “enterprise layer cake.”  
If a diagram shows seven boxes but the hot path only touches three modules, the diagram is wrong — see [Reality check](#reality-check) below.

## Public entry points (use these)

| Task | Import / call |
|------|----------------|
| Local search | `from src.services.search_service import run_search, run_chunk_search` |
| Search scope (desktop + Agent default) | `from src.services.search_scope import resolve_default_active_search_scope, resolve_effective_search_scope` |
| Preset / inline query (Agent + preset chip) | `from src.services.search_request_service import resolve_search_query_inputs` |
| Image precision (Agent / shared) | `from src.services.search_request_service import normalize_search_precision_mode` |
| Index rebuild orchestration | `from src.workflows.update_video import update_videos_flow` |
| Embedding / ONNX | `from src.core.clip_embedding import get_engine` |
| Agent HTTP | `src/web/agent_api.py` → `execute_agent_search` (calls `search_service` directly) |

**Removed:** `src/core/core.py` was a 4-line re-export shim (`run_search` → `search_service`). Do not add it back.

## Reality check

Gemini-style critiques often assume: *UI → Service → Core → Storage × 7* for every change.

**Actual local search (desktop):**

```mermaid
flowchart TB
  GUI["gui.start_search()"]
  SC["SearchController"]
  SW["SearchWorker"]
  SS["search_service.run_search()"]
  CE["clip_embedding.get_engine()"]
  RR["image_search_rerank / search_scope"]
  DISK[("FAISS + npy on disk")]

  GUI --> SC --> SW --> SS
  SS --> CE
  SS --> RR
  SS --> DISK
  SS --> |"List[SearchHit]"| SC
```

**Actual Agent search (no UI hop):**

```mermaid
flowchart LR
  HTTP["POST /api/v1/search"] --> AA["agent_api.execute_agent_search"]
  AA --> SS["search_service.run_search"]
  SS --> CE["clip_embedding"]
```

**Actual indexing:**

```mermaid
flowchart TB
  GL["gui_library_indexing"] --> IC["IndexingController — thread wiring only"]
  IC --> IW["IndexUpdateWorker"]
  IW --> WF["workflows/update_video"]
  WF --> IS["indexing_service"]
  IS --> CE["clip_embedding + extract_frames + faiss_index"]
```

### Layer verdict (where complexity really lives)

| Module | Role | Verdict |
|--------|------|---------|
| `search_service.py` | FAISS load, scope, neighbor/pixel rerank, chunk/frame branches | **Main search brain** |
| `indexing_service.py` | Frame extract, embed, chunk, write indexes | **Main index brain** |
| `clip_embedding.py` | ONNX sessions, batch encode, engine singleton | **Inference core** |
| `search_request_service.py` | Precision mode + inline image validation + preset/inline query resolution | Shared GUI + Agent |
| `search_scope.py` | Active scope, filters, `resolve_effective_search_scope` | Shared GUI + Agent |
| `agent_api.py` | HTTP, preset/scope resolution, timeouts | Own subsystem; ends at `search_service` |
| `IndexingController` / `AgentApiController` / `MobileBridgeController` | Start/stop background services | Thin — OK |
| `src/domain/search_hit.py` | `SearchHit` dataclass | Boundary type only |
| `inference_registry.py` | 3 provider factories (~25 lines) | Small plug-in table |

This is **not** “FAISS + cosine only”: frame/chunk modes, per-library indexes, scoped over-fetch, neighbor rerank, precise image pixel rerank, presets, and Agent batching all live in **services**, with **core** doing inference and low-level index I/O.

## System overview

```mermaid
flowchart LR
  UI["ui/ — Qt GUI + workers"]
  SVC["src/services/ — business logic"]
  WF["src/workflows/ — long job orchestration"]
  CORE["src/core/ — inference + frame/chunk primitives"]
  WEB["src/web/ — Agent API + optional mobile bridge"]
  STO["src/storage/ + data/ — config + artifacts"]
  CFG["config.json + app_meta"]

  UI --> SVC
  UI --> WF
  WEB --> SVC
  SVC --> CORE
  SVC --> STO
  WF --> SVC
  CORE --> STO
  CFG --> UI
  CFG --> SVC
```

## Local search sequence

```mermaid
sequenceDiagram
  participant UI as Search UI
  participant W as SearchWorker
  participant SS as search_service
  participant CE as clip_embedding
  participant IX as FAISS + npy
  UI->>W: query + scope + precision
  W->>SS: run_search(...)
  SS->>CE: query vector (unless preset vector passed)
  SS->>IX: load index / per-library indexes
  SS->>SS: top-K, scope filter, rerank
  SS-->>W: List[SearchHit]
  W-->>UI: result_ready → table + thumbs
```

Inside `run_search`, major branches:

1. **Chunk mode** → `run_chunk_search`.
2. **Scoped video list** → per-video frame search.
3. **Scoped libraries + v2 per-library index ready** → query each library index, merge.
4. **Else** → global index, optional over-fetch + `apply_search_scope`, neighbor/pixel rerank.

See also `docs/ai/pipelines.md` for the same flow in Chinese.

## Domain models (`src/domain/`)

- **`SearchHit`**: one local match (`start_sec`, `end_sec`, `score`, `video_path`). Built in `search_service`; returned to UI and Agent.
- **`RemoteSearchHit`**: remote vector search row; built in `remote_search_service`.

**Legacy:** `coerce_search_hit()` still accepts old 4-tuples at the **view boundary** (`table_views`, `ThumbLoader`). New code should pass `SearchHit` only; do not emit tuples from services.

## Inference engines (`src/core/inference_registry.py`)

- Providers register with `register_inference_engine(provider_id, factory)`.
- `clip_embedding.get_engine()` resolves the active profile’s `provider` via `build_inference_engine`.
- Built-in: **`clip_onnx`**, **`siglip2_onnx`**, **`chinese_clip_onnx`**.
- Unknown `provider` **fail fast** (no silent fallback to another model — wrong fallback would corrupt search results).
- Disk layout: `resolve_provider_dir()` in `config_store`; vectors under `data/model_assets/<provider_dir>/<variant>/`.

### Adding a model provider

1. Implement `*OnnxEngine` (often `OnnxVisionBatchMixin`).
2. `register_inference_engine("<provider>_onnx", factory)` in `clip_embedding._register_default_inference_engines`.
3. Map folder in `resolve_provider_dir()`.
4. Manifest defaults in `model_package_service` / `model_service`.
5. Users must **rebuild the library index** after switching profile.

## Configuration

- **User:** `config.json` (theme, fps, search knobs, agent timeouts, …).
- **Product:** `src/app/app_meta.py` (version URLs, manifest endpoints).
- **Reads:** prefer `src/storage/config_store.py` getters (`get_search_mode`, `get_search_top_k`, rerank getters, …).

## Auxiliary HTTP (`src/web/`)

| Module | Purpose | Weight in architecture |
|--------|---------|-------------------------|
| `agent_api.py` | Localhost Agent API (health, search, batch, presets) | **Primary** automation surface |
| `mobile_bridge.py` | Phone upload companion | Optional; thin controller wrapper |
| `display_qr.py` | QR for mobile pairing | Optional UI helper |

## Main flows (short)

### Indexing

1. UI → `IndexingController` → `IndexUpdateWorker`.
2. `workflows/update_video.update_videos_flow` orchestrates scan, embed, global/per-library indexes.
3. `indexing_service` calls `clip_embedding`, `extract_frames`, `faiss_index`.

### Remote library

Presenters/controllers on Remote Library page → `remote_library_service` staged pipeline; search via `remote_search_service`.

## Repository layout (logical)

```text
main.py
src/
  app/           config, i18n, logging
  domain/        SearchHit, RemoteSearchHit
  services/      search_service, indexing_service, search_scope, search_request_service, …
  core/          clip_embedding, extract_frames, faiss_index, inference_registry, …
  storage/       config_store, asset_store, migration_runner
  web/           agent_api, mobile_bridge, display_qr
  workflows/     update_video (index job orchestration)
ui/
  windows/       gui + feature mixins
  controllers/   thread lifecycle (search, indexing, agent, mobile, …)
  workers.py     QThread wrappers → services / workflows
docs/
  architecture.md    (this file)
  for-agents.md      Agent HTTP contract
  ai/pipelines.md    pipeline notes (ZH)
```

## Changelog

| Date | Change |
|------|--------|
| 2026-06-10 | Add Chinese product overview at top: retrieval platform positioning, workflow闭环, search orchestration engine, product scope |
| 2026-05-31 | Consolidate Agent scope/query parsing into `search_scope` + `search_request_service`; slim `agent_api` wrappers |

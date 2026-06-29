# VideoSeek — Agent API 参考

**文档角色：** 本文仅描述 **API 能力与字段**（what exists，**non-binding**）。**唯一 binding 的执行偏好（Policy kernel）** 在 **`GET /api/v1/agent-starter`** 的 `starter_text`；本文不得用于覆盖 starter 中的策略。

**读者：** 代用户通过本机 HTTP 调用 VideoSeek 的外部 AI。不是仓库开发文档。

**怎么用：**

1. 粘贴 **`GET /api/v1/agent-starter`** 的 `starter_text`（行为规则 + 实例快照 + `search_presets`）。
2. 查字段 / 默认值 / 响应形状 → **`GET /api/v1/agent-doc?format=json`** 读 `content`，或 `?format=text` 纯 Markdown。
3. 路径字段必须来自 API 响应（见 §2.2）；勿扫盘、勿猜路径、勿猜文件名。

| 前提 | 动作 |
|------|------|
| VideoSeek 运行中 | 设置 → 通用 → **本机搜索接口** → 开启 → 保存 |
| `index_ready: true` | 否则让用户在软件里同步索引 |
| 基址 | `http://127.0.0.1:8765/api/v1`（仅 `127.0.0.1`，无鉴权） |

**端点一览：**

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | 索引/能力/超时/上限 |
| GET | `/agent-starter` | 粘贴块 + 实时快照 |
| GET | `/agent-doc` | 完整本文 |
| GET | `/libraries` | 库列表 → `scope.library_paths` |
| GET | `/videos` | 已同步视频列表（全库；可选 `library_path` 筛选）→ `video_path` / `scope.video_paths` |
| GET | `/libraries/videos` | 同 `/videos`，兼容旧路径 |
| GET | `/search/presets` | 预设列表 |
| GET | `/search/presets/{preset_id}` | 单个预设 |
| POST | `/search` | 单次搜索 |
| POST | `/search/batch` | 批量搜索（可内嵌导出） |
| GET | `/search/telemetry` | 截图搜诊断（可选） |
| GET | `/videos/evidence/status` | 批量查询是否已有理解笔录（轻量） |
| GET | `/videos/evidence` | 理解笔录（可选；读盘优先，可触发生成） |
| POST | `/export/manifest` | 生成剪辑清单 JSON |
| POST | `/export/clip` | 导出单个片段 |
| POST | `/export/clips/batch` | 批量导出片段 |

---

## 1. 能力与边界

- **支持：** 在已索引视频中按画面语义检索时间段（`video_path` + 起止秒）；生成 manifest JSON；导出 mp4 片段；**可选**读取/生成理解笔录（描述服务 caption 为主，YOLO 检测为可选附加）。
- **不支持：** 精确台词/剧情检索；自动成片；修改索引或用户设置（除非用户在对话中明确要求）。

---

## 2. 全局约定

### 2.1 成功 / 错误体

成功：`{ "api_version": "1", "ok": true, ... }`

错误：`{ "api_version": "1", "ok": false, "error": { "code", "message" } }`

| HTTP | code | 含义 |
|------|------|------|
| 400 | `invalid_request` | 请求体/参数不合法（含 Pydantic 校验失败） |
| 404 | `invalid_request` / `doc_not_found` | 库/视频/源文件不存在；或 `agent-doc` 缺 md |
| 409 | `index_not_ready` / `understanding_not_ready` | 索引未就绪；或理解资源未就绪且 `ensure=true` |
| 422 | `query_failed` / `export_failed` / `no_chunks` / `video_not_found` | 搜索/导出/理解执行失败 |
| 503 | `engine_busy` / `understanding_timeout` | 超时、并发满、FFmpeg 不可用、导出队列忙；理解生成超时 |

### 2.2 路径规则（必读）

- **`video_path`**：必须**原样**来自 `hits[]`、`GET /videos`（或 `/libraries/videos`）、或导出响应；禁止按显示名/语义/终端乱码猜中文文件名。
- **`library_path`**：必须来自 `/libraries` 的 `library_path`。
- **写出路径**（`output_path`、`export.output_dir`、`write_path`）：**不得**落在已索引库根目录内（防覆盖源媒体）。
- Python 写 JSON：`ensure_ascii=False`；POST body 用 UTF-8。

### 2.3 搜索范围 `scope`

```json
{
  "scope": {
    "library_paths": ["D:/Videos/MyLibrary"],
    "video_paths": ["D:/Videos/MyLibrary/ep01.mp4"],
    "use_saved_scope": false
  }
}
```

| 情况 | 行为 |
|------|------|
| **省略 `scope`** | 使用 VideoSeek 桌面当前保存的搜索范围 |
| `library_paths` | 只搜这些库（路径来自 `/libraries`） |
| `video_paths` | 只搜这些绝对路径（来自 `GET /videos`、`/libraries/videos` 或 hits） |
| `use_saved_scope: true` | 显式使用桌面保存的范围（无 paths 时） |
| 同时给 paths | **显式 paths 优先**于 `use_saved_scope` |

响应 `meta` 会回显：`scope_applied`、`scope_library_paths`、`scope_video_paths`、`scope_uses_per_library_indexes`、`saved_search_scope_mode`。

---

## 3. 搜索输入（preset / query）

预设 id 以 **`agent-starter.search_presets`** 或 **`GET /search/presets`** 为准（含用户自建）；文档内勿硬编码 id。

| 输入 | 说明 |
|------|------|
| `preset_id` | 与 `query` 互斥；二者都缺 → 400 |
| `query` + `query_type` | `text` 或 `image_path`（`image_path` 时 `query` 为本地图片绝对路径） |
| `top_k` | 每条 query 返回 hit 数上限（1–200） |
| `image_folder` | 与 `queries` 二选一；扫描 `.png/.jpg/.jpeg/.webp/.bmp/.gif`，每张图一条 query；`client_request_id` = 文件名 |

`search_precision_mode`（图搜）：`fast` \| `precise`；未传时见 `/health` 的 `agent_api_default_image_precision`；纯文搜忽略。  
`preview_anchor_sec`：图搜且 `scope.video_paths` 恰好 1 条时可用；服务端将 `search_precision_mode` 设为 `precise`。

---

## 4. 端点参考

### 4.1 `GET /health`

**Query：** `mode`（可选，`frame` | `chunk`；默认读桌面配置）

**主要字段：**

| 字段 | 说明 |
|------|------|
| `index_ready` | 当前 mode 下全局索引是否可用 |
| `index_sync_in_progress` | 桌面是否正在同步/重建索引；为 true 时搜索结果可能不完整 |
| `index_sync_target_library_path` | 同步中的库路径；省略表示全库或未知 |
| `index_stale` / `global_index_state` | 索引新鲜度 |
| `capabilities` | `text_search`, `image_search`, `frame_search`, `chunk_search`, `export_clip`, `export_manifest`, `batch_search`, `search_presets`, `crop_locate`, `video_evidence`, `video_evidence_ready` 等 |
| `ffmpeg.ffmpeg_available` | 为 false 则无法导出 |
| `model`, `provider`, `embedding_space`, `dimension`, `metric` | 当前 embedding |
| `search_mode_default` / `search_mode_checked` | 默认与本次检查的 mode |
| `max_concurrent_searches` | 搜索并发上限（2） |
| `search_timeout_sec` / `search_timeout_precise_sec` | 单次搜索超时（可配置） |
| `max_batch_queries` | 64 |
| `max_batch_export_clips` | 64 |
| `batch_timeout_sec` | batch 基础超时 |
| `library_indexes_upgrade_needed` | true 时需重启并完成迁移 |
| `agent_api_default_image_precision` | 图搜默认 `fast` 或 `precise` |
| `search_telemetry_enabled` | 遥测开关 |
| `understanding_ready` | 描述服务是否就绪（VLM caption）；false 时勿 `ensure=true`。YOLO 为可选附加 |
| `active_understanding_profile` | 当前理解方案 id |
| `understanding_missing_components` | 未就绪时的缺失**必需**组件 id 列表 |
| `understanding_optional_missing_components` | 可选组件缺失（如 YOLO）；不影响 `understanding_ready` |
| `capabilities.video_evidence` | 理解笔录 API 是否可用（`GET /videos/evidence` 端点存在，恒为 true） |
| `capabilities.video_evidence_ready` | 与 `understanding_ready` 相同；可生成/触发生成时为 true |

---

### 4.2 `GET /agent-starter`

**Query：** `locale`（`zh` | `en`，默认 `zh`）；`mode`（同 health）

**响应：**

| 字段 | 说明 |
|------|------|
| `starter_text` | **粘贴给外部 AI 的主文本** |
| `full_doc_path` | 本机 `docs/for-agents.md` 绝对路径（可读文件） |
| `full_doc_rel` | `docs/for-agents.md` |
| `meta.search_preset_count` | 快照里预设条数 |

`starter_text` 内嵌 JSON 快照含：`api_base`, `index_ready`, `capabilities`, `search_presets[]`（id/name/query/summary）等。

---

### 4.3 `GET /agent-doc`

**Query：** `format` = `json`（默认，返回 `{ content, full_doc_path, meta }`）| `text`（纯 Markdown，`Content-Type: text/markdown`）

缺文件 → 404 `doc_not_found`。

---

### 4.4 `GET /libraries`

**响应 `libraries[]` 每项：**

| 字段 | 说明 |
|------|------|
| `library_path` | 用于 `scope.library_paths` |
| `display_name` | 展示名 |
| `index_state` | 库索引状态 |
| `video_count_total` / `video_count_indexed_ready` / `video_count_missing_source` | 计数 |
| `per_library_index_ready` | 该库 per-library 索引是否就绪 |
| `sync_in_progress` | 该库是否正在同步（见 `/health` `index_sync_in_progress`） |
| `offline` | 库目录是否存在 |

---

### 4.5 `GET /videos` · `GET /libraries/videos`

列出**已同步且可检索**的视频（默认 `ready_only=true`：`asset_state=ready` 且源文件存在）。

**Query：**

| 参数 | 默认 | 说明 |
|------|------|------|
| `library_path` | 省略=全库 | 来自 `/libraries`；指定则只列该库 |
| `video_id` | — | 精确查单条；未找到 → 404 |
| `q` | — | 按 `video_rel_path` / 文件名 / `video_id` / 库名子串匹配（不区分大小写） |
| `has_evidence` | — | `true` 只列已有笔录；`false` 只列尚无笔录 |
| `ready_only` | `true` | 只返回已同步就绪且源文件存在的视频 |
| `limit` | 500 | 最大 2000 |
| `offset` | 0 | 分页 |

**响应 `videos[]` 每项：** `video_path`（绝对路径）, `video_rel_path`, `video_id`, `library_path`, `library_display_name`, `asset_state`, `source_exists`, **`has_evidence`**

指定 `library_path` 时，响应根级还会回显 `library_path` / `library_display_name`。

**meta：** `returned`, `total_listed`, `total_ready`, `offset`, `limit`, `ready_only`, `libraries_scanned`, **`filters`**

库不存在（传了错误 `library_path`）→ 404。`video_id` 不存在 → 404。

**推荐链路：** `/libraries` → `/videos?q=…` 或 `/videos?library_path=…` → 取 `video_path` → `/search`（`scope.video_paths`）→ `/videos/evidence`

**示例：**

```http
GET /api/v1/videos
GET /api/v1/videos?library_path=D:/222库路径
GET /api/v1/videos?video_id=abc123
GET /api/v1/videos?q=ep03&has_evidence=false
GET /api/v1/libraries/videos?library_path=D:/222库路径
```

---

### 4.6 `GET /search/presets` · `GET /search/presets/{preset_id}`

**列表 `presets[]`：** `id`, `name`, `query`, `summary`, `reference_image_count`；可选 `fusion`, `top_k`, `min_score`

**详情：** `{ "preset": { ...同上 } }`

未知 id → 404。

---

### 4.7 `POST /search`

**Body（`AgentSearchRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `preset_id` | 二选一 | — | 与 `query` 互斥 |
| `query` | 二选一 | — | 文本或图片路径 |
| `query_type` | 否 | `text` | `text` \| `image_path`（`image_path` 时 `query` 为本地图片绝对路径） |
| `top_k` | 否 | 桌面配置，clamp **1–200** | 返回 hit 数上限 |
| `mode` | 否 | 桌面 `search_mode` | `frame` \| `chunk` |
| `min_score` | 否 | preset 默认或不过滤 | 过滤低分 hit |
| `search_precision_mode` | 否 | 见 health | `fast` \| `precise`；图搜未传时用 `agent_api_default_image_precision`；纯文搜忽略 |
| `client_request_id` | 否 | — | 原样回显，便于对账 |
| `scope` | 否 | 桌面范围 | 见 §2.3 |
| `expand_frame_hits` | 否 | `true` | frame 模式下点命中扩成段 |
| `pad_before_sec` / `pad_after_sec` | 否 | **3.0** | 扩段 padding（秒） |
| `preview_anchor_sec` | 否 | — | 图搜 + `scope.video_paths` 恰好 1 条；服务端强制 `precise` |

**成功响应：**

```json
{
  "ok": true,
  "query": "…",
  "query_type": "text",
  "mode": "chunk",
  "client_request_id": "beat-1",
  "preset_id": "builtin_smile",
  "preset_name": "…",
  "hits": [
    {
      "rank": 1,
      "video_path": "D:/lib/ep01.mp4",
      "start_sec": 619.5,
      "end_sec": 625.5,
      "score": 0.87,
      "duration_sec": 6.0,
      "start_timecode": "00:10:19",
      "end_timecode": "00:10:25",
      "clip_window": {
        "start_sec": 619.5,
        "end_sec": 625.5,
        "padding_applied": false,
        "raw_start_sec": 619.5,
        "raw_end_sec": 625.5
      },
      "video_duration_sec": 3600.0
    }
  ],
  "meta": {
    "returned": 1,
    "top_k": 5,
    "fetch_top_k": 5,
    "search_precision_mode": "fast",
    "index_ready": true,
    "global_index_state": "fresh",
    "scope_applied": true,
    "scope_library_paths": ["D:/lib"],
    "elapsed_ms": 1200,
    "search_timeout_sec": 90
  }
}
```

**注意：** 搜索返回的 `start_sec`/`end_sec` 已含 frame 扩段（若开启）；**不含** copy 导出的 FFmpeg 边距。

---

### 4.8 `POST /search/batch`

**Body（`AgentBatchSearchRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `queries` | 与 folder 二选一 | `[]` | 最多 **64** 条；每项同单次 search，可单独 override `top_k`/`mode`/`scope` 等 |
| `image_folder` | 与 queries 二选一 | — | 扫描目录下 `.png/.jpg/.jpeg/.webp/.bmp/.gif`，每条图一条 query（`query_type=image_path`） |
| `top_k`, `mode`, `min_score`, `search_precision_mode` | 否 | — | **批量默认**，单条未设时继承 |
| `continue_on_error` | 否 | `true` | 单条失败是否继续 |
| `scope`, `expand_frame_hits`, `pad_before_sec`, `pad_after_sec` | 否 | 同单次 | 批量级默认 |
| `export` | 否 | — | 内嵌导出，见下 |

**`export`（可选，搜完自动写 mp4）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `output_dir` | **是** | — | 输出目录；勿在库根内 |
| `encode_mode` | 否 | `copy` | `copy` \| `original` |
| `silent` | 否 | 桌面 `export_video_silent` | 无声导出 |
| `keep_per_source` | 否 | **1** | 每条成功 query 保留前 N 个 hit |
| `dedupe` | 否 | `true` | 导出前去重 |
| `continue_on_error` | 否 | `true` | 导出项失败是否继续 |

内嵌导出文件名规则：`{client_request_id或query}_rank{NN}.mp4`（冲突加后缀）。导出条目数 > 64 → 400。

**成功响应：**

```json
{
  "ok": true,
  "results": [
    {
      "ok": true,
      "query": "…",
      "query_type": "text",
      "mode": "chunk",
      "client_request_id": "beat-1",
      "hits": [ "…同单次…" ],
      "meta": { "returned": 3, "top_k": 5, "…": "…" }
    },
    {
      "ok": false,
      "client_request_id": "bad",
      "query": "…",
      "hits": [],
      "error": { "code": "invalid_request", "message": "…" }
    }
  ],
  "meta": {
    "total": 2,
    "processed": 2,
    "succeeded": 1,
    "failed": 1,
    "continue_on_error": true,
    "elapsed_ms": 5000,
    "batch_timeout_sec": 1200
  },
  "export": { "ok": true, "results": [ "…见 export/clips/batch…" ], "meta": { "…": "…" } }
}
```

顶层 `ok`：全部 query 成功且（若有 export）导出全部成功才为 true。

---

### 4.9 `POST /export/manifest`

**Body（`AgentManifestRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `items` | 与 sources 二选一 | — | 自定义片段列表 |
| `sources` | 与 items 二选一 | — | `search/batch` 的 `results[]` 整段（含 `ok`, `query`, `hits[]`…） |
| `project` | 否 | `rough-cut` | 写入 manifest |
| `keep_per_source` | 否 | **2** | 仅 **sources** 模式：每条 result 取前 N hit |
| `dedupe` | 否 | `true` | 同视频区间重叠 >50%（frame 模式另：起点差 ≤2s）则去重 |
| `write_path` | 否 | — | 若提供则写入磁盘 JSON |
| `expand_frame_hits`, `pad_*`, `mode` | 否 | 同搜索默认 | 仅 **sources** 模式重新解析 hit 时用 |

**`items[]` 每项必填：** `video_path`, `start_sec`, `end_sec`；可选 `id`, `query`, `client_request_id`, `score`, `rank`, `notes`

**`items[]` 示例：**

```json
{
  "project": "rough-cut",
  "items": [
    {
      "id": "clip-01",
      "video_path": "D:/lib/episode02.mp4",
      "start_sec": 619.5,
      "end_sec": 625.5,
      "notes": "from search hit rank 1"
    }
  ],
  "dedupe": false,
  "write_path": "D:/Exports/manifest.json"
}
```

**易错 400：**

- 只给 `{video_path,start_sec,end_sec}` 当 `sources` → **错**；应放 `items[]`。
- `items` 与 `sources` 都缺 / 解析后无条目 → 400。

**成功响应：** `{ "manifest": { "version": 1, "project": "…", "items": […] }, "meta": { "item_count", "dedupe", "write_path" } }`

---

### 4.10 `POST /export/clip` · `POST /export/clips/batch`

**单条 `export/clip` Body：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `video_path` | 是 | — | 源视频绝对路径 |
| `start_sec` / `end_sec` | 是 | — | `end_sec` **必须大于** `start_sec` |
| `output_path` | 是 | — | 必须以 **`.mp4` / `.mkv` / `.mov`** 结尾；勿在库根内 |
| `encode_mode` | 否 | `copy` | `copy`（流复制，快）\| `original`（libx264 重编码，慢，时长准） |
| `silent` | 否 | 桌面配置 | 无声 |
| `client_request_id` | 否 | — | 回显 |

**`encode_mode=copy` 时长（必读）：** 在 `[start_sec, end_sec]` **两侧各加约 2s**（`export_copy_margin_sec`，默认 2），避免关键帧切不准。

| 请求区间 | copy 导出大约时长 |
|----------|-------------------|
| 6.0s（619.5–625.5） | **~10s**（+4s） |
| 2.0s（621.5–623.5） | **~6s** |

- 期望成片 **N 秒** → 请求区间约 **`N − 4` 秒**（默认边距），或以 hit 为中心缩短窗口。
- 要**精确时长** → `encode_mode: "original"`。

**单条成功响应：** `output_path`, `video_path`, `start_sec`, `end_sec`（**实际裁切窗口，已含 copy 边距**）, `duration_sec`, `encode_mode`

**批量 `export/clips/batch`：**

| 字段 | 说明 |
|------|------|
| `items[]` | 必填，最多 **64** 条；字段同单条；单项可 override `encode_mode`/`silent` |
| `encode_mode` / `silent` | 批量默认 |
| `continue_on_error` | 默认 `true` |

**批量响应：** `{ "ok", "results": [ { "ok", "output_path", … } | { "ok": false, "error": {code,message} } ], "meta": { total, succeeded, failed, batch_timeout_sec } }`

超时：单条 120s；批量按条数估算（copy 最多 3 路并行）。

---

### 4.11 `GET /search/telemetry`

**Query：** `locale`（`zh` | `en`）

**响应：** `enabled`, `summary`, `panel_text`, `file_path`（本地遥测文件路径）

---

### 4.11.5 `GET /videos/evidence/status`

批量查询是否已有落盘的理解笔录（不读 chunk 正文，不触发生成）。

**Query：**

| 参数 | 说明 |
|------|------|
| `video_ids` | 必填；可重复 query（`video_ids=a&video_ids=b`）或逗号分隔 |

最多 **64** 个 id。

**响应 `items[]`：** `{ "video_id", "has_evidence" }`

---

### 4.12 `GET /videos/evidence`

**可选模块。** 读取（或按需生成）单视频理解笔录：chunk 级 YOLO 检测 + 描述服务 caption，可选整片 `summary`。不影响搜索/索引。

**Query：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `video_id` 或 `video_path` | 二选一 | 与 search / libraries 路径规范一致 |
| `start_sec` / `end_sec` | 否 | 与笔录 chunk **时间重叠**过滤；仅影响响应，不改落盘 |
| `ensure` | 否，默认 `false` | `true`：无笔录时触发生成并落盘；`false`：仅读盘 |

**成功响应要点：**

| 字段 | 说明 |
|------|------|
| `evidence_available` | 是否有可用笔录 |
| `video_id`, `video` | 视频标识与路径 |
| `chunks[]` | 过滤后的 chunk 证据（`evidence.vision.object_detection` / `image_caption`） |
| `summary` | 整片总结对象 `{ "text": string, "source": string }`（若有；`text` 为描述正文） |
| `provenance` | 生成来源与 profile |
| `meta.generated_by` | API 本次触发生成时为 `"agent_api"` |
| `meta.understanding_timeout_sec` | 本次请求超时预算 |

无笔录且 `ensure=false` → **HTTP 200**，`evidence_available: false`，`chunks: []`（非错误）。

**推荐编排：**

```text
GET /health → understanding_ready?
POST /search → hits
GET /videos/evidence?video_path=…&start_sec=…&end_sec=…&ensure=false
  → 无笔录则询问用户是否 ensure=true
GET /videos/evidence?…&ensure=true
  → 读 caption / summary 供 LLM 解释
```

---

## 5. 能力组合（字段级）

### 5.0 何时用 search / 何时用理解笔录

| 用户意图 | 用什么 | 说明 |
|----------|--------|------|
| 在库里**找**镜头（未知在哪条视频） | `POST /search` 或 `/search/batch` | CLIP 画面语义匹配；返回 `hits[]` |
| **解释**某条视频或某段在发生什么 | `GET /videos/evidence` | 需 `understanding_ready`；通常 **在 search 给出 `video_path` + 时间窗之后** |
| 找片 + 说明 + 导出 | search → evidence → export | 笔录不是第三种搜索，是 search 之后的可读说明层 |
| 台词 / 对白 / 剧情因果 / 自动解说成片 | **都不适用** | 笔录是 VLM 画面描述，非 ASR |

**典型 Agent 链路：**

```text
POST /search → hits
GET /videos/evidence?video_path=…&start_sec=…&end_sec=…&ensure=false
  → 读 caption 解释或筛选 hits
  → 用户同意且无笔录时再 ensure=true
POST /export/clip 或 batch+export（用户要 mp4 时）
```

binding 执行偏好以 **`GET /agent-starter`** 内 Policy kernel + 能力路由 为准。

### 5.0.1 搜索无命中时（禁止扫盘）

| 步骤 | 允许 | 禁止 |
|------|------|------|
| 1 | 换 query / 加大 `top_k` / 试 `chunk` 模式 / 缩小 `scope.library_paths` | `ls`、`find`、猜桌面文件名 |
| 2 | `GET /libraries/videos?library_path=…` 或 **`GET /videos?library_path=…`** 列出已索引视频的 **`video_path`**，再 `scope.video_paths` 只搜该条并重试 | 用显示名或终端路径拼 `video_path` |
| 3 | 仍无 hit → 告诉用户「库内无匹配」；若用户只要整片笔录且路径来自 `/libraries/videos`，可 `GET /videos/evidence` | 扫盘「碰运气」找第二段 |

**第二库某段搜不到** 不等于可以扫桌面；要么 API 列出该库视频后重试，要么承认 CLIP 没匹配上。

### 搜索

| 端点 | 能力 |
|------|------|
| `POST /search` | 单次 query；返回 `hits[]` |
| `POST /search/batch` | 多 query 或 `image_folder`；返回 `results[]` |
| `POST /search/batch` + `export` | 同上，并在 `export.output_dir` 写入 mp4；响应含 `export` 块 |
| `GET /videos/evidence` | 搜索命中后读取/生成 chunk 级理解笔录（可选） |

### 导出（可独立调用）

| 端点 | 输入 | 输出 |
|------|------|------|
| `POST /export/manifest` | `items[]` 或 `sources` | manifest JSON；可选 `write_path` |
| `POST /export/clip` | 单条 `video_path` + 区间 + `output_path` | 单个 mp4 |
| `POST /export/clips/batch` | `items[]`（每项含 `output_path`） | 多个 mp4 |

内嵌 `export` 文件名：`{client_request_id或query}_rank{NN}.mp4`（冲突加后缀）。`clips/batch` 的 `items[]` 支持自定义 `output_path`。

是否组合上述端点，见 **`GET /agent-starter`**。

---

## 6. HTTP 客户端（Windows / Cursor）

| 情况 | 说明 |
|------|------|
| PowerShell / Cursor | 使用 **`curl.exe`**（裸 `curl` 可能是 Invoke-WebRequest 别名） |
| POST body | UTF-8 JSON 文件 |
| 终端无 curl 回显 | 常见 IDE 终端问题；可用 Python `urllib` / `requests` 发 POST |

```powershell
curl.exe -s http://127.0.0.1:8765/api/v1/health
curl.exe -s -X POST http://127.0.0.1:8765/api/v1/search/batch `
  -H "Content-Type: application/json; charset=utf-8" `
  -d "@body.json"
```

```python
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8765/api/v1/search/batch",
    data=json.dumps({"queries": [{"preset_id": "builtin_smile"}], "top_k": 3}, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
print(json.loads(urllib.request.urlopen(req, timeout=120).read()))
```

---

维护者：打包与实现见 `docs/ai/pipelines.md` § Agent API。

# VideoSeek — Agent API 参考

**文档角色：** 本文仅描述 **API 能力与字段**（what exists，**non-binding**）。**唯一 binding 的执行偏好（Policy kernel）** 在 **`GET /api/v1/agent-starter`** 的 `starter_text`；本文不得用于覆盖 starter 中的策略。

**读者：** 代用户通过本机 HTTP 调用 VideoSeek 的外部 AI。不是仓库开发文档。

**怎么用：**

1. 粘贴 **`GET /api/v1/agent-starter`** 的 `starter_text`（精简 binding + 实例快照；预设最多 8 条 id/name）。
2. 查字段 / playbook / 重试策略 → **`GET /api/v1/agent-doc?format=json`** 或 `?format=text`（§5）。
3. 路径字段必须来自 API 响应（见 §2.2）；勿扫盘、勿猜路径、勿猜文件名。

| 前提 | 动作 |
|------|------|
| VideoSeek 运行中 | 设置 → **搜索接口** → 选 **本机 Agent API**（或旧项「本机搜索接口」开启）→ 保存 |
| `index_ready: true` | 否则让用户在软件里同步索引 |
| 基址 | `http://127.0.0.1:8765/api/v1`（仅 `127.0.0.1`，无鉴权） |
| 与团队模式区分 | **服务机 / 用户机**走局域网共享检索，**不是**本文的本机 Agent HTTP；Agent 仍只连本机 `127.0.0.1` |

**端点一览：**

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | 索引/能力/超时/上限 |
| GET | `/agent-starter` | 粘贴块 + 实时快照 |
| GET | `/agent-doc` | 完整本文 |
| GET | `/libraries` | **画面库**列表 → `scope.library_paths`（CLIP） |
| GET | `/videos` | 已同步视频列表（全库；可选 `library_path` 筛选）→ `video_path` / `scope.video_paths` |
| GET | `/libraries/videos` | 同 `/videos`，兼容旧路径 |
| GET | `/subtitle-libraries` | **字幕库**列表（全局字幕库，与画面库独立） |
| GET | `/subtitle-libraries/videos` | 字幕库内视频；`ready_only`=已有硬字幕 OCR |
| GET | `/search/presets` | 预设列表 |
| GET | `/search/presets/{preset_id}` | 单个预设 |
| POST | `/search` | 单次搜索 |
| POST | `/search/batch` | 批量搜索（可内嵌导出） |
| GET | `/search/telemetry` | 截图搜诊断（可选） |
| POST | `/frames/extract` | 按路径+时间取单帧 JPEG（base64） |
| POST | `/frames/extract/batch` | 批量取帧（≤16，仍返回 base64） |
| POST | `/export/manifest` | 生成剪辑清单 JSON |
| POST | `/export/timeline` | 多片段 → 剪映草稿 / 达芬奇 FCPXML / Premiere XML |
| POST | `/export/clip` | 导出单个片段 |
| POST | `/export/clips/batch` | 批量导出片段 |

---

## 1. 能力与边界

- **支持：** 在已索引视频中按画面语义检索时间段（`video_path` + 起止秒）；硬字幕/台词关键词检索；按路径+时间取单帧 JPEG；多片段导出剪映草稿 / 达芬奇 FCPXML / Premiere XML；生成 manifest JSON；导出 mp4 片段。
- **不支持：** 视频理解/总结（桌面「视频理解」页）；实时 ASR；全库剧情推理；自动成片；修改索引或用户设置（除非用户在对话中明确要求）。

---

## 2. 全局约定

### 2.1 成功 / 错误体

成功：`{ "api_version": "1", "ok": true, ... }`

错误：`{ "api_version": "1", "ok": false, "error": { "code", "message" } }`

| HTTP | code | 含义 |
|------|------|------|
| 400 | `invalid_request` | 请求体/参数不合法（含 Pydantic 校验失败） |
| 404 | `invalid_request` / `doc_not_found` | 库/视频/源文件不存在；或 `agent-doc` 缺 md |
| 409 | `index_not_ready` | 索引未就绪 |
| 422 | `query_failed` / `export_failed` / `no_chunks` / `video_not_found` | 搜索/导出执行失败 |
| 503 | `engine_busy` | 超时、并发满、FFmpeg 不可用、导出队列忙 |

### 2.2 路径规则（必读）

- **`video_path`**：必须**原样**来自 `hits[]`、`GET /videos`（或 `/libraries/videos` / `/subtitle-libraries/videos`）、或导出响应；禁止按显示名/语义/终端乱码猜中文文件名。搜索 `hits[].video_path` 会按 `video_id` 回填绝对路径（台词命中尤其依赖此字段，勿自行拼路径）。
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

响应 `meta` 会回显：`scope_applied`、`scope_library_paths`、`scope_video_paths`、`scope_uses_per_library_indexes`（true 表示本次按库过滤 Lance 加载，**非** legacy FAISS 分库直查）、`saved_search_scope_mode`。

---

## 3. 搜索输入（preset / query）

预设 id 以 **`agent-starter.search_presets`** 或 **`GET /search/presets`** 为准（含用户自建）；文档内勿硬编码 id。

| 输入 | 说明 |
|------|------|
| `preset_id` | 与 `query` 互斥；二者都缺 → 400 |
| `query` + `query_type` | `text` 或 `image_path`（`image_path` 时 `query` 为本地图片绝对路径）；也可用简写字段 `image_path`（等价于 `query` + `query_type=image_path`） |
| `search_kind` | 可选：`visual`（默认，CLIP 画面）\| `dialogue`（硬字幕/台词关键词）\| `tags`（理解页 VLM 标签）；与 `mode` frame/chunk 正交 |
| `top_k` | 每条 query 返回 hit 数上限（1–200） |
| `image_folder` | 与 `queries` 二选一；扫描 `.png/.jpg/.jpeg/.webp/.bmp/.gif`，每张图一条 query；`client_request_id` = 文件名 |

`search_precision_mode`（图搜）：`fast` \| `precise`；未传时见 `/health` 的 `agent_api_default_image_precision`；纯文搜忽略。  
`preview_anchor_sec`：图搜且 `scope.video_paths` 恰好 1 条时可用；服务端将 `search_precision_mode` 设为 `precise`。  
`search_kind=dialogue`：仅 `query_type=text`；先看 `/health` 的 `dialogue_index_ready` / `capabilities.dialogue_search`（需在桌面字幕库完成提取）。  
`search_kind=tags`：仅 `query_type=text`；先看 `/health` 的 `tag_index_ready` / `capabilities.tag_search`（需在理解页生成标签，并点「同步到搜索」写入投影；Agent **不代跑** VLM）。命中时间为 chunk 段区间；`matched_text` 为该 chunk 完整标签集（多标签用 ` · ` 拼接）。多个标签可用 `query` 写成 `tagA · tagB`（AND：同一 chunk 须同时命中）。  
`match_mode`（`search_kind=dialogue` 或 `tags`）：`exact` \| `fuzzy`（及 `auto`）；团队用户机也可把同一值放在 `search_mode` 里透传。`fuzzy` 优先完整子字段命中，再按散落命中率排序。  
`text_enhance`（仅**画面文搜** `query_type=text`）：**由 Agent 按需开关**——`true`/`false` 覆盖本机/服务机面板默认；省略则跟 `/health.text_search_enhance_enabled`。frame 与 chunk 均可。响应看 `meta.text_enhance`（意图）与 `meta.text_enhance_applied`（是否真的跑了增强）。图搜、`query_vector` 预计算、dialogue/tags **不走**增强。

**文搜增强在做什么（预期管理）：**

1. 从查询拆短语，并做有限同义扩展（规则表，不是大模型改写整句）。  
2. 用 CLIP 在原文与候选短语间挑最多约 **4** 路语义相近且彼此不太重复的查询。  
3. 各路分别 ANN 检索，再用 **RRF** 融合排序（命中分变成融合分，与单路 CLIP 分数不可直接对比）。  

**适合：** 复合画面描述（多物体/属性/场景）、口语化或同义说法多的查询。  
**不适合当万能：** 不会理解剧情推理；不会把「找某句台词」变成字幕检索（台词用 `search_kind=dialogue`）；不会把「按标签找」变成画面检索（标签用 `search_kind=tags`）；过短/无有效短语时可能 `text_enhance_applied=false` 退回普通单路文搜；更慢、占更多搜索槽。召回变宽时噪声也可能变多——无结果可开增强重试，已经过噪可 `text_enhance=false`。

---

## 4. 端点参考

### 4.1 `GET /health`

**Query：** `mode`（可选，`frame` | `chunk`；默认读桌面配置）

**主要字段：**

| 字段 | 说明 |
|------|------|
| `index_ready` | 当前 mode 下 Lance 向量库是否可用（`lance_search_is_ready`） |
| `index_sync_in_progress` | 桌面是否正在同步/重建索引；为 true 时搜索结果可能不完整 |
| `index_sync_target_library_path` | 同步中的库路径；省略表示全库或未知 |
| `index_stale` / `global_index_state` | 兼容字段；本地搜索实际以 Lance 是否就绪、桌面是否在同步为准 |
| `capabilities` | `text_search`, `image_search`, `frame_search`, `chunk_search`, `dialogue_search`, `tag_search`, `subtitle_library_discovery`, `library_discovery`, `export_clip`, `export_manifest`, `batch_search`, `search_presets`, `crop_locate`, `frame_extract`, `batch_frame_extract`, `timeline_export`, `nle_xml_export`, `jianying_draft` 等 |
| `dialogue_index_ready` / `dialogue_indexed_videos` / `dialogue_rows` | 硬字幕索引是否可用及规模 |
| `dialogue_match_modes` | 台词检索可选匹配：`["exact","fuzzy"]` |
| `tag_index_ready` / `tag_indexed_videos` / `tag_rows` | VLM 标签投影是否可用及规模（权威稿仍在理解页 JSON） |
| `tag_match_modes` | 标签检索可选匹配：`["exact","fuzzy"]` |
| `text_search_enhance_enabled` | 服务机默认是否开启画面文搜增强（请求可用 `text_enhance` 覆盖） |
| `ffmpeg.ffmpeg_available` | 为 false 则无法导出 |
| `model`, `provider`, `embedding_space`, `dimension`, `metric` | 当前 embedding |
| `search_mode_default` / `search_mode_checked` | 默认与本次检查的 mode |
| `max_concurrent_searches` | 搜索并发上限（默认 10，可配 `agent_api_max_concurrent_searches`） |
| `search_queue_wait_sec` | 拿不到搜索槽位时最多等待秒数（默认 12，可配 `agent_api_search_queue_wait_sec`）；超时返回 `503 engine_busy` |
| `search_timeout_sec` / `search_timeout_precise_sec` | 单次搜索超时（可配置） |
| `max_batch_queries` | 64 |
| `max_batch_export_clips` | 64 |
| `batch_timeout_sec` | batch 基础超时 |
| `library_indexes_upgrade_needed` | 兼容字段；Lance 主线恒为 **false**（`needs_search_index_upgrade` 已 no-op） |
| `agent_api_default_image_precision` | 图搜默认 `fast` 或 `precise` |
| `search_telemetry_enabled` | 遥测开关 |

---

### 4.2 `GET /agent-starter`

**Query：** `locale`（`zh` | `en`，默认 `zh`）；`mode`（同 health）

**响应：**

| 字段 | 说明 |
|------|------|
| `starter_text` | **粘贴给外部 AI 的主文本**；内含「读完请先告诉用户」— Agent 第一条回复须向用户说明能做什么 |
| `full_doc_path` | 本机 `docs/for-agents.md` 绝对路径（可读文件） |
| `full_doc_rel` | `docs/for-agents.md` |
| `meta.search_preset_count` | 实例预设总数 |
| `meta.search_preset_snapshot_count` | 快照内 preset 条数（≤8） |

`starter_text` 结构：**读完请先告诉用户** → **Policy kernel** → **三条铁律** → 紧凑 JSON 快照（`search_presets[]` 仅 id/name；全量 `GET /search/presets`）。

开头 **「读完请先告诉用户」** 要求 Agent 第一条回复向用户介绍能做什么；playbook 与字段细节见 **agent-doc §5**。

---

### 4.3 `GET /agent-doc`

**Query：** `format` = `json`（默认，返回 `{ content, full_doc_path, meta }`）| `text`（纯 Markdown，`Content-Type: text/markdown`）

缺文件 → 404 `doc_not_found`。

---

### 4.4 `GET /libraries`

**画面（CLIP）库。** 与字幕库独立。

**响应 `libraries[]` 每项：**

| 字段 | 说明 |
|------|------|
| `library_path` | 用于 `scope.library_paths` |
| `display_name` | 展示名 |
| `index_state` | 库索引状态 |
| `video_count_total` / `video_count_indexed_ready` / `video_count_missing_source` | 计数 |
| `per_library_index_ready` | 该库是否有 `asset_state=ready` 视频且已在 Lance 中可搜（legacy 字段名；非 FAISS 分库文件） |
| `sync_in_progress` | 该库是否正在同步（见 `/health` `index_sync_in_progress`） |
| `offline` | 库目录是否存在 |

---

### 4.4b `GET /subtitle-libraries`

**全局字幕库探测**（桌面「字幕库」页同一套元数据；可与画面库路径重叠，但状态独立）。

**响应 `libraries[]` 每项：**

| 字段 | 说明 |
|------|------|
| `library_path` | 用于台词搜索 `scope.library_paths` |
| `display_name` | 展示名 |
| `index_state` | 与可搜性对齐：`pending` / `partial` / `ready`（有 OCR 可搜时不会再报空 `pending`） |
| `searchable` | `video_count_subtitle_ready > 0` 时为 `true`（台词搜索可用） |
| `video_count_total` | 库内登记视频数 |
| `video_count_subtitle_ready` | 已有硬字幕 OCR、可台词检索的数量 |
| `video_count_missing_source` | 源文件缺失数 |
| `offline` | 库目录是否存在 |

**meta：** `kind=subtitle`，以及 `dialogue_index_ready` / `dialogue_indexed_videos` / `dialogue_rows`，`saved_dialogue_search_scope_mode`。

**推荐链路（台词）：** `GET /subtitle-libraries` →（可选）`GET /subtitle-libraries/videos` → `POST /search`（`search_kind=dialogue`）。

### 4.4c `GET /subtitle-libraries/videos`

列出字幕库视频。

| 参数 | 默认 | 说明 |
|------|------|------|
| `library_path` | 省略=全部字幕库 | 来自 `/subtitle-libraries` |
| `video_id` / `q` | — | 同画面库视频列表 |
| `ready_only` | `true` | 只返回已有 OCR 字幕（`has_transcript`）的条目 |
| `limit` / `offset` | 500 / 0 | 分页 |

**响应 `videos[]`：** `video_path`, `video_rel_path`, `video_id`, `library_path`, `library_display_name`, `source_exists`, `has_transcript`, `asset_state`（有字幕且源存在时为 `ready`）。

---

### 4.5 `GET /videos` · `GET /libraries/videos`

列出**已同步且可检索**的视频（默认 `ready_only=true`：`asset_state=ready` 且源文件存在）。

**Query：**

| 参数 | 默认 | 说明 |
|------|------|------|
| `library_path` | 省略=全库 | 来自 `/libraries`；指定则只列该库 |
| `video_id` | — | 精确查单条；未找到 → 404 |
| `q` | — | 按 `video_rel_path` / 文件名 / `video_id` / 库名子串匹配（不区分大小写） |
| `ready_only` | `true` | 只返回已同步就绪且源文件存在的视频 |
| `limit` | 500 | 最大 2000 |
| `offset` | 0 | 分页 |

**响应 `videos[]` 每项：** `video_path`（绝对路径）, `video_rel_path`, `video_id`, `library_path`, `library_display_name`, `asset_state`, `source_exists`

指定 `library_path` 时，响应根级还会回显 `library_path` / `library_display_name`。

**meta：** `returned`, `total_listed`, `total_ready`, `offset`, `limit`, `ready_only`, `libraries_scanned`, **`filters`**

库不存在（传了错误 `library_path`）→ 404。`video_id` 不存在 → 404。

**推荐链路：** `/libraries` → `/videos?q=…` 或 `/videos?library_path=…` → 取 `video_path` → `/search`（`scope.video_paths`）→ export

**示例：**

```http
GET /api/v1/videos
GET /api/v1/videos?library_path=D:/222库路径
GET /api/v1/videos?video_id=abc123
GET /api/v1/videos?q=ep03
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
| `query_type` | 否 | `text` | `text` \| `image_path`（`image_path` 时 `query` 为本地图片绝对路径）；也可用顶层字段 `image_path` 简写 |
| `search_kind` | 否 | `visual` | `visual` \| `dialogue` \| `tags`；台词用 `dialogue`，VLM 标签用 `tags`（均仅文本 query） |
| `match_mode` | 否 | `auto` | `dialogue` / `tags`：`exact` \| `fuzzy` \| `auto`；团队客户端也可经 `search_mode` 透传 |
| `text_enhance` | 否 | 跟 `/health` | **Agent 可显式开关**画面文搜增强；见 §3 机制说明；`meta.text_enhance_applied` 表示是否生效 |
| `top_k` | 否 | 桌面配置，clamp **1–200** | 返回 hit 数上限 |
| `mode` | 否 | 桌面 `search_mode` | `frame` \| `chunk`（`dialogue`/`tags` 时响应 `mode` 分别为 `dialogue`/`tags`） |
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
    "text_enhance": null,
    "text_enhance_applied": false,
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
| `top_k`, `mode`, `min_score`, `search_precision_mode`, `text_enhance` | 否 | — | **批量默认**，单条未设时继承 |
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

### 4.10 `POST /frames/extract`

按 `video_path` + `time_sec` 抽取**单帧** JPEG（base64）。用于核对命中画面、或再作为 `image_base64` 图搜；**不是**导出成片（成片用 `/export/clip`）。

**Body（`AgentFrameExtractRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `video_path` | 是 | — | 服务机本地绝对路径（须来自 `hits[]` / `/videos`，勿自拼） |
| `time_sec` | 是 | — | 秒；负值按 `0` |
| `max_edge` | 否 | **1280** | 缩放后长边上限，clamp **64–1920** |
| `client_request_id` | 否 | — | 原样回显 |

**成功响应：** `ok`, `video_path`, `time_sec`, `width`, `height`, `mime: "image/jpeg"`, `image_base64`, `client_request_id`, `meta.max_edge` / `meta.elapsed_ms`

**易错：** 路径不存在 → 404；抽帧/编码失败 → 422 `frame_extract_failed`。不接受任意 HTTP URL。

---

### 4.10a `POST /frames/extract/batch`

批量取帧（仍只返回 JPEG base64，**不落盘**）。适合搜完后挑几条 hit 核对；**不要**默认给每条搜索结果带图。

**Body（`AgentBatchFrameExtractRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `items` | 是 | — | 最多 **16**；字段同单次 `/frames/extract` |
| `max_edge` | 否 | — | 批量默认；单项未设 `max_edge` 时继承 |
| `continue_on_error` | 否 | `true` | 单条失败是否继续 |

**成功响应：** `{ "ok", "results": [ 同单次… \| {ok:false,error} ], "meta": { total, succeeded, failed, max_batch_frame_extract } }`

推荐链路：`POST /search` → 选 hit → `POST /frames/extract/batch`。

---

### 4.10b `POST /export/timeline`

把多条命中铺成**一条时间线**（带声音）：剪映草稿、达芬奇 FCPXML、或 Premiere FCP7 XML。复用桌面素材篮导出逻辑；点命中默认**锚点±3s**（约 6s，贴片头片尾）。

**Body（`AgentTimelineExportRequest`）：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `format` | 是 | — | `jianying` \| `fcpxml`（达芬奇）\| `fcp7_xml`（Premiere）；别名：`resolve`/`davinci`→fcpxml，`premiere`/`pr`→fcp7_xml |
| `items` | 是 | — | 最多 **64** 条；每项见下 |
| `write_path` | 与 `output_dir` 二选一 | — | 完整输出文件；勿写在库根内；缺扩展名时按 format 补 |
| `output_dir` | 与 `write_path` 二选一 | — | 输出目录；服务端自动生成 `{project}.fcpxml` / `{project}.xml`（重名加时间戳） |
| `drafts_dir` / `draft_name` | 否 | 本机剪映草稿根 / 自动命名 | 仅 `jianying` |
| `project` | 否 | `VideoSeek` | 工程/序列名（也用于 `output_dir` 文件名） |
| `client_request_id` | 否 | — | 回显 |

**`items[]` 每项：**

| 字段 | 说明 |
|------|------|
| `video_path` | 服务机本地绝对路径（来自 hits/`/videos`） |
| `time_sec` | 点命中；与区间二选一 → `match_kind=frame`，导出时扩成 ±3s |
| `start_sec` + `end_sec` | 区间；与 `time_sec` 二选一 → 原样使用 |
| `client_request_id` | 可选 |

**成功响应：** 均含统一字段 `export_path`（XML=`write_path`，剪映=`draft_path`）。  
XML 另有 `write_path`；剪映另有 `draft_name` / `draft_path` / `drafts_dir`。另含 `clip_count`、`skipped` / `skipped_missing`、`meta`。

**易错：** 空 items / 非法 format / XML 既无 `write_path` 也无 `output_dir` → 400；未装 `pyJianYingDraft` 或草稿目录无效 → 422。远程 URL 素材会跳过。

---

### 4.11 `POST /export/clip` · `POST /export/clips/batch`

**单条 `export/clip` Body：**

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `video_path` | 是 | — | 源视频绝对路径（须来自 `hits[]` / `/videos`，勿自拼） |
| `start_sec` / `end_sec` | 是 | — | `end_sec` **必须大于** `start_sec` |
| `output_path` | 与 `output_dir` 二选一 | — | 完整输出文件路径；必须以 **`.mp4` / `.mkv` / `.mov`** 结尾；勿在库根内 |
| `output_dir` | 与 `output_path` 二选一 | — | 输出目录；服务端按源文件名+起止秒自动生成 `.mp4`（与 batch 内嵌 `export.output_dir` 同类） |
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

### 4.12 `GET /search/telemetry`

**Query：** `locale`（`zh` | `en`）

**响应：** `enabled`, `summary`, `panel_text`, `file_path`（本地遥测文件路径）

---

## 5. Agent playbook（non-binding）

**不覆盖** starter 内 Policy kernel。用户意图匹配时选用；字段细节见 §4。

### 5.1 搜索种类

| 用户意图 | 用什么 | 说明 |
|----------|--------|------|
| 在库里**找**镜头（画面） | `POST /search` 或 `/search/batch`（默认 `search_kind=visual`） | CLIP 画面匹配 → `hits[]` |
| 按硬字幕/台词找 | `POST /search`（`search_kind=dialogue`） | 需 `dialogue_index_ready`；先探测 `/subtitle-libraries` |
| 按标签找 | `POST /search`（`search_kind=tags`） | 需 `tag_index_ready`；理解页生成后「同步到搜索」，Agent 不代跑 VLM |
| 视频理解 / 画面描述 / ASR 解说 / 生成标签 | **不适用** | 仅桌面「视频理解」页；本 API 不提供生成管线 |

### 5.2 可选场景

| 场景 | 优先用法 |
|------|----------|
| 参考图 / 截图文件夹 | `query_type: image_path` 或 batch 的 `image_folder` |
| 精确瞬间 | `mode: frame` + `expand_frame_hits: true` |
| 复合画面描述难命中 | 画面文搜加 `text_enhance: true`；过噪则 `false`；看 `meta.text_enhance_applied`（§3） |
| 核对命中画面 / 取参考帧 | `POST /frames/extract` 或 `/frames/extract/batch`（≤16）→ `image_base64`（可再图搜）；勿默认给搜索全量带图 |
| 多 hit 进剪映 / 达芬奇 / PR | `POST /export/timeline`（`format=jianying` / `fcpxml` / `fcp7_xml`；XML 用 `output_dir` 或 `write_path`；点命中默认 ±3s） |
| 较长氛围 / 动作段 | `mode: chunk`（无命中时**先问用户**再切换） |
| 要 mp4 | batch + `export`（`encode_mode: copy`，默认） |
| 要剪辑清单 JSON | `POST /export/manifest`（用户明确要求） |
| 要重编码 | `encode_mode: original`（用户明确要求） |
| 多个 beat | `POST /search/batch`（≤64）；`keep_per_source`、`dedupe`、`silent` |
| 多库 | `GET /libraries` → `scope.library_paths`；看 `sync_in_progress` |
| 图搜异常 | `GET /search/telemetry` |

### 5.3 搜索无命中（禁止扫盘）

| 步骤 | 允许 | 禁止 |
|------|------|------|
| 1 | 换 query / 加大 `top_k` / 试 `chunk` / 缩 `scope` | `ls`、`find`、猜文件名 |
| 2 | `GET /videos?q=…` 或 `?library_path=…` → `scope.video_paths` 重试 | 拼 `video_path` |
| 3 | 仍无 hit → 告知用户 | 扫盘碰运气 |

**典型链路：** `GET /health` → `GET /libraries` → search/batch → export 或 manifest。

binding 以 **`GET /agent-starter`** 内 Policy kernel 为准。

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

维护者：实现见 `src/web/agent_api/`；打包与工程约定见 `docs/engineering.md`。

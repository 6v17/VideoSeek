# VideoSeek — Agent 操作说明（本机 API）

**读者：** 帮**用户操作 VideoSeek 桌面软件**的外部 AI（Cursor、Claude、脚本等）——通过本机 HTTP 代用户：**搜镜头 → 出粗剪清单 → 裁片段**。

**不是：** 仓库开发文档、打包说明、源码索引。字段以运行中的 `GET /api/v1/health` 为准。

**省 token：** 粘贴进模型时优先用 `GET /api/v1/agent-starter`（~80 行）；本文只在需要查完整字段时打开 **§4 API**。

| 前提 | 动作 |
|------|------|
| VideoSeek **正在运行** | 设置 → 通用 → **本机搜索接口** → 开启 → 保存 |
| `GET /health` → `index_ready: true` | 否则让用户先在软件里同步/更新索引 |
| 默认地址 | `http://127.0.0.1:8765/api/v1`（仅本机，无鉴权） |

**端点：** `GET /health` · `GET /agent-starter` · `GET /libraries` · `GET /libraries/videos` · `GET /search/presets` · `GET /search/presets/{id}` · `POST /search` · `POST /search/batch` · `GET /search/telemetry` · `POST /export/manifest` · `POST /export/clip` · `POST /export/clips/batch`

---

## 1. 软件能做什么 / 不能做什么

VideoSeek 用视觉向量在**已索引的本地视频**里找时间段（路径 + 起止秒），不负责成片剪辑逻辑。

| 适合 | 不适合（除非另有字幕/ASR） |
|------|---------------------------|
| 画面、动作、物体、景别、色调 | 精确台词、剧情推理 |
| 按脚本句找 B-roll、按参考图找相似镜头 | 自动成片、转场、版权音乐 |

**你的角色：** 把用户文案改写成**可见画面**的短查询，调 API，整理命中，导出 manifest / 小片段。

---

## 2. 标准流程（粗剪）

```
GET /health → GET /libraries（拿 library_path，禁止猜文件夹）
→ 每条脚本句：改写成视觉 query（§3）
→ POST /search/batch（expand_frame_hits: true，scope 见 §4；截图批处理加 `export.output_dir` 则 **1 次 POST 搜+导出**）
→ 或分步：manifest → export/clips/batch（output 不能在库目录内）
```

**`mode`：** `chunk` = 语义段起止；`frame` = 时间点（默认会 ±3s 扩成片段，`expand_frame_hits: true`）。

**`scope`：** 省略 = 跟桌面「搜索范围」一致；或 `scope.library_paths` / `scope.video_paths` 覆盖。库路径必须来自 `/libraries`。

**分库索引：** `/health` 里 `library_indexes_upgrade_needed: false` 且 `per_library_index_ready: true` 时，指定库搜索最快；未完成升级时仍可搜（全局索引 + 过滤）。

---

## 3. 查询怎么写（必做）

1. 一句脚本 ≈ **一个可见镜头**（中文约 4–20 字，英文 3–12 词）。
2. 写**镜头里能看见的**，不要整段粘贴台词/内心戏。
3. 只有对话时，推断机位（如「主持人 半身 访谈」）或问用户。

| 用户文案 | 差 | 好 |
|----------|----|----|
| 他进球后激动地拥抱队友 | （原文） | 足球进球 庆祝 球员拥抱 |
| Host introduces the topic | literal quote | host medium shot talking to camera |

空 `hits` 不是错误——改写后再搜，最多试 2 次。

**`query` 字段：** 每次搜索的查询串；会作为 manifest 行的「为何选中」。可用桌面 **`preset_id`** 代替手写 query。

---

## 4. API 参考

**错误体（统一）：** `{ "api_version":"1", "ok":false, "error":{ "code","message" } }`

| HTTP | code | 你该做什么 |
|------|------|------------|
| 400 | `invalid_request` | 改请求体 |
| 409 | `index_not_ready` | 让用户在 VideoSeek 里建索引/等升级完成 |
| 422 | `query_failed` | 重试一次，仍失败则汇报 |
| 503 | `engine_busy` | 退避重试（搜索并发上限 2；导出 `copy` 最多 3 路并行，`original` 1 路；batch 亦同） |

**安全：** 不能删文件、不能重建索引、不能改配置。`export/manifest` 仅在你传 `write_path` 时写 JSON；`export/clip` 写你指定的 mp4/mkv/mov。

---

### `GET /health`（每次任务开头）

可选 `?mode=frame|chunk`。重点字段：

| 字段 | 含义 |
|------|------|
| `index_ready` | false → 不要批量搜 |
| `index_stale` | true → 结果可能旧，提示用户更新索引 |
| `library_indexes_upgrade_needed` | true 且你要 `scope.library_paths` → 等启动迁移或让用户点「升级搜索索引」 |
| `capabilities.export_clip` | false → 用 `ffmpeg.ffmpeg_path` 自己裁 |
| `capabilities.search_presets` | false → 只用 inline `query` |
| `search_timeout_sec` / `search_timeout_precise_sec` | 单次搜索超时（默认 90 / 180） |
| `max_batch_queries` | `POST /search/batch` 最多查询条数（默认 64） |
| `max_batch_export_clips` | `POST /export/clips/batch` 或 `search/batch` 内 `export` 最多导出条数（默认 64） |
| `agent_api_default_image_precision` | 图搜省略 `search_precision_mode` 时的默认 fast/precise |
| `saved_search_scope_mode` | 桌面 `all` / `selected`；省略 scope 时与此一致 |

---

### `GET /agent-starter`

返回短文本 `starter_text` + `full_doc_rel`。**给模型粘贴用这一份即可**，不必全文灌本文。

---

### `GET /libraries` · `GET /libraries/videos`

- `library_path` → 填入 `scope.library_paths`
- `per_library_index_ready` → 分库直查是否可用
- `/libraries/videos?library_path=...&ready_only=true` → 单库视频列表，路径可进 `scope.video_paths`

---

### `GET /search/presets` · `GET /search/presets/{id}`

桌面保存的快捷搜索（文/图/混合）。搜索时用 `preset_id`，与 `query` 二选一。响应含 `reference_image_count`、`summary`，无本地 ref 绝对路径。

---

### `POST /search`

**二选一：** `preset_id` **或** `query`（+ 可选 `query_type: text|image_path`）。

| 常用字段 | 说明 |
|----------|------|
| `top_k` | 1–200，默认 20 |
| `mode` | `frame` \| `chunk`，默认跟桌面 |
| `search_precision_mode` | 图搜：`fast` \| `precise`（精搜管线）；文搜忽略 |
| `scope.library_paths` / `scope.video_paths` | 限制范围；省略=桌面范围 |
| `expand_frame_hits` | 默认 true，frame 点扩 ±3s |
| `preview_anchor_sec` | 截图二次定位：图搜 + **仅 1 个** `scope.video_paths`；强制 precise |

```json
{
  "query": "足球进球 庆祝",
  "query_type": "text",
  "top_k": 5,
  "mode": "chunk",
  "scope": { "library_paths": ["D:/Videos/MyLibrary"] },
  "expand_frame_hits": true
}
```

**响应：** `query`（标签）、`hits[]`（`rank`, `video_path`, `start_sec`, `end_sec`, `score`, `clip_window`, `start_timecode`…）、`meta.scope_uses_per_library_indexes`、`meta.search_precision_mode`。

**截图定位两步：** ① 无 `preview_anchor_sec` 图搜得 anchor → ② 同图 + `scope.video_paths:[该视频]` + `preview_anchor_sec: anchor`。

---

### `POST /search/batch`

最多 **64** 条；`image_folder` 自动扫 png/jpg/…；或 `queries[]` 每项同单次搜索。

批量级 `top_k` / `mode` / `scope` / `search_precision_mode` 等默认作用于全部条目。`continue_on_error: true` 时单条失败不中断。

响应 `results[]` 每项形状同单次搜索。

**无胶水导出（推荐截图批处理）：** 在同一请求里加 `export`，搜完自动按规则写入 `output_dir`（文件名 `{client_request_id或query}_rank{NN}.mp4`），响应多一节 `export`（同 `export/clips/batch`）。

| `export` 字段 | 说明 |
|---------------|------|
| `output_dir` | **必填**。导出目录，勿在任一 indexed library 根下；不存在会自动创建 |
| `encode_mode` | 默认 `copy`（流拷贝，快）；`original` 重编码慢 |
| `keep_per_source` | 每条查询保留前 N 个 hit（默认 1） |
| `dedupe` | 默认 `true`，按重叠去重后再导出 |
| `continue_on_error` | 默认 `true`，单条导出失败不中断 |
| `silent` | 可选，省略则用桌面 `export_video_silent` |

```json
{
  "image_folder": "D:/Screenshots",
  "search_precision_mode": "precise",
  "expand_frame_hits": true,
  "export": {
    "output_dir": "D:/Screenshots/data",
    "encode_mode": "copy",
    "keep_per_source": 1,
    "dedupe": true
  }
}
```

仍需分步时：`results` → `export/manifest` 的 `sources`，或自建 `items[]` → `export/clips/batch`。

---

### `POST /export/manifest`

把搜索/批量结果整理成 `cuts.json`（可 `dedupe: true` 按重叠去重）。

```json
{
  "project": "ep01",
  "sources": [ "... 粘贴 batch.results 或单次响应 ..." ],
  "keep_per_source": 2,
  "dedupe": true,
  "write_path": "D:/cuts.json"
}
```

或传 `items[]` 显式行。省略 `write_path` 则只在响应体返回 manifest。

---

### `POST /export/clip`

用本机 FFmpeg 按命中时间裁片段。**一次一条**；`encode_mode: copy` 时最多 **3** 路并行，`original` 仍为 1 路。

| 字段 | 要求 |
|------|------|
| `video_path` | 源文件存在 |
| `start_sec` / `end_sec` | 来自命中，`end > start` |
| `output_path` | `.mp4`/`.mkv`/`.mov`，**不能在任一 indexed library 根目录下** |
| `encode_mode` | `copy`（默认，流拷贝，快，切点近关键帧）或 `original`（重编码 libx264，慢，兼容性好） |

先查 `/health` 的 `capabilities.export_clip`。单条调试可用本端点；**多条请用 batch**。

---

### `POST /export/clips/batch`

一次请求导出多条（最多 **64**，见 `/health` 的 `max_batch_export_clips`）。默认 `continue_on_error: true` 时并行导出；`copy` 模式仍受 3 路并发限制。

| 字段 | 说明 |
|------|------|
| `items[]` | 每项同单条：`video_path`, `start_sec`, `end_sec`, `output_path`；可选 `client_request_id`, `encode_mode`, `silent` |
| `encode_mode` | 批次默认（单项可覆盖），建议 `copy` |
| `continue_on_error` | 默认 `true`：失败项记入 `results`，其余继续；`false` 时遇错即停 |
| 响应 | `ok` 为是否全部成功；`results[]` 与单条结构相同，失败项含 `error.code` / `error.message` |

```json
{
  "encode_mode": "copy",
  "items": [
    {
      "client_request_id": "hit-1",
      "video_path": "D:/lib/ep01.mp4",
      "start_sec": 120.5,
      "end_sec": 126.5,
      "output_path": "D:/cuts/ep01_0120.mp4"
    }
  ]
}
```

**Windows + 中文路径：** PowerShell 直接 `Invoke-RestMethod` 易乱码；用 **curl** 或把 JSON 写入 UTF-8 文件再 `curl -d @body.json`（`search/batch` 的 `export` 示例见上；分步导出同理）。

---

### `GET /search/telemetry`

只读本地截图搜诊断（用户曾在桌面预览时才有 playback 偏差意义）。可选 `?locale=zh|en`。

---

## 5. 系统提示词（可复制）

```text
你是本机 VideoSeek 粗剪助手：帮用户用视觉搜索找镜头，不是改 VideoSeek 源码。
1. 把脚本改写成短视觉 query，禁止搜字面台词。
2. GET http://127.0.0.1:8765/api/v1/health — index_ready 为 false 则停。
3. GET /libraries — scope.library_paths 用返回的 library_path。
4. POST /search/batch — expand_frame_hits=true；图搜 precise；截图批处理加 export.output_dir（一次搜+导出，无需胶水）。
5. 分步时才 manifest → export/clips/batch。输出路径勿在库内。
不要重建索引、不要改用户设置，除非用户明确要求。
IDE 访问不了 127.0.0.1 时，在用户终端用 curl 调 API；Windows 中文路径用 curl + UTF-8 JSON 文件（见 §search/batch 的 export 示例）。
```

---

## 6. 环境（仅操作相关）

| 项 | 默认 |
|----|------|
| 开关 | 设置里 `agent_api_enabled`，或环境变量 `VIDEOSEEK_AGENT_API=1` |
|  host / port | `127.0.0.1` / `8765`（`VIDEOSEEK_AGENT_API_HOST` / `PORT`） |

**Windows 调 API：** 优先 `curl`；请求体存 UTF-8 的 `body.json`，避免 PowerShell 中文路径/编码乱码。示例：

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/search/batch -H "Content-Type: application/json; charset=utf-8" -d @body.json
```

维护者：打包与源码映射见 `docs/ai/pipelines.md` § Agent API。

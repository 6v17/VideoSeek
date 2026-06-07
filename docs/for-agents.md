# VideoSeek — Agent 操作说明（本机 API）

**读者：** 代用户通过本机 HTTP **搜镜头 → 出清单 → 裁片段** 的外部 AI。不是仓库开发文档。

**怎么用：** 日常只粘贴 **`GET /api/v1/agent-starter`** 返回的 `starter_text`（含实例快照、`search_presets`、流程）。需要查字段时再 **`GET /api/v1/agent-doc?format=text`**，勿扫盘、勿 `@` 猜路径。

| 前提 | 动作 |
|------|------|
| VideoSeek 运行中 | 设置 → 通用 → **本机搜索接口** → 开启 → 保存 |
| `index_ready: true` | 否则让用户在软件里同步索引 |
| 基址 | `http://127.0.0.1:8765/api/v1`（仅本机，无鉴权） |

**端点：** `health` · `agent-starter` · `agent-doc` · `libraries` · `libraries/videos` · `search/presets` · `search` · `search/batch` · `export/manifest` · `export/clip` · `export/clips/batch` · `search/telemetry`

---

## 1. 能力与边界

- **能做：** 在已索引视频里按**画面语义**找时间段（路径 + 起止秒）；导出 manifest / 小片段。
- **不能：** 按精确台词/剧情搜、自动成片、改索引或用户设置（除非用户明确要求）。
- **你的事：** 脚本拆成镜头任务 → **优先 `preset_id`** → 配不上再 inline `query` → `search/batch` → 按需导出。

---

## 2. 脚本 → preset / query

预设列表以 **`agent-starter` 的 `search_presets` 或 `GET /search/presets`** 为准（含用户自建）；不要在 md 里猜 id。

1. 一句脚本 ≈ 一个镜头任务（一条 batch 条目）。
2. 能映射到已有预设 → **`preset_id`**；勿对同一语义重复手写 query。
3. 无合适预设 → inline **`query` 对齐预设的 `query`/`summary` 风格**（景别 + 主体 + 可见动作；非台词、非剧情）。语言与当前 model 一致。
4. 空 `hits` 可换 preset、改 query 或放宽 scope；最多重试 2 次。

```json
{
  "queries": [
    { "preset_id": "builtin_smile", "client_request_id": "beat-1" },
    { "query": "主持人 半身 口播", "query_type": "text", "client_request_id": "beat-2" }
  ],
  "top_k": 5,
  "mode": "chunk",
  "scope": { "library_paths": ["D:/Videos/MyLibrary"] },
  "expand_frame_hits": true
}
```

**常用约定：** `mode` — `chunk` 语义段 / `frame` 时间点（默认 ±3s 扩段）。`scope` 省略 = 桌面搜索范围；`library_path` 必须来自 `/libraries`。

---

## 3. API 参考

**错误体：** `{ "ok": false, "error": { "code", "message" } }`

| code | 处理 |
|------|------|
| `invalid_request` | 改请求体 |
| `index_not_ready` | 让用户同步/升级索引 |
| `query_failed` | 重试一次 |
| `engine_busy` | 退避（搜索并发 2；导出 copy 最多 3 路） |
| `doc_not_found` | `agent-doc` 时安装包缺 `docs/for-agents.md` |

---

### `POST /search` · `POST /search/batch`

单次与批量共用字段。**`preset_id` 与 `query` 二选一，优先 preset。**

| 字段 | 说明 |
|------|------|
| `top_k` | 1–200，默认 20 |
| `mode` | `frame` \| `chunk` |
| `search_precision_mode` | 图搜：`fast` \| `precise`；文搜忽略 |
| `scope.library_paths` / `scope.video_paths` | 省略 = 桌面范围 |
| `expand_frame_hits` | 默认 true |
| `preview_anchor_sec` | 图搜 + 单视频 scope 时二次定位；强制 precise |

**batch：** 最多 64 条；`queries[]` 或 `image_folder`；批量级 `scope`/`mode`/`top_k` 作用于全部。`continue_on_error: true` 时单条失败不中断。

**batch 内嵌导出（截图批处理）：** 加 `export` 一次搜+写出 mp4：

| `export` | 说明 |
|----------|------|
| `output_dir` | **必填**；勿在 indexed library 根下 |
| `encode_mode` | `copy`（默认）或 `original` |
| `keep_per_source` | 每条查询保留前 N hit（默认 1） |
| `dedupe` | 默认 true |

分步导出：`results` → `export/manifest`（可选 `write_path`）→ `export/clips/batch`。

**响应 hit：** `video_path`, `start_sec`, `end_sec`, `score`, `clip_window`, `start_timecode`…

---

### `POST /export/manifest` · `/export/clip` · `/export/clips/batch`

- **manifest：** `sources`（粘贴 batch 结果）或 `items[]`；`dedupe` / `keep_per_source`；`write_path` 可选。
- **clip：** 一次一条；`video_path`, `start_sec`, `end_sec`, `output_path`（勿在库根下）；`encode_mode` 默认 `copy`。
- **clips/batch：** 最多 64 条；字段同单条；`continue_on_error` 默认 true。

先查 `/health` → `capabilities.export_clip`；无则用手动 ffmpeg（`ffmpeg_path`）。

---

### 只读端点（摘要）

| 端点 | 用途 |
|------|------|
| `GET /health` | `index_ready`, `capabilities`, 超时与 batch 上限、`library_indexes_upgrade_needed` |
| `GET /libraries` | `library_path` → `scope.library_paths` |
| `GET /libraries/videos` | 单库视频列表 → `scope.video_paths` |
| `GET /search/presets` | 预设 id/name/query/summary（与 starter 同步） |
| `GET /search/telemetry` | 截图搜诊断（可选） |

---

## 4. Windows 调 API

用 **curl**；JSON 存 UTF-8 文件，避免 PowerShell 中文路径乱码：

```bash
curl -s -X POST http://127.0.0.1:8765/api/v1/search/batch -H "Content-Type: application/json; charset=utf-8" -d @body.json
```

维护者：打包与实现见 `docs/ai/pipelines.md` § Agent API。

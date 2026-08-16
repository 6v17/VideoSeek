# VideoSeek 架构

桌面语义视频检索（PySide6 + ONNX + Lance + FFmpeg）。主流程：

```text
建索引 → 语义检索 / 硬字幕检索 → 定位 / 预览 → 导出片段 →（可选）视频理解 →（可选）本机 Agent API
```

主要模块：

| 模块 | 职责 |
|------|------|
| `search_service.py` | frame/chunk 搜索编排（`run_search` / `run_chunk_search`） |
| `search_*` 子模块 | 邻居重排、定位管线、chunk 聚合、资产加载、query 向量等（由 `search_service` 组合） |
| `search_telemetry*` | 截图搜索遥测：持久化 store、定位/播放/置信度记录、UI 格式化（由 `search_telemetry` 门面 re-export） |
| `search_preset*` | 混合搜索预设：JSON 存储、记录规范化、query 向量缓存、CRUD、搜索 plan（由 `search_preset_service` 门面 re-export） |
| `indexing_service.py` | 索引构建与复用、库内路径对齐、写 Lance |
| `clip_embedding.py` | ONNX 推理（`clip_onnx` / `siglip2_onnx` / `chinese_clip_onnx`；换模型须重建索引） |
| `lance_dialogue_search.py` / `dialogue_transcript_store.py` | 硬字幕（OCR）关键词检索；SQLite 字幕库；精确 / 模糊（单字落点命中率） |
| `understanding_service.py` | 视频总结生成、读盘/写盘、`EvidenceBundle` 编排 |
| `understanding_resource_service.py` | profile 扫描、描述服务探测、`understanding_ready`（caption-only） |
| `src/infra/` | 路径 / FFmpeg 等基础设施（从 `utils` 拆出；见 [`engineering.md`](engineering.md)） |

工程约定（新功能边界、legacy 禁扩、lint）：[`docs/engineering.md`](engineering.md)。

**存储：** 画面向量索引为 **Lance**；硬字幕文本在 **SQLite**（`transcripts.db` / `dialogue_transcript_store`），关键词 / 模糊检索**只**走该库。Lance `dialogue_segments` 无产品读写（Whisper 台词未发布；语义字幕暂缓），删除字幕时仅作防御性清理。遗留 `*_vectors.npy` / `*.faiss` 仅用于启动迁移导入与清理，不再作为热路径读缓存。

**视频理解**为可选扩展，不阻塞搜索与索引；仅桌面「视频理解」页使用，**不**暴露给 Agent API。

`ui/` 与 `src/web/agent_api/`（FastAPI 包）负责调度；搜索逻辑在 `search_service`，HTTP 层不复制。Agent 契约见 [`docs/for-agents.md`](for-agents.md)。工程硬规则见 [`docs/engineering.md`](engineering.md)。

下文按实际调用关系说明。热路径与分层图不一致时，以 [热路径](#热路径) 为准。

## 入口（改功能从这里找）

| 任务 | 导入 / 调用 |
|------|----------------|
| 本地搜索 | `from src.services.search_service import run_search, run_chunk_search` |
| 搜索范围（桌面 + Agent 默认） | `from src.services.search_scope import resolve_default_active_search_scope, resolve_effective_search_scope` |
| 预设 / 内联 query（Agent + 预设 chip） | `from src.services.search_request_service import resolve_search_query_inputs` |
| 图搜精度（Agent / 共用） | `from src.services.search_request_service import normalize_search_precision_mode` |
| 索引重建编排 | `from src.workflows.update_video import update_videos_flow` |
| Embedding / ONNX | `from src.core.clip_embedding import get_engine` |
| 硬字幕搜索 | `from src.storage.lance_dialogue_search import keyword_search_dialogue` |
| 视频总结生成 | `from src.services.understanding_service import generate_evidence_for_video` |
| 理解资源就绪 | `from src.services.understanding_resource_service import get_understanding_resource_status` |
| Agent HTTP | `src/web/agent_api/` → `execute_agent_search`（直接调 `search_service`） |

## 热路径

复杂逻辑集中在少数模块，不必按目录层级逐层改。

**桌面本地搜索：**

```mermaid
flowchart TB
  GUI["gui.start_search()"]
  SC["SearchController"]
  SW["SearchWorker"]
  SS["search_service.run_search()"]
  CE["clip_embedding.get_engine()"]
  RR["image_search_rerank / search_scope"]
  DISK[("Lance frames/chunks")]

  GUI --> SC --> SW --> SS
  SS --> CE
  SS --> RR
  SS --> DISK
  SS --> |"List[SearchHit]"| SC
```

**Agent 搜索（不经 UI）：**

```mermaid
flowchart LR
  HTTP["POST /api/v1/search"] --> AA["agent_api.execute_agent_search"]
  AA --> SS["search_service.run_search"]
  SS --> CE["clip_embedding"]
```

**建索引：**

```mermaid
flowchart TB
  GL["gui_library_indexing"] --> IC["IndexingController — 仅线程接线"]
  IC --> IW["IndexUpdateWorker"]
  IW --> WF["workflows/update_video"]
  WF --> IS["indexing_service"]
  IS --> CE["clip_embedding + extract_frames"]
  IS --> LS["lance_store upsert（带版本日志）"]
```

索引写入以 **Lance** 为准（`upsert_profile_video_vectors_from_arrays`）。默认可并行预取解码（`indexing_video_workers`，默认 2）；ONNX 推理仍串行持锁。可选实验开关 `lance_ann_enabled`（默认关）在同步结束时为大体量库建 IVF，查询仍做精确余弦重排。进程内同一时刻只允许一个索引更新任务。

**视频理解 / 总结（可选，桌面手动触发）：**

```mermaid
flowchart TB
  GU["gui_understanding — 侧栏「视频理解」页"]
  URS["understanding_resource_service — 描述服务就绪"]
  UC["UnderstandingController — 仅线程接线"]
  UW["UnderstandingVideoWorker / UnderstandingWorker"]
  US["understanding_service.generate_evidence_for_video"]
  PIPE["core/understanding/pipeline — remote caption only"]
  DISK[("data/evidence/<video_id>.json")]

  GU --> URS
  GU --> UC --> UW --> US --> PIPE
  US --> DISK
```

进入理解页时本地 profile/组件检查同步完成；**描述服务连通性**在 `UnderstandingResourceStatusWorker` 后台探测（不阻塞切页）。流水线仅跑画面描述（`image_caption` / OpenAI 兼容描述服务）；不再内置目标检测引擎。旧 evidence JSON 若含 `object_detection` 仍可展示。生成仍走 `understanding_service`，与搜索/索引解耦。

### 各层实际权重

| 模块 | 作用 | 说明 |
|------|------|------|
| `search_service.py` | Lance 资产加载、scope、neighbor/pixel rerank、chunk/frame 分支 | **搜索主逻辑** |
| `indexing_service.py` | 抽帧、embedding、chunk、写 Lance | **索引主逻辑** |
| `clip_embedding.py` | ONNX session、批量编码、引擎单例 | **推理核心** |
| `search_request_service.py` | 精度模式、内联图校验、预设/query 解析 | GUI + Agent 共用 |
| `search_scope.py` | 当前范围、过滤、`resolve_effective_search_scope` | GUI + Agent 共用 |
| `agent_api/` | HTTP、预设/scope、超时 | 独立子系统；止于 `search_service` |
| `understanding_service.py` | 单视频/批量生成、bundle 读写、历史列表 | **视频总结主逻辑** |
| `understanding_resource_service.py` | manifest 扫描、profile、remote VLM 探测 | **理解资源层** |
| `core/understanding/` | remote caption、pipeline（caption-only） | **理解推理** |
| `dialogue_transcript_store.py` | 字幕 SQLite 读写与精确/模糊匹配 | **硬字幕存储** |
| `IndexingController` / `AgentApiController` / `MobileBridgeController` / `UnderstandingController` | 启停后台服务 | 薄层 |
| `src/domain/search_hit.py` | `SearchHit` dataclass | 边界类型 |
| `src/domain/evidence_bundle.py` | `EvidenceBundle` schema | 视频总结边界类型 |
| `inference_registry.py` | 3 个 provider 工厂（约 25 行） | 小插件表 |

Frame/chunk、scope over-fetch、rerank、预设与 Agent 批处理在 **services**；**core** 负责推理与向量 I/O 原语；**storage/lance_*** 负责 Lance 持久化与检索资产加载。

## 系统总览

```mermaid
flowchart LR
  UI["ui/ — Qt GUI + workers"]
  SVC["src/services/ — 业务逻辑"]
  WF["src/workflows/ — 长任务编排"]
  CORE["src/core/ — 推理 + 抽帧/chunk 原语"]
  WEB["src/web/ — Agent API + 手机桥接"]
  STO["src/storage/ + data/ — 配置与产物"]
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

## 本地搜索时序

```mermaid
sequenceDiagram
  participant UI as 搜索 UI
  participant W as SearchWorker
  participant SS as search_service
  participant CE as clip_embedding
  participant IX as Lance（精确扫描；可选 ANN+重排）
  UI->>W: query + scope + precision
  W->>SS: run_search(...)
  SS->>CE: 查询向量（除非 preset 已带向量）
  SS->>IX: 从 Lance 表加载 frame/chunk 向量
  SS->>SS: top-K、scope 过滤、rerank
  SS-->>W: List[SearchHit]
  W-->>UI: result_ready → 表格 + 缩略图
```

`run_search` 内主要分支：

1. **Chunk 模式** → `run_chunk_search`
2. **限定视频列表** → 按视频 frame 搜
3. **限定库** → 按 `library_path` 过滤 Lance 行后检索
4. **全库** → 加载当前 profile 的 Lance frame/chunk 表，必要时 over-fetch + `apply_search_scope`，再 rerank

遗留 `*_vectors.npy` / `*.faiss` 仅迁移与清理，不参与热路径读。

## 领域模型（`src/domain/`）

- **`SearchHit`**：一条本地命中（`start_sec`、`end_sec`、`score`、`video_path`）。在 `search_service` 构造；返回给 UI 与 Agent。
- **`EvidenceBundle`**：单视频视频总结（chunk 级 caption + 可选整片 summary；schema 仍可解析旧数据中的 `object_detection`）。在 `understanding_service` 读写；schema 见 `evidence_bundle.py`。仅桌面理解页使用。

**遗留：** `coerce_search_hit()` 仍在**视图边界**（`table_views`、`ThumbLoader`）接受旧 4-tuple。新代码只传 `SearchHit`；services 不要 emit tuple。

## 推理引擎（`src/core/inference_registry.py`）

- Provider 通过 `register_inference_engine(provider_id, factory)` 注册。
- `clip_embedding.get_engine()` 按当前 profile 的 `provider` 经 `build_inference_engine` 解析。
- 内置：**`clip_onnx`**、**`siglip2_onnx`**、**`chinese_clip_onnx`**。
- 未知 `provider` **直接失败**（不静默换模型，否则会污染检索结果）。
- 磁盘布局：`config_store.resolve_provider_dir()`；向量在 `data/model_assets/<provider_dir>/<variant>/`。

### 新增模型 provider

1. 实现 `*OnnxEngine`（常用 `OnnxVisionBatchMixin`）。
2. 在 `clip_embedding._register_default_inference_engines` 里 `register_inference_engine("<provider>_onnx", factory)`。
3. 在 `resolve_provider_dir()` 映射目录名。
4. 在 `model_package_service` / `model_service` 补 manifest 默认值。
5. 用户切换 profile 后须 **重建媒体库索引**。

## 配置

- **用户：** `config.json`（主题、fps、搜索参数、Agent 超时、`understanding.remote_vlm` 等）。
- **产品：** `src/app/app_meta.py`（版本 URL、manifest 端点）。
- **读取：** 优先用 `src/storage/config_store.py` 的 getter（`get_search_mode`、`get_search_top_k`、rerank 相关等）。

## 辅助 HTTP（`src/web/`）

| 模块 | 用途 | 权重 |
|------|------|------|
| `agent_api/` | 本机 Agent API（health、search、batch、presets、export） | **主要**自动化入口；见 `for-agents.md` |
| `mobile_bridge.py` | 手机传图 | 可选；薄封装 |
| `display_qr.py` | 手机配对二维码 | 可选 UI 辅助 |

## 主流程（简）

### 建索引

1. UI → `IndexingController` → `IndexUpdateWorker`
2. `workflows/update_video.update_videos_flow` 编排扫描与提交（进程内单飞；结束时 reconcile meta↔Lance）
3. `indexing_service`：抽帧 → `clip_embedding` → `lance_store` 写入（崩溃用 upsert 版本日志回滚）

### 视频下载（可选）

侧栏 **视频下载** → `video_download_service` 解析链接并下载到本地目录；下载完成后按普通视频库同步索引。不再有独立的「远程库向量检索」路径。

### 硬字幕搜索（可选）

1. 侧栏 **视频库 → 字幕库** → 勾选视频提取画面字幕（OCR）
2. 字幕段落写入 SQLite（`dialogue_transcript_store` / `transcripts.db`）
3. 搜索页 **字幕** 标签 → `keyword_search_dialogue`：`exact` 子串，或 `fuzzy` 单字落点命中率排序（仅 SQLite；不读 Lance）
4. 结果列表对命中字做 UI 高亮（`ui/views/dialogue_highlight.py`，仅当前页渲染）

### 视频理解 / 总结（可选）

1. 侧栏 **视频理解** → `UnderstandingGuiMixin`（`gui_understanding.py`）
2. 就绪检查 → `understanding_resource_service.get_understanding_resource_status`（描述服务后台 probe）
3. 用户点「生成总结」→ `UnderstandingController` → `UnderstandingVideoWorker` → `understanding_service.generate_evidence_for_video`
4. 推理 → `core/understanding/pipeline`（仅 OpenAI 兼容描述服务 caption/summary）
5. 落盘 → `data/evidence/videos/<video_id>.json`（路径由 `understanding_paths` 解析）

不影响 `run_search` / 索引主链路。不经 Agent HTTP 暴露。

## 目录结构（逻辑）

```text
main.py
src/
  app/           配置、i18n、日志
  domain/        SearchHit, EvidenceBundle
  services/      search_service, indexing_service, understanding_*, search_scope, video_download_*, …
  core/          clip_embedding, extract_frames, faiss_index（仅 legacy/迁移）, understanding/, …
  storage/       config_store, lance_store, lance_search_index, migration_runner, …
  web/           agent_api/（包）, mobile_bridge, display_qr
  workflows/     update_video
ui/
  windows/       gui + mixin（含 gui_understanding、视频下载）
  controllers/   搜索、索引、理解、Agent、手机等线程生命周期
  workers.py     QThread → services / workflows
docs/
  architecture.md
  engineering.md
  for-agents.md
  quickstart.md
```

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-08-16 | 对齐 Lance 主线：建索引段去掉 FAISS/远程库检索；`agent_api/` 包路径；去掉对私有/缺失文档的硬链 |
| 2026-07-21 | 硬字幕仅 SQLite：去掉 Lance 文本兜底与空库导入；`dialogue_segments` 无产品读写；Lance 就绪后可手动清理遗留 npy/faiss |
| 2026-07-19 | 硬字幕 SQLite + 模糊落点检索；视频理解改为 caption-only；文案「笔录」→「总结」 |
| 2026-06-26 | 补充理解模块：入口表、热路径、领域模型、`understanding_*` 服务 |
| 2026-06-12 | 全文改为中文；精简文首概览 |
| 2026-06-10 | 增加文首中文概览 |
| 2026-05-31 | Agent scope/query 收敛到 `search_scope` + `search_request_service` |

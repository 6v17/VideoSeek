# Deep audit notes — 2026-10

## 新功能复核：`f207884` 跨机迁移（PC migrate）

### 已确证缺口（引入时）

`apply_library_path_remaps` 最初只改了：

- `meta["libraries"]` 键
- config 范围列表（`search_scope_library_paths` 等）

**没有**改写 Lance 行上的 `library_path`。

索引状态判定（`indexing_service.py`）会对比：

- `want_lib` = 当前库根（remap 后的新路径）
- `stored_lib` = Lance 里保存的 `library_path`（仍是旧机路径）

二者不一致时 `return None` → 整库被当成「未索引」，用户需要重跑 GPU 索引，尽管向量仍在磁盘上。

这与历史 S1（空 `library_path` / 按库过滤静默丢结果）同属 **「两个本该一致的身份字段分叉」** 模式。

### 修复方向（同会话落地）

在 `apply_library_path_remaps` 中补齐：

1. `lance_store.remap_lance_library_roots` — frames / chunks / dialogue_segments 的 `library_path` + `video_path` 前缀
2. `dialogue_transcript_store.remap_transcript_library_roots`
3. `evidence_tags_store.remap_tag_library_roots`

并校验导入 `format_version`（拒绝未来版本 / 非法版本）。

### 仍开放（黄灯，未在本次封死）

| 问题 | 说明 |
|---|---|
| 导入中途失败 | 目标 `data/` 可能半写入；「非空」护栏会挡住重试，无自动回滚 |
| `save_config` 时机 | 数据复制成功后才写配置；若配置保存失败会出现「数据已到、配置未切」 |

### 做得好的地方（保留）

- 拒绝导入到非空目录
- bundle format / `data/` 存在性校验
- 导入后自检 meta / library.db
- 保留本机 `ffmpeg_path` / `model_dir` 等
- 导出密钥脱敏
- remap 后 `invalidate_searchable_path_index_cache`
- 查表用 canonicalize（normcase），写入保留真实大小写

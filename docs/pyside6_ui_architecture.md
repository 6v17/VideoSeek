# VideoSeek PySide6 界面架构说明

面向 UI/UX 设计与协作的代码侧说明：描述当前主窗口如何拆分、搜索与结果如何呈现、样式与主题机制、异步与状态展示位置，以及便于改版时注意的代码结构特点。

---

## 1. 整体布局结构（`QMainWindow` 如何拆分）

- **根结构**：`MainWindow`（`QMainWindow`，`ui/windows/gui.py`）的 `centralWidget` 为横向 `QHBoxLayout` 容器（`objectName: AppRoot`）。
- **左侧**：固定宽度的 **`NavigationSidebar`**（宽度见 `ui/widgets/layout.py` 中 `COMPONENT_SIZES["sidebar_width"]`，约 248px）——品牌标题、副标题、工作区说明卡片、**五个**主导航按钮（本地搜索 / 媒体库 / **理解笔录** / 远程链接 / 设置），底部为通知、关于、语言切换、主题切换；可选 **`runtime_hint`**（推理后端简短提示，默认隐藏）。
- **右侧**：**`ContentArea`** 内为 **`QStackedWidget`**，页面顺序为：本地搜索 → 媒体库 → **理解笔录** → 远程链接 → 设置（`MainWindow._NAV_PAGE_ORDER`）。
- **页面滚动**：除**设置页**外，搜索 / 媒体库 / 链接 / 理解页均包在 **`QScrollArea`**（`_build_scroll_page`）中，`setWidgetResizable(True)`，整页纵向滚动；设置页直接放入 `QStackedWidget`，无外层 `QScrollArea`。
- **典型「搜索页」纵向层次**（`SearchPage`，`ui/widgets/components.py`）：`PageHeader`（标题、副标题、运行时资源横幅）→ 索引进行中提示条 → 「会话」横条卡片 → **左右分栏**（左：查询与操作；右：内嵌 `QVideoWidget` 预览区，`stretch` 约 5:7）→ 底部「结果」卡片。
- **典型「理解页」纵向层次**（`UnderstandingEvidencePage`）：`PageHeader` → 步骤条 → **当前一步的卡片** → 页级「上一步 / 下一步」。步骤是选片、语音、说明、剪辑、审稿（标签模式只有选片和说明）。选片卡片里是范围、视频和模型服务；「测试连接」「保存」在**这张卡片底部**，只作用于模型配置。它们不放到卡片外面，避免和「下一步」变成同一层动作。解说剪辑可用片库硬字幕 OCR + 语音 ASR；对白空说话人可用本地 CAM++ 聚声线。

**设计一句话**：左侧固定导航 + 右侧整页堆叠；内容以 **`#PanelCard`** 等大卡片分段，而非顶部 Tab 导航。

---

## 2. 核心组件：搜索栏与「过滤条件」

**本地搜索页（`SearchPage`）**

- **查询 Tab**：`#SearchQueryTabs` 三页——图搜（`#ImageDropZone`）、文搜（`QTextEdit` `text_search`）、组合搜（`SearchComposeFormWidget`）。
- **文搜粒度**：`QComboBox` `search_mode`（`"frame"` / `"chunk"`，仅文搜 Tab）。
- **搜索范围**：`SearchScopeSelect`（点击打开 `search_scope_editor`）。
- **图搜深入搜索**：`search_precision_toggle` 与手机传图同一行；仅图搜 Tab 显示（`gui_search_panel_state.py`）。
- **组合搜**：临时图文融合搜索；可「保存为预设」。预设 chip / 管理见 `gui_search_presets.py`。
- **动作**：搜索 / 清空；组合搜 Tab 另有「保存为预设」。

**结论**：图搜、文搜、组合搜（融合向量）三条 pipeline 分离；左右检索区固定等高（`search_compare_baseline_height`）。

**远程链接页（`LinkSearchPage`）** 另有链接输入、`QTextEdit` 批量链接、`QComboBox` 构建模式（下载/流式）等，属于独立的「构建 + 检索」流程。

---

## 3. 视频检索结果如何展示

- **本地向量搜索结果**：**`ResultTable`（`QTableWidget`，7 列）**，不是 `QGridLayout` 卡片墙，也不是 `QListView`。第 2 列为缩略图占位 / 异步加载后的图像；其余列为序号、文件名、时间范围、模式、相似度、操作按钮组。表格填充在 **`ui/views/table_views.py`** 的 `populate_result_table`。
- **媒体库列表**：**`QScrollArea` + 垂直 `QVBoxLayout`**，每行由 **`table_views._build_library_row_card`** 拼成库卡片（`#LibraryCard` 等），不是 `QListWidget`。
- **远程链接检索结果**：**`LinkResultTable`**，由 `ResultView.populate_network` 填充。

---

## 4. 自定义 Widget / 页面类（类名与职责摘要）

**页面级**

| 类名 | 文件 | 主要职责 |
|------|------|----------|
| `NavigationSidebar` | `ui/widgets/components.py` | 左侧导航、品牌与主题/语言入口 |
| `PageHeader` | `ui/widgets/scaffold.py` | 各页统一页头（标题、副标题）。运行时资源缺失提示在内容区顶部一条，不在每个页头里重复 |
| `SearchPage` | `ui/widgets/components.py` | 本地搜索整页（查询卡、预览卡、结果表） |
| `LibraryPage` | `ui/widgets/components.py` | 媒体库工具条、进度、库列表滚动区 |
| `UnderstandingEvidencePage` | `ui/widgets/understanding_page.py` | 理解笔录向导。模型配置的测试/保存在选片卡片内；上一步/下一步是唯一的页级动作 |
| `LinkSearchPage` | `ui/widgets/components.py` | 远程链接构建与检索整页 |
| `SettingsPage` | `ui/widgets/settings/page.py`（表单行辅助：`form.py`） | 设置表单；五张 `VSCard` 分组 |

**可复用小组件（同文件）**

| 类名 | 主要职责 |
|------|----------|
| `ResultTable` | 本地搜索结果专用 `QTableWidget` |
| `LinkResultTable` | 链接检索结果表 |
| `ClickableLabel` | 可点击标签 |
| `SamplingRuleRow` | 单条采样规则行 |
| `SettingDetailPopup` | 设置项说明浮层 |
| `NoWheelSpinBox` / `NoWheelDoubleSpinBox` / `NoWheelComboBox` | 禁用滚轮改值的输入控件 |
| `ChunkTimelineWidget` | `ui/widgets/chunk_timeline.py` | 理解页 chunk 比例时间轴；`chunk_clicked` / `chunk_double_clicked` |

**搜索范围树（`ui/widgets/video_scope_tree.py`）**

| 类名 | 主要职责 |
|------|----------|
| `VideoScopeTreeWidget` | 按库分组的卡片 + `QTreeWidget`，用于搜索范围 / 预设范围选择 |

**弹窗（`ui/dialogs/*.py`）**：多为 `QDialog` 子类，如 `AppMessageDialog`、`AboutDialog`、`NoticeDialog`、`ModelDownloadDialog`、`MobileBridgeDialog`、`SamplingRulesDialog`、`SearchScopeEditorDialog`、`SearchPresetDialog`、`ResourceTableDialog` 等。

---

## 5. 样式与主题管理

### 5.1 全局 QSS（无独立 `.qss` 文件）

- 主题定义在 **`ui/widgets/styles.py`**：长字符串 **`STYLE_TEMPLATE`**，配合 **`build_style()`** 将占位符替换为具体颜色后得到完整 QSS。
- **应用方式**：仅在 **`MainWindow.apply_theme()`**（`ui/windows/gui.py`）中对 **`QApplication.setStyleSheet(...)`** 设置**全局**样式；业务代码中一般不散落 `setStyleSheet`。
- **组件挂钩**：大量使用 **`objectName`（如 `#PanelCard`、`#ResultTable`）** 与 Qt 属性选择器，便于与 Design Token 对齐。
- **按钮角色**：主窗口 `QPushButton` 只用 `PrimaryButton` / `AccentGhostButton` / `GhostButton` / `DangerGhostButton` / `SuccessGhostButton`（`ui.widgets.button_roles.set_button_role`）。侧栏导航、向导步骤、分段开关等特殊外观用 Qt 属性 `chrome`（如 `#GhostButton[chrome="nav"]`），不再单独起 objectName。
- **动态属性**：部分控件依赖 Qt 动态属性（如 `#StatusHint[state="ok"]`），变更后通过 **`repolish_widget()`** 重新 polish。

### 5.2 明暗双主题（两套完整皮肤）

- **不是「只有暗黑」**：同一套 `STYLE_TEMPLATE` 中颜色以 token 占位（如 `__WINDOW__`、`__ACCENT__`）；**`THEME_COLORS_DARK`** 与 **`THEME_COLORS_LIGHT`** 两套色表分别生成 **`DARK_STYLE`** / **`LIGHT_STYLE`**。切换主题 = 替换整张全局 QSS。
- **切换与持久化**：侧栏主题按钮触发 **`toggle_theme()`**，更新 `is_dark_mode` 并 **`save_config`** 写入 `config["theme"]` 为 `"dark"` 或 `"light"`**；启动时从 **`load_config()`** 恢复。
- **与国际化联动**：**`toggle_language()`** 在更新文案后会再次调用 **`apply_theme()`**，减少语言切换后的样式不一致。
- **第三方 UI 皮肤库**：无（依赖 PySide6 自带控件 + 自写 QSS）。若设计稿仅针对某一主题，建议在模板中**继续使用 token** 或为另一主题单独维护色表，避免硬编码单色把浅色主题破坏。

---

## 6. 性能与交互逻辑

### 6.1 视频缩略图

- **`ThumbLoader`（`QThread`）**（`ui/workers.py`）：顺序抽帧（`get_single_thumbnail`）→ `QPixmap`，通过 **`thumb_ready`** 信号回到主线程更新表格单元格中的 `QLabel`。
- 线程内行与行之间有短 **`msleep`**，减轻 CPU 占用；为**单线程顺序**加载，非线程池并发。
- **本地搜索**：`SearchController._update_row_thumb`。占位图在 **`populate_result_table`** 中创建。

### 6.2 处理进度

- **索引更新**：`IndexingController` → `IndexUpdateWorker` 的进度信号 → **`LibraryPage`** 的 **`QProgressBar`** 与状态 **`QLabel`**。
- **理解笔录生成**：`UnderstandingController` → `UnderstandingVideoWorker` / `UnderstandingWorker` → **`UnderstandingEvidencePage`** 进度条与 chunk 时间轴（`gui_understanding.py`）；画面描述经 **描述服务**（`remote_vlm`，LM Studio / Ollama 等 OpenAI 兼容 API）。
- **段预览播放**：时间轴 **双击** → `open_segment_preview_dialog()`（`gui_preview.py`）→ **`PreviewDialog`** + VLC，播放 chunk 的 `[start_sec, end_sec]`。
- **远程库构建 / 链接检索**：**`LinkSearchPage`** 内进度条与 **`lbl_build_status` / `lbl_search_status`**（由对应 controller 驱动）。
- **首次资源下载**：`ResourceDownloadWorker` 等，多通过对话框或状态文案反馈。

### 6.3 GPU / 推理状态展示

- **设置页**：**`RuntimeGuiMixin._update_inference_backend_hint`**（`ui/windows/gui_runtime.py`）根据 **`get_engine_runtime_status()`** 更新设置区内推理后端、FFmpeg、数据目录等文案；**「查看 GPU 诊断」** 等入口在此 mixin。
- **全页横幅**：模型或 FFmpeg 未就绪时，内容区顶部**一条** `RuntimeInlineTip`（`MainWindow.runtime_banner`）显示缺失说明和「前往导入」。各页页头不再各放一份。
- **搜索失败且存在 runtime 警告**：`SearchController` 可能弹出 GPU 不可用类提示（带一次性展示控制）。

---

## 7. 代码侧改版注意点（非功能缺陷，偏协作成本）

1. **`ui/widgets/components.py` 体量很大**：多页面与小组件集中在单文件，视觉改版时 diff 面大，与 Figma 组件化拆分不易一一对应。
2. **`MainWindow.apply_texts` 集中绑定多页文案**：国际化与控件状态耦合紧，新增页面或字段常需改此处。
3. **`MainWindow` + 多个 GuiMixin**：逻辑已按文件拆分，但窗口仍是搜索、索引、预览、运行时等状态的聚合点，理解数据流需要跨文件阅读。
4. **结果展示形态不统一**：本地/远程为表，媒体库为卡片列表；若产品上要统一为卡片流或虚拟化长列表，需改 `populate_result_table` 等，而非仅换肤。
5. **缩略图策略较简单**：顺序加载 + 每行控件替换，结果量很大时需关注滚动性能与内存；已有重新搜索时 **`stop_thumbnail_loading`** 中止线程。

---

## 8. 关键文件索引（供设计/dev 对照）

| 路径 | 说明 |
|------|------|
| `ui/windows/gui.py` | `MainWindow`、页面堆叠、主题应用入口 |
| `ui/widgets/components.py` | 侧栏、各 `*Page` |
| `ui/widgets/scaffold.py` | Phase 0 页面壳与卡片 |
| `ui/widgets/result_view.py` | 结果表 + 缩略图 API |
| `ui/widgets/search_panel.py` / `preview_panel.py` | 搜索页查询区 / 预览区 |
| `ui/widgets/styles.py` | QSS 模板、明暗色表、`build_style` |
| `ui/widgets/layout.py` | 窗口与组件建议尺寸常量 |
| `ui/views/table_views.py` | 结果表/库列表等填充与行内控件组装 |
| `ui/controllers/search_controller.py` | 搜索与缩略图线程衔接 |
| `ui/controllers/understanding_controller.py` | 理解笔录生成与取消 |
| `ui/windows/gui_understanding.py` | 理解页逻辑、时间轴、导出 JSON、段预览入口 |
| `ui/windows/gui_preview.py` | 内嵌预览、`PreviewDialog`、`open_segment_preview_dialog` |
| `ui/workers.py` | `SearchWorker`、`ThumbLoader`、`IndexUpdateWorker`、`Understanding*Worker` 等 |
| `ui/windows/gui_runtime.py` | 运行时横幅、推理/GPU 相关文案与诊断 |

文档随代码演进可能滞后；以仓库当前实现为准。

---

## 9. Phase 0 组件骨架（已实现）

**代码位置**：`ui/widgets/scaffold.py`

| 组件 | objectName / 样式 | 用途 | 已接入页面 |
|------|-------------------|------|------------|
| `VSCard` | `PanelCard` / `SubPanelCard` / `NoticeCard` / `Card`（`variant="dialog"`）及 `object_name` 覆写 | 统一卡片内边距与 `content_layout` | 各主页面 + 多处 `ui/dialogs/*` |
| `VSProgressStatusRow` | 子控件 `StatusLabel` + 默认 `QProgressBar` | 进度条 + 状态文案横排 | `LibraryPage`（`progress_bar`、`lbl_status` 别名保留） |
| `PageScaffold` | 子控件 `PageHeader` | 页头 + 内容区 `content_layout` | `SearchPage`、`LibraryPage`、`LinkSearchPage`、`SettingsPage` |
| `PageHeader` | `PageHeader` | 标题 / 副标题 | 经各页 `PageScaffold.header` |
| `make_runtime_inline_tip()` | `RuntimeInlineTip`、`RuntimeInlineTipText`、`AccentGhostButton` | 内容区顶部一条运行时提示（全页共用「前往导入」） | `MainWindow.runtime_banner` |
| `make_runtime_banner()` | `RuntimeBanner`、`RuntimeBannerText` | 索引进行中等页内横幅 | `SearchPage.indexing_notice` |

**弹窗卡片**：`VSCard` 支持 `variant="dialog"`（`QFrame#Card`，与 `styles.py` 对话框区样式一致），以及关键字参数 **`object_name=`** 覆盖为 `ToolbarCard`、`DetailsCard`、`SummaryCard` 等；`link_editor`、`search_scope_editor` 等整页内容亦包在 **`VSCard`** 内。

**Phase 1 组合组件**（`ui/widgets/`）

| 组件 | 文件 | objectName 要点 | 接入 |
|------|------|-----------------|------|
| `ResultView` | `result_view.py` | 可注入 `ResultTable` / `LinkResultTable`；`populate_local` / `populate_network` | `SearchPage`、`LinkSearchPage` |
| `LinkResultTable` | `result_table.py` | `#ResultTable`（6 列，无缩略图列） | 链接页 `ResultView` |
| `DataTable` | `data_table.py` | 由 `TableSpec` 应用列宽与 resize | 表工厂基类 |
| `TableSpec` | `table_specs.py` | `LOCAL_SEARCH` / `NETWORK_LINK` 规格 | Figma 列宽对齐入口 |
| `LocalSearchCol` / `NetworkLinkCol` | `table_specs.py` | 列索引枚举 | `table_views.populate_*` |
| `SearchPanel` | `search_panel.py` | `#PanelCard` + `#SearchInput` / `#ImageDropZone` 等 | `SearchPage`（`query_card` 别名） |
| `PreviewPanel` | `preview_panel.py` | `#VideoContainer`、`#PreviewPlaceholder` | `SearchPage`（`preview_card` 别名） |
| `ResultTable` | `result_table.py` | `#ResultTable` | 由 `ResultView` 创建 |

**Figma / QSS 对齐**：改版时优先改 `styles.py` 里上述 objectName 对应段落；新页面应用 `VSCard` / `PageScaffold`，避免再手写 `QFrame` + `setObjectName("PanelCard")`。

---

## 10. 组件化演进路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| **Phase 0** | `VSCard`、`VSProgressStatusRow`、`PageScaffold`；搜索页 / 媒体库页接入；本文档组件表 | ✅ 已落地 |
| **Phase 1** | `SearchPanel`、`PreviewPanel`、`ResultView`；缩略图经 `ResultView.set_thumbnail` | ✅ 已落地 |
| **Phase 2-A** | `AppUiState` + `push_resources_status` / `push_inference_status`；索引/资源/推理 UI 经 Signal 刷新 | ✅ 已落地 |
| **Phase 2** | 链接页 `ResultView` + `populate_network`；三页结果 API 统一 | ✅ 已落地 |
| **Phase 2b** | `table_specs.py` + `DataTable`；列宽/行高/列枚举集中配置 | ✅ 已落地 |
| **Phase 2c** | `ResultView` 空结果叠层 + `set_busy`（检索中不闪空态） | ✅ 已落地 |
| **Phase 2d** | `models_ready` / `resources_ready` 改读 `ui_state`（`MainWindow.models_ready` 为属性别名） | ✅ 已落地 |
| **Phase 3-A** | `resources/tokens_*.json` → `theme_tokens.py` → `build_style()` | ✅ 已落地（token 子集，其余用默认色） |
| **Phase 3** | `SettingsPage` → `ui/widgets/settings/`；五张 `VSCard` 分组 | ✅ 已落地 |
| **Phase 3-B** | 设置页/表格 QSS 细调；Figma token 补全 | 可选 |

**原则**：Controller / Worker / Service 逻辑不动；只抽 UI 壳与状态展示入口。

---

## 11. AppUiState（Phase 2-A）

**代码**：`ui/state/app_ui_state.py`，接线在 `ui/windows/gui_ui_state.py`（`AppUiStateMixin`）。

| 状态 | 写入入口 | 信号 | UI 响应 |
|------|----------|------|---------|
| `indexing_running` | 索引开始/结束（`gui_library_indexing`） | `indexing_changed` | 搜索页索引横幅 + 动画 |
| `resources_status` | `RuntimeResourceController.status_changed` → `push_resources_status` | `resources_changed` | 横幅、禁用搜索/同步、warmup |
| `inference_status` | `push_inference_status()`（搜索/索引/设置等） | `inference_changed` | 设置页 GPU / 后端文案 |

**约定**：业务层仍用各 Controller；跨页展示状态优先 `push_*` 更新 `ui_state`，避免直接散落改多个 `lbl_status` / 横幅。

**资源就绪**：`MainWindow.models_ready` / `resources_ready` 为只读属性，转发 `ui_state`；`push_resources_status()` 为唯一写入路径（经 `RuntimeResourceController.status_changed`）。

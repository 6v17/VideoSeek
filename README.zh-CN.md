# VideoSeek 中文说明

[**中文**](./README.zh-CN.md) | [English](./README.md)

VideoSeek 是一个基于 `PySide6 + ONNX Runtime + FAISS + FFmpeg` 的桌面语义视频检索工具。

## 技术栈

- 语言：`Python`
- 桌面 UI：`PySide6`（Qt for Python）
- 向量推理：`ONNX Runtime`
- 向量索引与检索：`FAISS`
- 视频处理：`FFmpeg`
- 链接媒体提取：`yt-dlp`

## 功能概览

- 本地视频库语义检索，支持文本查询和图片查询
- CLIP 向量构建与 FAISS 近邻检索
- 命中片段应用内预览播放
- 网络库从链接增量构建并直接检索
- 应用内查看本地向量路径和网络来源链接详情

## 安装与启动

1. 安装依赖

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow ftfy regex yt-dlp
```

2. 启动应用

```bash
python main.py
```

首次启动时，程序可按 `src/app/app_meta.py` 中的远程清单自动准备运行资源。

## 项目结构

```text
main.py
src/
  app/
  core/
  services/
  workflows/
ui/
  gui.py
  components.py
  workers.py
  *_controller.py
tests/
```

## 配置说明

用户配置文件：`config.json`

- `fps`：统一抽帧频率，本地建索引与网络库构建共用
- `remote_max_frames`：网络视频抽帧保护上限（高级参数）
- `search_top_k`：检索返回条数上限
- `preview_seconds`：预览时长
- `ffmpeg_path`：FFmpeg 路径
- `model_dir`：模型目录

## 使用模型与运行资源

核心向量模型（CLIP ONNX）：

- `clip_visual.onnx`：图像编码器
- `clip_text.onnx`：文本编码器
- `bpe_simple_vocab_16e6.txt.gz`：文本 tokenizer 词表

默认模型目录：

- `%LOCALAPPDATA%\VideoSeek\models\`
- 项目目录下 `models/`

视频处理依赖：

- `ffmpeg.exe`（用于抽帧与预览）

## 网络库页面说明

网络库页面已拆分为两个区域：

- 构建区（Build Remote Library）
  - 多行链接输入框（直接粘贴链接，无弹窗）
  - 构建模式选择
  - 构建、导入、导出、查看链接、打开下载目录
  - 构建专用进度条与构建状态
- 搜索区（Search Remote Library）
  - 文本查询与图片查询
  - 搜索、清空
  - 搜索专用状态

当前交互变更：

- 输入链接不再弹“链接编辑器”窗口
- 预检不再弹阻塞弹窗
- 预检结果以状态摘要显示（accepted/blocked/risky）
- 构建与搜索状态分离显示，互不覆盖

## 网络库构建模式

- `先下载再构建`：兼容性更高
- `直接流构建`：更快，但依赖站点可稳定提供直链流

## 常见问题

1. 为什么某些链接报 `Unsupported URL`？

- 常见于搜索页、列表页、频道页，不是视频详情页
- 请使用可访问的视频详情页链接

2. 为什么某些站点报 `Fresh cookies needed`？

- 这是站点风控/鉴权限制，不是本项目内部算法错误
- 例如部分抖音页面可能要求浏览器侧最新 cookies

3. 为什么构建后新增 0 条向量？

- 输入链接可能都被预检拦截或被判定重复
- 也可能源站无法抽帧/解析，建议查看构建状态摘要

## 默认路径

- 网络索引：`data/remote/remote_index.faiss`
- 网络向量：`data/remote/remote_vectors.npy`
- 网络构建缓存：`data/remote_build_cache`
- 链接检索缓存：`data/link_cache`

## 打包

示例 Nuitka 命令（PowerShell）：

```powershell
python -m nuitka --standalone `
--plugin-enable=pyside6 `
--include-qt-plugins=multimedia `
--windows-console-mode=disable `
--output-dir=dist `
--output-filename=VideoSeek `
--windows-icon-from-ico=icon.ico `
--include-data-file=config.json=config.json `
--include-data-dir=vlc_lib=vlc_lib `
--include-package=yt_dlp `
--nofollow-import-to=yt_dlp.extractor.lazy_extractors `
--show-progress `
--verbose `
main.py
```

如果一起打包 `config.json`，建议保持以下机器本地字段为空：

- `model_dir`
- `ffmpeg_path`

否则切换到另一台机器首次启动时，可能先继承构建机上的绝对路径，再迁移到 `%LOCALAPPDATA%\VideoSeek\config.json`。

VLC 打包说明：

- 本地 VLC 预览依赖 `vlc_lib`
- 实际打包时，Nuitka 可能不会完整带上 VLC 目录中的全部 DLL
- 如果打包后的程序无法正常用 VLC 预览，建议在打包完成后，把整个 `vlc_lib` 目录完整复制到 `dist/main.dist\vlc_lib`
- 发布前至少确认以下内容存在：
  - `libvlc.dll`
  - `libvlccore.dll`
  - `plugins/`

## 测试

```bash
python -m unittest
```

## 许可证

MIT

# VideoSeek

**中文** | [English](./README.en.md)

VideoSeek 是一个基于 PySide6 + ONNX Runtime + FAISS + FFmpeg 的桌面语义视频检索工具。

## 快速开始

1. 安装依赖：

```bash
pip install -r requirements.txt
```

或手动安装（Windows；含手机桥接与二维码相关包）：

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

在 Linux / macOS 上请用 `onnxruntime` 替代 `onnxruntime-directml`（当前 GPU 路径面向 Windows DirectML，其它系统一般为 CPU 推理）。

2. 启动应用：

```bash
python main.py
```

3. 首次启动：**模型与 FFmpeg 不会随仓库自带。** 推荐：从 [123 云盘（模型）](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) 下载官方 **zip**，运行 `python main.py`，打开 **导入运行资源**，添加 `.zip` 后点 **导入并解析**（详见 **`docs/quickstart.md` 第 3.1 节**）。高级手动摆放见 § 3.2。

## 运行资源要求

- 模型文件随**当前激活的模型配置**变化（默认 `clip_onnx`；亦可通过 `model_manifest.json` 导入 `siglip2_onnx`、`chinese_clip_onnx` 等）。**主路径：** 使用 [123 云盘（模型）](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) 提供的 zip，在应用内 **导入并解析**（与 quickstart § 3.1 一致）。`src/app/app_meta.py` 中的链接主要用于 **公告 / 版本 / 关于** 等 JSON，以及对话框里 **前往下载** 打开网盘；**不要理解为**启动即可全自动拉取 ONNX（除非你自行配置可解析的 JSON 清单 URL）。
- `clip_onnx` 默认示例文件：
  - `clip_visual.onnx`
  - `clip_text.onnx`
  - `bpe_simple_vocab_16e6.txt.gz`
- `ffmpeg.exe`（用于抽帧与预览）。
- `python-vlc` + VLC 运行时（用于应用内预览播放）。

Windows 项目内 VLC 目录建议：
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/`

若 `vlc_lib/` 缺失或不完整，搜索/建库通常仍可用，但应用内预览播放可能不可用。

## 从旧版升级（≥ 1.0.82）

- 首次启动会自动做**数据结构**与**视频索引 ID**迁移（免重算，只重命名 `vector/`、`index/` 下文件并更新 `meta.json`）。
- 启动完成后若弹窗含 **【视频索引 ID（免重算）】**，表示已对齐新 ID；库同步日志里应出现 `reuse_cached_vectors`，而不是整库重新抽帧。
- 若提示仍有待迁移项，**再启动一次**即可；详情见 `docs/migration_forced_upgrade_checklist.md` §4.1。
- 关闭主窗口可在设置里选 **退出** 或 **最小化到托盘**（索引进行中会单独询问）。

## 测试

常用子集：

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

全量：`python -m unittest discover -s tests -p "test_*.py"`（见 `docs/quickstart.md`）。

## 更多文档

- 详细安装与排障：`docs/quickstart.md`
- 架构与模块说明：`docs/architecture.md`
- 外部 Agent 集成（搜索 API）：`docs/for-agents.md`

## 许可证

MIT

# VideoSeek 快速上手

本地开发与日常使用的安装、运行资源与排障说明。英文摘要见 [README.en.md](../README.en.md)。

## 1) 环境

- 系统：当前打包布局以 **Windows** 为主。
- Python：使用较新的 Python 3.x 环境。
- 安装依赖：

```bash
pip install -r requirements.txt
```

或手动安装（Windows）：

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

Linux / macOS 请将 `onnxruntime-directml` 换成 `onnxruntime`。

## 2) 启动

```bash
python main.py
```

仓库**不包含**模型与 FFmpeg。首次启动通常会弹出运行资源对话框（若已配置则可跳过）。

## 3) 运行资源（模型与 FFmpeg）

**推荐流程：** 从维护者网盘下载官方 **zip**，在应用内 **导入并解析**（见 § 3.1）。仅自定义环境或调试时再用手动摆放（§ 3.2）。

**关于 `src/app/app_meta.py`：** 其中的 URL 用于 **公告 / 版本 / 关于** 等 JSON，以及 **「前往下载」** 打开浏览器；也可能指向同一网盘。代码里仅在 `model_manifest_url` 返回 **JSON 清单** 时才会走 HTTP 拉权重——很多发行版把该字段当作 **人工下载页**，此时请走下方 zip 导入流程。

### 3.1 123 云盘模型 zip（推荐）

README 中的 **[123 云盘（模型）](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA)** 由项目维护：提供 **打包好的压缩包**，不是散落的权重文件。下载包内通常有 **PDF 教程**（多为中文），步骤如下：

1. 启动应用（`python main.py`）。
2. 出现运行资源对话框时（或从横幅 / 菜单打开 **导入运行资源**），用 **拖放区** 或 **添加文件** 选中模型 `.zip`。
3. 若压缩包附带 **`*.sha256`**，可一并加入以校验。
4. 点击 **导入并解析**。应用会解压到模型目录，并把 **`model_manifest.json`** 合并进设置（字段说明见 **§ 3.3**）。一般**不必**先手动解压到 `%LOCALAPPDATA%\VideoSeek\models\`。
5. 若注册了多个模型配置，在设置里选择 **当前模型配置**。

FFmpeg 可在**同一文件列表**中加入 **`ffmpeg.exe`**，再点 **导入并解析**，会复制到应用管理的 FFmpeg 目录。

终端用户与贡献者验证发行版时，都应优先走此路径。

### 3.2 模型文件 — 手动摆放（进阶）

仅在**不用**官方 zip 时使用，例如自定义构建或调试。

可放在：

- `%LOCALAPPDATA%\VideoSeek\models\`
- 项目根目录下的 `models/`

须与 **当前激活的模型配置** 目录结构一致（manifest 与权重同级）。默认 `clip_onnx` 示例文件名：

- `clip_visual.onnx`
- `clip_text.onnx`
- `bpe_simple_vocab_16e6.txt.gz`

换用其他 provider（如 `siglip2_onnx`、`chinese_clip_onnx`）时，所需文件随配置变化；运行时按当前 profile 校验。

zip 导入实现见 `src/services/model_package_service.py`。

### 3.3 `model_manifest.json`（打包 / 自定义）

123 云盘官方 zip **已自带**此文件——**仅在你自行打包或排查自定义包时需要本节。**

- **文件名：** **`model_manifest.json`**（不是 `manifest.json`）。
- **位置：** zip 内（或导入后磁盘上）须与模型权重 **同一文件夹**。导入后路径形如  
  `<model_dir>/<provider_folder>/<variant>/`  
  **`provider_folder`** 由 `provider` 推导，例如 `clip_onnx` → `openai-clip`，`siglip2_onnx` → `siglip2`，`chinese_clip_onnx` → `chinese-clip`（见 `src/storage/config_store.py` 的 `resolve_provider_dir`）。

**必填字段**

| 字段 | 含义 |
|------|------|
| `provider` | 推理后端 id，如 `clip_onnx`、`siglip2_onnx`、`chinese_clip_onnx` |
| `variant` 或 `model_variant` | 该 provider 下的子目录名，如 `vit-base-patch32` |

**可选字段**

| 字段 | 含义 |
|------|------|
| `id` | 设置里的 profile id；省略时由 `provider` + `variant` 推导 |
| `display_name` | 模型配置 UI 显示名 |
| `prefer_gpu` | 布尔，默认 `true` |
| `required_files` | manifest 旁必须存在的文件名列表；省略时用各 provider 内置默认 |
| `files` | 逻辑键 → 文件名的映射；省略时对已知 provider 用内置默认 |

**最小示例（`clip_onnx`）：**

```json
{
  "provider": "clip_onnx",
  "variant": "vit-base-patch32",
  "display_name": "CLIP ONNX (example)"
}
```

**最小示例（`chinese_clip_onnx`）：**

```json
{
  "provider": "chinese_clip_onnx",
  "variant": "vit-base-patch16",
  "display_name": "Chinese CLIP ViT-B/16 (512-d)"
}
```

zip 内布局示例：`chinese-clip/vit-base-patch16/model_manifest.json`，以及 `chinese_clip_image.onnx`、`chinese_clip_text.onnx`、`vocab.txt`、`preprocessor_config.json`、`config.json`。

校验与默认值以 `src/services/model_package_service.py` 的 `import_model_packages` / `_install_extracted_packages` 为准。

**切换当前模型配置**（设置 → 当前模型）：向量与 FAISS 索引在 `data/model_assets/<provider_folder>/<variant>/`。切换后须 **重新同步 / 重建媒体库索引**，再搜索或调 Agent API。搜索预设也绑定 `embedding_spec` / `model_profile_id`。

### 3.4 FFmpeg

任选其一：

- 将 `ffmpeg.exe` 放到 `%LOCALAPPDATA%\VideoSeek\bin\`
- 或保证 `ffmpeg` 在 `PATH` 中

**实验性硬件解码（Windows）：** 设置 → 模型/GPU → **实验性：硬件解码（D3D11VA）**。默认关闭（CPU 解码）。开启后索引进程尝试 GPU 解码，失败自动回退 CPU；NVIDIA 上 10-bit HEVC 可能走 `p010` 滤镜链。详见 **`docs/ai/pipelines.md`** Pipeline 1。

### 3.5 VLC 运行时（应用内预览）

安装 `python-vlc`（见 § 1 依赖列表）。

**从源码运行（Windows）：** 下载 [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip)，解压到**项目根目录**（与 `main.py` 同级）。目录结构：

- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/`（完整插件目录）

**安装包用户：** 发布版已内置 `vlc_lib`，无需单独下载。

`ui/playback/vlc_player.py` 会通过 `get_resource_path("vlc_lib")` 加载：开发时读项目根下 `vlc_lib/`，打包后读安装包内资源目录。

VLC 缺失或不完整时，搜索与建库通常仍可用，但应用内预览可能无法播放。

## 4) 测试

**常用子集**（快速冒烟）：

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

**全量**（`tests/` 下所有模块）：

```bash
python -m unittest discover -s tests -p "test_*.py"
```

建议在 conda `VideoSeek` 环境中运行；UI 相关测试需要已安装 PySide6。

## 5) 常见问题

### 不支持的 URL

- 常见原因：用了搜索页 / 列表页 / 频道页，而非视频详情页。
- 请使用可直接打开的单条视频详情链接。

### 需要刷新 Cookie

- 常见原因：来源站反爬或登录态限制。
- 刷新浏览器 Cookie 后重试链接提取。

### 构建完成但新增向量为 0

- 链接可能被预检拦截或判为重复。
- 源视频提取/解析失败；在 UI 查看构建状态摘要。

# VideoSeek 快速上手

给 **从源码跑** 或需要排障的人看。装安装包的用户看 [README](../README.md) 即可。

## 1) 依赖与启动

```bash
pip install -r requirements.txt
python main.py
```

Windows 上 `requirements.txt` 已含 DirectML 等；Linux / macOS 需自行把 `onnxruntime-directml` 换成 `onnxruntime`。

## 2) 运行资源

仓库不带模型、FFmpeg、VLC 二进制。按弹窗或设置里的 **导入运行资源** 处理：

| 资源 | 做法 |
|------|------|
| **模型 + FFmpeg** | **方式一**：下载 [123 云盘 zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA)，在应用内 **导入并解析**（可把 `ffmpeg.exe` 和 zip 一起加入）。**方式二**：从 [GitHub Releases — models](https://github.com/6v17/VideoSeek/releases/tag/models) 下载所需文件（如 `openai-clip.zip`、`siglip2.zip`、`chinese-clip.zip`、`ffmpeg.exe`），同样在应用内 **导入并解析** |
| **VLC（Windows 源码）** | 从 [GitHub Releases — vlc_lib](https://github.com/6v17/VideoSeek/releases/tag/vlc_lib) 下载 `vlc_lib.zip`，解压到与 `main.py` 同级的 `vlc_lib/` |
| **安装包用户** | 一般已全部内置 |

缺 VLC 时搜索/建库仍可用，预览可能不能播。

## 3) 常见问题

**不支持的 URL** — 用视频详情页链接，不要用列表/频道页。

**需要刷新 Cookie** — 来源站限制；更新浏览器 Cookie 后重试。

**构建完成但新增向量为 0** — 链接被预检拦截、重复，或源视频解析失败；看 UI 构建摘要。

**从旧版升级（≥ 1.0.82）** — 首次启动自动迁移：配置 schema v2、视频 ID（免重算）、legacy npy → **Lance** 向量库。多模型 profile 各自独立迁移。仍提示未完成则再启动一次。详见 `docs/migration_forced_upgrade_checklist.md` §4–§5。

### 版本号（正式 / QQ 群测）

- **唯一真相源：** `src/app/app_meta.py` 的 `version`（窗口标题、关于页、打包 `VERSION.txt` 都读它）。
- **群测：** `1.0.88-beta.1`（同一基线可 `.2`…）；包名 `VideoSeek-1.0.88-beta.1.zip`；**不要**写入公开 `version.json`。
- **正式：** `1.0.88`；打 tag `v1.0.88`；再更新 OSS `version.json`。
- 比较规则：同基线时 `beta` **小于** 正式版（`1.0.88-beta.1` < `1.0.88`）。
- 打包：本地 `build_release.ps1`（先改好 `app_meta` 再打；`-Zip` 可选，Inno Setup 二次打包可不加）。

---

## 附录 A：手动摆模型（一般不用）

仅在不走 zip 导入时用。路径：`%LOCALAPPDATA%\VideoSeek\models\` 或项目根 `models/`。

默认 `clip_onnx` 需要同目录下的 `clip_visual.onnx`、`clip_text.onnx`、`bpe_simple_vocab_16e6.txt.gz`。换 `siglip2_onnx` / `chinese_clip_onnx` 等时文件列表随 profile 变。

自定义包需同目录放置 **`model_manifest.json`**（不是 `manifest.json`），至少含 `provider` 与 `variant`。官方 zip 已自带，字段细节见 `src/services/model_package_service.py`。

切换设置里的当前模型后，须重新同步媒体库索引。

## 附录 B：测试

```bash
python -m pytest tests/ -q
```

UI 相关测试需已安装 PySide6（`pip install -r requirements.txt` 即可）。

## 附录 C：其它

- **FFmpeg 路径**：也可放到 `%LOCALAPPDATA%\VideoSeek\bin\` 或系统 `PATH`。
- **硬件解码（Windows 实验）**：设置 → 模型/GPU → D3D11VA；见 `docs/ai/pipelines.md` Pipeline 1。
- **`app_meta.py` URL**：主要用于公告/版本/关于与「前往下载」；`model_manifest_url` 当前指向 123 云盘。应用内一键下载依赖该 manifest；若不可用，请改从 [GitHub Releases — models](https://github.com/6v17/VideoSeek/releases/tag/models) 手动下载后导入。

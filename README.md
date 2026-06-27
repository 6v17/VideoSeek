# VideoSeek

**中文** | [English](./README.en.md)

桌面语义视频检索（PySide6 + ONNX + FAISS + FFmpeg）。

## 下载

不想自己配 Python / 依赖？直接去 **[lv17.top](https://www.lv17.top/)** 下现成打包好的安装包。首次启动按应用内提示下载并导入运行资源（模型、FFmpeg 等）即可使用。

## 最小使用步骤

1. **配置运行资源** — 首次启动按提示操作，或在 **设置** 中下载并 **导入** 模型、FFmpeg 等。
2. **添加视频库** — 侧边栏 **视频库** → 添加本地文件夹为库。
3. **同步视频库** — 选中库后点 **同步**，等待抽帧与向量化完成。
4. **搜索** — 侧边栏 **搜索** → 输入文字或图片检索已同步视频。

理解笔录、Agent API 等为可选扩展，**需先完成视频库同步**后才能使用。

## 交流

- **QQ 群**：1033551438（安装、使用问题与反馈）

## 源码运行

```bash
pip install -r requirements.txt
python main.py
```

首次启动会提示缺运行资源（安装包与源码用户均需在应用内导入）：

| 缺什么 | 怎么办 |
|--------|--------|
| 模型、FFmpeg | 按应用内提示下载，或 [123 云盘 zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → **导入并解析** |
| VLC（仅 Windows 源码） | [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip) 解压到项目根目录 |

排障、手动摆模型、测试命令见 **`docs/quickstart.md`**。

## 文档

- `docs/quickstart.md` — 安装细节与常见问题
- `docs/architecture.md` — 架构
- `docs/for-agents.md` — 本机 Agent API
- `docs/cuda-experiment.md` — 实验性 NVIDIA CUDA 建索（conda 实验室环境，非默认 Release 路径）

## 许可证

MIT

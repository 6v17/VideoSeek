# VideoSeek

**中文** | [English](./README.en.md)

桌面语义视频检索（PySide6 + ONNX + FAISS + FFmpeg）。

## 下载

不想自己配 Python / 依赖？直接去 **[lv17.top](https://www.lv17.top/)** 下现成打包好的安装包。首次启动按应用内提示下载并导入运行资源（模型、FFmpeg 等）即可使用。

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

## 许可证

MIT

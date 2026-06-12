# VideoSeek

**中文** | [English](./README.en.md)

桌面语义视频检索（PySide6 + ONNX + FAISS + FFmpeg）。

## 下载

普通用户 → **[官网发布页](https://www.lv17.top/)** 下载安装包即可。

## 源码运行

```bash
pip install -r requirements.txt
python main.py
```

首次启动会提示缺运行资源：

| 缺什么 | 怎么办 |
|--------|--------|
| 模型、FFmpeg | [123 云盘 zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → 应用内 **导入并解析** |
| VLC（仅 Windows 源码） | [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip) 解压到项目根目录 |

安装包用户已内置上述资源。排障、手动摆模型、测试命令见 **`docs/quickstart.md`**。

## 文档

- `docs/quickstart.md` — 安装细节与常见问题
- `docs/architecture.md` — 架构
- `docs/for-agents.md` — 本机 Agent API
- `docs/cuda-experiment.md` — 实验性 NVIDIA CUDA 建索（conda 实验室环境，非默认 Release 路径）

## 许可证

MIT

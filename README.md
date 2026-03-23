# 🔍 VideoSeek

![Banner](./assets/banner_demo.gif)  
> 🔥 Search video footage with a sentence or an image — no manual tagging required.  
> 🔥 用一句话、一张图搜索视频画面 —— 无需人工打标签
> ⚠️ Notice / 版权说明  
> VideoSeek is released under the MIT License. Please retain the copyright notice when using or redistributing this software.  
> VideoSeek 由 **liuvgg** 开发并原创维护，请在使用或转载时注明作者。
---

## 🎬 Demo | 演示

Bilibili 演示视频 / Bilibili Demo Video:  
https://b23.tv/b1OlUUf  
💡 Tip: Watch the demo to see VideoSeek in action! / 观看演示视频了解 VideoSeek 实时效果

### Screenshots / 界面截图 
<img width="300" alt="image3" src="https://github.com/user-attachments/assets/81224961-d511-484a-bcc7-7004e061e4dd" />  
<img width="300" alt="image4" src="https://github.com/user-attachments/assets/bd893de5-f825-4906-9d0c-4d0fc1d217ee" />  

---

## 🚀 Download | 下载

### 🖥️ Windows Installer

👉 https://github.com/liuvgg/VideoSeek/releases/download/v1.0.1/VideoSeekSetup.exe  
No setup required — just install and start using  
无需安装复杂依赖，直接下载安装即可使用

---

## ✨ Features | 核心功能

* 🔍 Search videos with text or images  
  支持“以文搜影 / 以图搜影”

* 🧠 Semantic understanding (CLIP)  
  基于 CLIP 的语义理解

* ⚡ High-performance inference (ONNX Runtime)  
  ONNX Runtime 加速，启动更快，内存占用更低

* 🎞️ Frame-level indexing (FAISS)  
  FAISS 向量索引，高效检索

* 🚀 Zero-file pipeline (FFmpeg)  
  无临时文件抽帧，完全内存处理

* 🎬 Instant preview clips  
  点击即可秒级预览视频片段

* 🖼️ Real-time thumbnails  
  实时生成缩略图，无需提前存储

* 📂 Library management  
  支持自定义视频库路径，增量更新

---

## 🎯 Use Cases | 使用场景

* 🎬 Video editing (find clips instantly)  
  视频剪辑快速定位素材

* 📚 Content indexing  
  视频内容检索

* 🤖 AI-powered video analysis  
  AI 视频分析

* 🎥 Personal media search  
  本地视频管理与搜索

---

## 🛠️ Tech Stack | 技术栈

* **Frontend / 前端**: PySide6  
* **AI Engine / AI 引擎**: ONNX Runtime (CLIP ViT-B/32)  
* **Vector DB / 向量数据库**: FAISS  
* **Video Processing / 视频处理**: FFmpeg  
* **Language / 编程语言**: Python 3.10+

---

## 🚀 Quick Start | 快速开始

### 1. Clone the repo | 克隆项目
```bash
git clone https://github.com/liuvgg/VideoSeek.git
cd VideoSeek
```
### 2. Install dependencies | 安装依赖

```bash
pip install onnxruntime-gpu opencv-python PySide6 faiss-cpu numpy pillow ftfy regex
```

### 3. Prepare models | 准备模型

Download / 下载：
https://github.com/liuvgg/VideoSeek/archive/refs/tags/models.zip

Place into `models/` / 放入 `models/` 文件夹：

* clip_visual.onnx
* clip_text.onnx
* bpe_simple_vocab_16e6.txt.gz

### 4. Add FFmpeg | 添加 FFmpeg

Place `ffmpeg.exe` in project root / 将 `ffmpeg.exe` 放在项目根目录

### 5. Run | 运行

```bash
python main.py
```

---

## 📦 Packaging | 打包发布

Use Nuitka for standalone executable / 使用 Nuitka 打包独立可执行文件：

```bash
python -m nuitka --standalone ^
--plugin-enable=pyside6 ^
--include-qt-plugins=multimedia ^
--windows-console-mode=disable ^
--output-dir=dist ^
--output-filename=VideoSeek ^
--windows-icon-from-ico=icon.ico ^
--include-data-dir=models=models ^
--include-data-file=config.json=config.json ^
--include-data-file=ffmpeg.exe=ffmpeg.exe ^
main.py
```

Optional: use Inno Setup to create an installer / 可选使用 Inno Setup 制作安装包

---

## 🤝 Credits | 致谢

* OpenAI for CLIP / 感谢 OpenAI 提供 CLIP 模型
* FFmpeg for video processing / 感谢 FFmpeg 强大的音视频处理能力
* Meta AI for FAISS / 感谢 FAISS 提供高效向量检索

---

## ⭐ Support | 支持

If you find this project useful, consider giving it a ⭐ on GitHub!
如果你觉得项目不错，欢迎点个 Star ⭐

---

## 🧠 Roadmap | 未来计划

* [ ] Multi-language search / 多语言搜索
* [ ] Faster indexing / 更快索引
* [ ] Better UI/UX / UI 优化
* [ ] Streaming support / 视频流支持
......
---

## 📬 Feedback | 反馈

Issues and PRs are welcome!
欢迎提交 Issues 或 PR！

# 🔍 VideoSeek

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-green.svg)](https://pypi.org/project/PySide6/)
[![ONNX Runtime](https://img.shields.io/badge/AI-ONNX--Runtime-orange.svg)](https://onnxruntime.ai/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**VideoSeek** 是一款基于 OpenAI CLIP 多模态模型和 FAISS 向量数据库开发的智能视频检索工具。它可以让你通过 **一段文字描述** 或 **一张图片**，在海量本地视频库中瞬间定位到最符合条件的精彩瞬间。

> **VideoSeek** is an intelligent video retrieval tool based on OpenAI CLIP and FAISS. It allows you to instantly locate specific moments in local video libraries using **text descriptions** or **images**.

---

## ✨ 核心特性 | Key Features

-   **🚀 全内存流水线 (Zero-File Indexing)**: 使用 FFmpeg 内存管道流处理，索引过程中不产生任何临时图片文件，极速且环保。
-   **🤖 多模态搜索 (Multi-modal Search)**: 支持“以图搜影”和“以文搜影”（需输入英文描述以获得最佳效果）。
-   **⚡ ONNX 加速 (High Performance)**: 核心 AI 引擎已从 PyTorch 迁移至 ONNX Runtime，启动更快，内存占用降低 80%，支持 CPU/GPU 自动切换。
-   **🖼️ 实时预览图 (Instant Thumbnails)**: 搜索结果实时从原视频中提取缩略图，无需提前存储预览图。
-   **🎬 精准预览 (Smart Clip)**: 点击结果即可秒级切出前后 4 秒的片段进行快速预览。
-   **📂 库管理 (Library Management)**: 支持自定义视频库路径，具备增量更新功能，仅处理新加入的视频。

---

## 🛠️ 技术架构 | Tech Stack

-   **Frontend**: PySide6 (Qt for Python)
-   **AI Engine**: ONNX Runtime (CLIP ViT-B/32)
-   **Vector DB**: FAISS (Facebook AI Similarity Search)
-   **Video Engine**: FFmpeg (via Memory Pipes)
-   **Language**: Python 3.10+

---

## 🚀 快速开始 | Quick Start

### 1. 克隆项目 | Clone the Repo
```bash
git clone https://github.com/liuvgg/VideoSeek.git
cd VideoSeek
```

### 2. 安装依赖 | Install Dependencies
```Bash
pip install onnxruntime-gpu opencv-python PySide6 faiss-cpu numpy pillow ftfy regex
Note: If no NVIDIA GPU, install onnxruntime instead.
```
### 3. 准备模型 | Prepare Models
将转换好的模型文件放入 models/ 文件夹：
clip_visual.onnx
clip_text.onnx
bpe_simple_vocab_16e6.txt.gz
### 4. 运行 | Run
```Bash
python main.py
```
### 📦 打包与发布 | Packaging
项目支持使用 PyInstaller 进行打包，并使用 Inno Setup 制作安装包。
```Bash
# 示例打包命令 | Example Build Command
pyinstaller --noconfirm --onedir --windowed --name "VideoSeek" --icon="icon.ico" --add-binary "ffmpeg.exe;." --add-data "models;models" --add-data "config.json;." --add-data "C:\path\to\clip\bpe_simple_vocab_16e6.txt.gz;clip" --hidden-import "onnxruntime" --hidden-import "cv2" --hidden-import "regex" --hidden-import "ftfy" --hidden-import "faiss" main.py
```
### 📸 界面预览 | Screenshots
[主界面截图]
[检索结果截图]
[同步进度条截图]
### 🤝 贡献与感谢 | Credits
感谢 OpenAI 提供的 CLIP 模型。
感谢 FFmpeg 强大的音视频处理能力。
感谢 Gemini 提供的全流程调优建议。

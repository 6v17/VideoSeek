# VideoSeek

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-brightgreen)](https://www.lv17.top/)
[![Release](https://img.shields.io/github/v/release/6v17/VideoSeek?include_prereleases)](https://github.com/6v17/VideoSeek/releases)

[中文说明](./README.zh.md) | **English**

Search a local video library by **text or screenshot**, with **hard-subtitle OCR**; preview hits and export MP4, Jianying, or NLE timelines.  
By default, indexing stays on your machine (ONNX · Lance · FFmpeg) and **media is not uploaded**. If you turn on Cloud embedding in Settings, extracted frames and queries are sent to the cloud service you configure.

> **Free forever.** Do not pay for resale or “paid install” copies — get it from [GitHub](https://github.com/6v17/VideoSeek) / [the site](https://www.lv17.top/).

[Download](https://www.lv17.top/) · [Releases](https://github.com/6v17/VideoSeek/releases) · [User guide (ZH)](https://ycnwd8tcjgtu.feishu.cn/docx/ZWkrdSqA6oJTOrxQ2XscxYtmnad) · QQ `1033551438`

<p align="center">
  <img src="docs/assets/图搜视频.png" alt="VideoSeek search UI" width="800">
</p>

---

## Features

- **Text & image search** — Natural language or a reference image to find similar shot time ranges  
- **Hard-subtitle OCR** — Keyword search over on-screen dialogue  
- **Libraries & scope** — Multiple libraries, selected videos, search presets  
- **Preview & export** — Timeline preview; MP4; Jianying draft / Premiere XML / DaVinci FCPXML  
- **Local-first** — Sync and search stay on this machine unless you turn on Cloud embedding, which sends frames and queries to the service you configure. Optional LAN search and localhost Agent API  

> Optional: video understanding, tag search, multiple CLIP-family models, experimental recap cuts, and more. **Main path: sync → search → export.**

## Use cases

| You have… | You want… |
|-----------|-----------|
| Large local or NAS libraries | Find shots by semantics, not filenames |
| Dialogue or hard subs you remember | Jump to timestamps after OCR keyword search |
| An editing workflow | Rough-locate clips, then open Jianying / PR / DaVinci |

## Quick start (installer)

1. Download from **[lv17.top](https://www.lv17.top/)** or [Releases](https://github.com/6v17/VideoSeek/releases)  
2. On first launch, **import runtime assets** when prompted (models, FFmpeg; OCR pack if you need subtitles)  
3. Sidebar **Local Library** → add a folder → select videos → **Sync selected**  
4. **Search** → query → preview → export  

## Quick start (from source)

**Windows 10/11** recommended. Other OS: see [`docs/quickstart.md`](docs/quickstart.md).

```bash
pip install -r requirements.txt
python main.py
```

```bash
conda env create -f environment.yml
conda activate VideoSeek
```

| Missing | Action |
|---------|--------|
| Models / FFmpeg | In-app import, [123 cloud zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA), or [models release](https://github.com/6v17/VideoSeek/releases/tag/models) |
| VLC (Windows source only) | [vlc_lib release](https://github.com/6v17/VideoSeek/releases/tag/vlc_lib) → extract at repo root |

Fallback: if the model zip and `ffmpeg.exe` are already on disk, close VideoSeek, download [import_runtime_resources.py](https://raw.githubusercontent.com/6v17/VideoSeek/master/scripts/import_runtime_resources.py), and run (no git checkout; writes `%LOCALAPPDATA%\VideoSeek`):

```bat
python import_runtime_resources.py openai-clip.zip ffmpeg.exe
```

## Documentation

- [User guide (ZH)](https://ycnwd8tcjgtu.feishu.cn/docx/ZWkrdSqA6oJTOrxQ2XscxYtmnad) — illustrated installer walkthrough  
- [`docs/quickstart.md`](docs/quickstart.md) — from-source setup and troubleshooting  
- [`docs/for-agents.md`](docs/for-agents.md) — localhost Agent API  
- [`docs/architecture.md`](docs/architecture.md) — architecture (developers)  
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute  

## Community

- QQ group: **1033551438**  
- [GitHub Issues](https://github.com/6v17/VideoSeek/issues) — bugs, source builds, Agent API  

## License

[AGPL-3.0](LICENSE) © 2026 [6v17](https://github.com/6v17)

## Support

<p align="center">
  <img src="docs/assets/支持我.png" alt="Support" width="360">
</p>

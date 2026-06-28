# VideoSeek

[中文说明](./README.md) | **English**

**Search your local video library by text or screenshot, preview hits, export clips.**  
Indexing and retrieval run on your machine (ONNX + FAISS + FFmpeg); your media files are not uploaded.

> Personal open-source utility. **Windows-first**; installer and from-source builds share the same UI.

## Features

### Core (available after you **sync a library**)

| Feature | Description |
|---------|-------------|
| **Local libraries** | Add folders, sync to extract frames and build embeddings |
| **Text search** | Describe a scene; get time ranges in indexed videos |
| **Image / screenshot search** | Find similar shots from a reference or cropped frame |
| **Scope & presets** | All libraries, selected libraries/videos; saved search presets |
| **frame / chunk modes** | Per-frame hits or semantic chunk aggregation |
| **Preview & export** | Timeline preview; export mp4 segments |

### Optional

| Feature | Description |
|---------|-------------|
| **Understanding evidence** | Per-chunk detection + captions + video summary (YOLO + caption service) |
| **Localhost Agent API** | HTTP on `127.0.0.1`: search, libraries, export, evidence (see `docs/for-agents.md`) |
| **Remote libraries** | Import linked libraries and search them like local ones |

## Who is it for?

- Large local or NAS media folders — find **semantically similar shots**, not filenames
- **Rough-cut prep** before editing in a NLE
- **Local models** plus optional HTTP access for Cursor / other agents

## Screenshots

![搜索界面](docs/assets/图搜视频.png)
![搜索界面](docs/assets/文搜视频.png)
![搜索界面](docs/assets/视频理解.png)

## Download

Prefer not to manage Python? Get the **installer** from **[lv17.top](https://www.lv17.top/)**. On first launch, import **runtime assets** (models, FFmpeg) as prompted.

## Minimal workflow

1. **Runtime assets** — First-launch prompts, or **Settings** → import models and FFmpeg.
2. **Add a library** — Sidebar **Local Library** → add a folder.
3. **Sync** — Select the library → **Sync**; wait for indexing.
4. **Search** — Sidebar **Search** → text or image query.

Understanding evidence and the Agent API are optional — **sync a library first**.

## Community

- **QQ group**: 1033551438
- **GitHub Issues** — especially for source builds and the Agent API

## From source

**Windows 10/11 recommended.** Linux / macOS: adjust ONNX runtime (see `docs/quickstart.md`).

```bash
pip install -r requirements.txt
python main.py
```

Or Conda: `conda env create -f environment.yml` → `conda activate VideoSeek`.

Missing runtime assets (import in-app for both installer and source):

| Missing | Fix |
|---------|-----|
| Models, FFmpeg | In-app prompts, or [123 cloud zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → **Import and Parse** |
| VLC (Windows source only) | [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip) at project root |

See **`docs/quickstart.md`** for troubleshooting and tests.

## Docs

| Doc | Topic |
|-----|--------|
| `docs/quickstart.md` | Setup, troubleshooting, tests |
| `docs/for-agents.md` | Localhost Agent API |
| `docs/architecture.md` | Architecture (developers) |

## License

Copyright (c) 2026 [6v17](https://github.com/6v17)

Licensed under [AGPL-3.0](LICENSE) (GNU Affero General Public License v3.0).

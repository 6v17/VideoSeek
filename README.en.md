# VideoSeek

[中文说明](./README.md) | **English**

**Search your local video library by text or screenshot, preview hits, export clips.**  
Indexing and retrieval run on your machine (ONNX + Lance + FFmpeg); your media files are not uploaded.

> Personal open-source utility. **Windows-first**; installer and from-source builds share the same UI.  
> **Free forever.** Don’t pay for resale or “paid install” copies — get it from [GitHub](https://github.com/6v17/VideoSeek) / [the site](https://www.lv17.top/).

## Features

### Core (available after you **sync a library**)

| Feature | Description |
|---------|-------------|
| **Local libraries** | Add folders, sync to extract frames and build embeddings |
| **Text search** | Describe a scene; get time ranges in indexed videos |
| **Image / screenshot search** | Find similar shots from a reference or cropped frame |
| **Hard-subtitle search** | OCR on-screen subtitles, then keyword search by time; exact match or fuzzy (unordered single-char hit-rate ranking with result highlighting) |
| **Scope & presets** | All libraries, selected libraries/videos; saved search presets |
| **frame / chunk modes** | Per-frame hits or semantic chunk aggregation |
| **Preview & export** | Timeline preview; export mp4 segments |

### Optional

| Feature | Description |
|---------|-------------|
| **Video understanding** | Desktop-only optional: per-chunk captions + whole-video summary via an OpenAI-compatible caption service (**not** exposed on the Agent API) |
| **Localhost Agent API** | HTTP on `127.0.0.1`: semantic/subtitle search, list libraries/videos, export clips (see `docs/for-agents.md`; no understanding endpoints) |
| **Video download** | Resolve page links, download into a local folder, then sync like a normal library |

## Who is it for?

- Large local or NAS media folders — find **semantically similar shots**, not filenames
- **Rough-cut prep** before editing in a NLE
- **Local models** plus optional HTTP access for Cursor / other agents

## Screenshots

![搜索界面](docs/assets/图搜视频.png)

## Download

Prefer not to manage Python? Get the **installer** from **[lv17.top](https://www.lv17.top/)**. On first launch, import **runtime assets** (models, FFmpeg) as prompted.

## Minimal workflow

1. **Runtime assets** — First-launch prompts, or **Settings** → import models and FFmpeg.
2. **Add a library** — Sidebar **Local Library** → **Videos** tab → add a folder.
3. **Sync selected** — Check videos → **Sync selected**; wait for indexing.
4. **Search** — Sidebar **Search** → text or image query.

Video understanding, subtitle extraction, and the Agent API are optional — **sync a library first** (subtitle search also needs the OCR pack and extraction under the **Subtitles** tab).

Illustrated walkthrough (Chinese): **[User guide (Feishu)](https://ycnwd8tcjgtu.feishu.cn/docx/ZWkrdSqA6oJTOrxQ2XscxYtmnad)**.

## Community

- **User guide (ZH)**: [Feishu doc](https://ycnwd8tcjgtu.feishu.cn/docx/ZWkrdSqA6oJTOrxQ2XscxYtmnad)
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
| Models, FFmpeg | In-app prompts, or [123 cloud zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → **Import and Parse**; or download model zips and `ffmpeg.exe` from [GitHub Releases — models](https://github.com/6v17/VideoSeek/releases/tag/models), then import |
| VLC (Windows source only) | Download `vlc_lib.zip` from [GitHub Releases — vlc_lib](https://github.com/6v17/VideoSeek/releases/tag/vlc_lib) and extract at project root |

See **`docs/quickstart.md`** for troubleshooting and tests.

## Docs

| Doc | Topic |
|-----|--------|
| [User guide (Feishu, ZH)](https://ycnwd8tcjgtu.feishu.cn/docx/ZWkrdSqA6oJTOrxQ2XscxYtmnad) | Illustrated setup for installer users |
| `docs/quickstart.md` | From-source setup, troubleshooting, tests |
| `docs/for-agents.md` | Localhost Agent API |
| `docs/architecture.md` | Architecture (developers) |

## License

Copyright (c) 2026 [6v17](https://github.com/6v17)

Licensed under [AGPL-3.0](LICENSE) (GNU Affero General Public License v3.0).

## Thanks for your support

Sincere thanks to everyone who tipped VideoSeek — your encouragement keeps the project going. Listed by date; **amounts are not shown**.

To use your own avatar, email **2627538472@qq.com** with your WeChat nickname and an image.

| Avatar | Nickname | Message | Date |
|:---:|:---|:---|:---:|
| <img src="https://ui-avatars.com/api/?name=%E7%83%AD%E5%BF%83%E7%94%A8%E6%88%B7&background=6b7280&color=fff&size=80" width="40" height="40" alt="" /> | 热心用户 | 很好用！感谢！😋 | 2026-07-13 |
| <img src="https://ui-avatars.com/api/?name=%E5%B2%81%E5%B2%81%E5%B9%B3%E5%AE%89&background=0d9488&color=fff&size=80" width="40" height="40" alt="" /> | 岁岁平安 | 软件很牛逼，你也很牛逼 | 2026-07-17 |
| <img src="https://ui-avatars.com/api/?name=%E6%A6%A8%E4%B8%80%E6%9D%AF%E6%A9%99%E6%B1%81&background=d97706&color=fff&size=80" width="40" height="40" alt="" /> | 榨一杯橙汁 | 默默支持！ | 2026-07-29 |
| <img src="https://ui-avatars.com/api/?name=%F0%9F%98%8A&background=6366f1&color=fff&size=80" width="40" height="40" alt="" /> | 😊 | 默默支持！ | 2026-07-29 |

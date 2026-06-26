# VideoSeek

[中文说明](./README.md) | **English**

Desktop semantic video search (PySide6 + ONNX + FAISS + FFmpeg).

## Download

Don't want to set up Python and dependencies? Grab the **pre-built installer** from **[lv17.top](https://www.lv17.top/)**. On first launch, follow the in-app prompts to download and import runtime assets (models, FFmpeg, etc.).

## Minimal workflow

1. **Set up runtime assets** — Follow first-launch prompts, or download and **import** models and FFmpeg under **Settings** (see table below).
2. **Add a library** — Open **Local Library** in the sidebar and add a folder.
3. **Sync the library** — Select the library and click **Sync**; wait for frame extraction and indexing to finish.
4. **Search** — Open **Search** in the sidebar and query with text or images over synced videos.

Understanding evidence and the Agent API are optional add-ons — **sync a library first** before using them.

## Community

- **QQ group**: 1033551438 (install help, usage questions, feedback)

## From source

```bash
pip install -r requirements.txt
python main.py
```

On first launch, missing runtime assets must be imported in the app (same for installer and source builds):

| Missing | Fix |
|---------|-----|
| Models, FFmpeg | Follow in-app prompts, or use [123 cloud zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → **Import and Parse** |
| VLC (Windows source only) | [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip) at project root |

See **`docs/quickstart.md`** for troubleshooting and advanced layout.

## Docs

- `docs/quickstart.md` — setup details (Chinese)
- `docs/architecture.md` — architecture
- `docs/for-agents.md` — localhost Agent API

## License

MIT

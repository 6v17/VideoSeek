# VideoSeek

[中文说明](./README.md) | **English**

Desktop semantic video search (PySide6 + ONNX + FAISS + FFmpeg).

## Download

End users → **[Releases](https://www.lv17.top/)** (installer).

## From source

```bash
pip install -r requirements.txt
python main.py
```

On first launch, import missing runtime assets:

| Missing | Fix |
|---------|-----|
| Models, FFmpeg | [123 cloud zip](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) → **Import and Parse** in the app |
| VLC (Windows source only) | [vlc_lib.zip](https://github.com/6v17/VideoSeek/releases/download/vlc_lib/vlc_lib.zip) at project root |

Installers bundle these. See **`docs/quickstart.md`** for troubleshooting and advanced layout.

## Docs

- `docs/quickstart.md` — setup details (Chinese)
- `docs/architecture.md` — architecture
- `docs/for-agents.md` — localhost Agent API
- `docs/cuda-experiment.md` — experimental NVIDIA CUDA indexing (conda lab env; not the default release path)

## License

MIT

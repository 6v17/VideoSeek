"""Quick test: rookiepy vs yt-dlp browser cookie read on Windows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_rookiepy() -> None:
    import rookiepy

    for name, fn in [("edge", rookiepy.edge), ("chrome", rookiepy.chrome)]:
        try:
            cookies = fn(["douyin.com"])
            names = sorted({c.get("name", "") for c in cookies})
            print(f"rookiepy {name}: OK, {len(cookies)} cookies")
            print(f"  names: {names[:15]}")
        except Exception as exc:
            print(f"rookiepy {name}: FAIL - {type(exc).__name__}: {exc}")


def test_ytdlp() -> None:
    import yt_dlp

    opts = {"quiet": True, "cookiesfrombrowser": ("edge",), "simulate": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info("https://www.douyin.com", download=False)
        print("yt-dlp cookiesfrombrowser edge: OK")
    except Exception as exc:
        print("yt-dlp cookiesfrombrowser edge: FAIL")
        print(f"  {type(exc).__name__}: {str(exc)[:400]}")


if __name__ == "__main__":
    test_rookiepy()
    print()
    test_ytdlp()

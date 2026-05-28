# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys

MANIFEST = r"d:\PycharmProjects\VideoSeek\cuts-aot-s1-hype-5.json"
OUT_DIR = r"C:\Users\LiuWei\Desktop\cursor帮我找的视频"
FFMPEG = r"C:\Users\LiuWei\AppData\Local\VideoSeek\bin\ffmpeg.exe"


def export_one(item: dict, out_path: str) -> None:
    start = item["start_sec"]
    end = item["end_sec"]
    inp = item["video_path"]
    cmd_copy = [
        FFMPEG,
        "-y",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        inp,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        out_path,
    ]
    r = subprocess.run(cmd_copy, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 1000:
        return
    cmd_enc = [
        FFMPEG,
        "-y",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        inp,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        out_path,
    ]
    r2 = subprocess.run(cmd_enc, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r2.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path}\n{r.stderr}\n{r2.stderr}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    for item in items:
        base = os.path.splitext(os.path.basename(item["video_path"]))[0]
        tc = item.get("timecode", "").replace(":", "m", 1).replace(":", "s").replace("-", "_")
        name = f"{item['id']}_{base}_{tc}.mp4"
        out_path = os.path.join(OUT_DIR, name)
        print(f"Exporting {item['id']} -> {name}")
        export_one(item, out_path)
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"  OK ({size_mb:.2f} MB)")
    print("DONE:", OUT_DIR)


if __name__ == "__main__":
    main()

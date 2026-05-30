import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\LiuWei\Desktop\狂暴飞车\report_phase2.json")
d = json.loads(path.read_text(encoding="utf-8"))
s = d["summary"]
print("=== SUMMARY ===")
for key, value in s.items():
    print(f"  {key}: {value}")

paths = d["strong_paths"]
print(f"\n=== STRONG PATHS ({len(paths)}) ===")
for pth in paths:
    remix = pth["remix"]
    src = pth["source"]
    al = pth["alignment"]
    chunks = src.get("chunks") or []
    print(
        f"  path {pth['path_id']}: remix {remix['start_sec']}-{remix['end_sec']}s "
        f"({remix['duration_sec']}s) | src span {src.get('span_sec', '-')}s "
        f"contiguous={src.get('contiguous')} chunks={len(chunks)} "
        f"| avg={pth['avg_similarity']} links={al['link_count']}"
    )
    if chunks and not src.get("contiguous"):
        for i, chunk in enumerate(chunks[:4]):
            print(f"      chunk {i + 1}: {chunk['start_sec']}-{chunk['end_sec']}s")

weak = d["weak_evidence"]
print(f"\n=== WEAK ({len(weak)}) ===")
for item in weak:
    candidates = item.get("candidates") or []
    top = candidates[0] if candidates else {}
    remix = item["remix"]
    print(
        f"  shot {item['remix_shot_id']} @ {remix['start_sec']}-{remix['end_sec']}s "
        f"reason={item['reason']} top1={top.get('score', '-')}"
    )

rets = d.get("retrievals") or []
if rets:
    duration = max(row["remix_shot"]["end_sec"] for row in rets)
    covered = float(s.get("strong_path_remix_sec", 0))
    print(f"\nremix duration ~{duration:.1f}s")
    print(f"uncovered ~{duration - covered:.1f}s ({100.0 - float(s.get('strong_path_remix_percent', 0)):.1f}%)")

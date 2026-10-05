"""ASR/VLM plot spine and OCR cue compaction for recap planning.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from src.services.recap_constants import PLAN_ACT_ASR_LIMIT
from src.services.recap_match import _time_span

_DIALOGUE_OUTCOME_RE = re.compile(
    r"(不行|不可以|别再|不许|拒绝|拒收|拒了|收下|接住|答应|同意|成交|决定|胜负|赢了|输了|揭穿|识破|"
    r"坦白|承认|否认|推回|还回去|交给你|就这样|算了|滚|走开|回去吧|走吧|没事了|放过|"
    r"原谅|解决|搞定|到此为止|就到这|回头见|离开|真相|结果出来|全勾完|结束了|完了|完蛋|成立|不成立|"
    r"refuse|reject|accept|deal|decide|won|lost|confess|deny)",
    re.IGNORECASE,
)


def _normalize_ocr_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    cleaned = re.sub(r"[の私督载回始机一次口前最後人]+$", "", cleaned)
    return cleaned

def sample_timeline_items(items: list[Any], limit: int) -> list[Any]:
    """Keep head, evenly spaced middle, and tail so later plot is not dropped."""
    rows = list(items or [])
    cap = max(1, int(limit or 1))
    if len(rows) <= cap:
        return rows
    if cap == 1:
        return [rows[-1]]
    n_tail = max(1, min(len(rows) // 3, int(round(cap * 0.28))))
    n_head = max(1, min(len(rows) // 3, int(round(cap * 0.22))))
    if n_head + n_tail >= cap:
        n_tail = max(1, cap // 3)
        n_head = max(1, min(cap - n_tail - 1, cap // 4))
    n_mid = cap - n_head - n_tail
    head = rows[:n_head]
    tail = rows[-n_tail:]
    mid_src = rows[n_head : len(rows) - n_tail]
    if n_mid <= 0 or not mid_src:
        picked = head + tail
        return picked[:cap] if len(picked) > cap else picked
    if len(mid_src) <= n_mid:
        mid = list(mid_src)
    elif n_mid == 1:
        mid = [mid_src[len(mid_src) // 2]]
    else:
        step = (len(mid_src) - 1) / (n_mid - 1)
        mid = [mid_src[int(round(index * step))] for index in range(n_mid)]
    return head + mid + tail

def compact_ocr_cues(
    video_id: str,
    *,
    config=None,
    limit: int = 220,
    text_limit: int = 80,
    speech_only: bool = True,
) -> list[dict[str, Any]]:
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import iter_shared_transcript_segment_rows

    cap = max(1, int(limit or 220))
    clip = max(12, int(text_limit or 80))
    cues: list[dict[str, Any]] = []
    last_key = ""
    last_speaker = ""
    for row in iter_shared_transcript_segment_rows(video_id=video_id, config=config):
        source = str(row.get("asr_source") or "").strip()
        if speech_only and (not source or is_hardsub_ocr_source(source)):
            continue
        text = str(row.get("text") or "").strip()
        key = _normalize_ocr_text(text)
        if not key:
            continue
        start = round(float(row.get("start", 0.0) or 0.0), 2)
        end = round(float(row.get("end", start) or start), 2)
        speaker = str(row.get("speaker") or "").strip()[:40]
        if key == last_key and cues and last_speaker == speaker:
            cues[-1]["end"] = max(cues[-1]["end"], end)
            continue
        last_key = key
        last_speaker = speaker
        cue = {
            "start": start,
            "end": end,
            "text": text[:clip],
            "asr_source": source,
        }
        if speaker:
            cue["speaker"] = speaker
        cues.append(cue)
    return sample_timeline_items(cues, cap)

def compact_ocr_cues_in_span(
    video_id: str,
    start_sec: float,
    end_sec: float,
    *,
    config=None,
    limit: int = PLAN_ACT_ASR_LIMIT,
    text_limit: int = 80,
    pad_sec: float = 2.0,
) -> list[dict[str, Any]]:
    """ASR for one act window — keep local density; do not thin against the whole episode."""
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import iter_shared_transcript_segment_rows

    lo = float(start_sec) - float(pad_sec)
    hi = float(end_sec) + float(pad_sec)
    cap = max(1, int(limit or PLAN_ACT_ASR_LIMIT))
    clip = max(12, int(text_limit or 80))
    cues: list[dict[str, Any]] = []
    last_key = ""
    last_speaker = ""
    for row in iter_shared_transcript_segment_rows(video_id=video_id, config=config):
        source = str(row.get("asr_source") or "").strip()
        if not source or is_hardsub_ocr_source(source):
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            continue
        if end < lo or start > hi:
            continue
        text = str(row.get("text") or "").strip()
        key = _normalize_ocr_text(text)
        if not key:
            continue
        speaker = str(row.get("speaker") or "").strip()[:40]
        if key == last_key and cues and last_speaker == speaker:
            cues[-1]["end"] = max(float(cues[-1]["end"]), round(end, 2))
            continue
        last_key = key
        last_speaker = speaker
        cue = {
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text[:clip],
            "asr_source": source,
        }
        if speaker:
            cue["speaker"] = speaker
        cues.append(cue)
    if len(cues) <= cap:
        return cues
    return sample_timeline_items(cues, cap)

def build_asr_vlm_spine(
    pack: Mapping[str, Any],
    *,
    gap_sec: float = 12.0,
    min_seg_sec: float = 5.0,
    max_seg_sec: float = 48.0,
) -> list[dict[str, Any]]:
    """Cluster ASR on the shared clock and attach overlapping VLM caps — the plot spine."""
    cues = sorted(
        (row for row in (pack.get("ocr") or []) if isinstance(row, Mapping) and str(row.get("text") or "").strip()),
        key=lambda row: float(row.get("start") or 0.0),
    )
    chunks = [row for row in (pack.get("chunks") or []) if isinstance(row, Mapping)]
    if not cues:
        return []
    clusters: list[list[Mapping[str, Any]]] = []
    for cue in cues:
        start = float(cue.get("start") or 0.0)
        end = float(cue.get("end") or start)
        if not clusters:
            clusters.append([cue])
            continue
        prev = clusters[-1]
        prev_start = float(prev[0].get("start") or 0.0)
        prev_end = max(float(item.get("end") or item.get("start") or 0.0) for item in prev)
        if start - prev_end <= float(gap_sec) and (end - prev_start) <= float(max_seg_sec):
            prev.append(cue)
        else:
            clusters.append([cue])
    spine: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, 1):
        lo = float(cluster[0].get("start") or 0.0)
        hi = max(float(item.get("end") or item.get("start") or lo) for item in cluster)
        if hi - lo < float(min_seg_sec):
            hi = lo + float(min_seg_sec)
        picked = cluster if len(cluster) <= 24 else sample_timeline_items(list(cluster), 24)
        asr_rows: list[dict[str, Any]] = []
        speakers: list[str] = []
        for item in picked:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            speaker = str(item.get("speaker") or "").strip()[:40]
            row = {
                "start": round(float(item.get("start") or lo), 2),
                "end": round(float(item.get("end") or item.get("start") or lo), 2),
                "text": text[:80],
            }
            if speaker:
                row["speaker"] = speaker
                if speaker not in speakers:
                    speakers.append(speaker)
            asr_rows.append(row)
        caps: list[dict[str, Any]] = []
        for chunk in chunks:
            span = _time_span(chunk.get("t"))
            if not span:
                continue
            if span[1] < lo - 2.0 or span[0] > hi + 2.0:
                continue
            cap = str(chunk.get("cap") or "").strip()
            if not cap:
                continue
            caps.append(
                {
                    "i": chunk.get("i"),
                    "t": [round(span[0], 2), round(span[1], 2)],
                    "cap": cap[:80],
                }
            )
            if len(caps) >= 8:
                break
        spine.append(
            {
                "i": index,
                "t": [round(lo, 2), round(hi, 2)],
                "asr": asr_rows,
                "caps": caps,
                "speakers": speakers[:6],
            }
        )
    return expand_spine_plot_phases(spine)

def expand_spine_plot_phases(spine: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Split dense dialogue clusters into enter / mid / land so unfold cannot vanish."""
    out: list[dict[str, Any]] = []
    for seg in spine or []:
        if not isinstance(seg, Mapping):
            continue
        window = _time_span(seg.get("t"))
        if not window:
            continue
        asr = [row for row in (seg.get("asr") or []) if isinstance(row, Mapping)]
        caps = [row for row in (seg.get("caps") or []) if isinstance(row, Mapping)]
        speakers = list(seg.get("speakers") or [])
        dur = max(0.0, window[1] - window[0])
        outcomes = [row for row in asr if _DIALOGUE_OUTCOME_RE.search(str(row.get("text") or ""))]
        needs_split = dur >= 28.0 or len(asr) >= 4 or (outcomes and dur >= 18.0)
        if not needs_split:
            row = dict(seg)
            row["phase"] = "full"
            out.append(row)
            continue

        def _slice(lo: float, hi: float, phase: str) -> dict[str, Any] | None:
            if hi - lo < 3.5:
                return None
            sub_asr = [
                dict(item)
                for item in asr
                if float(item.get("end") or item.get("start") or 0.0) >= lo - 0.5
                and float(item.get("start") or 0.0) <= hi + 0.5
            ]
            sub_caps = [
                dict(item)
                for item in caps
                if (_time_span(item.get("t")) or (0.0, 0.0))[0] <= hi + 1.0
                and (_time_span(item.get("t")) or (0.0, 0.0))[1] >= lo - 1.0
            ]
            if not sub_asr and not sub_caps:
                return None
            return {
                "i": seg.get("i"),
                "t": [round(lo, 2), round(hi, 2)],
                "asr": sub_asr[:16],
                "caps": sub_caps[:6],
                "speakers": speakers[:6],
                "phase": phase,
            }

        if outcomes:
            last = outcomes[-1]
            try:
                cue_start = float(last.get("start") or window[0])
                cue_end = float(last.get("end") or cue_start)
            except (TypeError, ValueError):
                cue_start, cue_end = window[0], window[1]
            land_lo = max(window[0], cue_start - 8.0)
            land_hi = min(window[1], max(cue_end + 10.0, land_lo + 8.0))
            mid_hi = max(window[0] + 4.0, land_lo)
            enter_hi = window[0] + max(8.0, (mid_hi - window[0]) * 0.45)
            phases = [
                _slice(window[0], min(enter_hi, mid_hi), "enter"),
                _slice(min(enter_hi, mid_hi), mid_hi, "mid"),
                _slice(land_lo, land_hi, "land"),
            ]
        else:
            a = window[0]
            b = window[0] + dur / 3.0
            c = window[0] + 2.0 * dur / 3.0
            d = window[1]
            phases = [
                _slice(a, b, "enter"),
                _slice(b, c, "mid"),
                _slice(c, d, "land"),
            ]
        kept = [item for item in phases if item is not None]
        if len(kept) <= 1:
            row = dict(seg)
            row["phase"] = "full"
            out.append(row)
        else:
            out.extend(kept)
    # Re-number for stable ids in prompts.
    for index, row in enumerate(out, 1):
        row["i"] = index
    return out

def _spine_event_label(seg: Mapping[str, Any]) -> str:
    asr = [row for row in (seg.get("asr") or []) if isinstance(row, Mapping)]
    speakers = [str(item).strip() for item in (seg.get("speakers") or []) if str(item).strip()]
    texts = [re.sub(r"\s+", "", str(row.get("text") or "")) for row in asr if str(row.get("text") or "").strip()]
    who = speakers[0] if len(speakers) == 1 else ("、".join(speakers[:2]) if speakers else "")
    phase = str(seg.get("phase") or "full").strip().lower()
    if phase == "enter":
        body = texts[0][:22] if texts else ""
        if who and body:
            return f"{who}进入局面{body}"
        if who:
            return f"{who}进入局面"
        return f"进入局面{body}" if body else "进入局面"
    if phase == "mid":
        body = texts[len(texts) // 2][:22] if texts else ""
        if who and body:
            return f"{who}推进冲突{body}"
        if who:
            return f"{who}中间展开"
        return f"中间展开{body}" if body else "中间展开"
    if phase == "land" or any(_DIALOGUE_OUTCOME_RE.search(text) for text in texts):
        for text in reversed(texts):
            if _DIALOGUE_OUTCOME_RE.search(text):
                body = text[:28]
                return f"{who}{body}收束局面" if who else f"对白收束至{body}"
        body = texts[-1][:22] if texts else ""
        return f"{who}收束至{body}" if who else (f"对白收束至{body}" if body else "对白收束")
    for text in reversed(texts):
        if _DIALOGUE_OUTCOME_RE.search(text):
            body = text[:28]
            return f"{who}{body}收束局面" if who else f"对白收束至{body}"
    caps = [str(row.get("cap") or "").strip() for row in (seg.get("caps") or []) if str(row.get("cap") or "").strip()]
    if who and texts:
        tail = texts[-1][:22]
        return f"{who}一带对白推进至{tail}"
    if caps:
        return f"画面推进：{caps[0][:28]}"
    if texts:
        return f"对白推进至{texts[-1][:28]}"
    return "时间轴证据推进"

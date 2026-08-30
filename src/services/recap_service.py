"""Recap job: motion evidence + dialogue cues → LLM cut list + SRT. Jianying / FCPXML are separate exports."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.media.fcpxml import layout_clips_on_timeline, write_cuts_json, write_fcpxml, write_srt
from src.services.llm_settings import call_remote_llm, get_remote_llm_settings
from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION

BASE_CHARS_PER_SEC = 5.0
TTS_SPEED = 1.35
CHARS_PER_SEC = BASE_CHARS_PER_SEC * TTS_SPEED
MIN_CLIP_SEC = 4.0
MAX_CLIP_SEC = 12.0
MAX_TTS_CLIP_SEC = 36.0
TARGET_RECAP_SEC = 330
MIN_RECAP_SEC = 300
MAX_RECAP_SEC = 390
VO_FILL_RATIO = 0.9
VO_COVER_RATIO = 0.80
MIN_BEAT_BUDGET_SEC = 8.0
MAX_BEAT_BUDGET_SEC = 24.0
HARD_MIN_BEAT_SEC = 6.0
RECAP_START_PLAN = "plan"
RECAP_START_MATCH = "match"
RECAP_START_CAPTIONS = "captions"
MATCH_BEATS_PER_WAVE = 7
ENDING_COVER_RATIO = 0.78
RECAP_OCR_LIMIT = 96
MAX_CAPTION_SEC = 18.0
MIN_BRIDGE_SEC = 2.4

_TEXTURE_BEAT_RE = re.compile(
    r"(设定|世界观|规则说明|能力说明|教室|空间|角色侧面|性格|态度|习惯|表情|换场|过渡|气氛|环境)"
)
_OP_ED_RE = re.compile(
    r"(片头曲|片尾曲|片頭曲|オープニング|エンディング|opening\s*theme|ending\s*theme|"
    r"演职员表|演職員表|制作委员会|製作委員会|下集预告|下一集预告|下集預告|"
    r"to\s*be\s*continued|\bending\s*credits\b)",
    re.IGNORECASE,
)

RECAP_NAME_POLICY = """【人物】必须把反复出场的人分开，不要用同一个「他」指两个人。
先给出稳定称呼，整集不要换：优先画面特征或职业（红衣女人、柜台职员、戴帽男人）。
禁止男主/女主/主角。不要瞎起人名。
对白明确自报或当面称呼的名字，才能当作那个人的称呼，并且整集只绑同一个人。
对白里提到的别人的名字，不要安到正在出镜/说话的人身上。
asr 条目的 speaker 非空时，就是谁在说：当事实。event / 口播必须用这个称呼，不要改成别人，也不要用「他」盖掉。
people 里已经有的说话人称呼必须沿用。
错误：「他走进店，他又拒收，他又报了警。」（三个人并成一个他）
错误：「女主报了警。」「把柜台职员的话写成女人说的。」
正确：「柜台职员拒收。红衣女人报了警。」
"""

RECAP_PLAN_SYSTEM = """你是影视解说的剧情策划，只规划故事节拍，不写剪辑表、不写口播。

根据 Chunk 视觉事件和对白时间轴，列出能讲清这一集的 beats，通常 14–20 条，最多 24 条。
因果必须连续，宁多勿跳：每一次对峙、每一次身份/目标变化、每一个关键发现都要单独成条。
禁止把两次同类事件并成一条；禁止从「出事」直接跳到「结果」——中间过程必须有自己的 beat。
必须覆盖正片开场、中段推进、以及正片收束。不要把全部 beats 堆在中后段。
成片目标约 5 分半：因果一条不删，用压缩过渡和低权重镜头控时长，不要靠删剧情来缩短。
主线因果是骨架，质感点到为止，不要为了细把过场拆成一串独立 beat：
- 1–2 条设定/空间/规则展示（importance 0.25–0.45）
- 1–2 条角色侧面（表情、习惯、态度、关系，不是新冲突）
- 换场尽量并进相邻主线；必须单独写时用低权重（进门、赶路、气氛），event 只写看得见的场面
换场过渡禁止编新对质、揭秘、胜负，也不要认错人。
不要把无意义重复走路写成独立 beat。
不要选 OP/片头曲、ED/片尾曲、演职员表、标题动画、下一集预告。
开场必须要：OP 之前的冷开场（如果有），以及片头曲之后的第一场戏。不要因为「去 OP」把开头剧情一起丢掉。
不要按前 90 秒一刀切。只丢掉片头曲本身（歌词、标题动画、演职员表）。
正片收束是片尾曲之前的最后剧情，不是 ED。
最后一条 beat 必须落在正片后段、片尾曲之前。
不要编造对白里没有的人物关系、动机、背景。
""" + RECAP_NAME_POLICY + """
importance 是剧情重要性 0.05–1.0，不是原片时长。精彩短镜头可以很高，注水长镜头必须很低。

只输出 JSON，不要 markdown。
JSON schema:
{"title":"...","people":[{"id":"p1","label":"红衣女人","look":"长发红裙"},{"id":"p2","label":"柜台职员","look":"工装"}],"beats":[{"id":1,"event":"柜台职员当众拒收","importance":0.9,"needed_visual":"需要什么画面","t":[120.0,151.0]}]}
"""

RECAP_PLAN_HEAD_SYSTEM = """你只补正片开场，不写剪辑表、不写口播。

已经有后面的 beats。现在只看原片开头尚未覆盖的部分，补 1–3 条开场因果。
必须包含：OP 之前的冷开场（如果有），以及片头曲之后的第一场戏。
不要选 OP/片头曲、歌词、标题动画、演职员表。
不要重复已有事件。
""" + RECAP_NAME_POLICY + """
importance 仍然看剧情，不是原片时长。

只输出 JSON，不要 markdown。
JSON schema:
{"title":"...","people":[{"id":"p1","label":"红衣女人","look":"长发红裙"}],"beats":[{"id":1,"event":"发生了什么","importance":0.9,"needed_visual":"需要什么画面","t":[120.0,151.0]}]}
"""

RECAP_PLAN_TAIL_SYSTEM = """你只补正片收尾剧情，不写剪辑表、不写口播。

已经有前半段 beats。现在只看尚未覆盖的正片后段，补 1–3 条收尾因果。
不要重复已有事件，不要从开头再讲一遍。
不要选 ED/片尾曲、演职员表、下一集预告。
""" + RECAP_NAME_POLICY + """
importance 仍然看剧情，不是原片时长。

只输出 JSON，不要 markdown。
JSON schema:
{"title":"...","people":[{"id":"p1","label":"红衣女人","look":"长发红裙"}],"beats":[{"id":1,"event":"发生了什么","importance":0.9,"needed_visual":"需要什么画面","t":[120.0,151.0]}]}
"""

RECAP_PLAN_GAP_SYSTEM = """你只补漏掉的剧情因果，不写剪辑表、不写口播。

已经有若干 beats，但中间有一段时间没有节拍。只检查这些空档里是否漏了推进故事的事件。
只补真正改变人物关系、目标、胜负、秘密的 1–4 条。走路、气氛、重复动作不要。
不要重复已有事件，不要从开头或结尾再讲一遍。
""" + RECAP_NAME_POLICY + """
不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。
importance 仍然看剧情，不是原片时长。

只输出 JSON，不要 markdown。
JSON schema:
{"title":"...","beats":[{"id":1,"event":"发生了什么","importance":0.9,"needed_visual":"需要什么画面","t":[120.0,151.0]}]}
"""

RECAP_SYSTEM = """你是影视解说剪辑 Agent 的镜头规划节点。

输入：
1. 剧情 beats（叙事目标）
2. Chunk 视觉事件描述（视觉证据）
3. 语音对白时间轴（只确认说过的话；谁在做这件事看 people / beat，不要靠猜）

beats 决定「讲什么」，是叙事真相来源。
Chunk 决定「看什么」，是视觉证据来源。
people 是人物称呼表。口播必须用表里的稳定称呼，不要把两个人写成同一个他。
对白只确认台词内容；asr[].speaker 非空时就是谁在说，不要改。
不要把对白里的名字随便安到出镜人身上。

禁止修改 beat 的事件含义，只能寻找支持该 beat 的画面。
不要重新创作剧情，不要翻译对白。
错误：beat 是「这人发现钥匙」，Chunk 是「拿起杯子」，却写成「发现隐藏线索」。
正确：找不到钥匙画面就换 Chunk，或明说画面只是相关反应，不要改写事件。

【旁白规则】
1. vo 必须是第三人称影视解说口吻，像 B 站影视速看。
2. 按 beat importance / budget_sec 调整口播长度：
   高权重（importance≥0.75 或高 budget）：2–4 句，讲清因果。
   普通：1–2 句。
   低权重：1 句带过，不要注水。
3. 口播先按拍写满，不必塞进单镜。后续会按 1.35 倍语速把字幕铺在同一拍的后续空镜上。
4. 可以吐槽、补一句反应，但不要改变事实。
5. 禁止复制 ASR 长句、禁止第一人称角色独白、禁止编造关系。
错误：「我是店长，现在开始盘点。」
正确：「柜台后的店长宣布开始盘点。」
6. """ + RECAP_NAME_POLICY + """口播跟 beat / people 的称呼走，不要改成另一个人。
错误：职员在说话，写成「女人说拒收」或「女主说拒收」。
正确：「柜台职员当众拒收。」
7. 引用原对白只能极短，用「」包裹。对白里的人名若不是在称呼当前这个人，不要拿来当他的名字。

【镜头规则】
1. 每个 beat 已有 budget_sec（成片配额）和 shots（建议刀数）。高权重多讲、多留证据镜；低权重少讲或一刀带过。
2. Chunk 是基本单位。优先用 cap 视觉事件判断画面。
3. 一个 beat 可用相邻 Chunk：建立、动作、反应、特写。不要为了碎而碎。
4. 每个镜头至少一种作用：推进剧情、关键动作、情绪强化、必要过渡、重要细节。
5. 同一个 beat 内，相邻 clip 必须提供新的视觉信息。禁止用多个近似镜头重复描述同一事件。
6. 普通镜头 5–12 秒，过程镜头不要 3 秒闪过去。口播和单镜不必 1:1。
7. src_in/src_out 必须落在对应 Chunk 时间范围内。可同时给 duration（秒）。同一连续动作可以略微连到相邻 Chunk。
8. 成片目标约 5 分半。高权重尽量用满 budget_sec，低权重宁可短不要注水。不要为了赶时间跳过因果。
9. 不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。时间最早的开场 beat 必须留下画面；冷开场要，片头曲不要。
10. 给定的每一条 beat 都必须至少有一刀。正片收尾不得省略。剧情过程要讲连贯，不要只留高潮闪回。
11. 主线优先一刀讲清事件；只有高权重才加反应或设定镜。不要每条都切三刀。
12. 换场能并进主线就不要单独一刀。必须加时 vo 只交代场面，不要发明新事件，不要认错人。

每个 clip 写 beat_id、reason、duration。reason 说明这个画面如何证明该 beat。同一句若需补特写，第二刀 vo 可空。

JSON schema:
{"title":"...","clips":[{"name":"01 短名","beat_id":1,"chunk_index":0,"src_in":0.0,"src_out":8.5,"duration":8.5,"vo":"第三人称解说旁白","reason":"该镜包含 beat 所需的人物反应"}]}
"""

RECAP_GAP_SYSTEM = """你是影视解说的查漏员。画面已经锁定，已有字幕不要改，只补漏掉的解说。

任务：找出「画面在讲事，但这条镜头没有字幕」的漏镜，只给这些镜头补 1–2 句第三人称口播。

【语速】
1. 按 1.0 倍约每秒 5 个汉字/字母，1.35 倍约每秒 6.75 个。实际可用按 fill=0.9，约每秒 6 个。
2. 每条 fill 的字数不得超过该镜 char_budget。

【规则】
1. 不要改画面，不要改已有 captions，不要发明剧情，不要翻译对白。
2. 只处理 gaps 里的镜头。特写、反应、过渡镜填 skip，不要硬补。
3. 推进剧情、关键动作、必要信息的镜头不能空着。空着就是漏。
4. 新口播要接上前后句，第三人称影视解说口吻。不要重复前后句已经讲过的事实。
5. """ + RECAP_NAME_POLICY + """不要把配角对白安成别人在说。
6. 引用原对白只能极短，用「」包裹。对白里的人名也不要拿来称呼画面人物。

只输出 JSON，不要 markdown。
JSON schema:
{"fills":[{"i":3,"text":"第三人称解说","skip":false}]}
"""


def looks_like_op_ed_text(*parts: Any) -> bool:
    body = " ".join(str(part or "") for part in parts).strip()
    if not body:
        return False
    return bool(_OP_ED_RE.search(body))


def recap_story_window(duration_sec: float) -> tuple[float, float]:
    """Keep cold open from 0. Only exclude typical ED at the tail."""
    duration = max(0.0, float(duration_sec or 0.0))
    if duration < 360:
        return 0.0, duration
    skip = 90.0 if duration >= 900 else 50.0
    end = max(30.0, duration - skip)
    return 0.0, round(end, 2)


def opening_deadline_sec(duration_sec: float) -> float:
    duration = max(0.0, float(duration_sec or 0.0))
    if duration < 360:
        return max(20.0, duration * 0.25)
    return min(210.0, max(150.0, duration * 0.12))


def _caption_one_liner(text: str, limit: int = 72) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body.startswith("{"):
        return ""
    line = body.split("\n", 1)[0].strip()
    json_at = line.find("{")
    if json_at > 0:
        line = line[:json_at].strip()
    return line[:limit]


def compact_motion_chunks(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    chunks = []
    for raw in evidence.get("chunks") or []:
        if not isinstance(raw, Mapping):
            continue
        caption = ""
        vision = ((raw.get("evidence") or {}).get("vision") or {})
        image = vision.get("image_caption") or {}
        if isinstance(image, Mapping):
            caption = _caption_one_liner(str(image.get("text") or ""), limit=160)
        tags = [str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()]
        tags = [t for t in tags if len(t) <= 12][:8]
        skip = "op_ed" if looks_like_op_ed_text(caption, " ".join(tags)) else ""
        chunks.append(
            {
                "i": int(raw.get("chunk_index", 0) or 0),
                "t": [round(float(raw.get("start_sec", 0.0) or 0.0), 2), round(float(raw.get("end_sec", 0.0) or 0.0), 2)],
                "dur": round(max(0.0, float(raw.get("end_sec", 0.0) or 0.0) - float(raw.get("start_sec", 0.0) or 0.0)), 2),
                "tags": tags,
                "cap": caption,
                "skip": skip,
            }
        )
    return chunks


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


def list_speech_dialogue_cues(video_id: str, *, config=None) -> list[dict[str, Any]]:
    """Full ASR rows for the understanding table, including speaker labels."""
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import load_dialogue_transcript

    payload = load_dialogue_transcript(str(video_id or "").strip(), config=config) or {}
    default_source = str(payload.get("asr_source") or "").strip()
    cues: list[dict[str, Any]] = []
    for index, row in enumerate(payload.get("segments") or []):
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("asr_source") or default_source or "").strip()
        if not source or is_hardsub_ocr_source(source):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            seg_index = int(row.get("seg_index", index))
        except (TypeError, ValueError):
            seg_index = index
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or start)
        cues.append(
            {
                "seg_index": seg_index,
                "start": start,
                "end": end,
                "text": text,
                "asr_source": source,
                "speaker": str(row.get("speaker") or "").strip()[:40],
            }
        )
    return cues


def recap_dialogue_status(video_id: str, *, config=None) -> dict[str, Any]:
    vid = str(video_id or "").strip()
    if not vid:
        return {"ready": False, "count": 0, "source": ""}
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    rows = list_dialogue_transcript_summaries(config=config, video_ids=[vid])
    if not rows:
        return {"ready": False, "count": 0, "source": ""}
    source = str(rows[0].get("asr_source") or "").strip()
    if not source or is_hardsub_ocr_source(source):
        return {"ready": False, "count": 0, "source": source}
    count = int(rows[0].get("segment_count") or 0)
    return {"ready": count > 0, "count": count, "source": source}


def people_from_dialogue_speakers(cues: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Seed the recap people table from labeled ASR speakers."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        out.append({"id": f"s{len(out) + 1}", "label": label, "look": "对白说话人"})
        if len(out) >= 12:
            break
    return out


def ensure_recap_dialogue_cues(cues: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = list(cues or [])
    if not items:
        raise RuntimeError(
            "没有语音对白。请先在理解页提取语音 ASR。"
        )
    return items


def build_recap_pack(video_id: str, *, config=None) -> dict[str, Any]:
    from src.services.understanding_service import load_evidence_bundle

    cfg = config if config is not None else load_config()
    evidence = load_evidence_bundle(video_id, config=cfg, mode=UNDERSTANDING_MODE_MOTION)
    if not evidence:
        raise RuntimeError("没有运动说明证据。请先在理解页生成运动说明。")
    video = dict(evidence.get("video") or {})
    chunks = compact_motion_chunks(evidence)
    if not chunks:
        raise RuntimeError("运动说明里没有可用分段。")
    ocr = compact_ocr_cues(video_id, config=cfg, limit=RECAP_OCR_LIMIT)
    ensure_recap_dialogue_cues(ocr)
    return {
        "video_id": video_id,
        "video_path": str(video.get("video_path") or ""),
        "duration_sec": float(video.get("duration_sec") or 0.0),
        "chunks": chunks,
        "ocr": ocr,
        "ocr_source": "asr",
        "people": people_from_dialogue_speakers(ocr),
    }


def recap_plan_user_prompt(pack: Mapping[str, Any]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _story_start, story_end = recap_story_window(duration)
    return (
        f"原片时长 {duration:.0f} 秒。请规划 14–20 条因果 beats（最多 24），不要写 clips。\n"
        f"从 0 秒开始覆盖开场，正片在大约 {story_end:.0f} 秒结束（片尾曲之前）。\n"
        "因果必须连续：每一次对峙、身份/目标变化、关键发现都要各自成条，中间过程不要跳。成片目标约 5 分半，用压缩过场控时长，不要删因果。\n"
        "先列 people（稳定称呼），event 里用这些称呼。禁止男主/女主。不要用同一个他指两个人。\n"
        "必须有冷开场或片头曲之后的第一场戏，不要因为去 OP 把开头剧情切掉。\n"
        "不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。skip=op_ed 的不要用。\n"
        "chunks 是视觉事件：i=chunk_index，t=[start,end]，dur=秒，cap=看得见的变化。\n"
        "asr[].speaker 非空=谁在说，当事实。不要把这句安到别人身上。空的才用画面特征称呼。\n"
        "对白只确认说过的话。人名只有自报或当面称呼才能用，且整集只绑同一个人。\n"
        "必须包含设定/空间、角色侧面，以及主线换场时的过渡；过渡只写看得见的场面，不要编新冲突。\n"
        "t 填该 beat 在原片中大约落在哪一段。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "ed_before_sec": story_end,
                "people": pack.get("people") or [],
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def recap_user_prompt(pack: Mapping[str, Any], beats: list[Mapping[str, Any]] | None = None) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    planned = list(beats or [])
    return (
        f"原片时长 {duration:.0f} 秒。成片目标约 5 分半。本段 beats 全部都要剪进去。\n"
        f"本段 beats 配额合计 {sum(float(item.get('budget_sec') or 0.0) for item in planned):.0f} 秒，clips 合计时长必须接近这个数：高权重用满，低权重一刀带过，不要漏拍也不要注水。\n"
        "先按 beats 讲故事：id、event、importance、budget_sec=这拍成片配额、shots=建议刀数、needed_visual、t=原片范围。\n"
        "beats 是叙事真相，Chunk 是视觉证据。禁止改写 beat 事件去迁就画面。\n"
        "高 importance / 高 budget 写 2–4 句并多留证据镜；普通 1–2 句；低权重 1 句带过。\n"
        "同一 beat 的相邻镜头必须有新的视觉信息，不要用近似镜头重复同一事件。\n"
        "高权重才加设定/反应镜；换场能并进主线就不要单独一刀，vo 只交代场面，不要编新剧情。\n"
        "口播不必和单镜 1:1，后面会按 1.35 倍语速铺字幕。每条 beat 的 clips 时长合计要接近 budget_sec。每个 clip 给 duration。\n"
        "时间最早的 beat 是开场，必须剪进去。不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。skip=op_ed 的 chunk 不要用。只输出这些 beats 的 clips。\n"
        "chunks 是视觉证据：i=chunk_index，t=[start,end]，cap=看得见的变化。\n"
        "口播必须用 people 里的稳定称呼，不要把两个人写成同一个他。禁止男主/女主。每个 clip 必须带 beat_id 和 reason。\n"
        "asr[].speaker 非空=谁在说，当事实。口播正确：「柜台职员当众拒收。红衣女人报了警。」\n"
        "口播错误：「他拒收，他又报了警。」「女主说拒收。」「把带 speaker 的台词安到别人身上。」\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "people": pack.get("people") or [],
                "beats": planned,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def _extract_json(text: str) -> str:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.startswith("json"):
            body = body[4:]
        body = body.strip()
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        return body[start : end + 1]
    return body


def _repair_llm_json(text: str) -> str:
    """Fix the usual LLM JSON slips: trailing commas, missing commas, smart quotes."""
    body = str(text or "").replace("\u201c", '"').replace("\u201d", '"')
    body = body.replace("\u2018", "'").replace("\u2019", "'")
    body = re.sub(r",\s*([}\]])", r"\1", body)
    body = re.sub(r"([}\]])\s*([{\[])", r"\1,\2", body)
    body = re.sub(
        r'("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)\s*\n\s*"',
        r'\1,\n"',
        body,
        flags=re.IGNORECASE,
    )
    return body


def _extract_balanced_object(text: str, start: int) -> str:
    if start < 0 or start >= len(text) or text[start] != "{":
        return ""
    depth = 0
    in_str = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _salvage_cut_list_payload(text: str) -> dict[str, Any]:
    title = "解说剪辑"
    match = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if match:
        try:
            title = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            title = match.group(1)
    clips: list[Any] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            break
        blob = _extract_balanced_object(text, start)
        if not blob:
            cursor = start + 1
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(_repair_llm_json(blob))
            except json.JSONDecodeError:
                cursor = start + 1
                continue
        if isinstance(parsed, dict) and "clips" not in parsed and ("src_in" in parsed or "vo" in parsed):
            clips.append(parsed)
            cursor = start + len(blob)
            continue
        cursor = start + 1
    if not clips:
        raise json.JSONDecodeError("No clip objects", text, 0)
    return {"title": str(title or "解说剪辑").strip() or "解说剪辑", "clips": clips}


def _loads_json_object(text: str) -> dict[str, Any]:
    raw = _extract_json(text)
    for candidate in (raw, _repair_llm_json(raw)):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise json.JSONDecodeError("No JSON object", str(text or ""), 0)


def _loads_cut_list_json(text: str) -> dict[str, Any]:
    try:
        return _loads_json_object(text)
    except json.JSONDecodeError:
        pass
    body = str(text or "").strip()
    start = body.find("{")
    salvage_src = body[start:] if start >= 0 else _extract_json(text)
    return _salvage_cut_list_payload(salvage_src)


def _time_span(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        start = float(value[0])
        end = float(value[1])
    except (TypeError, ValueError):
        return None
    if end < start:
        start, end = end, start
    return start, end


def _overlap_sec(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))


def beat_evidence_sec(beat: Mapping[str, Any], chunks: list[Mapping[str, Any]] | None = None) -> float:
    span = _time_span(beat.get("t"))
    if not span:
        return 0.0
    total = 0.0
    for item in chunks or []:
        window = _time_span(item.get("t"))
        if window:
            total += _overlap_sec(span, window)
    if total <= 0.0:
        total = min(max(0.0, span[1] - span[0]), 12.0)
    return round(total, 2)


def beat_evidence_score(evidence_sec: float) -> float:
    capped = min(max(0.0, float(evidence_sec or 0.0)), 12.0)
    return min(1.0, capped / 8.0)


def beats_cover_ending(beats: list[Mapping[str, Any]], duration_sec: float) -> bool:
    duration = float(duration_sec or 0.0)
    if duration <= 1.0 or not beats:
        return True
    _op_start, story_end = recap_story_window(duration)
    last_story = 0.0
    for beat in beats:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        if span[0] >= story_end:
            continue
        last_story = max(last_story, min(span[1], story_end))
    return last_story >= story_end * ENDING_COVER_RATIO


def beats_cover_opening(beats: list[Mapping[str, Any]], duration_sec: float) -> bool:
    duration = float(duration_sec or 0.0)
    if duration <= 1.0 or not beats:
        return True
    first_start: float | None = None
    for beat in beats:
        if looks_like_op_ed_text(beat.get("event"), beat.get("needed_visual")):
            continue
        span = _time_span(beat.get("t"))
        if not span:
            continue
        first_start = span[0] if first_start is None else min(first_start, span[0])
    if first_start is None:
        return False
    return first_start <= opening_deadline_sec(duration)


def story_gap_min_sec(duration_sec: float) -> float:
    duration = max(0.0, float(duration_sec or 0.0))
    return round(max(48.0, min(110.0, duration * 0.07)), 1)


def story_beat_gaps(
    beats: Sequence[Mapping[str, Any]],
    duration_sec: float,
) -> list[tuple[float, float]]:
    """Uncovered story windows long enough to hide a missing plot beat."""
    duration = float(duration_sec or 0.0)
    if duration <= 1.0:
        return []
    story_start, story_end = recap_story_window(duration)
    spans: list[tuple[float, float]] = []
    for beat in beats:
        if looks_like_op_ed_text(beat.get("event"), beat.get("needed_visual")):
            continue
        span = _time_span(beat.get("t"))
        if not span:
            continue
        lo = max(story_start, span[0])
        hi = min(story_end, span[1])
        if hi - lo > 0.4:
            spans.append((lo, hi))
    spans.sort()
    merged: list[tuple[float, float]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + 8.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    threshold = story_gap_min_sec(duration)
    gaps: list[tuple[float, float]] = []
    cursor = story_start
    for lo, hi in merged:
        if lo - cursor >= threshold:
            gaps.append((round(cursor, 2), round(lo, 2)))
        cursor = max(cursor, hi)
    if story_end - cursor >= threshold:
        gaps.append((round(cursor, 2), round(story_end, 2)))
    return gaps


def drop_op_ed_beats(
    beats: list[Mapping[str, Any]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    duration = float(duration_sec or 0.0)
    _op_start, story_end = recap_story_window(duration)
    kept: list[dict[str, Any]] = []
    for beat in beats:
        event = str(beat.get("event") or "")
        needed = str(beat.get("needed_visual") or "")
        if looks_like_op_ed_text(event, needed):
            continue
        span = _time_span(beat.get("t"))
        if span and duration >= 360 and span[0] >= story_end:
            continue
        kept.append(dict(beat))
    return kept or [dict(item) for item in beats]


def keep_chunk_for_recap(chunk: Mapping[str, Any], duration_sec: float) -> bool:
    if str(chunk.get("skip") or "").strip():
        return False
    span = _time_span(chunk.get("t"))
    if not span:
        return True
    _op_start, story_end = recap_story_window(duration_sec)
    if float(duration_sec or 0.0) >= 360 and span[0] >= story_end:
        return False
    return True


def _beats_brief(existing: list[Mapping[str, Any]]) -> tuple[float, float, list[dict[str, Any]]]:
    first_start = 0.0
    last_end = 0.0
    brief: list[dict[str, Any]] = []
    for beat in existing:
        span = _time_span(beat.get("t")) or (0.0, 0.0)
        if brief:
            first_start = min(first_start, span[0])
            last_end = max(last_end, span[1])
        else:
            first_start, last_end = span
        brief.append(
            {
                "id": beat.get("id"),
                "event": beat.get("event"),
                "t": [round(span[0], 2), round(span[1], 2)],
            }
        )
    return first_start, last_end, brief


def recap_plan_head_user_prompt(pack: Mapping[str, Any], existing: list[Mapping[str, Any]]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    first_start, _last_end, brief = _beats_brief(existing)
    until = min(duration, max(opening_deadline_sec(duration), first_start))
    return (
        f"原片时长 {duration:.0f} 秒。已有 beats 最早从 {first_start:.0f} 秒才开始。\n"
        f"只规划 0 秒到 {until:.0f} 秒的开场 2–4 条 beats：冷开场（如有）+ 片头曲之后第一场戏。\n"
        "沿用或补全 people 稳定称呼。不要 OP/片头曲/歌词/标题动画，不要重复下面 already。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "until_sec": round(until, 2),
                "people": pack.get("people") or [],
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def recap_plan_tail_user_prompt(pack: Mapping[str, Any], existing: list[Mapping[str, Any]]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    last_end = 0.0
    brief = []
    for beat in existing:
        span = _time_span(beat.get("t")) or (0.0, 0.0)
        last_end = max(last_end, span[1])
        brief.append(
            {
                "id": beat.get("id"),
                "event": beat.get("event"),
                "t": [round(span[0], 2), round(span[1], 2)],
            }
        )
    _op_start, story_end = recap_story_window(duration)
    start = min(story_end, max(0.0, last_end))
    return (
        f"原片时长 {duration:.0f} 秒。已有 beats 最晚只覆盖到 {start:.0f} 秒。\n"
        f"只规划 {start:.0f} 秒到正片结束（约 {story_end:.0f} 秒、片尾曲之前）的 2–4 条收尾 beats。\n"
        "沿用或补全 people 稳定称呼。不要 ED/片尾曲/演职员表/预告，不要重复下面 already。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "from_sec": round(start, 2),
                "people": pack.get("people") or [],
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def recap_plan_gap_user_prompt(
    pack: Mapping[str, Any],
    existing: list[Mapping[str, Any]],
    gaps: Sequence[tuple[float, float]],
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _first, _last, brief = _beats_brief(existing)
    windows = [{"t": [round(float(lo), 2), round(float(hi), 2)]} for lo, hi in gaps]
    return (
        f"原片时长 {duration:.0f} 秒。下面 gaps 是已有 beats 没盖住的正片空档。\n"
        "只补这些空档里漏掉的因果 1–4 条。不要重复 already，不要补走路和气氛。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "gaps": windows,
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def merge_story_beats(
    head: list[Mapping[str, Any]],
    tail: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(item) for item in head]
    used = {int(item.get("id") or 0) for item in out}
    next_id = max(used) + 1 if used else 1
    for raw in tail:
        item = dict(raw)
        span = _time_span(item.get("t"))
        if span:
            dup = False
            for prev in out:
                prev_span = _time_span(prev.get("t"))
                width = max(span[1] - span[0], 0.4)
                if prev_span and _overlap_sec(span, prev_span) > 0.6 * width:
                    dup = True
                    break
            if dup:
                continue
        try:
            beat_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        if beat_id in used or beat_id <= 0:
            beat_id = next_id
        item["id"] = beat_id
        used.add(beat_id)
        next_id = max(next_id, beat_id + 1)
        out.append(item)
    out.sort(key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)))
    return out


def filter_pack_to_spans(
    pack: Mapping[str, Any],
    windows: Sequence[tuple[float, float]],
    *,
    pad_sec: float = 20.0,
) -> dict[str, Any]:
    padded = [
        (float(lo) - float(pad_sec), float(hi) + float(pad_sec))
        for lo, hi in windows
        if float(hi) > float(lo)
    ]
    if not padded:
        out = dict(pack)
        out["chunks"] = []
        out["ocr"] = []
        return out
    chunks = []
    for item in pack.get("chunks") or []:
        span = _time_span(item.get("t"))
        if span and any(_overlap_sec(span, window) > 0 for window in padded):
            chunks.append(item)
    ocr = []
    for row in pack.get("ocr") or []:
        try:
            span = (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
        if any(_overlap_sec(span, window) > 0 for window in padded):
            ocr.append(row)
    out = dict(pack)
    out["chunks"] = chunks
    out["ocr"] = ocr
    return out


def filter_pack_to_span(
    pack: Mapping[str, Any],
    start_sec: float,
    end_sec: float,
    *,
    pad_sec: float = 20.0,
) -> dict[str, Any]:
    lo = float(start_sec) - float(pad_sec)
    hi = float(end_sec) + float(pad_sec)
    window = (lo, hi)
    chunks = []
    for item in pack.get("chunks") or []:
        span = _time_span(item.get("t"))
        if span and _overlap_sec(span, window) > 0:
            chunks.append(item)
    ocr = []
    for row in pack.get("ocr") or []:
        try:
            span = (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
        if _overlap_sec(span, window) > 0:
            ocr.append(row)
    out = dict(pack)
    out["chunks"] = chunks
    out["ocr"] = ocr
    return out


def pack_for_beats(
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]],
    *,
    pad_sec: float = 24.0,
) -> dict[str, Any]:
    starts: list[float] = []
    ends: list[float] = []
    for beat in beats:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        starts.append(span[0])
        ends.append(span[1])
    if not starts:
        out = dict(pack)
    else:
        out = filter_pack_to_span(pack, min(starts), max(ends), pad_sec=pad_sec)
    duration = float(pack.get("duration_sec") or 0.0)
    out["chunks"] = [item for item in (out.get("chunks") or []) if keep_chunk_for_recap(item, duration)]
    if pack.get("people") and not out.get("people"):
        out["people"] = list(pack.get("people") or [])
    return out


def split_beats_for_match(
    beats: list[Mapping[str, Any]],
    *,
    per_wave: int = MATCH_BEATS_PER_WAVE,
) -> list[list[dict[str, Any]]]:
    items = [dict(beat) for beat in beats]
    size = max(1, int(per_wave or MATCH_BEATS_PER_WAVE))
    if len(items) <= size:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


def missing_match_beats(
    beats: list[Mapping[str, Any]],
    cuts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    have_ids = {
        int(cut.get("beat_id"))
        for cut in cuts
        if cut.get("beat_id") is not None
    }
    missing: list[dict[str, Any]] = []
    for beat in beats:
        try:
            beat_id = int(beat.get("id"))
        except (TypeError, ValueError):
            beat_id = None
        if beat_id is not None and beat_id in have_ids:
            continue
        span = _time_span(beat.get("t"))
        covered = False
        if span:
            for cut in cuts:
                try:
                    clip_span = (float(cut.get("src_in")), float(cut.get("src_out")))
                except (TypeError, ValueError):
                    continue
                if _overlap_sec(clip_span, span) > 0.5:
                    covered = True
                    break
        if not covered:
            missing.append(dict(beat))
    return missing


def _coverage_pin_ids(beats: list[Mapping[str, Any]]) -> set[int]:
    by_time = sorted(
        beats,
        key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)),
    )
    pins: set[int] = set()
    if by_time:
        pins.add(int(by_time[0].get("id") or 0))
        pins.add(int(by_time[-1].get("id") or 0))
    for beat in beats:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        if float(beat.get("importance") or 0.0) >= 0.65:
            pins.add(beat_id)
    pins.update(_texture_pin_ids(beats))
    return {pin for pin in pins if pin}


def _is_texture_beat(beat: Mapping[str, Any]) -> bool:
    body = f"{beat.get('event') or ''} {beat.get('needed_visual') or ''}"
    return bool(_TEXTURE_BEAT_RE.search(body))


def _texture_pin_ids(beats: Sequence[Mapping[str, Any]], *, limit: int = 3) -> set[int]:
    """Keep a few setting / character / scene-change beats so allocate does not drop them all."""
    textured: list[tuple[float, int]] = []
    for beat in beats:
        if not _is_texture_beat(beat):
            continue
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        start = (_time_span(beat.get("t")) or (0.0, 0.0))[0]
        textured.append((start, beat_id))
    if not textured:
        return set()
    textured.sort()
    if len(textured) <= limit:
        return {beat_id for _start, beat_id in textured}
    picks = {textured[0][1], textured[-1][1]}
    mid = textured[len(textured) // 2][1]
    picks.add(mid)
    return picks


def _ensure_pinned_rows(
    keep: list[tuple[float, float, dict[str, Any]]],
    scored: list[tuple[float, float, dict[str, Any]]],
    pin_ids: set[int],
) -> list[tuple[float, float, dict[str, Any]]]:
    rows = list(keep)
    have = {int(row[2].get("id") or 0) for row in rows}
    for row in scored:
        beat_id = int(row[2].get("id") or 0)
        if beat_id not in pin_ids or beat_id in have:
            continue
        if len(rows) >= MAX_PLAN_BEATS:
            drop_at = None
            for index in range(len(rows) - 1, -1, -1):
                other_id = int(rows[index][2].get("id") or 0)
                if other_id not in pin_ids:
                    drop_at = index
                    break
            if drop_at is None:
                continue
            dropped = rows.pop(drop_at)
            have.discard(int(dropped[2].get("id") or 0))
        rows.append(row)
        have.add(beat_id)
    return rows


def normalize_story_beats(raw: Mapping[str, Any] | list[Any]) -> list[dict[str, Any]]:
    items = raw.get("beats") if isinstance(raw, Mapping) else raw
    if not isinstance(items, list) or not items:
        raise RuntimeError("LLM 没有返回剧情节拍。")
    out: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    next_id = 1
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        event = str(item.get("event") or "").strip()
        if not event:
            continue
        try:
            importance = float(item.get("importance") or 0.5)
        except (TypeError, ValueError):
            importance = 0.5
        importance = min(1.0, max(0.05, importance))
        span = _time_span(item.get("t")) or (0.0, 0.0)
        try:
            beat_id = int(item.get("id"))
        except (TypeError, ValueError):
            beat_id = index
        if beat_id in used_ids or beat_id <= 0:
            while next_id in used_ids:
                next_id += 1
            beat_id = next_id
        used_ids.add(beat_id)
        next_id = max(next_id, beat_id + 1)
        needed = str(item.get("needed_visual") or item.get("needed") or "").strip()[:80]
        out.append(
            {
                "id": beat_id,
                "event": event[:120],
                "importance": round(importance, 3),
                "needed_visual": needed,
                "t": [round(span[0], 2), round(span[1], 2)],
            }
        )
    if not out:
        raise RuntimeError("LLM 剧情节拍没有可用条目。")
    return out


def normalize_story_people(raw: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    items = raw.get("people") if isinstance(raw, Mapping) else raw
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()[:40]
        if not label:
            continue
        look = str(item.get("look") or item.get("needed_visual") or "").strip()[:60]
        who_id = str(item.get("id") or f"p{index}").strip()[:16] or f"p{index}"
        if who_id in used:
            who_id = f"p{index}"
        used.add(who_id)
        out.append({"id": who_id, "label": label, "look": look})
        if len(out) >= 12:
            break
    return out


def merge_story_people(*groups: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in normalize_story_people({"people": list(group or [])}):
            key = str(item.get("label") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def parse_story_plan(text: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        payload = _loads_json_object(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("语言模型返回的剧情节拍不是合法 JSON。请再生成一次。") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM 输出不是 JSON 对象。")
    title = str(payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    return title, normalize_story_beats(payload), normalize_story_people(payload)


def parse_story_beats(text: str) -> tuple[str, list[dict[str, Any]]]:
    title, beats, _people = parse_story_plan(text)
    del _people
    return title, beats


def allocate_beat_budgets(
    beats: list[Mapping[str, Any]],
    *,
    chunks: list[Mapping[str, Any]] | None = None,
    target_sec: float = TARGET_RECAP_SEC,
    duration_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Keep every planned beat and scale quotas so the recap lands near target_sec."""
    items = drop_op_ed_beats(beats, duration_sec)
    if not items:
        raise RuntimeError("没有可分配的剧情节拍。")
    chunk_list = list(chunks or [])
    scored: list[tuple[dict[str, Any], float, float]] = []
    for beat in items:
        evidence = beat_evidence_sec(beat, chunk_list)
        evid_score = beat_evidence_score(evidence)
        importance = float(beat.get("importance") or 0.5)
        weight = importance * (0.35 + 0.65 * evid_score)
        scored.append((dict(beat), evidence, weight))
    budgets = _fit_budgets_to_target(
        [item[2] for item in scored],
        float(target_sec or TARGET_RECAP_SEC),
    )
    allocated: list[dict[str, Any]] = []
    for (beat, evidence, weight), budget in zip(scored, budgets):
        out = dict(beat)
        out["evidence_sec"] = round(evidence, 2)
        out["weight"] = round(weight, 4)
        out["budget_sec"] = budget
        out["shots"] = min(5, max(1, int(round(budget / 6.0))))
        allocated.append(out)
    allocated.sort(key=lambda item: ((item.get("t") or [0.0, 0.0])[0], int(item.get("id") or 0)))
    return allocated


def _fit_budgets_to_target(
    weights: Sequence[float],
    target_sec: float,
    *,
    min_sec: float = MIN_BEAT_BUDGET_SEC,
    max_sec: float = MAX_BEAT_BUDGET_SEC,
) -> list[float]:
    n = len(weights)
    if n <= 0:
        return []
    target = max(n * HARD_MIN_BEAT_SEC, float(target_sec or TARGET_RECAP_SEC))
    floor = float(min_sec)
    if n * floor > target:
        floor = max(HARD_MIN_BEAT_SEC, target / n)
    cap = max(floor, float(max_sec))
    remaining = max(0.0, target - n * floor)
    wsum = sum(max(0.05, float(weight or 0.0)) for weight in weights) or float(n)
    budgets = [
        min(cap, floor + remaining * (max(0.05, float(weight or 0.0)) / wsum))
        for weight in weights
    ]
    for _ in range(8):
        total = sum(budgets)
        diff = target - total
        if abs(diff) < 0.2:
            break
        if diff > 0:
            room = [max(0.0, cap - item) for item in budgets]
            rsum = sum(room)
            if rsum <= 0.05:
                break
            budgets = [item + diff * (slot / rsum) for item, slot in zip(budgets, room)]
        else:
            slack = [max(0.0, item - floor) for item in budgets]
            ssum = sum(slack)
            if ssum <= 0.05:
                break
            budgets = [item + diff * (slot / ssum) for item, slot in zip(budgets, slack)]
    return [round(min(cap, max(floor, item)), 1) for item in budgets]


def recap_caption_user_prompt(clips: list[Mapping[str, Any]]) -> str:
    rows = _caption_clip_rows(clips)
    seed = pack_captions_for_tts(clips)
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，成片 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍，不要真去合成语音。\n"
        f"1.0 倍约 {BASE_CHARS_PER_SEC:.0f} 字/秒，当前约 {CHARS_PER_SEC:.2f} 字/秒，fill={VO_FILL_RATIO}。\n"
        f"全片大约能讲 {tts_char_budget(total)} 字。口播跟画面走，不要为了填满再注水。\n"
        "from/to 用 clip 的 i。一句旁白可跨连续多刀。只输出 captions。\n"
        "seed 是按语速预铺的建议，可改写、合并，不要丢掉关键因果。\n\n"
        + json.dumps({"clips": rows, "seed": seed}, ensure_ascii=False)
    )


def recap_gap_user_prompt(
    clips: list[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
    gap_indices: Sequence[int],
    people: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    rows = _caption_clip_rows(clips)
    gaps = [index + 1 for index in gap_indices]
    for row in rows:
        row["gap"] = int(row["i"]) in gaps
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，成片 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍。已有字幕不要改。\n"
        "gaps 是目前没有字幕盖住的镜头。只给确实漏解说的镜头补 fills，特写/反应/过渡填 skip。\n"
        "口播跟 people 里的稳定称呼走，不要把两个人写成同一个他。\n\n"
        + json.dumps(
            {
                "people": list(people or []),
                "clips": rows,
                "captions": list(captions or []),
                "gaps": gaps,
            },
            ensure_ascii=False,
        )
    )


def _caption_clip_rows(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, clip in enumerate(clips, 1):
        start = float(clip.get("tl_in") or 0.0)
        end = float(clip.get("tl_out") or 0.0)
        dur = max(0.0, end - start)
        rows.append(
            {
                "i": index,
                "name": str(clip.get("name") or f"{index:02d}"),
                "tl": [round(start, 3), round(end, 3)],
                "dur": round(dur, 3),
                "budget": tts_char_budget(dur),
                "need": round(vo_needed_sec(str(clip.get("vo_draft") or clip.get("vo") or "")), 2),
                "beat_id": clip.get("beat_id"),
                "reason": str(clip.get("reason") or ""),
                "vo": str(clip.get("vo") or "").strip(),
                "vo_draft": str(clip.get("vo_draft") or clip.get("vo") or "").strip(),
            }
        )
    return rows


def _counted_chars(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or ch.isalnum())


def tts_char_budget(
    duration_sec: float,
    *,
    speed: float = TTS_SPEED,
    fill_ratio: float = VO_FILL_RATIO,
) -> int:
    rate = BASE_CHARS_PER_SEC * max(0.1, float(speed or 1.0)) * max(0.1, float(fill_ratio or 1.0))
    return max(0, int(float(duration_sec or 0.0) * rate))


def vo_sec(text: str, chars_per_sec: float | None = None) -> float:
    n = _counted_chars(text)
    rate = float(chars_per_sec) if chars_per_sec is not None else CHARS_PER_SEC
    return round(n / max(0.1, rate), 2)


def vo_needed_sec(text: str) -> float:
    """Picture seconds needed to speak ``text`` at the preset TTS speed."""
    return round(vo_sec(text) / max(0.1, VO_FILL_RATIO), 2)


def _caption_clip_sec(clip: Mapping[str, Any]) -> float:
    if clip.get("tl_out") is not None and clip.get("tl_in") is not None:
        return max(0.0, float(clip["tl_out"]) - float(clip["tl_in"]))
    if clip.get("duration") is not None:
        return max(0.0, float(clip["duration"]))
    return _clip_len(clip)


def _vo_needs_more_picture(text: str, picture_sec: float) -> bool:
    """True when this line still overflows the picture it currently covers.

    A shot that is already ~80% filled does not absorb later empty cuts.
    Overflow still covers later empty bridges that were added for speaking time.
    """
    picture = max(0.0, float(picture_sec or 0.0))
    need = vo_needed_sec(text)
    if picture <= 0.08:
        return need > 0.08
    return need > picture * VO_COVER_RATIO + 0.08


def _clip_duration_for_vo(text: str) -> float:
    needed = max(MIN_CLIP_SEC, vo_sec(text) / VO_FILL_RATIO)
    return min(MAX_TTS_CLIP_SEC, needed)


def _join_vo(*parts: str) -> str:
    out = ""
    for part in parts:
        body = str(part or "").strip()
        if not body:
            continue
        if not out:
            out = body
            continue
        if _vo_covers(out, body):
            continue
        if _vo_covers(body, out):
            out = body
            continue
        if out[-1] in "。！？!?…":
            out += body
        else:
            out += "，" + body
    return out


def _normalize_vo_key(text: str) -> str:
    return re.sub(r"[\s，,。！？!?…；;：:、]+", "", str(text or "").strip())


def _vo_covers(long: str, short: str) -> bool:
    a = _normalize_vo_key(long)
    b = _normalize_vo_key(short)
    return bool(a and b and (a == b or b in a))


def trim_vo_to_budget(text: str, budget: int) -> str:
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    if _counted_chars(body) <= budget:
        return body
    pieces = [item for item in re.split(r"(?<=[。！？!?；;])", body) if str(item or "").strip()]
    kept: list[str] = []
    used = 0
    for piece in pieces:
        take = _counted_chars(piece)
        if kept and used + take > budget:
            break
        if not kept and take > budget:
            buf = []
            count = 0
            for ch in piece:
                step = 1 if ("\u4e00" <= ch <= "\u9fff" or ch.isalnum()) else 0
                if count + step > budget:
                    break
                buf.append(ch)
                count += step
            return "".join(buf).strip()
        kept.append(piece)
        used += take
        if used >= budget:
            break
    return "".join(kept).strip() or body[:budget]


def _clip_vo_text(clip: Mapping[str, Any], *, use_draft: bool = False) -> str:
    if use_draft:
        return str(clip.get("vo_draft") or clip.get("vo") or "").strip()
    return str(clip.get("vo") or clip.get("vo_draft") or "").strip()


def pack_captions_for_tts(
    clips: Sequence[Mapping[str, Any]],
    *,
    use_draft: bool = False,
) -> list[dict[str, Any]]:
    """Keep VO on its own shot.

    Later empty same-beat cuts are covered only while this line still overflows
    ~80% of the picture it already has. Distinct VO shots keep their own caption.
    """
    items = list(clips or [])
    if not items:
        return []
    captions: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        text = _clip_vo_text(items[index], use_draft=use_draft)
        if not text:
            index += 1
            continue
        beat_id = items[index].get("beat_id")
        start_i = index
        end_i = index
        covered = _caption_clip_sec(items[index])
        cursor = index + 1
        while cursor < len(items):
            nxt_beat = items[cursor].get("beat_id")
            if beat_id is not None and nxt_beat is not None and nxt_beat != beat_id:
                break
            nxt_vo = _clip_vo_text(items[cursor], use_draft=use_draft)
            if nxt_vo:
                if _vo_covers(text, nxt_vo):
                    covered += _caption_clip_sec(items[cursor])
                    end_i = cursor
                    cursor += 1
                    continue
                if _vo_covers(nxt_vo, text):
                    text = nxt_vo
                    covered += _caption_clip_sec(items[cursor])
                    end_i = cursor
                    cursor += 1
                    continue
                break
            if not _vo_needs_more_picture(text, covered):
                break
            covered += _caption_clip_sec(items[cursor])
            end_i = cursor
            cursor += 1
        start = float(items[start_i].get("tl_in") or 0.0)
        end = float(items[end_i].get("tl_out") or 0.0)
        if end <= start + 0.04:
            index = end_i + 1
            continue
        if text:
            captions.append(
                {
                    "text": text,
                    "from": start_i + 1,
                    "to": end_i + 1,
                    "tl_in": round(start, 3),
                    "tl_out": round(end, 3),
                }
            )
        index = end_i + 1
    return captions


def parse_caption_cues(text: str, clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = _loads_json_object(text)
    raw = payload.get("captions") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("LLM 没有返回 captions。")
    return normalize_caption_cues(raw, clips)


def normalize_caption_cues(
    raw: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    last_end = -1
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        body = str(item.get("text") or item.get("vo") or "").strip()
        if not body:
            continue
        start_i, end_i = _caption_index_span(item, items)
        if start_i is None:
            continue
        start_i = max(last_end + 1, start_i)
        if start_i >= len(items) or end_i < start_i:
            continue
        end_i = min(end_i, len(items) - 1)
        start = float(items[start_i].get("tl_in") or 0.0)
        end = float(items[end_i].get("tl_out") or 0.0)
        if not body:
            continue
        out.append(
            {
                "text": body,
                "from": start_i + 1,
                "to": end_i + 1,
                "tl_in": round(start, 3),
                "tl_out": round(end, 3),
            }
        )
        last_end = end_i
    if not out:
        raise RuntimeError("LLM 字幕没有可用条目。")
    return out


def _caption_index_span(
    item: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
) -> tuple[int | None, int]:
    count = len(clips)
    from_raw = item.get("from", item.get("clip_from"))
    to_raw = item.get("to", item.get("clip_to", from_raw))
    try:
        start_i = int(from_raw) - 1
        end_i = int(to_raw) - 1
    except (TypeError, ValueError):
        start_i = None
        end_i = -1
    if start_i is not None and 0 <= start_i < count:
        end_i = min(max(start_i, end_i), count - 1)
        return start_i, end_i
    try:
        tl_in = float(item.get("tl_in"))
        tl_out = float(item.get("tl_out"))
    except (TypeError, ValueError):
        return None, -1
    overlapping = [
        index
        for index, clip in enumerate(clips)
        if not (
            float(clip.get("tl_out") or 0.0) <= tl_in + 0.04
            or float(clip.get("tl_in") or 0.0) >= tl_out - 0.04
        )
    ]
    if not overlapping:
        return None, -1
    return overlapping[0], overlapping[-1]


def apply_caption_cues(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(clip) for clip in clips]
    for clip in out:
        clip.setdefault("vo_draft", str(clip.get("vo_draft") or clip.get("vo") or "").strip())
        clip["vo"] = ""
        clip.pop("vo_tl_in", None)
        clip.pop("vo_tl_out", None)
    for cap in captions:
        start_i, end_i = _caption_index_span(cap, out)
        if start_i is None:
            continue
        text = str(cap.get("text") or "").strip()
        if not text:
            continue
        out[start_i]["vo"] = text
        if cap.get("tl_in") is not None:
            out[start_i]["vo_tl_in"] = round(float(cap["tl_in"]), 3)
        if cap.get("tl_out") is not None:
            out[start_i]["vo_tl_out"] = round(float(cap["tl_out"]), 3)
        for index in range(start_i + 1, end_i + 1):
            out[index]["vo"] = ""
    return out


def fit_recap_captions_to_tts(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    laid = [dict(clip) for clip in clips]
    for clip in laid:
        clip.setdefault("vo_draft", str(clip.get("vo") or "").strip())
    packed = pack_captions_for_tts(laid, use_draft=True)
    if not packed:
        return laid
    work = apply_caption_cues(laid, packed)
    gaps = recap_gap_clip_indices(work, packed)
    if not gaps:
        return work
    if progress_callback:
        progress_callback(86, "gaps")
    try:
        gap_text = call_remote_llm(
            system=resolve_recap_prompt(system_prompt, RECAP_GAP_SYSTEM),
            user=recap_gap_user_prompt(work, packed, gaps, people=people),
            config=config,
            temperature=0.3,
            max_tokens=2048,
            should_stop_callback=should_stop_callback,
        )
        fills = parse_gap_fills(gap_text, work, allowed=set(gaps))
        if fills:
            work = apply_gap_fills(work, fills)
            packed = pack_captions_for_tts(work) or packed
            work = apply_caption_cues(work, packed)
    except UnderstandingStoppedError:
        raise
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return work


def _is_bridge_clip(clip: Mapping[str, Any]) -> bool:
    name = str(clip.get("name") or "").strip()
    reason = str(clip.get("reason") or "").strip()
    return name == "过渡" or reason == "过渡"


def recap_gap_clip_indices(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]] | None = None,
) -> list[int]:
    """Shots with no caption coverage, excluding duration-padding bridges."""
    items = list(clips or [])
    caps = list(captions if captions is not None else pack_captions_for_tts(items))
    covered: set[int] = set()
    for cap in caps:
        start_i, end_i = _caption_index_span(cap, items)
        if start_i is None:
            continue
        for index in range(start_i, min(end_i, len(items) - 1) + 1):
            covered.add(index)
    return [
        index
        for index, clip in enumerate(items)
        if index not in covered and not _is_bridge_clip(clip)
    ]


def parse_gap_fills(
    text: str,
    clips: Sequence[Mapping[str, Any]],
    *,
    allowed: set[int] | None = None,
) -> list[dict[str, Any]]:
    payload = _loads_json_object(text)
    raw = payload.get("fills") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise RuntimeError("LLM 没有返回 fills。")
    if not raw:
        return []
    items = list(clips or [])
    fills: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        skip = item.get("skip")
        if skip in (True, "true", "True", 1, "1"):
            continue
        try:
            index = int(item.get("i") or item.get("from") or 0) - 1
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items):
            continue
        if allowed is not None and index not in allowed:
            continue
        if str(items[index].get("vo") or "").strip():
            continue
        body = str(item.get("text") or item.get("vo") or "").strip()
        if not body:
            continue
        budget = tts_char_budget(_caption_clip_sec(items[index]))
        if budget:
            body = trim_vo_to_budget(body, budget)
        if not body:
            continue
        prev = ""
        nxt = ""
        if index > 0:
            prev = str(items[index - 1].get("vo") or items[index - 1].get("vo_draft") or "").strip()
        if index + 1 < len(items):
            nxt = str(items[index + 1].get("vo") or items[index + 1].get("vo_draft") or "").strip()
        if prev and _vo_covers(prev, body):
            continue
        if nxt and _vo_covers(nxt, body):
            continue
        fills.append({"index": index, "text": body})
    return fills


def apply_gap_fills(
    clips: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(clip) for clip in clips]
    for fill in fills:
        try:
            index = int(fill.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(out):
            continue
        text = str(fill.get("text") or "").strip()
        if not text or str(out[index].get("vo") or "").strip():
            continue
        out[index]["vo"] = text
        if not str(out[index].get("vo_draft") or "").strip():
            out[index]["vo_draft"] = text
    return out


def _chunk_window(pack: Mapping[str, Any], chunk_index: int) -> tuple[float, float] | None:
    for item in pack.get("chunks") or []:
        if int(item.get("i", -1)) == int(chunk_index):
            times = item.get("t") or [0, 0]
            return float(times[0]), float(times[1])
    return None


def _chunk_is_skipped(pack: Mapping[str, Any], chunk_index: int | None) -> bool:
    if chunk_index is None:
        return False
    for item in pack.get("chunks") or []:
        if int(item.get("i", -1)) == int(chunk_index):
            return bool(str(item.get("skip") or "").strip())
    return False


def normalize_cut_list(raw: Mapping[str, Any], pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    duration = float(pack.get("duration_sec") or 0.0)
    _op_start, story_end = recap_story_window(duration)
    clips_in = raw.get("clips") if isinstance(raw, Mapping) else None
    if not isinstance(clips_in, list) or not clips_in:
        raise RuntimeError("LLM 没有返回 clips。")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(clips_in, 1):
        if not isinstance(item, Mapping):
            continue
        vo = str(item.get("vo") or "").strip()
        try:
            src_in = float(item.get("src_in"))
        except (TypeError, ValueError):
            continue
        src_out = item.get("src_out")
        duration_in = item.get("duration")
        try:
            if src_out is None and duration_in is not None:
                src_out = src_in + float(duration_in)
            else:
                src_out = float(src_out)
        except (TypeError, ValueError):
            continue
        chunk_index = item.get("chunk_index")
        try:
            chunk_index_i = int(chunk_index)
        except (TypeError, ValueError):
            chunk_index_i = None
        window = _chunk_window(pack, chunk_index_i) if chunk_index_i is not None else None
        if window:
            src_in = max(window[0], src_in)
            src_out = min(window[1], src_out)
            # Allow a little spill into the next chunk for merged beats.
            src_out = max(src_out, src_in + 0.4)
        if duration > 0:
            src_in = min(max(0.0, src_in), duration)
            src_out = min(max(src_in + 0.4, src_out), duration)
        span = src_out - src_in
        vo_need = vo_needed_sec(vo) if vo else 0.0
        max_keep = max(MAX_CLIP_SEC, min(MAX_TTS_CLIP_SEC, vo_need)) if vo else MAX_CLIP_SEC
        floor = MIN_CLIP_SEC if vo else min(MIN_CLIP_SEC, max(2.4, span))
        if span > max_keep + 0.15:
            # Keep the later part of the window (the beat), not the establishing head.
            src_in = round(src_out - max_keep, 2)
        elif span < floor and duration:
            extra = floor - span
            src_out = min(duration, src_out + extra)
            if window:
                src_out = min(window[1], src_out)
            if src_out - src_in < floor:
                src_in = max(0.0 if not window else window[0], src_out - floor)
        if src_out - src_in < 0.8:
            continue
        if _chunk_is_skipped(pack, chunk_index_i):
            continue
        if duration >= 360 and src_in >= story_end:
            continue
        name = str(item.get("name") or "").strip() or f"{index:02d}"
        reason = str(item.get("reason") or "").strip()[:80]
        beat_raw = item.get("beat_id", item.get("beat"))
        try:
            beat_id = int(beat_raw)
        except (TypeError, ValueError):
            beat_id = None
        out.append(
            {
                "name": name[:40],
                "beat_id": beat_id,
                "chunk_index": chunk_index_i,
                "src_in": round(src_in, 3),
                "src_out": round(src_out, 3),
                "duration": round(src_out - src_in, 3),
                "vo": vo,
                "reason": reason,
            }
        )
    if not out:
        raise RuntimeError("LLM 剪辑表没有可用镜头。")
    return out


def _clip_len(clip: Mapping[str, Any]) -> float:
    return max(0.0, float(clip.get("src_out") or 0.0) - float(clip.get("src_in") or 0.0))


def recap_cuts_duration(cuts: list[Mapping[str, Any]]) -> float:
    return round(sum(_clip_len(clip) for clip in cuts), 3)


def _source_hits_op_ed(pack: Mapping[str, Any], start: float, end: float) -> bool:
    if end <= start:
        return False
    for chunk in pack.get("chunks") or []:
        if not str(chunk.get("skip") or "").strip() and not looks_like_op_ed_text(
            chunk.get("cap"), " ".join(str(tag) for tag in (chunk.get("tags") or []))
        ):
            continue
        span = _time_span(chunk.get("t"))
        if span and _overlap_sec((start, end), span) > 0.25:
            return True
    return False


def _clamp_window_away_from_op_ed(
    pack: Mapping[str, Any],
    lo: float,
    hi: float,
    *,
    src_in: float,
    src_out: float,
) -> tuple[float, float]:
    for chunk in pack.get("chunks") or []:
        skip = str(chunk.get("skip") or "").strip() or looks_like_op_ed_text(
            chunk.get("cap"), " ".join(str(tag) for tag in (chunk.get("tags") or []))
        )
        if not skip:
            continue
        span = _time_span(chunk.get("t"))
        if not span:
            continue
        if span[1] <= src_in + 0.35:
            lo = max(lo, span[1])
        if span[0] >= src_out - 0.35:
            hi = min(hi, span[0])
    return lo, hi


def _neighbor_source_window(
    pack: Mapping[str, Any],
    chunk_index: int | None,
    beat_span: tuple[float, float] | None = None,
    *,
    strict: bool = False,
) -> tuple[float, float] | None:
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    chunks = [
        item
        for item in (pack.get("chunks") or [])
        if keep_chunk_for_recap(item, duration) and _time_span(item.get("t"))
    ]
    chunks.sort(key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("i") or 0)))
    if not chunks:
        window = _chunk_window(pack, int(chunk_index or 0)) if chunk_index is not None else None
        return window
    index = None
    if chunk_index is not None:
        for pos, item in enumerate(chunks):
            if int(item.get("i", -1)) == int(chunk_index):
                index = pos
                break
    if index is None:
        window = _chunk_window(pack, int(chunk_index or 0)) if chunk_index is not None else None
        return window
    lo, hi = _time_span(chunks[index].get("t")) or (0.0, 0.0)
    slack = 0.0 if strict else 10.0
    cursor = index - 1
    while cursor >= 0:
        prev = _time_span(chunks[cursor].get("t"))
        if not prev or lo - prev[1] > 0.85:
            break
        if beat_span and prev[0] < beat_span[0] - slack:
            break
        lo = prev[0]
        cursor -= 1
    cursor = index + 1
    while cursor < len(chunks):
        nxt = _time_span(chunks[cursor].get("t"))
        if not nxt or nxt[0] - hi > 0.85:
            break
        if beat_span and nxt[1] > beat_span[1] + slack:
            break
        hi = nxt[1]
        cursor += 1
    if beat_span:
        pad = 0.0 if strict else 2.0
        lo = max(lo, beat_span[0] - pad)
        hi = min(hi, beat_span[1] + pad)
    if duration >= 360:
        hi = min(hi, story_end)
    if duration > 0:
        lo = max(float(story_start or 0.0), lo)
        hi = min(duration, hi)
    if hi - lo < 0.8:
        return _chunk_window(pack, int(chunk_index))
    return (lo, hi)


def _expand_clip(
    clip: dict[str, Any],
    pack: Mapping[str, Any],
    extra: float,
    beat_span: tuple[float, float] | None = None,
    *,
    forward_only: bool = False,
    max_len: float | None = None,
) -> float:
    cap = float(MAX_CLIP_SEC if max_len is None else max_len)
    room = min(max(0.0, extra), cap - _clip_len(clip))
    if room <= 0.05:
        return 0.0
    window = _neighbor_source_window(
        pack,
        clip.get("chunk_index"),
        beat_span,
        strict=forward_only,
    )
    src_in = float(clip["src_in"])
    src_out = float(clip["src_out"])
    if not window:
        own = _chunk_window(pack, int(clip.get("chunk_index") or 0)) if clip.get("chunk_index") is not None else None
        window = own or (src_in, src_out + room)
    lo, hi = window
    lo, hi = _clamp_window_away_from_op_ed(pack, lo, hi, src_in=src_in, src_out=src_out)
    take_out = min(max(0.0, hi - src_out), room)
    if take_out > 0 and _source_hits_op_ed(pack, src_out, src_out + take_out):
        take_out = 0.0
    src_out += take_out
    room -= take_out
    take_in = 0.0
    if not forward_only and room > 0.05:
        take_in = min(max(0.0, src_in - lo), room)
        if take_in > 0 and _source_hits_op_ed(pack, src_in - take_in, src_in):
            take_in = 0.0
        src_in -= take_in
    clip["src_in"] = round(src_in, 3)
    clip["src_out"] = round(src_out, 3)
    clip["duration"] = round(src_out - src_in, 3)
    return take_out + take_in


def _shrink_clip(clip: dict[str, Any], extra: float, min_len: float = MIN_CLIP_SEC) -> float:
    have = _clip_len(clip)
    take = min(max(0.0, extra), max(0.0, have - min_len))
    if take <= 0.05:
        return 0.0
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    clip["src_out"] = round(src_out - take, 3)
    clip["duration"] = round(float(clip["src_out"]) - src_in, 3)
    return take


def _trim_group_to_budget(
    out: list[dict[str, Any]],
    group: list[dict[str, Any]],
    budget: float,
) -> None:
    extra = sum(_clip_len(clip) for clip in group) - budget
    if extra <= 0.25:
        return
    empties = [clip for clip in group if not str(clip.get("vo") or "").strip()]
    while extra > 0.25 and len(group) > 1 and empties:
        victim = max(empties, key=_clip_len)
        extra -= _clip_len(victim)
        empties.remove(victim)
        group.remove(victim)
        out.remove(victim)
    order = sorted(
        group,
        key=lambda clip: (1 if str(clip.get("vo") or "").strip() else 0, -_clip_len(clip)),
    )
    for clip in order:
        if extra <= 0.05:
            break
        extra -= _shrink_clip(clip, extra)


def _make_tts_bridge_clip(
    clip: Mapping[str, Any],
    pack: Mapping[str, Any],
    need: float,
    nxt: Mapping[str, Any] | None,
    beat_span: tuple[float, float] | None,
) -> dict[str, Any] | None:
    window = _neighbor_source_window(pack, clip.get("chunk_index"), beat_span, strict=True)
    if not window:
        return None
    lo, hi = window
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    lo, hi = _clamp_window_away_from_op_ed(pack, lo, hi, src_in=src_in, src_out=src_out)
    take = min(max(MIN_BRIDGE_SEC, float(need or 0.0)), MAX_TTS_CLIP_SEC)
    avail_after = max(0.0, hi - src_out)
    if nxt is not None:
        nxt_in = float(nxt.get("src_in") or 0.0)
        if nxt_in > src_out + 0.2:
            avail_after = min(avail_after, nxt_in - src_out)
    if avail_after < MIN_BRIDGE_SEC:
        return None
    dur = min(take, avail_after)
    start, end = src_out, src_out + dur
    if _source_hits_op_ed(pack, start, end):
        return None
    return {
        "name": "过渡",
        "beat_id": clip.get("beat_id"),
        "chunk_index": clip.get("chunk_index"),
        "src_in": round(start, 3),
        "src_out": round(end, 3),
        "vo": "",
        "reason": "过渡",
    }


def _vo_cover_span(clips: Sequence[Mapping[str, Any]], start: int) -> tuple[float, int]:
    """Picture seconds covering this spoken line.

    Later empty same-beat shots count only while the line still overflows ~80%
    of the picture it already has, so extra B-roll is not treated as VO time.
    """
    if start < 0 or start >= len(clips):
        return 0.0, start
    head = clips[start]
    beat_id = head.get("beat_id")
    total = _clip_len(head)
    last = start
    cursor = start + 1
    vo = str(head.get("vo") or "").strip()
    while cursor < len(clips):
        nxt = clips[cursor]
        if beat_id is not None and nxt.get("beat_id") is not None and nxt.get("beat_id") != beat_id:
            break
        if str(nxt.get("vo") or "").strip():
            break
        if vo and not _vo_needs_more_picture(vo, total):
            break
        total += _clip_len(nxt)
        last = cursor
        cursor += 1
    return total, last


def _preferred_clip_vo(clip: Mapping[str, Any]) -> str:
    vo = str(clip.get("vo") or "").strip()
    draft = str(clip.get("vo_draft") or "").strip()
    if _counted_chars(draft) > _counted_chars(vo):
        return draft
    return vo


def restore_recap_vo_text(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Use the longer draft line on shots that still have VO. Leave packed empty follows empty."""
    out = [dict(clip) for clip in clips]
    for clip in out:
        if not str(clip.get("vo") or "").strip():
            continue
        text = _preferred_clip_vo(clip)
        if text:
            clip["vo"] = text
    return out


def stretch_recap_clips_for_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    media_duration: float = 0.0,
) -> list[dict[str, Any]]:
    """If this line needs more time at 1.35x than its shot, extend that same shot forward."""
    out = restore_recap_vo_text(clips)
    media_hi = max(0.0, float(media_duration or 0.0))
    index = 0
    while index < len(out):
        vo = str(out[index].get("vo") or "").strip()
        if not vo:
            index += 1
            continue
        need = vo_needed_sec(vo)
        have, last = _vo_cover_span(out, index)
        extra = need - have
        if extra > 0.08:
            grow = out[last]
            src_in = float(grow.get("src_in") or 0.0)
            src_out = float(grow.get("src_out") or 0.0)
            room = max(0.0, MAX_TTS_CLIP_SEC - (src_out - src_in))
            if media_hi > 0:
                room = min(room, max(0.0, media_hi - src_out))
            take = min(extra, room)
            if take > 0.05:
                grow["src_out"] = round(src_out + take, 3)
                grow["duration"] = round(float(grow["src_out"]) - src_in, 3)
        index += 1
    return out


def pad_cuts_for_tts(
    cuts: list[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Grow shots or insert bridges when VO speaking time exceeds picture."""
    out = [dict(clip) for clip in cuts]
    by_id: dict[Any, Mapping[str, Any]] = {}
    for beat in beats or []:
        try:
            by_id[int(beat.get("id"))] = beat
        except (TypeError, ValueError):
            continue
    index = 0
    while index < len(out):
        clip = out[index]
        vo = str(clip.get("vo") or "").strip()
        if vo:
            clip["vo"] = _preferred_clip_vo(clip)
            vo = str(clip.get("vo") or "").strip()
        need = vo_needed_sec(vo)
        have, last = _vo_cover_span(out, index)
        if not vo or need <= have + 0.08:
            index += 1
            continue
        beat = None
        try:
            if clip.get("beat_id") is not None:
                beat = by_id.get(int(clip["beat_id"]))
        except (TypeError, ValueError):
            beat = None
        beat_span = _time_span((beat or {}).get("t"))
        extra = need - have
        _expand_clip(
            out[last],
            pack,
            extra,
            beat_span,
            forward_only=True,
            max_len=MAX_TTS_CLIP_SEC,
        )
        have, last = _vo_cover_span(out, index)
        still = need - have
        while still > 0.5:
            nxt = out[last + 1] if last + 1 < len(out) else None
            bridge = _make_tts_bridge_clip(out[last], pack, still, nxt, beat_span)
            if not bridge:
                break
            out.insert(last + 1, bridge)
            last += 1
            still = need - _vo_cover_span(out, index)[0]
        index += 1
    return out


def apply_recap_duration(
    cuts: list[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
    *,
    target_sec: float = TARGET_RECAP_SEC,
    min_sec: float = MIN_RECAP_SEC,
) -> list[dict[str, Any]]:
    """Stretch short beats toward their quota; trim beats that overshoot."""
    _ = (target_sec, min_sec)
    out = [dict(clip) for clip in cuts]
    if not out:
        return out
    by_id = {}
    for beat in beats or []:
        try:
            by_id[int(beat.get("id"))] = dict(beat)
        except (TypeError, ValueError):
            continue
    groups: dict[Any, list[dict[str, Any]]] = {}
    for clip in out:
        groups.setdefault(clip.get("beat_id"), []).append(clip)
    for beat_id, group in groups.items():
        beat = None
        if beat_id is not None:
            try:
                beat = by_id.get(int(beat_id))
            except (TypeError, ValueError):
                beat = None
        budget = float((beat or {}).get("budget_sec") or 0.0)
        if budget <= 0:
            continue
        have = sum(_clip_len(clip) for clip in group)
        need = budget - have
        beat_span = _time_span((beat or {}).get("t"))
        if need > 0.05:
            for clip in sorted(group, key=lambda item: -len(str(item.get("vo") or ""))):
                if need <= 0.05:
                    break
                need -= _expand_clip(clip, pack, need, beat_span)
        elif need < -0.25:
            _trim_group_to_budget(out, group, budget)
    return out


def parse_cut_list(text: str, pack: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = _loads_cut_list_json(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "语言模型返回的剪辑表不是合法 JSON（常见于漏逗号或镜头太多被截断）。请再生成一次。"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM 输出不是 JSON 对象。")
    title = str(payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    return title, normalize_cut_list(payload, pack)


def _probe_media(video_path: str) -> dict[str, Any]:
    from src.media.probe import _probe_video_stream_with_opencv

    info = _probe_video_stream_with_opencv(video_path)
    if not info.get("fps"):
        info["fps"] = 24.0
    if not info.get("width"):
        info["width"] = 1920
    if not info.get("height"):
        info["height"] = 1080
    return info


def resolve_recap_prompt(text: str | None, default: str) -> str:
    body = str(text or "").strip()
    return body or default


def resolve_recap_system_prompt(text: str | None) -> str:
    return resolve_recap_prompt(text, RECAP_SYSTEM)


def normalize_recap_start_from(value: str | None) -> str:
    key = str(value or RECAP_START_PLAN).strip().lower()
    if key in {RECAP_START_MATCH, "matching", "2"}:
        return RECAP_START_MATCH
    if key in {RECAP_START_CAPTIONS, "caption", "gaps", "3"}:
        return RECAP_START_CAPTIONS
    return RECAP_START_PLAN


def recap_beats_path_for_video(video_path: str) -> Path:
    video = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    return video.parent / f"{video.stem}_recap_beats.json"


def load_recap_beats(video_path: str) -> dict[str, Any] | None:
    path = recap_beats_path_for_video(video_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("beats"), list):
        return None
    if not payload.get("beats"):
        return None
    return payload


def write_recap_beats_file(
    dest: str | Path,
    *,
    title: str,
    video_id: str,
    allocated: list[Mapping[str, Any]],
    people: list[Mapping[str, Any]] | None = None,
    stage: str = RECAP_START_PLAN,
) -> Path:
    path = Path(dest)
    path.write_text(
        json.dumps(
            {
                "title": title,
                "video_id": video_id,
                "stage": stage,
                "target_sec": round(sum(float(item.get("budget_sec") or 0.0) for item in allocated), 1),
                "people": list(people or []),
                "beats": list(allocated),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _recap_clip_records(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clip in clips:
        rows.append(
            {
                "name": clip.get("name"),
                "beat_id": clip.get("beat_id"),
                "chunk_index": clip.get("chunk_index"),
                "src_in": round(float(clip.get("src_in") or 0.0), 3),
                "src_out": round(float(clip.get("src_out") or 0.0), 3),
                "duration": round(
                    float(clip.get("duration") or (float(clip.get("src_out") or 0.0) - float(clip.get("src_in") or 0.0))),
                    3,
                ),
                "tl_in": round(float(clip.get("tl_in") or 0.0), 3),
                "tl_out": round(float(clip.get("tl_out") or 0.0), 3),
                "vo": clip.get("vo") or "",
                "vo_draft": str(clip.get("vo_draft") or clip.get("vo") or ""),
                "vo_tl_in": clip.get("vo_tl_in"),
                "vo_tl_out": clip.get("vo_tl_out"),
                "reason": str(clip.get("reason") or ""),
            }
        )
    return rows


def write_recap_cuts_file(
    dest: str | Path,
    *,
    title: str,
    video_path: str,
    video_id: str,
    info: Mapping[str, Any],
    laid_out: Sequence[Mapping[str, Any]],
    beats_path: str | Path,
    stage: str,
) -> Path:
    clips = list(laid_out or [])
    return write_cuts_json(
        {
            "title": title,
            "video": video_path,
            "video_id": video_id,
            "stage": stage,
            "fps": info.get("fps"),
            "duration_sec": clips[-1]["tl_out"] if clips else 0,
            "tts_speed": TTS_SPEED,
            "clip_count": len(clips),
            "beats_path": str(beats_path),
            "clips": _recap_clip_records(clips),
        },
        dest,
    )


def generate_recap_timeline(
    video_id: str,
    dest_dir: str,
    *,
    config=None,
    system_prompt: str | None = None,
    plan_prompt: str | None = None,
    caption_prompt: str | None = None,
    start_from: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    cfg = config if config is not None else load_config()
    llm = get_remote_llm_settings(cfg)
    if not str(llm.get("model") or "").strip():
        raise RuntimeError("尚未配置语言模型。请先在模型服务 → LLM 里填写并保存。")
    pack = build_recap_pack(video_id, config=cfg)
    video_path = str(pack.get("video_path") or "")
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"找不到原片：{video_path or '(空路径)'}")

    def _progress(value: int, stage: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(stage))

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("Recap stopped by user")

    _raise_if_stopped()
    stage = normalize_recap_start_from(start_from)
    plan_system = resolve_recap_prompt(plan_prompt, RECAP_PLAN_SYSTEM)
    match_system = resolve_recap_system_prompt(system_prompt)
    gap_system = resolve_recap_prompt(caption_prompt, RECAP_GAP_SYSTEM)
    duration = float(pack.get("duration_sec") or 0.0)
    out_dir = Path(str(dest_dir or "").strip() or Path(video_path).resolve().parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    beats_path = out_dir / f"{stem}_recap_beats.json"
    cuts_path = out_dir / f"{stem}_recap_cuts.json"
    info: dict[str, Any] | None = None
    plan_title = "解说剪辑"
    allocated: list[dict[str, Any]] = []
    cuts: list[dict[str, Any]] = []
    title = plan_title
    people: list[dict[str, Any]] = []
    pack = dict(pack)

    if stage == RECAP_START_CAPTIONS:
        saved_cuts = load_recap_cuts(video_path)
        if not saved_cuts:
            raise RuntimeError("没有已保存的选镜表。请先跑第二阶段，或从第一阶段开始。")
        title = str(saved_cuts.get("title") or "").strip() or plan_title
        saved_beats = load_recap_beats(video_path)
        if saved_beats:
            plan_title = str(saved_beats.get("title") or plan_title)
            beats_path = recap_beats_path_for_video(video_path)
            people = normalize_story_people(saved_beats)
        cuts = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
        pack["people"] = people
    else:
        if stage == RECAP_START_MATCH:
            saved = load_recap_beats(video_path)
            if not saved:
                raise RuntimeError("没有已保存的剧情规划。请先跑第一阶段，或从第一阶段开始。")
            plan_title = str(saved.get("title") or "").strip() or plan_title
            beats = list(saved.get("beats") or [])
            people = normalize_story_people(saved)
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=float(saved.get("target_sec") or TARGET_RECAP_SEC),
                duration_sec=duration,
            )
            beats_path = write_recap_beats_file(
                recap_beats_path_for_video(video_path),
                title=plan_title,
                video_id=video_id,
                allocated=allocated,
                people=people,
            )
        else:
            _progress(12, "planning")
            plan_text = call_remote_llm(
                system=plan_system,
                user=recap_plan_user_prompt(pack),
                config=cfg,
                temperature=0.3,
                max_tokens=8192,
                should_stop_callback=should_stop_callback,
            )
            plan_title, beats, people = parse_story_plan(plan_text)
            beats = drop_op_ed_beats(beats, duration)
            people = merge_story_people(pack.get("people"), people)
            pack["people"] = people
            _story_start, story_end = recap_story_window(duration)
            if duration > 1.0 and not beats_cover_opening(beats, duration):
                first_start = opening_deadline_sec(duration)
                for beat in beats:
                    span = _time_span(beat.get("t"))
                    if span:
                        first_start = min(first_start, span[0])
                _raise_if_stopped()
                _progress(22, "planning")
                head_pack = filter_pack_to_span(pack, 0.0, first_start, pad_sec=12.0)
                try:
                    head_text = call_remote_llm(
                        system=RECAP_PLAN_HEAD_SYSTEM,
                        user=recap_plan_head_user_prompt(head_pack, beats),
                        config=cfg,
                        temperature=0.3,
                        max_tokens=2048,
                        should_stop_callback=should_stop_callback,
                    )
                    _head_title, head_beats, head_people = parse_story_plan(head_text)
                    del _head_title
                    beats = drop_op_ed_beats(merge_story_beats(head_beats, beats), duration)
                    people = merge_story_people(head_people, people)
                    pack["people"] = people
                except RuntimeError:
                    pass
            if duration > 1.0 and not beats_cover_ending(beats, duration):
                last_end = 0.0
                for beat in beats:
                    span = _time_span(beat.get("t"))
                    if span:
                        last_end = max(last_end, min(span[1], story_end))
                _raise_if_stopped()
                _progress(32, "closing")
                tail_pack = filter_pack_to_span(pack, last_end, story_end, pad_sec=8.0)
                try:
                    tail_text = call_remote_llm(
                        system=RECAP_PLAN_TAIL_SYSTEM,
                        user=recap_plan_tail_user_prompt(tail_pack, beats),
                        config=cfg,
                        temperature=0.3,
                        max_tokens=2048,
                        should_stop_callback=should_stop_callback,
                    )
                    _tail_title, tail_beats, tail_people = parse_story_plan(tail_text)
                    del _tail_title
                    beats = drop_op_ed_beats(merge_story_beats(beats, tail_beats), duration)
                    people = merge_story_people(people, tail_people)
                except RuntimeError:
                    pass
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=TARGET_RECAP_SEC,
                duration_sec=duration,
            )
            _raise_if_stopped()
            beats_path = write_recap_beats_file(
                beats_path,
                title=plan_title,
                video_id=video_id,
                allocated=allocated,
                people=people,
            )

        cuts = []
        match_title = plan_title
        waves = split_beats_for_match(allocated)
        for index, wave in enumerate(waves):
            _raise_if_stopped()
            _progress(48 + min(24, index * 14), "matching")
            wave_pack = pack_for_beats(pack, wave)
            match_text = call_remote_llm(
                system=match_system,
                user=recap_user_prompt(wave_pack, wave),
                config=cfg,
                temperature=0.4,
                max_tokens=8192,
                should_stop_callback=should_stop_callback,
            )
            wave_title, wave_cuts = parse_cut_list(match_text, pack)
            if wave_title and wave_title != "解说剪辑":
                match_title = wave_title
            cuts.extend(wave_cuts)
        leftover = missing_match_beats(allocated, cuts)
        if leftover:
            _raise_if_stopped()
            _progress(82, "closing")
            close_pack = pack_for_beats(pack, leftover)
            try:
                close_text = call_remote_llm(
                    system=match_system,
                    user=recap_user_prompt(close_pack, leftover),
                    config=cfg,
                    temperature=0.3,
                    max_tokens=4096,
                    should_stop_callback=should_stop_callback,
                )
                _close_title, close_cuts = parse_cut_list(close_text, pack)
                del _close_title
                cuts.extend(close_cuts)
            except RuntimeError:
                pass
        cuts.sort(key=lambda item: (float(item.get("src_in") or 0.0), int(item.get("beat_id") or 0)))
        cuts = apply_recap_duration(cuts, pack, allocated)
        cuts = pad_cuts_for_tts(cuts, pack, allocated)
        title = str(match_title or "").strip() or plan_title
        if title == "解说剪辑" and plan_title and plan_title != "解说剪辑":
            title = plan_title
        _raise_if_stopped()
        info = _probe_media(video_path)
        laid_match = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
        write_recap_cuts_file(
            cuts_path,
            title=title,
            video_path=video_path,
            video_id=video_id,
            info=info,
            laid_out=laid_match,
            beats_path=beats_path,
            stage=RECAP_START_MATCH,
        )
        cuts = laid_match

    _raise_if_stopped()
    if info is None:
        info = _probe_media(video_path)
    laid_out = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
    _progress(84, "captions")
    laid_out = fit_recap_captions_to_tts(
        laid_out,
        config=cfg,
        system_prompt=gap_system,
        people=people,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    _raise_if_stopped()
    _progress(90, "writing")
    cuts_path = write_recap_cuts_file(
        cuts_path,
        title=title,
        video_path=video_path,
        video_id=video_id,
        info=info,
        laid_out=laid_out,
        beats_path=beats_path,
        stage=RECAP_START_CAPTIONS,
    )
    srt_path = write_srt(laid_out, out_dir / f"{stem}_recap.srt")
    return {
        "title": title,
        "video_id": video_id,
        "stage": RECAP_START_CAPTIONS,
        "clip_count": len(laid_out),
        "duration_sec": laid_out[-1]["tl_out"] if laid_out else 0,
        "beats_path": str(beats_path),
        "cuts_path": str(cuts_path),
        "srt_path": str(srt_path),
    }


def recap_cuts_path_for_video(video_path: str) -> Path:
    video = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    return video.parent / f"{video.stem}_recap_cuts.json"


def load_recap_cuts(video_path: str) -> dict[str, Any] | None:
    path = recap_cuts_path_for_video(video_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("clips"), list):
        return None
    if not payload.get("clips"):
        return None
    return payload


def export_saved_recap_fcpxml(
    payload: Mapping[str, Any],
    dest_path: str | Path,
    *,
    video_path: str = "",
) -> Path:
    video = str(video_path or payload.get("video") or "").strip()
    if not video or not os.path.isfile(video):
        raise RuntimeError(f"找不到原片：{video or '(空路径)'}")
    info = _probe_media(video)
    clips = stretch_recap_clips_for_vo(
        list(payload.get("clips") or []),
        media_duration=float(info.get("duration") or 0.0),
    )
    if not clips:
        raise RuntimeError("剪辑表没有镜头。")
    laid = layout_clips_on_timeline(clips, fps=float(info.get("fps") or payload.get("fps") or 24.0))
    return write_fcpxml(
        laid,
        video_path=video,
        info=info,
        dest_path=dest_path,
        project_name=str(payload.get("title") or "解说剪辑"),
    )

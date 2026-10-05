"""Plan / match / rematch user prompts for the recap LLM stages.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.services.recap_clock import recap_target_sec
from src.services.recap_match import recap_story_window

def recap_plan_user_prompt(pack: Mapping[str, Any]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _story_start, story_end = recap_story_window(duration)
    target = recap_target_sec(duration)
    seeded = list(pack.get("people") or [])
    name_line = (
        "people 已有稳定称呼（含用户命名与声线聚类）。event/口播主语优先跟 asr.speaker / people.label 走；"
        "声线N 可先当临时称呼；可用男主/女主/发色外号，但禁止用外号顶替已有真名/用户命名。\n"
        if seeded
        else "先列 people（稳定称呼，可用男主/女主/黄毛/蓝毛等）；无人名再用画面特征。\n"
    )
    return (
        f"原片时长 {duration:.0f} 秒。请规划有证据支撑的故事线大纲 beats（有 asr/cap 就写，条数不设上限），不要写 clips。\n"
        f"从 0 秒开始覆盖开场，正片在大约 {story_end:.0f} 秒结束（片尾曲之前）。\n"
        f"【证据优先】asr/cap 撑得住才写；台词密就写密，禁止为省条数砍收束。禁止稀薄提纲、禁止大段无节拍空档。\n"
        f"自检：只读全部 event 必须能听成有头有尾的故事（进入→展开→高潮→收束）。相邻纲要必须递进或转场。成片目标约 {target:.0f} 秒（软上限；禁止删进入/收束/因果来凑时长）。\n"
        "进入新活动/新空间前必须有进入拍（赶到现场、入座开始、走进房间等）；禁止直接蹦到场内「某人惊讶了」或场内结果（全勾完了/结果出来了）。\n"
        "相邻场面或活动性质变了时，中间必须有进入/离开过渡 beat；禁止上一段刚结束下一句就直接写下一段场内结果。\n"
        "每段新小剧场：进入 → 中间过程 → 落点都要有；对白已讲清的答应/拒绝/决定/胜负必须成落点，禁止讲完过程不写结果。\n"
        "禁止孤立反应句当大纲（XX惊讶了/愣住了）；先有触发事件，再写局面变化。\n"
        "高潮/对决/身份揭晓/胜负分晓 importance≥0.85，禁止跳过最精彩的冲突。\n"
        "短而关键的动作（失手、得手、致命一击等）必须各自成条且高权重，禁止因只有几秒就并进前后大段。\n"
        "对白骨架的前后因果不得跳空：后果与起因各自成 beat，禁止只留两端结果。\n"
        "相邻 beats 的 t 不要留下大段无节拍空档；中段推进过程要盖住，收束也要盖住。\n"
        "同场戏按剧情递进拆拍，不要把每一次表情/反应拆成大纲条目。\n"
        + name_line
        + "不要用同一个他指两个人。\n"
        "必须有冷开场或片头曲之后的第一场戏，不要因为去 OP 把开头剧情切掉。\n"
        "不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。asr 是叙事骨架。chunks 可能只有时间没有 cap；有 cap 才是看见的变化。skip=op_ed 不要用。\n"
        "asr[].speaker 非空=谁在说，绝对证据。不要把这句安到别人身上。空的且对白也无人名时才用画面特征称呼。\n"
        "对白只确认说过的话。人名只有自报或当面称呼才能用，且整集只绑同一个人；禁止从 people 表乱抓名字张冠李戴。\n"
        "event 写成故事线纲要句（谁做了什么、局面怎么变），且能被画面/对白核对；禁止空洞主题句；禁止「XX说/觉得/认为」；禁止单独「XX惊讶了」。\n"
        "每条 beat 必须带 evidence_required（1–4 个：人物/动作/反应/物品/对话/变化/场面）和 needed_visual，供选镜找证据。\n"
        "分清主语宾语：谁找到谁的名字必须写清；禁止并成「找到了两人名字」又自相矛盾。\n"
        "必须包含设定/空间、角色侧面。换场/换冲突必须有过渡 beat；同场也要递进，禁止高潮直接跳到下一场。\n"
        "t 填该 beat 在原片中大约落在哪一段。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "ed_before_sec": story_end,
                "people": seeded,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def recap_user_prompt(
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
    *,
    used_src: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    planned = list(beats or [])
    target = recap_target_sec(duration)
    used = list(used_src or [])
    used_line = (
        "【已用画面】下面 used_src 已占用，禁止再剪重叠超过约三成的同一段原片（连续复用更禁止）。\n"
        if used
        else "【已用画面】本段若多刀，每刀 src 不得互相大面积重叠；更禁止连着几刀同一画面。\n"
    )
    return (
        f"原片时长 {duration:.0f} 秒。成片目标约 {target:.0f} 秒（按原片比例，约 3–8 分钟，作软上限：不要为凑分钟注水）。本段 beats 全部都要剪进去。\n"
        f"本段 beats 配额合计 {sum(float(item.get('budget_sec') or 0.0) for item in planned):.0f} 秒：每条 beat 的进入/推进/收束画面都要有；低权重可短，不可省略进入与落点；不要漏拍、不要注水。\n"
        "先按 beats 找证据画面：id、event、vo=已写好的解说稿、evidence_required、importance、budget_sec=这拍成片配额上限、shots=建议刀数、needed_visual、t=原片范围。\n"
        "【硬约束】每条 clip 的 src_in/src_out 必须落在该 beat.t 内（允许前后各约 10 秒）；禁止跨到别的 beat 时间去「借」画面。\n"
        + used_line
        + "画面必须服务 beat.vo：优先选 cap 能证明这段旁白的 chunk；无 vo 时才退回按 event/evidence_required 选。"
        "无 cap 的 chunk 只能当时间兜底，reason 禁止瞎猜看见了什么；证据对不上就标弱证据，不要硬编。\n"
        "禁止改写 beat 事件或旁白去迁就画面。\n"
        "不要输出 vo 字段；正式旁白已在 beat.vo，铺字幕阶段只润色。\n"
        "同一 beat 的相邻镜头必须有新的视觉信息，不要用近似镜头重复同一事件，也不要把两刀粘成一条长镜头。\n"
        "shots>=2 时后几刀优先特写/反应，role=insert，不要为了赶时间并进主线。"
        "insert 必须贴着同一 beat 的主线动作与 beat.t：优先同 chunk/紧邻 chunk，紧跟主镜之后。"
        "禁止整段复用同一 src_in/src_out；禁止把别的 beat 已经用过的画面再剪一遍；允许动作后紧挨着的反应特写（可与主镜同 chunk，但 src 区间仍须错开）。"
        "禁止为了凑 insert 去选远晚于该 beat.t 的表情/特写。\n"
        "相邻 beats 换场/换人/换冲突时必须单独留 role=bridge 过渡镜（离开/赶到/进门/场面变化），禁止并进主线导致跳远；纯无信息走路才可并进。bridge 的 reason 只交代场面，不要编新剧情。\n"
        "每条 beat 的 clips：先保证进入→关键变化→落点都有画面；合计时长贴近 vo 口播时长，再控制不超过 budget_sec；禁止「证据够了就停」只留半截。每个 clip 给 duration。\n"
        "时间最早的 beat 是开场，必须剪进去。不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。skip=op_ed 的 chunk 不要用。只输出这些 beats 的 clips。\n"
        "chunks 是视觉证据：i=chunk_index，t=[start,end]，cap=看得见的变化。"
        "有 cap 必须优先；无 cap 时只按 asr 时间与 chunk.t 选镜，禁止瞎猜画面内容。\n"
        "reason 用 people 里的稳定称呼（优先用户命名的 speaker label）；可用男主/女主/发色外号，有真名时不要用外号顶替。"
        "不要把两个人写成同一个他。每个 clip 必须带 beat_id 和 reason。\n"
        "asr[].speaker 非空=谁在说，当事实。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "people": pack.get("people") or [],
                "beats": planned,
                "used_src": used,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def rematch_recap_user_prompt(
    pack: Mapping[str, Any],
    *,
    beat: Mapping[str, Any],
    prev_beat: Mapping[str, Any] | None = None,
    next_beat: Mapping[str, Any] | None = None,
    prev_vo: Sequence[str] | None = None,
    next_vo: Sequence[str] | None = None,
    old_cuts: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Match prompt for one beat with locked neighbor context (read-only)."""
    target_id = int(beat.get("id"))
    context_beats = [item for item in (prev_beat, beat, next_beat) if item]
    base = recap_user_prompt(pack, context_beats)
    old_rows = []
    for clip in old_cuts or []:
        old_rows.append(
            {
                "src_in": clip.get("src_in"),
                "src_out": clip.get("src_out"),
                "reason": str(clip.get("reason") or "")[:80],
                "role": str(clip.get("role") or ""),
                "vo": str(clip.get("vo") or "")[:120],
            }
        )
    extra = {
        "rematch": {
            "target_beat_id": target_id,
            "instruction": (
                f"这是定点重选镜：只输出 beat_id={target_id} 的 clips。"
                "前后拍已锁定，禁止输出其它 beat_id，禁止改写前后旁白。"
                "结合 asr 台词与 chunks.cap 画面证据重选；不要凭空编表情/动机。"
                "旧刀仅作参考，可以整段换掉，但事件必须仍是该 beat.event。"
            ),
            "locked_prev_vo": list(prev_vo or []),
            "locked_next_vo": list(next_vo or []),
            "old_cuts_for_target": old_rows,
        }
    }
    return base + "\n\n" + json.dumps(extra, ensure_ascii=False)

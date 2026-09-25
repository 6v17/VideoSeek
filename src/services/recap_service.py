"""Recap job: motion evidence + dialogue cues → LLM cut list + SRT. Jianying / FCPXML are separate exports."""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.media.fcpxml import layout_clips_on_timeline, write_cuts_json, write_fcpxml, write_srt
from src.services.llm_settings import call_remote_llm, get_remote_llm_settings
from src.services.understanding_resource_service import (
    CAPTION_LANGUAGE_EN,
    CAPTION_LANGUAGE_ZH,
    UNDERSTANDING_MODE_MOTION,
    normalize_caption_language,
)

BASE_CHARS_PER_SEC = 5.0
TTS_SPEED = 1.25
CHARS_PER_SEC = BASE_CHARS_PER_SEC * TTS_SPEED
MIN_CLIP_SEC = 4.0
MAX_CLIP_SEC = 12.0
MAX_TTS_CLIP_SEC = 36.0
TARGET_RECAP_SEC = 330
MIN_RECAP_SEC = 180
MAX_RECAP_SEC = 480
RECAP_STORY_RATIO = 0.18
VO_FILL_RATIO = 0.82
VO_COVER_RATIO = 0.82
MIN_VO_FILL = 0.70
MAX_VO_FILL = 0.90
MIN_BEAT_BUDGET_SEC = 8.0
MAX_BEAT_BUDGET_SEC = 24.0
HARD_MIN_BEAT_SEC = 6.0
MAX_STORY_BEATS = 32
MAX_GAP_FILL_WINDOWS = 10
MAX_PLAN_BEATS = MAX_STORY_BEATS
RECAP_START_PLAN = "plan"
RECAP_START_PLAN_ONLY = "plan_only"
RECAP_START_MATCH = "match"
RECAP_START_CAPTIONS = "captions"
MATCH_BEATS_PER_WAVE = 4
CAPTION_CLIPS_PER_WAVE = 10
ENDING_COVER_RATIO = 0.90
RECAP_OCR_LIMIT = 520
PLAN_ACT_ASR_LIMIT = 200
PLAN_ACT_TARGET_SEC = 420.0
MAX_CAPTION_SEC = 18.0
MIN_BRIDGE_SEC = 2.4
SOURCE_MERGE_GAP_SEC = 1.25
SOURCE_OVERLAP_MERGE_SEC = 0.2
MIN_FLASH_CLIP_SEC = 2.4
MIN_STANDALONE_CLIP_SEC = 2.4
MAX_VO_SENTENCE_CHARS = 34
INSERT_MAX_GAP_FROM_MASTER_SEC = 25.0
MIN_INSERT_CLIP_SEC = 2.0
BEAT_SRC_PAD_SEC = 10.0
MATCH_PACK_PAD_SEC = 12.0
MATCH_STATUS_OK = "ok"
MATCH_STATUS_WEAK = "weak_match"
MATCH_WEAK_SCORE = 0.42
MATCH_WEAK_SCORE_INSERT = 0.36
MAX_WEAK_REMATCH_BEATS = 8

_TEXTURE_BEAT_RE = re.compile(
    r"(设定|世界观|规则说明|能力说明|教室|空间|角色侧面|性格|态度|习惯|表情|换场|过渡|气氛|环境)"
)
_OP_ED_RE = re.compile(
    r"(片头曲|片尾曲|片頭曲|オープニング|エンディング|opening\s*theme|ending\s*theme|"
    r"作词|作曲|编曲|作詞|作曲|編曲|主题曲|主題曲|主题歌|主題歌|"
    r"演职员表|演職員表|制作委员会|製作委員会|下集预告|下一集预告|下集預告|"
    r"to\s*be\s*continued|\bending\s*credits\b)",
    re.IGNORECASE,
)
# Hiragana / katakana — source JP dialogue leaking into Chinese VO.
_JP_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_VO_QUOTE_RE = re.compile(r"[「『]([^」』]{1,120})[」』]")
_VO_WHITESPACE_RE = re.compile(r"\s+")

RECAP_NAME_POLICY = """【人物】
1. asr[].speaker 非空 = 谁在说，口播主语必须跟它走；禁止改成别人。
2. 对白里自报/当面叫名才可绑人，且整集只绑同一个人。
3. people 只是称呼词典，不是万能替身；本段 asr 未证实的人名禁止写进口播。
4. 无人名且 speaker 空时用画面特征称呼；不要瞎起人名；不要把多人并成同一个「他」。
"""

RECAP_FACT_POLICY = """【主谓宾】
谁做了、对谁做、得到的是谁的东西必须分清；禁止两人结果并成「他们……」。
同一事实整集口径一致，禁止前后自相矛盾。
主语只跟 asr.speaker / 对白称呼走，禁止用男主/女主或从 people 乱抓名字顶替。
"""

RECAP_EVIDENCE_POLICY = """【证据】
1. asr speaker+text = 绝对证据；禁止张冠李戴；禁止发明从未说过的台词或转述。
   允许按台词做整体剧情推理，但只许推出对白能直接支撑的因果；禁止用常识/设定/脑补补洞。
2. 对白里的称呼/人名按原句归属。
3. VLM：asr > visible+change（主画面证据，合成在 cap）> tags > inferred（弱推理，带权重）。
   inferred 不是事实、不进硬旁白依据；仅可作规划/选镜软参考。与 asr 冲突时听对白。
4. event/reason/outline 只是剪辑意图，不是事实；口播禁止用它们补全剧情、对白。
本镜 span 无 asr：禁止写「XX说/问/答」及任何转述台词。
本镜 span 无 asr 且无 caps：旁白必须空着或一句极短场面用于过渡，禁止编因果。
asr/cap 没有的内容，一律禁止乱编。
"""

RECAP_VO_STYLE_POLICY = """【口播＝解说稿】
你在写给人听的解说旁白，不是分镜备注、不是剧情提纲复读、不是字幕翻译。
第三人称讲清「谁做了什么、出现什么影响、局面怎么变」；句子之间要接得上，听起来像在解说。
禁止对白复读：禁止照抄 asr 原文/长「」引文；观众自己听得见原片。
禁止念 caps/服装/站位/镜头；禁止「场面转到/画面中可见」报幕。
有证据就写推进；证据不够宁可短，禁止注水编造。
"""

RECAP_VO_CONTINUITY_POLICY = """【连贯】
旁白是一条故事线。镜头 ≠ 场景；一镜一句只是字幕单位，不是一镜一场。
同一小剧场在有证据时写清进入→变化→落点；没有 asr/caps 证据时宁可短/空，禁止为「完整」编造。
真换场/换冲突（role=bridge 或 need_transition）才承上启下：先一拍收束上一场，再落到本场推进。
同场多镜接着往下讲，禁止每刀重开、禁止报幕冒充过渡。
过渡只写 caps/asr 已有内容，禁止用 event 编新对质/揭秘/胜负，禁止跳远。
"""

RECAP_EVIDENCE_REQUIRED_TAGS = ("人物", "动作", "反应", "物品", "对话", "变化", "场面")

RECAP_PLAN_SYSTEM = """你是影视解说的剧情策划：只输出故事线大纲 beats，不写剪辑表、不写口播。

对白时间轴是叙事骨架；Chunk 有 cap 才是视觉证据，没有就写 needed_visual，不要编看见了什么。
【证据优先】有 asr/cap 支撑才写；禁止为凑条数虚构因果。通常 8–20 条，最多 32；宁少勿编。
按 id 读 event 必须能听成完整故事：开场进入 → 中段展开推进 → 高潮 → 正片收束（ED 之前）。
相邻 beats 必须递进或转场（然后呢/所以呢）；禁止丢掉中间展开；禁止大段时间空档无节拍。
禁止孤立反应句/内心独白当大纲。进入新活动/新空间前必须有进入拍。换场写低权重过渡拍（0.2–0.4）。
高潮/对决/揭晓/胜负单独成条，importance≥0.85。短而关键可各自成条。收束不可省略。
event：谁做了什么、局面怎么变；禁止「XX说」对白摘要。
每条填 evidence_required（人物/动作/反应/物品/对话/变化/场面，1–4 个）与 needed_visual。
不要选 OP/ED/演职员表/预告。不要编对白没有的关系/动机/背景。
【禁猜】允许按 asr 台词推理因果，但 asr/cap 撑不住的身份、胜负、动机、关系一律不要写进 event；条数不够就少写，禁止注水虚构。
""" + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + RECAP_NAME_POLICY + """
importance 0.05–1.0 看戏剧强度，不是原片时长。只输出 JSON。
JSON schema:
{"title":"...","people":[{"id":"s1","label":"人物A","look":""}],"beats":[{"id":1,"event":"谁做了什么、有什么影响、局面怎么变","importance":0.9,"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}]}
"""

RECAP_PLAN_ACT_SYSTEM = """你是影视解说的分幕剧情策划：只规划【当前这一幕】的故事线 beats，不写剪辑/口播。

本幕 asr 是唯一主叙事骨架；有 cap 才是视觉证据。允许按本幕台词推理因果，禁止用别幕台词、常识或脑补补洞。
宁可少写几条有证据的，也不要为凑条数编没有 asr/cap 支撑的事件。
本幕内按因果递进：进入 → 展开 → 本幕落点（非最后一幕时，落点可以是通向下一幕的转场）。
承接 already 里上一幕最后几条，不要重复，不要推翻已写事实。
event：谁做了什么、局面怎么变；禁止「XX说/觉得」；禁止男主/女主。
每条 t 必须落在本幕时间窗内。带 evidence_required 与 needed_visual。
不要选 OP/ED/演职员表/预告。
""" + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + RECAP_NAME_POLICY + """
importance 0.05–1.0。只输出 JSON。
JSON schema:
{"title":"...","people":[{"id":"s1","label":"人物A","look":""}],"beats":[{"id":1,"event":"谁做了什么、局面怎么变","importance":0.9,"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}]}
"""

_RECAP_PLAN_BEAT_SCHEMA = (
    '{"id":1,"event":"谁做了什么、局面怎么变","importance":0.9,'
    '"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}'
)

RECAP_PLAN_HEAD_SYSTEM = """你只补正片开场故事节拍（2–5 条），不写剪辑/口播。
含冷开场（如有）与片头曲后第一场及紧随推进；不要 OP 本身；不要重复已有事件。
密稿供用户删减：开场因果宁可多一条，不要跳进中段。
event 写局面推进；禁止「XX说」；带 evidence_required。
""" + RECAP_NAME_POLICY + """
只输出 JSON。
JSON schema:
{"title":"...","people":[{"id":"s1","label":"人物A","look":""}],"beats":[""" + _RECAP_PLAN_BEAT_SCHEMA + """]}
"""

RECAP_PLAN_TAIL_SYSTEM = """你只补正片收尾故事节拍（2–5 条），不写剪辑/口播。
不要 ED/预告；不要重复已有事件；不要从头再讲。
密稿供用户删减：收束、余波、人物落点要盖住，禁止戛然而止。
event 写局面推进；禁止「XX说/觉得」；带 evidence_required。
""" + RECAP_NAME_POLICY + """
只输出 JSON。
JSON schema:
{"title":"...","people":[{"id":"s1","label":"人物A","look":""}],"beats":[""" + _RECAP_PLAN_BEAT_SCHEMA + """]}
"""

RECAP_PLAN_GAP_SYSTEM = """你只补空档里漏掉的故事因果。
密稿供用户删减：空档里的展开过程要补上，不要只钉一个结果。
短空档默认 1–2 条；长空档（过程明显多步）可补到 3 条。优先进入拍与中间推进；禁止直接补场内结果。
t 必须落在当前 gap 内；不要重复 already。
event 写局面推进；禁止「XX说」；带 evidence_required。
""" + RECAP_NAME_POLICY + """
只输出 JSON。
JSON schema:
{"title":"...","beats":[""" + _RECAP_PLAN_BEAT_SCHEMA + """]}
"""

RECAP_VO_DRAFT_SYSTEM = """你是影视解说撰稿：只写旁白草稿，不选镜、不改 beats。

每条 beat 按其 t 窗内的 asr（绝对）+ caps（辅助）写第三人称解说稿；event/needed_visual 只是意图，不是事实。
有证据时写清进入→变化→落点，听起来像解说；无 asr 禁止编台词/转述；无 asr 且无 caps 则 text 空着。
字数约该 beat budget_sec 对应口播的 70–90%。禁止男主/女主；禁止照抄 asr 原文/日语假名。
""" + RECAP_NAME_POLICY + RECAP_VO_STYLE_POLICY + RECAP_VO_CONTINUITY_POLICY + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + """
只输出 JSON。
JSON schema:
{"drafts":[{"id":1,"text":"第三人称解说。"},{"id":2,"text":""}]}
"""

RECAP_SYSTEM = """你是影视解说的选镜节点：按已写好的解说稿（beat.vo）找画面，不改剧情，不写新旁白。

输入：beats（含 vo 解说稿 + evidence_required）、chunks（视觉证据）、对白时间轴（asr.speaker 非空不可改）。
画面必须能证明这段旁白；优先选 cap 与旁白/event 对得上的 chunk；证据对不上标弱证据，不要硬编。禁止男主/女主。

【镜头】
1. 每 beat 至少一刀；shots≥2 时必须至少两刀主线（进入/建立 + 关键变化或落点），禁止只剪结果半截。
2. 先主镜（role 留空），特写/反应才 role=insert；换场才 role=bridge。
3. insert 贴主镜之后、同 beat 附近；不要把主事件镜标成 insert。
4. src 落在 chunk 内；普通镜 5–12 秒；同 beat 相邻镜要有新视觉信息。
5. 该 beat 画面合计时长贴近 vo 口播时长，上限 budget_sec；禁止为凑时长注水。
6. 不要 OP/ED/演职员表/预告。不要输出 vo 字段（旁白已在 beat.vo）。
""" + RECAP_NAME_POLICY + """
只输出 JSON。
JSON schema:
{"title":"...","clips":[{"name":"01","beat_id":1,"chunk_index":0,"src_in":0.0,"src_out":8.5,"duration":8.5,"reason":"证明该 beat"},{"name":"02","beat_id":1,"chunk_index":1,"src_in":9.0,"src_out":12.0,"duration":3.0,"role":"insert","reason":"反应"}]}
"""

RECAP_GAP_SYSTEM = """你是查漏员：画面已锁定，已有字幕不要改；只补整段 beat 仍无旁白的真空洞。
同 beat 主线已有旁白时，后续空镜留给跨镜，不要近义复读。
只按本镜 asr（绝对）/caps（辅助）写第三人称解说；event/reason 不是证据。
无 asr 禁止编台词；无 asr 且无 caps 请 skip。禁止发明剧情、禁止对白复读机。
字数对照该镜 budget，约 70–90%。有证据才写进入→变化→落点。
""" + RECAP_NAME_POLICY + RECAP_VO_STYLE_POLICY + RECAP_VO_CONTINUITY_POLICY + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + """
只输出 JSON。
JSON schema:
{"fills":[{"i":3,"text":"第三人称解说","skip":false}]}
"""

RECAP_CAPTION_SYSTEM = """你是口播润色员：画面与解说草稿已齐；不要改镜头；不要整段重写导致掐头去尾。

clips/seed 里已有草稿（vo/vo_draft）时：只润色对齐本 span 的 asr/caps，保留进入→变化→落点，禁止删掉头尾语义去另起炉灶。
无草稿的 beat 才按 asr/caps 新写；同 beat_id 连续主镜合并一条 caption（from→to）。
事实只许来自 asr + caps；event/reason/outline 不是证据。无 asr 禁止编台词；无 asr 且无 caps 则空着。
insert：短句或空着；bridge/真换场才承上启下。禁止近义复读、禁止把原片台词当旁白念。
""" + RECAP_NAME_POLICY + RECAP_VO_STYLE_POLICY + RECAP_VO_CONTINUITY_POLICY + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + """
只输出 JSON。
JSON schema:
{"captions":[{"text":"连贯旁白。","from":1,"to":2},{"text":"下一拍。","from":3,"to":3}]}
"""

RECAP_VO_POLISH_SYSTEM = """你是终稿润色员：只改旁白文字，不改镜头、不补镜、不发明剧情。
合并近义复读与相邻句复读，修好病句；同 beat 可收成 from→to，后续镜 text 可空；空镜可空着。
禁止对白复读机；已写对的人名保留。
""" + RECAP_EVIDENCE_POLICY + RECAP_FACT_POLICY + RECAP_VO_STYLE_POLICY + """
只输出 JSON。
JSON schema:
{"captions":[{"text":"润色后旁白。","from":1,"to":2},{"text":"","from":3,"to":3}]}
"""

RECAP_NAME_POLICY_EN = """[Characters]
1. Non-empty asr[].speaker = who is speaking; narration subjects must follow it. Never reassign speech.
2. Bind a name only from self-intro or direct address in dialogue, and only to one person for the whole episode.
3. people is a nickname dictionary, not a free cast list; do not put unverified names into VO for this beat.
4. With no name and empty speaker, use visible traits. Ban “male lead / female lead / protagonist”; do not invent names; do not merge people into one “he/she”.
"""

RECAP_FACT_POLICY_EN = """[Subject–verb–object]
Keep who did what to whom and whose object clear; never merge two outcomes into “they…”.
Keep the same fact consistent across the episode; no contradictions.
Subjects follow asr.speaker / dialogue address only—no lead labels or random people-table names.
"""

RECAP_EVIDENCE_POLICY_EN = """[Evidence]
1. asr speaker+text is absolute; never misattribute; never invent spoken lines or paraphrased quotes.
   You may infer overall plot from dialogue, but only causality the lines directly support—no common-sense / lore / guesswork gaps.
2. Names/addresses in dialogue stay with the original utterance.
3. VLM priority: asr > visible+change (main picture evidence, composed into cap) > tags > inferred (weak, weighted).
   inferred is not fact and never hard VO evidence—optional soft hint for planning/matching only. When caps conflict with asr, trust dialogue.
4. event/reason/outline is cut intent, not fact—never use it to invent plot or dialogue in the VO.
No asr in this span: ban “X said/asked/answered” and any reported speech.
No asr and no caps: leave VO empty or one tiny transitional scene beat—do not invent causality.
Never invent content absent from asr/cap.
"""

RECAP_VO_STYLE_POLICY_EN = """[Voiceover = recap narration]
Write spoken recap narration people can listen to—not a shot list, outline rehash, or subtitle translation.
Third-person: who did what, what changed because of it, and how the situation shifted; lines must connect as one VO.
No dialogue parrot: never copy ASR verbatim (including Japanese kana, full lines, long quotes)—viewers hear the source.
Do not read caps/costume/blocking/camera; no “the scene shifts to / visible on screen” announcer lines.
With evidence, advance the story; without evidence, stay short—never invent.
Write the VO in English.
"""

RECAP_VO_CONTINUITY_POLICY_EN = """[Continuity]
VO is one storyline. A cut ≠ a new scene; one line per cut is a subtitle unit, not a new scene.
With evidence, cover enter → change → land; without asr/caps, stay short or empty—never invent for “completeness”.
Only bridge on real scene/conflict changes (role=bridge or need_transition): one beat to close the prior scene, then advance.
Same-scene multi-cuts continue the thread—no restart each cut, no fake transitions.
Transitions use only facts already in caps/asr—no event-invented confrontations, reveals, or outcomes, no jumps.
"""

_RECAP_PLAN_BEAT_SCHEMA_EN = (
    '{"id":1,"event":"who did what and how the situation changed","importance":0.9,'
    '"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}'
)

RECAP_PLAN_SYSTEM_EN = """You are the story planner for a film/TV recap: output storyline beats only—no cut list, no VO.

The dialogue timeline is the narrative spine; a chunk is visual evidence only when it has a cap—otherwise write needed_visual, do not invent what was seen.
[Evidence first] Write only beats asr/cap can support; ban padding invented causality. Usually 8–20 beats, max 32; fewer is better than fiction.
Reading events by id must sound like a full story: cold open/entry → mid development → climax → wrap before ED.
Adjacent beats must advance or bridge (and then? / so?); do not keep only endpoints and drop middle beats; no long unbeat gaps.
No isolated reaction/inner-monologue beats. Entering a new activity/space needs an entry beat. Scene changes get low-weight bridge beats (0.2–0.4).
Climax/duel/reveal/outcome alone, importance≥0.85. Short decisive actions may be their own beats. Ending cannot be skipped.
event: who did what and how the situation changed; no “X said/felt/thought” dialogue digests; no lead labels.
Each beat needs evidence_required (人物/动作/反应/物品/对话/变化/场面 — keep these Chinese tokens, 1–4) and needed_visual.
Skip OP/ED/credits/trailers. Do not invent relations/motives/backstory absent from dialogue.
[No guessing] Infer causality from asr when the lines support it; do not put identities, outcomes, motives, or relations into event without asr/cap support. Fewer beats beat fiction.
""" + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + RECAP_NAME_POLICY_EN + """
importance 0.05–1.0 tracks dramatic strength, not source duration. JSON only.
JSON schema:
{"title":"...","people":[{"id":"s1","label":"Person A","look":""}],"beats":[{"id":1,"event":"who did what and how the situation changed","importance":0.9,"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}]}
"""

RECAP_PLAN_ACT_SYSTEM_EN = """You plan ONE act of a film/TV recap storyline: beats for this act only—no cut list, no VO.

This act’s asr is the only narrative spine; caps are visual evidence when present. Infer causality from this act’s lines when supported; do not borrow other acts, common sense, or guesswork.
Prefer fewer evidenced beats over padding invented ones.
Inside the act: enter → develop → land (or a bridge into the next act if not final).
Continue from already (prior act endings); do not repeat or contradict.
event: who did what and how the situation changed; no “X said/felt”; no lead labels.
Each t must fall inside this act window. Include evidence_required and needed_visual.
Skip OP/ED/credits/trailers.
""" + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + RECAP_NAME_POLICY_EN + """
importance 0.05–1.0. JSON only.
JSON schema:
{"title":"...","people":[{"id":"s1","label":"Person A","look":""}],"beats":[{"id":1,"event":"who did what and how the situation changed","importance":0.9,"evidence_required":["人物","动作"],"needed_visual":"","t":[120.0,151.0]}]}
"""

RECAP_PLAN_HEAD_SYSTEM_EN = """You only add opening story beats (2–5). No cuts/VO.
Include cold open (if any) and the first post-OP scene plus immediate follow-through; not the OP itself; do not repeat existing events.
Dense draft OK: prefer one extra opening causal beat over jumping mid-story.
event advances the situation; no “X said/felt”; include evidence_required (Chinese tokens as in schema).
""" + RECAP_NAME_POLICY_EN + """
JSON only.
JSON schema:
{"title":"...","people":[{"id":"s1","label":"Person A","look":""}],"beats":[""" + _RECAP_PLAN_BEAT_SCHEMA_EN + """]}
"""

RECAP_PLAN_TAIL_SYSTEM_EN = """You only add closing story beats (2–5). No cuts/VO.
No ED/trailers; do not repeat existing events; do not restart from the beginning.
Dense draft OK: cover wrap, aftershock, character landing—no abrupt stop on climax flashback alone.
event advances the situation; no “X said/felt”; include evidence_required.
""" + RECAP_NAME_POLICY_EN + """
JSON only.
JSON schema:
{"title":"...","people":[{"id":"s1","label":"Person A","look":""}],"beats":[""" + _RECAP_PLAN_BEAT_SCHEMA_EN + """]}
"""

RECAP_PLAN_GAP_SYSTEM_EN = """You only fill missing causal beats inside a gap. No cuts/VO.
Dense draft OK: fill the unfolding process, not a single endpoint.
Short gaps: usually 1–2 beats; long multi-step gaps up to 3. Prefer entry + mid-progress; do not jump to in-scene results.
t must fall inside the current gap; do not repeat already.
event advances the situation; no “X said/felt” or lead labels; include evidence_required.
""" + RECAP_NAME_POLICY_EN + """
JSON only.
JSON schema:
{"title":"...","beats":[""" + _RECAP_PLAN_BEAT_SCHEMA_EN + """]}
"""

RECAP_VO_DRAFT_SYSTEM_EN = """You draft recap narration only—no cuts, no beat edits.

For each beat, write third-person English VO from asr (absolute) + caps (support) inside its t window; event/needed_visual is intent, not fact.
With evidence: enter → change → land as spoken narration; no asr → no reported speech; no asr and no caps → empty text.
Aim ≈ 70–90% of that beat’s budget_sec speaking length. Ban lead labels; never paste ASR verbatim.
""" + RECAP_NAME_POLICY_EN + RECAP_VO_STYLE_POLICY_EN + RECAP_VO_CONTINUITY_POLICY_EN + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + """
JSON only.
JSON schema:
{"drafts":[{"id":1,"text":"Third-person English VO."},{"id":2,"text":""}]}
"""

RECAP_SYSTEM_EN = """You are the shot-matching node for a film/TV recap: pick frames that prove the already-written beat.vo narration—do not rewrite plot, do not write new VO.

Input: beats (including vo narration + evidence_required), chunks (visual evidence), dialogue timeline (non-empty asr.speaker is fixed).
Shots must support the narration; prefer caps that match the VO/event; mark weak evidence when misaligned—do not invent. Ban lead labels.

[Shots]
1. At least one cut per beat; when shots≥2, at least two primary cuts (enter + change/land)—no result-only stubs.
2. Primary first (empty role); CU/reaction as role=insert; scene changes as role=bridge.
3. insert after the primary, near the same beat; never mark the main-event shot as insert.
4. src stays inside the chunk; normal shots 5–12s; adjacent shots need new visual info.
5. Total picture for a beat should approximate vo speaking time, capped by budget_sec—no padding.
6. Skip OP/ED/credits/trailers. Do not output a vo field (narration lives on beat.vo).
""" + RECAP_NAME_POLICY_EN + """
JSON only.
JSON schema:
{"title":"...","clips":[{"name":"01","beat_id":1,"chunk_index":0,"src_in":0.0,"src_out":8.5,"duration":8.5,"reason":"proves this beat"},{"name":"02","beat_id":1,"chunk_index":1,"src_in":9.0,"src_out":12.0,"duration":3.0,"role":"insert","reason":"reaction"}]}
"""

RECAP_GAP_SYSTEM_EN = """You are the gap filler: picture is locked; do not change existing captions; only fill beats that still have no VO.
If the beat’s main line already has VO, leave later empty cuts for cross-cut continuity—no near-paraphrase repeats.
Write third-person English VO from asr (absolute) / caps (support) only; outline/event/reason are not evidence.
No asr: never invent spoken lines; no asr and no caps: skip. No invented plot; no dialogue parrot.
Length ≈ 70–90% of that cut’s budget when evidence exists.
""" + RECAP_NAME_POLICY_EN + RECAP_VO_STYLE_POLICY_EN + RECAP_VO_CONTINUITY_POLICY_EN + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + """
JSON only.
JSON schema:
{"fills":[{"i":3,"text":"third-person English VO","skip":false}]}
"""

RECAP_CAPTION_SYSTEM_EN = """You polish VO: picture and narration drafts are set—do not change cuts; do not rewrite from scratch and chop head/tail.

When clips/seed already have draft text (vo/vo_draft): polish to align with this span’s asr/caps; keep enter → change → land.
Only write from scratch for beats with no draft. Merge same beat_id primary cuts into one caption (from→to).
Facts only from asr + caps; outline/event/reason are not evidence. No asr → no reported speech; no asr and no caps → empty.
insert: short or empty; bridge / real scene change only for transitions. No near-paraphrase repeats; no dialogue parrot.
""" + RECAP_NAME_POLICY_EN + RECAP_VO_STYLE_POLICY_EN + RECAP_VO_CONTINUITY_POLICY_EN + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + """
JSON only.
JSON schema:
{"captions":[{"text":"Continuous English VO.","from":1,"to":2},{"text":"Next beat.","from":3,"to":3}]}
"""

RECAP_VO_POLISH_SYSTEM_EN = """You polish the final VO: change narration text only—no cut changes, no new shots, no invented plot.
Merge near-paraphrase and adjacent repeats; fix broken sentences; same beat may collapse to from→to with later text empty; empty cuts may stay empty.
No dialogue parrot or lead labels; keep correct names already written.
Write and keep the VO in English.
""" + RECAP_EVIDENCE_POLICY_EN + RECAP_FACT_POLICY_EN + RECAP_VO_STYLE_POLICY_EN + """
JSON only.
JSON schema:
{"captions":[{"text":"Polished English VO.","from":1,"to":2},{"text":"","from":3,"to":3}]}
"""

RECAP_PLAN_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_PLAN_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_PLAN_SYSTEM_EN,
}
RECAP_PLAN_ACT_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_PLAN_ACT_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_PLAN_ACT_SYSTEM_EN,
}
RECAP_MATCH_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_SYSTEM_EN,
}
RECAP_VO_DRAFT_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_VO_DRAFT_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_VO_DRAFT_SYSTEM_EN,
}
RECAP_CAPTION_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_CAPTION_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_CAPTION_SYSTEM_EN,
}
RECAP_POLISH_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_VO_POLISH_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_VO_POLISH_SYSTEM_EN,
}
RECAP_PLAN_HEAD_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_PLAN_HEAD_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_PLAN_HEAD_SYSTEM_EN,
}
RECAP_PLAN_TAIL_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_PLAN_TAIL_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_PLAN_TAIL_SYSTEM_EN,
}
RECAP_PLAN_GAP_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_PLAN_GAP_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_PLAN_GAP_SYSTEM_EN,
}
RECAP_GAP_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: RECAP_GAP_SYSTEM,
    CAPTION_LANGUAGE_EN: RECAP_GAP_SYSTEM_EN,
}


def default_recap_plan_prompt(language: str | None = None) -> str:
    return RECAP_PLAN_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_plan_act_prompt(language: str | None = None) -> str:
    return RECAP_PLAN_ACT_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_match_prompt(language: str | None = None) -> str:
    return RECAP_MATCH_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_vo_draft_prompt(language: str | None = None) -> str:
    return RECAP_VO_DRAFT_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_caption_prompt(language: str | None = None) -> str:
    return RECAP_CAPTION_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_polish_prompt(language: str | None = None) -> str:
    return RECAP_POLISH_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_plan_head_prompt(language: str | None = None) -> str:
    return RECAP_PLAN_HEAD_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_plan_tail_prompt(language: str | None = None) -> str:
    return RECAP_PLAN_TAIL_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_plan_gap_prompt(language: str | None = None) -> str:
    return RECAP_PLAN_GAP_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def default_recap_gap_prompt(language: str | None = None) -> str:
    return RECAP_GAP_LANGUAGE_PROMPTS[normalize_caption_language(language)]


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


def recap_target_sec(duration_sec: float) -> float:
    """Scale recap length to the story window, clamped to about 3–8 minutes."""
    _start, story_end = recap_story_window(duration_sec)
    raw = max(0.0, float(story_end or 0.0)) * RECAP_STORY_RATIO
    return round(min(MAX_RECAP_SEC, max(MIN_RECAP_SEC, raw or TARGET_RECAP_SEC)), 1)


def recap_duration_bounds(target_sec: float) -> tuple[float, float]:
    """Soft floor + hard ceiling. Floor is advisory; we never pad cuts just to hit it."""
    target = max(MIN_RECAP_SEC, float(target_sec or TARGET_RECAP_SEC))
    return (
        round(max(90.0, target * 0.5), 1),
        round(min(MAX_RECAP_SEC, max(target, target * 1.15)), 1),
    )


def format_recap_clock(sec: float) -> str:
    total = max(0.0, float(sec or 0.0))
    minutes = int(total // 60)
    seconds = int(round(total - minutes * 60.0))
    if seconds >= 60:
        minutes += 1
        seconds = 0
    return f"{minutes:02d}:{seconds:02d}"


def format_recap_clock_range(start: float, end: float) -> str:
    return f"{format_recap_clock(start)}–{format_recap_clock(end)}"


def group_recap_vo_units(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group flat clips into narration units: one parent VO covering child shots.

    A unit starts at each clip that owns VO, or at the first empty clip after the
    previous unit. Following empty same-beat shots stay as children until the next
    VO-bearing clip (or beat change).
    """
    items = [dict(clip) for clip in clips or [] if isinstance(clip, Mapping)]
    by_id = _beats_by_id(beats)
    units: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        start = index
        head = items[start]
        vo = str(head.get("vo") or "").strip()
        beat_id = head.get("beat_id")
        end = start
        cursor = start + 1
        while cursor < len(items):
            nxt = items[cursor]
            nxt_vo = str(nxt.get("vo") or "").strip()
            if nxt_vo:
                break
            nxt_beat = nxt.get("beat_id")
            if beat_id is not None and nxt_beat is not None and nxt_beat != beat_id:
                break
            end = cursor
            cursor += 1
        indices = list(range(start, end + 1))
        shots: list[dict[str, Any]] = []
        picture = 0.0
        src_lo = float(items[start].get("src_in") or 0.0)
        src_hi = float(items[start].get("src_out") or src_lo)
        tl_lo = float(items[start].get("tl_in") or 0.0)
        tl_hi = float(items[end].get("tl_out") or tl_lo)
        for offset, clip_i in enumerate(indices):
            clip = items[clip_i]
            role = _clip_role(clip) or ("insert" if _looks_like_insert_cut(clip) else "")
            if _is_bridge_clip(clip):
                role = "bridge"
            if role == "vo_hold":
                # Narration placeholder with no picture shot — keep unit, hide from children.
                continue
            src_in = float(clip.get("src_in") or 0.0)
            src_out = float(clip.get("src_out") or src_in)
            tl_in = float(clip.get("tl_in") or 0.0)
            tl_out = float(clip.get("tl_out") or tl_in)
            span = max(0.0, tl_out - tl_in)
            if span <= 0.04 and clip.get("duration") is not None:
                span = max(0.0, float(clip.get("duration") or 0.0))
            picture += span
            src_lo = min(src_lo, src_in)
            src_hi = max(src_hi, src_out)
            shots.append(
                {
                    "offset": offset,
                    "clip_index": clip_i,
                    "name": str(clip.get("name") or f"{clip_i + 1:02d}"),
                    "role": role,
                    "src_in": round(src_in, 3),
                    "src_out": round(src_out, 3),
                    "tl_in": round(tl_in, 3),
                    "tl_out": round(tl_out, 3),
                    "picture_sec": round(span, 3),
                }
            )
        # Re-number shot offsets so UI delete/reorder match visible children.
        for shot_i, shot in enumerate(shots):
            shot["offset"] = shot_i
        try:
            beat_int = int(beat_id) if beat_id is not None else 0
        except (TypeError, ValueError):
            beat_int = 0
        beat = by_id.get(beat_int) or {}
        speak = vo_sec(vo) if vo else 0.0
        units.append(
            {
                "unit_index": len(units),
                "clip_indices": indices,
                "start_index": start,
                "end_index": end,
                "vo": vo,
                "beat_id": beat_int or None,
                "event": str(head.get("event") or beat.get("event") or "").strip(),
                "picture_sec": round(picture, 3),
                "speak_sec": round(speak, 3),
                "cover_sec": round(max(speak, 0.0), 3),
                "src_in": round(src_lo, 3),
                "src_out": round(src_hi, 3),
                "tl_in": round(tl_lo, 3),
                "tl_out": round(tl_hi, 3),
                "shots": shots,
                "shortfall_sec": round(max(0.0, speak - picture), 3),
            }
        )
        index = end + 1
    return units


def _write_recap_clips_payload(
    media: str,
    payload: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
    *,
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    info = {
        "fps": float(payload.get("fps") or 24.0),
        "width": int(payload.get("width") or 1920),
        "height": int(payload.get("height") or 1080),
    }
    laid = layout_clips_on_timeline(list(clips), fps=float(info["fps"]))
    dest = recap_cuts_path_for_video(media)
    cuts_path = write_recap_cuts_file(
        dest,
        title=str(payload.get("title") or ""),
        video_path=media,
        video_id=str(payload.get("video_id") or ""),
        info=info,
        laid_out=laid,
        beats_path=str(payload.get("beats_path") or ""),
        stage=str(payload.get("stage") or "captions"),
    )
    srt_path = ""
    if rewrite_srt:
        stem = Path(os.path.abspath(os.path.expanduser(media))).stem
        srt_dest = Path(os.path.abspath(os.path.expanduser(media))).parent / f"{stem}_recap.srt"
        srt_path = str(write_srt(laid, srt_dest))
    return {
        "ok": True,
        "cuts_path": str(cuts_path),
        "srt_path": srt_path,
        "clips": laid,
        "units": group_recap_vo_units(laid),
    }


def save_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    text: str,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Hand-edit one narration unit: VO on first shot, clear children, stamp cover time."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    body = str(text or "").strip()
    speak = _max_picture_for_vo(body) if body else 0.0
    first = indices[0]
    last = indices[-1]
    for pos in indices:
        row = dict(clips[pos])
        if pos == first:
            row["vo"] = body
            row["vo_draft"] = body
        else:
            row["vo"] = ""
            if "vo_draft" in row:
                row["vo_draft"] = ""
            row.pop("vo_tl_in", None)
            row.pop("vo_tl_out", None)
        clips[pos] = row
    head = clips[first]
    tl_in = float(head.get("tl_in") or 0.0)
    unit_out = float(clips[last].get("tl_out") or tl_in)
    if body and speak > 0:
        vo_end = min(unit_out, tl_in + max(speak, 0.5))
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        else:
            head.pop("vo_tl_in", None)
            head.pop("vo_tl_out", None)
    else:
        head.pop("vo_tl_in", None)
        head.pop("vo_tl_out", None)
    clips[first] = head
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["start_index"] = first
    result["end_index"] = last
    result["vo"] = body
    result["speak_sec"] = round(vo_sec(body) if body else 0.0, 3)
    return result


def reorder_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    from_offset: int,
    to_offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Move one child shot inside its narration unit, then re-layout timeline."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if len(indices) < 2:
        raise RuntimeError("至少两个子镜头才能调序。")
    if from_offset < 0 or to_offset < 0 or from_offset >= len(indices) or to_offset >= len(indices):
        raise RuntimeError("子镜头位置无效。")
    if from_offset == to_offset:
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    block = [clips[i] for i in indices]
    item = block.pop(from_offset)
    block.insert(to_offset, item)
    # Keep unit VO on the chronologically first slot after reorder.
    voiced = [str(row.get("vo") or "").strip() for row in block]
    unit_vo = next((text for text in voiced if text), "")
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        clips[indices[offset]] = next_row
    if unit_vo:
        head = clips[indices[0]]
        tl_in = float(head.get("tl_in") or 0.0)
        last = clips[indices[-1]]
        unit_out = float(last.get("tl_out") or tl_in)
        speak = _max_picture_for_vo(unit_vo)
        vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        clips[indices[0]] = head
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)


def owned_chunk_indices_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    overlap_ratio: float = 0.45,
) -> set[int]:
    """Chunks covered by the given clips (by chunk_index or time overlap)."""
    return set(
        classify_chunk_usage_for_clips(
            chunks,
            unit_clips=clips,
            all_clips=clips,
            overlap_ratio=overlap_ratio,
        )
    )


def classify_chunk_usage_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    *,
    unit_clips: Sequence[Mapping[str, Any]] | None = None,
    all_clips: Sequence[Mapping[str, Any]] | None = None,
    overlap_ratio: float = 0.45,
) -> dict[int, str]:
    """Map chunk index -> ``unit`` | ``used`` for picker coloring.

    - ``unit``: already in the current narration unit
    - ``used``: used by some other shot in the full cut list (not in the unit)
    """

    def _covered(shots: Sequence[Mapping[str, Any]] | None) -> set[int]:
        owned: set[int] = set()
        rows = [dict(row) for row in chunks or [] if isinstance(row, Mapping)]
        items = [dict(row) for row in shots or [] if isinstance(row, Mapping)]
        if not rows or not items:
            return owned
        for index, chunk in enumerate(rows):
            try:
                c0 = float(chunk.get("start") or chunk.get("src_in") or 0.0)
                c1 = float(chunk.get("end") or chunk.get("src_out") or c0)
            except (TypeError, ValueError):
                continue
            if c1 <= c0 + 0.04:
                continue
            span = max(0.001, c1 - c0)
            for shot in items:
                try:
                    if int(shot.get("chunk_index")) == index:
                        owned.add(index)
                        break
                except (TypeError, ValueError):
                    pass
                try:
                    s0 = float(shot.get("src_in") or 0.0)
                    s1 = float(shot.get("src_out") or s0)
                except (TypeError, ValueError):
                    continue
                overlap = max(0.0, min(c1, s1) - max(c0, s0))
                if overlap >= max(0.5, span * float(overlap_ratio)):
                    owned.add(index)
                    break
        return owned

    unit_set = _covered(unit_clips)
    all_set = _covered(all_clips if all_clips is not None else unit_clips)
    usage: dict[int, str] = {}
    for index in sorted(all_set | unit_set):
        if index in unit_set:
            usage[index] = "unit"
        else:
            usage[index] = "used"
    return usage


def add_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    src_in: float,
    src_out: float,
    after_offset: int | None = None,
    name: str = "",
    chunk_index: int | None = None,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Insert a child shot into a narration unit (no LLM)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    start = float(src_in)
    end = float(src_out)
    if end <= start + 0.04:
        raise RuntimeError("原片入点/出点无效。")
    anchor = clips[indices[0]]
    # VO-only placeholder: replace with the first real shot, keep narration text.
    if len(indices) == 1 and _clip_role(anchor) == "vo_hold":
        hold_vo = str(anchor.get("vo") or "").strip()
        replacement = {
            "name": str(name or "").strip() or str(anchor.get("name") or f"{len(clips):02d}"),
            "beat_id": anchor.get("beat_id"),
            "src_in": round(start, 3),
            "src_out": round(end, 3),
            "duration": round(end - start, 3),
            "vo": hold_vo,
            "vo_draft": hold_vo,
            "role": "",
            "reason": str(anchor.get("reason") or ""),
            "event": str(anchor.get("event") or ""),
        }
        if chunk_index is not None:
            try:
                replacement["chunk_index"] = int(chunk_index)
            except (TypeError, ValueError):
                pass
        clips[indices[0]] = replacement
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    insert_at = indices[-1] + 1
    if after_offset is not None and 0 <= int(after_offset) < len(indices):
        insert_at = indices[int(after_offset)] + 1
    new_clip = {
        "name": str(name or "").strip() or f"{len(clips) + 1:02d}",
        "beat_id": anchor.get("beat_id"),
        "src_in": round(start, 3),
        "src_out": round(end, 3),
        "duration": round(end - start, 3),
        "vo": "",
        "role": str(anchor.get("role") or ""),
        "reason": str(anchor.get("reason") or ""),
        "event": str(anchor.get("event") or ""),
    }
    if chunk_index is not None:
        try:
            new_clip["chunk_index"] = int(chunk_index)
        except (TypeError, ValueError):
            pass
    clips.insert(insert_at, new_clip)
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)


def _unit_vo_text(block: Sequence[Mapping[str, Any]]) -> str:
    for row in block:
        text = str(row.get("vo") or "").strip()
        if text:
            return text
    return ""


def _stamp_unit_vo_on_block(block: list[dict[str, Any]], unit_vo: str) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
            if unit_vo:
                tl_in = float(next_row.get("tl_in") or 0.0)
                last = block[-1]
                unit_out = float(last.get("tl_out") or next_row.get("tl_out") or tl_in)
                speak = _max_picture_for_vo(unit_vo)
                vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
                if vo_end > tl_in + 0.04:
                    next_row["vo_tl_in"] = round(tl_in, 3)
                    next_row["vo_tl_out"] = round(vo_end, 3)
                else:
                    next_row.pop("vo_tl_in", None)
                    next_row.pop("vo_tl_out", None)
            else:
                next_row.pop("vo_tl_in", None)
                next_row.pop("vo_tl_out", None)
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        stamped.append(next_row)
    return stamped


def delete_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove one child shot. Last picture shot may leave a VO-only hold clip."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    # Visible shots skip vo_hold; map UI offset → real clip index.
    picture_indices = [
        i for i in indices if _clip_role(clips[i]) != "vo_hold"
    ] if indices and max(indices) < len(clips) else []
    if offset < 0 or offset >= len(picture_indices):
        raise RuntimeError("子镜头位置无效。")
    remove_at = int(picture_indices[offset])
    block = [clips[i] for i in indices]
    unit_vo = _unit_vo_text(block)
    event = str(block[0].get("event") or "").strip()
    beat_id = block[0].get("beat_id")
    removed = dict(clips[remove_at])
    del clips[remove_at]

    remaining_picture = len(picture_indices) - 1
    if remaining_picture <= 0:
        if not unit_vo:
            # No VO and no shots left — drop the unit entirely.
            return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
        speak = max(0.5, float(_max_picture_for_vo(unit_vo) or 0.5))
        src_in = float(removed.get("src_in") or 0.0)
        hold = {
            "name": str(removed.get("name") or "vo"),
            "beat_id": beat_id,
            "src_in": round(src_in, 3),
            "src_out": round(src_in + speak, 3),
            "duration": round(speak, 3),
            "vo": unit_vo,
            "vo_draft": unit_vo,
            "role": "vo_hold",
            "event": event,
            "reason": str(removed.get("reason") or ""),
        }
        clips.insert(remove_at, hold)
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)

    # Rebuild remaining unit block after the deletion (indices shift past remove_at).
    new_indices: list[int] = []
    for old in indices:
        if old == remove_at:
            continue
        new_indices.append(old - 1 if old > remove_at else old)
    remaining = [clips[i] for i in new_indices]
    stamped = _stamp_unit_vo_on_block(remaining, unit_vo)
    for idx, row in zip(new_indices, stamped):
        clips[idx] = row
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_offset"] = int(offset)
    result["vo_hold"] = False
    return result


def delete_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove a whole narration unit (VO + all child shots)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    for index in reversed(indices):
        del clips[index]
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_unit_clips"] = len(indices)
    return result


def recap_clip_review_rows(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Readonly review rows for the understanding-page QC table (not an NLE)."""
    by_id = _beats_by_id(beats)
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(clips or []):
        if not isinstance(clip, Mapping):
            continue
        tl_in = float(clip.get("tl_in") or 0.0)
        tl_out = float(clip.get("tl_out") or 0.0)
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
        picture = max(0.0, tl_out - tl_in)
        if picture <= 0.04 and clip.get("duration") is not None:
            picture = max(0.0, float(clip.get("duration") or 0.0))
        text = str(clip.get("vo") or "").strip()
        speak = vo_sec(text) if text else 0.0
        fill = (speak / picture) if picture > 0.08 else 0.0
        try:
            beat_id = int(clip.get("beat_id"))
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) or {}
        event = str(clip.get("event") or beat.get("event") or "").strip()
        flags: list[str] = []
        if _looks_like_insert_cut(clip):
            flags.append("insert")
        if _is_bridge_clip(clip):
            flags.append("bridge")
        if not text:
            if "bridge" not in flags:
                flags.append("empty_vo")
        elif _vo_underfills_picture(text, picture):
            flags.append("underfill")
        if is_weak_match_clip(clip):
            flags.append("weak_match")
        support = clip.get("evidence_support")
        if not isinstance(support, Mapping):
            support = {}
        evidence_flags: list[str] = []
        if support.get("asr"):
            evidence_flags.append("asr")
        if support.get("vlm"):
            evidence_flags.append("vlm")
        if support.get("character"):
            evidence_flags.append("character")
        if is_weak_match_clip(clip) and "vlm" not in evidence_flags and "asr" not in evidence_flags:
            evidence_flags.append("thin")
        rows.append(
            {
                "index": index,
                "name": str(clip.get("name") or f"{index + 1:02d}"),
                "tl_in": round(tl_in, 3),
                "tl_out": round(tl_out, 3),
                "src_in": round(src_in, 3),
                "src_out": round(src_out, 3),
                "beat_id": beat_id or None,
                "event": event,
                "vo": text,
                "vo_owns_shot": bool(text),
                "fill_ratio": round(fill, 3),
                "flags": flags,
                "evidence_flags": evidence_flags,
                "match_status": str(clip.get("match_status") or MATCH_STATUS_OK),
                "match_score": clip.get("match_score"),
                "picture_sec": round(picture, 3),
                "reason": str(clip.get("reason") or "").strip(),
                "evidence_required": list(
                    beat.get("evidence_required") or clip.get("evidence_required") or []
                ),
            }
        )
    return rows


def parse_recap_clock(text: str) -> float:
    body = str(text or "").strip().replace("，", ".").replace("：", ":")
    if not body:
        return 0.0
    if ":" in body:
        parts = [part.strip() for part in body.split(":")]
        if len(parts) == 2:
            return max(0.0, float(parts[0] or 0.0) * 60.0 + float(parts[1] or 0.0))
        if len(parts) == 3:
            return max(
                0.0,
                float(parts[0] or 0.0) * 3600.0
                + float(parts[1] or 0.0) * 60.0
                + float(parts[2] or 0.0),
            )
    return max(0.0, float(body))


def recap_speaker_stats(cues: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    blank = 0
    auto = 0
    named = 0
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()
        if not label:
            blank += 1
        elif is_auto_speaker_label(label):
            auto += 1
        else:
            named += 1
    unnamed = blank + auto
    return {
        "blank": blank,
        "auto": auto,
        "named": named,
        "unnamed": unnamed,
        "needs_naming": unnamed > 0,
    }


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
    from src.services.understanding_tags import format_motion_cap_text, parse_motion_vlm_payload

    chunks = []
    for raw in evidence.get("chunks") or []:
        if not isinstance(raw, Mapping):
            continue
        caption = ""
        visible = ""
        change = ""
        inferred = ""
        inferred_weight = 0.0
        vision = ((raw.get("evidence") or {}).get("vision") or {})
        image = vision.get("image_caption") or {}
        if isinstance(image, Mapping):
            visible = str(image.get("visible") or "").strip()
            change = str(image.get("change") or "").strip()
            inferred = str(image.get("inferred") or "").strip()
            try:
                inferred_weight = float(image.get("inferred_weight") or 0.0)
            except (TypeError, ValueError):
                inferred_weight = 0.0
            caption = format_motion_cap_text(visible, change)
            parsed_tags: list[str] = []
            if not caption or (not visible and not change) or not image.get("tags"):
                parsed = parse_motion_vlm_payload(str(image.get("text") or image.get("raw_text") or ""))
                visible = visible or str(parsed.get("visible") or "").strip()
                change = change or str(parsed.get("change") or "").strip()
                if not inferred:
                    inferred = str(parsed.get("inferred") or "").strip()
                    try:
                        inferred_weight = float(parsed.get("inferred_weight") or 0.0)
                    except (TypeError, ValueError):
                        inferred_weight = 0.0
                parsed_tags = [str(t).strip() for t in (parsed.get("tags") or []) if str(t).strip()]
                caption = format_motion_cap_text(visible, change) or _caption_one_liner(
                    str(image.get("text") or ""), limit=160
                )
            tags = [
                str(t).strip()
                for t in (image.get("tags") or parsed_tags or raw.get("tags") or [])
                if str(t).strip()
            ]
        else:
            tags = [str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()]
        tags = [t for t in tags if len(t) <= 12][:8]
        skip = "op_ed" if looks_like_op_ed_text(caption, " ".join(tags), inferred) else ""
        row = {
            "i": int(raw.get("chunk_index", 0) or 0),
            "t": [round(float(raw.get("start_sec", 0.0) or 0.0), 2), round(float(raw.get("end_sec", 0.0) or 0.0), 2)],
            "dur": round(max(0.0, float(raw.get("end_sec", 0.0) or 0.0) - float(raw.get("start_sec", 0.0) or 0.0)), 2),
            "tags": tags,
            "cap": caption,
            "skip": skip,
        }
        if visible:
            row["visible"] = visible[:120]
        if change:
            row["change"] = change[:120]
        if inferred:
            row["inferred"] = inferred[:80]
            row["inferred_weight"] = round(min(1.0, max(0.0, inferred_weight)), 3)
        chunks.append(row)
    return chunks


def compact_index_chunks(raw_chunks: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_chunks or []):
        if not isinstance(raw, Mapping):
            continue
        try:
            start = float(raw.get("start", raw.get("start_sec", 0.0)) or 0.0)
            end = float(raw.get("end", raw.get("end_sec", start)) or start)
        except (TypeError, ValueError):
            continue
        if end < start:
            start, end = end, start
        try:
            chunk_i = int(raw.get("i", raw.get("chunk_index", index)))
        except (TypeError, ValueError):
            chunk_i = index
        out.append(
            {
                "i": chunk_i,
                "t": [round(start, 2), round(end, 2)],
                "dur": round(max(0.0, end - start), 2),
                "tags": [],
                "cap": "",
                "skip": "",
            }
        )
    return out


def overlay_motion_captions(
    chunks: Sequence[Mapping[str, Any]],
    motion_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_i: dict[int, Mapping[str, Any]] = {}
    for row in motion_rows or []:
        try:
            by_i[int(row.get("i"))] = row
        except (TypeError, ValueError):
            continue
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in chunks or []:
        item = dict(row)
        try:
            chunk_i = int(item.get("i"))
        except (TypeError, ValueError):
            chunk_i = None
        extra = by_i.get(chunk_i) if chunk_i is not None else None
        if extra:
            if str(extra.get("cap") or "").strip():
                item["cap"] = extra.get("cap") or ""
            if extra.get("tags"):
                item["tags"] = list(extra.get("tags") or [])
            for key in ("visible", "change", "inferred"):
                if str(extra.get(key) or "").strip():
                    item[key] = str(extra.get(key) or "").strip()
            if extra.get("inferred_weight") is not None:
                try:
                    item["inferred_weight"] = float(extra.get("inferred_weight") or 0.0)
                except (TypeError, ValueError):
                    pass
            if str(extra.get("skip") or "").strip():
                item["skip"] = str(extra.get("skip") or "").strip()
        if chunk_i is not None:
            seen.add(chunk_i)
        out.append(item)
    for extra in motion_rows or []:
        try:
            chunk_i = int(extra.get("i"))
        except (TypeError, ValueError):
            continue
        if chunk_i in seen:
            continue
        out.append(dict(extra))
    out.sort(key=lambda row: (float((row.get("t") or [0.0])[0] or 0.0), int(row.get("i") or 0)))
    return out


def apply_recap_skip_marks(
    chunks: Sequence[Mapping[str, Any]],
    asr: Sequence[Mapping[str, Any]] | None,
    duration_sec: float,
) -> list[dict[str, Any]]:
    cues = list(asr or [])
    _start, story_end = recap_story_window(duration_sec)
    out: list[dict[str, Any]] = []
    for row in chunks or []:
        item = dict(row)
        if str(item.get("skip") or "").strip():
            out.append(item)
            continue
        span = _time_span(item.get("t"))
        if not span:
            out.append(item)
            continue
        lo, _hi = span
        if float(duration_sec or 0.0) >= 360 and lo >= story_end:
            item["skip"] = "op_ed"
            out.append(item)
            continue
        blob = " ".join(
            str(cue.get("text") or "")
            for cue in cues
            if _overlap_sec(
                (float(cue.get("start") or 0.0), float(cue.get("end") or cue.get("start") or 0.0)),
                span,
            )
            > 0.35
        )
        if looks_like_op_ed_text(blob):
            item["skip"] = "op_ed"
        out.append(item)
    return out


RECAP_VISUAL_EVIDENCE_TAGS = frozenset({"动作", "反应", "物品", "变化", "场面"})
RECAP_CLIMAX_IMPORTANCE = 0.85


def _cue_span(cue: Mapping[str, Any]) -> tuple[float, float] | None:
    if "start" in cue or "end" in cue:
        try:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") if cue.get("end") is not None else start)
        except (TypeError, ValueError):
            return None
        if end < start:
            start, end = end, start
        return start, end
    return _time_span(cue.get("t"))


def _beat_evidence_tags(beat: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    for raw in beat.get("evidence_required") or []:
        text = str(raw or "").strip()
        if text:
            tags.add(text)
    return tags


def _beat_needs_visual_motion(beat: Mapping[str, Any]) -> bool:
    """Unknown requirements still get a caption. Dialogue-only beats can skip."""
    tags = _beat_evidence_tags(beat)
    if not tags:
        return True
    return bool(tags & RECAP_VISUAL_EVIDENCE_TAGS)


def _asr_covers_span(
    span: tuple[float, float],
    cues: Sequence[Mapping[str, Any]] | None,
) -> bool:
    duration = max(0.0, float(span[1]) - float(span[0]))
    if duration <= 0.0:
        return False
    covered = 0.0
    for cue in cues or []:
        cue_span = _cue_span(cue)
        if cue_span:
            covered += _overlap_sec(span, cue_span)
    need = min(8.0, max(2.0, duration * 0.25))
    return covered >= need


def _chunk_motion_beats(
    chunk: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    pad_sec: float,
) -> list[Mapping[str, Any]]:
    span = _time_span(chunk.get("t"))
    if not span:
        return []
    matched: list[Mapping[str, Any]] = []
    for beat in beats or []:
        beat_span = _time_span(beat.get("t"))
        if not beat_span:
            continue
        window = (beat_span[0] - pad_sec, beat_span[1] + pad_sec)
        if _overlap_sec(span, window) > 0.4:
            matched.append(beat)
    return matched


def recap_motion_gap_chunk_indices(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    pad_sec: float = 24.0,
) -> list[int]:
    """Chunks in beat windows that still need a VLM caption.

    Dialogue coverage does **not** skip motion: picture must still match the VO,
    and ASR-only planning otherwise leaves Match guessing empty caps.
    """
    pad = max(0.0, float(pad_sec or 0.0))
    windows = []
    for beat in beats or []:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        windows.append((span[0] - pad, span[1] + pad))
    if not windows:
        return []
    indices: list[int] = []
    for chunk in pack.get("chunks") or []:
        if str(chunk.get("skip") or "").strip() or str(chunk.get("cap") or "").strip():
            continue
        span = _time_span(chunk.get("t"))
        if not span:
            continue
        if not any(_overlap_sec(span, window) > 0.4 for window in windows):
            continue
        try:
            indices.append(int(chunk.get("i")))
        except (TypeError, ValueError):
            continue
    return indices


def recap_motion_dense_chunk_indices(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    gap_indices: Sequence[int],
    *,
    pad_sec: float = 24.0,
) -> list[int]:
    """Climax beats that still need a picture get a 4-frame grid in one call."""
    wanted = {int(index) for index in gap_indices}
    if not wanted:
        return []
    pad = max(0.0, float(pad_sec or 0.0))
    dense: list[int] = []
    for chunk in pack.get("chunks") or []:
        try:
            index = int(chunk.get("i"))
        except (TypeError, ValueError):
            continue
        if index not in wanted:
            continue
        if any(
            _beat_needs_visual_motion(beat)
            and float(beat.get("importance") or 0.0) >= RECAP_CLIMAX_IMPORTANCE
            for beat in _chunk_motion_beats(chunk, beats, pad_sec=pad)
        ):
            dense.append(index)
    return dense


def fill_recap_motion_for_beats(
    video_id: str,
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    config=None,
    should_stop_callback: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    chunk_completed_callback: Callable[..., None] | None = None,
) -> tuple[dict[str, Any], list[str], int]:
    """VLM every beat-window chunk that still lacks a motion caption.

    Climax windows use a four-frame grid in one call. Dialogue coverage alone
    never skips motion — empty caps make Match/VO picture-blind.
    """
    indices = recap_motion_gap_chunk_indices(pack, beats)
    if not indices:
        return dict(pack), [], 0
    dense = recap_motion_dense_chunk_indices(pack, beats, indices)
    from src.core.understanding.base import UnderstandingStoppedError
    from src.services.understanding_service import generate_evidence_for_video

    wanted = set()
    for raw in indices:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    done = {"n": 0}

    def _on_chunk(chunk_index, _total, _payload) -> None:
        try:
            index = int(chunk_index)
        except (TypeError, ValueError):
            return
        if index not in wanted:
            return
        done["n"] += 1
        if on_progress:
            on_progress(done["n"], len(indices))
        if chunk_completed_callback:
            chunk_completed_callback(index, len(indices), _payload)

    if on_progress:
        on_progress(0, len(indices))
    try:
        generate_evidence_for_video(
            video_id,
            config=config,
            mode=UNDERSTANDING_MODE_MOTION,
            chunk_indices=indices,
            dense_chunk_indices=dense,
            should_stop_callback=should_stop_callback,
            chunk_completed_callback=_on_chunk,
        )
    except UnderstandingStoppedError:
        raise
    except Exception:
        return dict(pack), ["recap_warn_motion_gaps"], done["n"]
    refreshed = build_recap_pack(video_id, config=config)
    if pack.get("people"):
        refreshed["people"] = list(pack.get("people") or [])
    leftover = recap_motion_gap_chunk_indices(refreshed, beats)
    filled = max(0, len(indices) - len(leftover))
    return refreshed, [], filled


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


def split_story_into_plan_acts(
    pack: Mapping[str, Any],
    *,
    target_sec: float = PLAN_ACT_TARGET_SEC,
) -> list[tuple[float, float]]:
    """Split the story window into ~7-minute acts, preferring ASR silence as cuts."""
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    width = max(0.0, story_end - story_start)
    goal = max(180.0, float(target_sec or PLAN_ACT_TARGET_SEC))
    if width <= goal * 1.25:
        return [(story_start, story_end)] if width > 1.0 else []

    cues = sorted(
        (
            (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
            for row in (pack.get("ocr") or [])
            if isinstance(row, Mapping)
        ),
        key=lambda item: item[0],
    )
    cuts: list[float] = [story_start]
    cursor = story_start
    silence_need = 18.0
    for start, end in cues:
        if start < story_start or end > story_end + 1.0:
            continue
        if start - cursor >= silence_need and (start - story_start) - (cuts[-1] - story_start) >= goal * 0.55:
            if start - cuts[-1] >= goal * 0.55:
                cuts.append(start)
                cursor = end
                continue
        cursor = max(cursor, end)
    cuts.append(story_end)

    # Merge undersized tails / inflate evenly if ASR gave too few cuts.
    merged: list[tuple[float, float]] = []
    for index in range(len(cuts) - 1):
        lo, hi = cuts[index], cuts[index + 1]
        if hi - lo < 60.0 and merged:
            prev_lo, _prev_hi = merged[-1]
            merged[-1] = (prev_lo, hi)
        else:
            merged.append((lo, hi))
    if len(merged) <= 1:
        n = max(2, int(round(width / goal)))
        step = width / float(n)
        return [
            (
                story_start + index * step,
                story_end if index == n - 1 else story_start + (index + 1) * step,
            )
            for index in range(n)
        ]
    # Cap act length by splitting oversize windows evenly.
    out: list[tuple[float, float]] = []
    for lo, hi in merged:
        span = hi - lo
        if span <= goal * 1.35:
            out.append((lo, hi))
            continue
        pieces = max(2, int(round(span / goal)))
        step = span / float(pieces)
        for index in range(pieces):
            a = lo + index * step
            b = hi if index == pieces - 1 else lo + (index + 1) * step
            out.append((a, b))
    return out


def clamp_beats_to_act_window(
    beats: Sequence[Mapping[str, Any]],
    window: tuple[float, float],
    *,
    pad_sec: float = 8.0,
) -> list[dict[str, Any]]:
    lo = float(window[0]) - float(pad_sec)
    hi = float(window[1]) + float(pad_sec)
    out: list[dict[str, Any]] = []
    for beat in beats or []:
        row = dict(beat)
        span = _time_span(row.get("t"))
        if not span:
            continue
        if span[1] < lo or span[0] > hi:
            continue
        trimmed = (max(span[0], float(window[0])), min(span[1], float(window[1])))
        if trimmed[1] - trimmed[0] < 1.0:
            mid = 0.5 * (float(window[0]) + float(window[1]))
            trimmed = (max(float(window[0]), mid - 4.0), min(float(window[1]), mid + 4.0))
        if trimmed[1] <= trimmed[0]:
            continue
        row["t"] = [round(trimmed[0], 2), round(trimmed[1], 2)]
        out.append(row)
    return out


def scrub_unevidenced_beats(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any] | None,
    *,
    pad_sec: float = 14.0,
) -> list[dict[str, Any]]:
    """Drop invented plot beats whose time window has no asr and no caps."""
    items = [dict(beat) for beat in beats or []]
    if not items or pack is None:
        return items
    kept: list[dict[str, Any]] = []
    for beat in items:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        evidence = _evidence_for_source_span(
            pack,
            span[0],
            span[1],
            pad_sec=pad_sec,
            asr_limit=24,
            cap_limit=12,
        )
        has_asr = bool(evidence.get("asr"))
        has_caps = bool(evidence.get("caps"))
        if has_asr or has_caps:
            kept.append(beat)
            continue
        # Empty window = wrong t or pure hallucination. Keep only soft texture/bridge.
        try:
            importance = float(beat.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        if importance >= 0.45:
            continue
        if _is_texture_beat(beat) or _looks_like_scene_shift_text(beat.get("event")):
            # Still drop — no picture/dialogue to land on.
            continue
    if not kept:
        return items
    return kept


def recap_plan_act_user_prompt(
    pack: Mapping[str, Any],
    *,
    already: Sequence[Mapping[str, Any]] | None = None,
    act_index: int = 0,
    act_count: int = 1,
    window: tuple[float, float] | None = None,
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    if window is None:
        spans = [
            span
            for span in (
                _time_span(item.get("t"))
                for item in (pack.get("chunks") or [])
            )
            if span
        ]
        if spans:
            window = (min(s[0] for s in spans), max(s[1] for s in spans))
        else:
            window = (0.0, duration)
    lo, hi = float(window[0]), float(window[1])
    seeded = list(pack.get("people") or [])
    prior = [dict(item) for item in (already or [])][-6:]
    return (
        f"这是第 {act_index + 1}/{max(1, act_count)} 幕。只规划本幕 [{lo:.0f},{hi:.0f}] 秒内的故事线。\n"
        f"本幕 asr 已按时间窗灌满，是唯一叙事骨架；禁止用别幕台词或常识补因果。\n"
        "本幕通常 3–8 条有证据的 beats；宁少勿编。进入→展开→本幕落点"
        + ("（可接到下一幕的转场）" if act_index + 1 < act_count else "（正片收束，勿写 ED）")
        + "。\n"
        "already 是上一幕已写事实，承接不要重复、不要推翻。\n"
        "event：谁做了什么、局面怎么变；禁止「XX说/觉得」；禁止男主/女主。\n"
        "每条 t 必须落在本幕时间窗内；带 evidence_required 与 needed_visual。\n"
        "asr[].speaker 非空=谁在说。有 cap 才写看见的变化，否则写 needed_visual。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "act": {"index": act_index + 1, "count": act_count, "t": [round(lo, 2), round(hi, 2)]},
                "already": prior,
                "people": seeded,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def plan_story_beats_by_acts(
    pack: Mapping[str, Any],
    *,
    video_id: str,
    config=None,
    language: str | None = None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Plan beats act-by-act with dense local ASR so the model cannot invent mid-episode plot."""
    cfg = config if config is not None else load_config()
    acts = split_story_into_plan_acts(pack)
    warnings: list[str] = []
    if not acts:
        return "", [], list(pack.get("people") or []), ["recap_warn_plan_acts_empty"]

    def _progress(pct: int, stage: str, extra: Mapping[str, Any] | None = None) -> None:
        if progress_callback is None:
            return
        payload = {"stage": stage}
        if extra:
            payload.update(dict(extra))
        try:
            progress_callback(int(pct), payload)
        except TypeError:
            progress_callback(int(pct), stage)

    people = normalize_story_people(pack.get("people"))
    already: list[dict[str, Any]] = []
    title = ""
    act_system = resolve_recap_prompt(system_prompt, default_recap_plan_act_prompt(language))
    for index, window in enumerate(acts):
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")
        pct = 12 + int(round(20.0 * float(index) / float(max(len(acts), 1))))
        _progress(min(32, pct), "planning", {"act": index + 1, "acts": len(acts)})
        act_pack = filter_pack_to_span(pack, window[0], window[1], pad_sec=4.0)
        dense = compact_ocr_cues_in_span(
            video_id,
            window[0],
            window[1],
            config=cfg,
            limit=PLAN_ACT_ASR_LIMIT,
        )
        if dense:
            act_pack["ocr"] = dense
        if people and not act_pack.get("people"):
            act_pack["people"] = list(people)
        parsed = _try_story_plan_llm(
            system=act_system,
            user=recap_plan_act_user_prompt(
                act_pack,
                already=already,
                act_index=index,
                act_count=len(acts),
                window=window,
            ),
            config=cfg,
            should_stop_callback=should_stop_callback,
            temperature=0.25,
            max_tokens=4096,
        )
        if parsed is None:
            warnings.append("recap_warn_plan_act")
            continue
        act_title, act_beats, act_people = parsed
        if act_title and act_title.strip() and act_title.strip() != "解说剪辑":
            title = act_title.strip()
        act_beats = clamp_beats_to_act_window(act_beats, window)
        act_beats = drop_op_ed_beats(act_beats, float(pack.get("duration_sec") or 0.0))
        people = merge_story_people(people, act_people)
        already = merge_story_beats(already, act_beats, allowed_windows=[window])

    already = scrub_unevidenced_beats(already, pack)
    if not already:
        warnings.append("recap_warn_plan_acts_empty")
    return title or "解说剪辑", already, people, warnings


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
    """Seed the recap people table from ASR speakers (named + clustered 声线)."""
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    named: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        entry = {
            "id": f"s{len(seen)}",
            "label": label,
            "look": "声纹聚类" if is_auto_speaker_label(label) else "对白说话人",
        }
        if is_auto_speaker_label(label):
            auto.append(entry)
        else:
            named.append(entry)
        if len(named) + len(auto) >= 16:
            break
    # Prefer real names first; keep 声线N so plan/VO can tell talkers apart.
    return [*named, *auto][:16]


def ensure_recap_dialogue_cues(cues: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = list(cues or [])
    if not items:
        raise RuntimeError(
            "没有语音对白。请先在理解页提取语音 ASR。"
        )
    return items


def build_recap_pack(video_id: str, *, config=None) -> dict[str, Any]:
    from src.services.indexing_service import load_video_chunks_by_id
    from src.services.understanding_service import (
        load_evidence_bundle,
        resolve_current_media_path,
        resolve_video_context,
    )

    cfg = config if config is not None else load_config()
    evidence = load_evidence_bundle(video_id, config=cfg, mode=UNDERSTANDING_MODE_MOTION) or {}
    video = dict(evidence.get("video") or {})
    duration = float(video.get("duration_sec") or 0.0)
    stored = str(video.get("video_path") or "")
    video_path = resolve_current_media_path(video_id, stored=stored, config=cfg)
    if not duration or not video_path:
        try:
            context = resolve_video_context(video_id, config=cfg, probe_duration=not duration)
        except Exception:
            context = {}
        if not video_path:
            video_path = str(context.get("video_path") or "")
        if not duration:
            duration = float(context.get("duration_sec") or 0.0)
    ocr = compact_ocr_cues(video_id, config=cfg, limit=RECAP_OCR_LIMIT)
    ensure_recap_dialogue_cues(ocr)
    index_rows = compact_index_chunks(load_video_chunks_by_id(video_id, cfg))
    motion_rows = compact_motion_chunks(evidence) if evidence else []
    if index_rows:
        chunks = overlay_motion_captions(index_rows, motion_rows)
    else:
        chunks = motion_rows
    if not chunks:
        raise RuntimeError("没有可用分段。请先索引该视频。")
    chunks = apply_recap_skip_marks(chunks, ocr, duration)
    return {
        "video_id": video_id,
        "video_path": video_path,
        "duration_sec": duration,
        "chunks": chunks,
        "ocr": ocr,
        "ocr_source": "asr",
        "people": people_from_dialogue_speakers(ocr),
    }


def recap_plan_user_prompt(pack: Mapping[str, Any]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _story_start, story_end = recap_story_window(duration)
    target = recap_target_sec(duration)
    seeded = list(pack.get("people") or [])
    name_line = (
        "people 已有稳定称呼（含用户命名与声线聚类）。event/口播主语必须跟 asr.speaker / people.label 走；"
        "声线N 可先当临时称呼，禁止另造发色外号顶替已有 label。\n"
        if seeded
        else "先列 people（稳定称呼），无人名再用画面特征。禁止男主/女主。\n"
    )
    return (
        f"原片时长 {duration:.0f} 秒。请规划有证据支撑的故事线大纲 beats（通常 8–20 条，最多 32），不要写 clips。\n"
        f"从 0 秒开始覆盖开场，正片在大约 {story_end:.0f} 秒结束（片尾曲之前）。\n"
        f"【证据优先】asr/cap 撑得住才写；禁止为凑条数虚构。禁止稀薄提纲、禁止大段无节拍空档。\n"
        f"自检：只读全部 event 必须能听成有头有尾的故事（进入→展开→高潮→收束）。相邻纲要必须递进或转场。成片目标约 {target:.0f} 秒（软上限；禁止删进入/收束/因果来凑时长）。\n"
        "进入新活动/新空间前必须有进入拍（赶到现场、入座开始、走进房间等）；禁止直接蹦到场内「某人惊讶了」或场内结果（全勾完了/结果出来了）。\n"
        "相邻场面或活动性质变了时，中间必须有进入/离开过渡 beat；禁止上一段刚结束下一句就直接写下一段场内结果。\n"
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


def recap_user_prompt(pack: Mapping[str, Any], beats: list[Mapping[str, Any]] | None = None) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    planned = list(beats or [])
    target = recap_target_sec(duration)
    return (
        f"原片时长 {duration:.0f} 秒。成片目标约 {target:.0f} 秒（按原片比例，约 3–8 分钟，作软上限：不要为凑分钟注水）。本段 beats 全部都要剪进去。\n"
        f"本段 beats 配额合计 {sum(float(item.get('budget_sec') or 0.0) for item in planned):.0f} 秒：每条 beat 的进入/推进/收束画面都要有；低权重可短，不可省略进入与落点；不要漏拍、不要注水。\n"
        "先按 beats 找证据画面：id、event、vo=已写好的解说稿、evidence_required、importance、budget_sec=这拍成片配额上限、shots=建议刀数、needed_visual、t=原片范围。\n"
        "【硬约束】每条 clip 的 src_in/src_out 必须落在该 beat.t 内（允许前后各约 10 秒）；禁止跨到别的 beat 时间去「借」画面。\n"
        "画面必须服务 beat.vo：优先选 cap 能证明这段旁白的 chunk；无 vo 时才退回按 event/evidence_required 选。"
        "无 cap 的 chunk 只能当时间兜底，reason 禁止瞎猜看见了什么；证据对不上就标弱证据，不要硬编。\n"
        "禁止改写 beat 事件或旁白去迁就画面。\n"
        "不要输出 vo 字段；正式旁白已在 beat.vo，铺字幕阶段只润色。\n"
        "同一 beat 的相邻镜头必须有新的视觉信息，不要用近似镜头重复同一事件，也不要把两刀粘成一条长镜头。\n"
        "shots>=2 时后几刀优先特写/反应，role=insert，不要为了赶时间并进主线。"
        "insert 必须贴着同一 beat 的主线动作与 beat.t：优先同 chunk/紧邻 chunk，紧跟主镜之后。"
        "禁止整段复用同一 src_in/src_out；允许动作后紧挨着的反应特写（可与主镜同 chunk）。"
        "禁止为了凑 insert 去选远晚于该 beat.t 的表情/特写。\n"
        "相邻 beats 换场/换人/换冲突时必须单独留 role=bridge 过渡镜（离开/赶到/进门/场面变化），禁止并进主线导致跳远；纯无信息走路才可并进。bridge 的 reason 只交代场面，不要编新剧情。\n"
        "每条 beat 的 clips：先保证进入→关键变化→落点都有画面；合计时长贴近 vo 口播时长，再控制不超过 budget_sec；禁止「证据够了就停」只留半截。每个 clip 给 duration。\n"
        "时间最早的 beat 是开场，必须剪进去。不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。skip=op_ed 的 chunk 不要用。只输出这些 beats 的 clips。\n"
        "chunks 是视觉证据：i=chunk_index，t=[start,end]，cap=看得见的变化。"
        "有 cap 必须优先；无 cap 时只按 asr 时间与 chunk.t 选镜，禁止瞎猜画面内容。\n"
        "reason 必须用 people 里的稳定称呼（优先用户命名的 speaker label），不要把两个人写成同一个他。禁止男主/女主，禁止用发色外号替换已有名字。每个 clip 必须带 beat_id 和 reason。\n"
        "asr[].speaker 非空=谁在说，当事实。\n\n"
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
    """Minimum uncovered window that still warrants a plot-gap pass."""
    duration = max(0.0, float(duration_sec or 0.0))
    # Lower threshold → catch more mid-story holes for a denser plan.
    return round(max(28.0, min(55.0, duration * 0.04)), 1)


def story_beat_gaps(
    beats: Sequence[Mapping[str, Any]],
    duration_sec: float,
    *,
    min_gap_sec: float | None = None,
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
    threshold = float(min_gap_sec) if min_gap_sec is not None else story_gap_min_sec(duration)
    gaps: list[tuple[float, float]] = []
    cursor = story_start
    for lo, hi in merged:
        if lo - cursor >= threshold:
            gaps.append((round(cursor, 2), round(lo, 2)))
        cursor = max(cursor, hi)
    if story_end - cursor >= threshold:
        gaps.append((round(cursor, 2), round(story_end, 2)))
    return gaps


def prioritize_story_gaps(
    gaps: Sequence[tuple[float, float]],
    *,
    limit: int = MAX_GAP_FILL_WINDOWS,
    pin: Sequence[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Keep pinned activity-shift holes first, then the largest remaining holes."""
    items = [(float(lo), float(hi)) for lo, hi in gaps if float(hi) - float(lo) > 1.0]
    if not items:
        return []

    def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) < 1.5 and abs(a[1] - b[1]) < 1.5

    pinned: list[tuple[float, float]] = []
    for cand in pin or ():
        target = (float(cand[0]), float(cand[1]))
        for item in items:
            if _near(item, target) and not any(_near(item, kept) for kept in pinned):
                pinned.append(item)
                break
    rest = [item for item in items if not any(_near(item, kept) for kept in pinned)]
    room = max(0, int(limit) - len(pinned))
    largest = sorted(rest, key=lambda item: item[1] - item[0], reverse=True)[:room]
    return sorted([*pinned, *largest], key=lambda item: item[0])


_ACTIVITY_EVENT_KEY_RE = re.compile(r"[\s，,。！？!?…；;：:、\"'「」『』（）()【】\[\]《》<>·\-—_]+")


def _event_overlap_ratio(left: str, right: str) -> float:
    """How similar two beat events are; low score means different story beats."""
    a = _ACTIVITY_EVENT_KEY_RE.sub("", str(left or ""))
    b = _ACTIVITY_EVENT_KEY_RE.sub("", str(right or ""))
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(None, a, b).ratio())


def activity_shift_gaps(
    beats: Sequence[Mapping[str, Any]],
    *,
    min_gap_sec: float,
) -> list[tuple[float, float]]:
    """Pin long holes between consecutive beats whose events barely overlap (domain-agnostic)."""
    ordered: list[tuple[float, float, str]] = []
    for beat in beats:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        ordered.append((span[0], span[1], str(beat.get("event") or "")))
    ordered.sort(key=lambda item: (item[0], item[1]))
    out: list[tuple[float, float]] = []
    threshold = max(20.0, float(min_gap_sec or 0.0) * 0.55)
    for prev, cur in zip(ordered, ordered[1:]):
        gap_lo, gap_hi = float(prev[1]), float(cur[0])
        if gap_hi - gap_lo < threshold:
            continue
        # Only pin when the outline itself jumped topics across a long hole.
        if _event_overlap_ratio(prev[2], cur[2]) <= 0.34:
            out.append((round(gap_lo, 2), round(gap_hi, 2)))
    return out


def trim_story_beats_to_limit(
    beats: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_STORY_BEATS,
) -> list[dict[str, Any]]:
    """Cap beat count so quotas stay differentiated instead of collapsing to the floor."""
    items = [dict(beat) for beat in beats]
    if len(items) <= limit:
        return items
    by_time = sorted(
        items,
        key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)),
    )
    hard: set[int] = set()
    if by_time:
        hard.add(int(by_time[0].get("id") or 0))
        hard.add(int(by_time[-1].get("id") or 0))
    for beat in items:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        importance = float(beat.get("importance") or 0.0)
        event = str(beat.get("event") or "")
        # Keep climax AND enter/exit/bridge texture — never drop story bookends as filler.
        if importance >= 0.85:
            hard.add(beat_id)
        elif _TEXTURE_BEAT_RE.search(event) or any(
            token in event for token in ("进入", "赶到", "走进", "离开", "收束", "结局", "落点", "余波")
        ):
            hard.add(beat_id)
    ranked = sorted(
        items,
        key=lambda item: (
            int(item.get("id") or 0) in hard,
            float(item.get("importance") or 0.5),
            -((_time_span(item.get("t")) or (0.0, 0.0))[1] - (_time_span(item.get("t")) or (0.0, 0.0))[0]),
        ),
        reverse=True,
    )
    kept_ids = {int(item.get("id") or 0) for item in ranked[:limit]}
    kept = [item for item in by_time if int(item.get("id") or 0) in kept_ids]
    return kept or by_time[:limit]


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
        f"只规划 0 秒到 {until:.0f} 秒的开场 2–5 条 beats：冷开场（如有）+ 片头曲之后第一场及紧随推进。\n"
        "密稿供用户删减，开场因果宁可多一条。沿用或补全 people 稳定称呼。不要 OP/片头曲/歌词/标题动画，不要重复下面 already。\n\n"
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
        f"只规划 {start:.0f} 秒到正片结束（约 {story_end:.0f} 秒、片尾曲之前）的 2–5 条收尾 beats。\n"
        "密稿供用户删减：收束与余波要盖住。沿用或补全 people 稳定称呼。不要 ED/片尾曲/演职员表/预告，不要重复下面 already。\n\n"
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
        f"原片时长 {duration:.0f} 秒。下面 gaps 是当前要检查的正片空档。\n"
        "每个 gap 短空档补 1–2 条，长空档可到 3 条；展开过程要盖住。t 必须落在对应 gap 内。\n"
        "若空档两端活动变了，优先补进入拍，禁止直接补场内结果。\n"
        "密稿供用户删减：补关键过程与中间推进，不要只钉结果；不要拆成表情碎拍。不要重复 already，不要补纯走路气氛。\n\n"
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


def _beat_event_key(text: str) -> str:
    return re.sub(r"[\s，,。！？!?…；;：:、\"'「」『』（）()【】\[\]《》<>·\-—_]+", "", str(text or "").strip())


def _char_ngrams(text: str, size: int = 3) -> set[str]:
    body = str(text or "")
    if not body:
        return set()
    if len(body) < size:
        return {body}
    return {body[index : index + size] for index in range(len(body) - size + 1)}


def _events_near_duplicate(left: str, right: str) -> bool:
    a = _beat_event_key(left)
    b = _beat_event_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 8 and short in long:
        return True
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.42:
        return True
    shared4 = len(_char_ngrams(a, 4) & _char_ngrams(b, 4))
    if shared4 >= 1 and ratio >= 0.30 and min(len(a), len(b)) >= 12:
        return True
    grams_a = _char_ngrams(a)
    grams_b = _char_ngrams(b)
    if not grams_a or not grams_b:
        return False
    shared = len(grams_a & grams_b)
    return shared >= 4 and shared / float(min(len(grams_a), len(grams_b))) >= 0.55


def _span_cover_ratio(span: tuple[float, float], covers: Sequence[tuple[float, float]]) -> float:
    lo, hi = span
    width = max(hi - lo, 1e-6)
    pieces: list[tuple[float, float]] = []
    for start, end in covers:
        left = max(lo, float(start))
        right = min(hi, float(end))
        if right - left > 1e-6:
            pieces.append((left, right))
    if not pieces:
        return 0.0
    pieces.sort()
    merged = [pieces[0]]
    for start, end in pieces[1:]:
        if start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    covered = sum(end - start for start, end in merged)
    return covered / width


def _beats_time_conflict(left: tuple[float, float], right: tuple[float, float]) -> bool:
    overlap = _overlap_sec(left, right)
    if overlap <= 0.05:
        return False
    left_w = max(left[1] - left[0], 0.4)
    right_w = max(right[1] - right[0], 0.4)
    return (
        overlap > 0.55 * min(left_w, right_w)
        or overlap > 0.45 * left_w
        or overlap > 0.55 * right_w
    )


def _beat_inside_windows(span: tuple[float, float], windows: Sequence[tuple[float, float]]) -> bool:
    if not windows:
        return True
    return _span_cover_ratio(span, windows) >= 0.55


def merge_story_beats(
    head: list[Mapping[str, Any]],
    tail: list[Mapping[str, Any]],
    *,
    allowed_windows: Sequence[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    out = [dict(item) for item in head]
    used = {int(item.get("id") or 0) for item in out}
    next_id = max(used) + 1 if used else 1
    existing_spans = [span for span in (_time_span(item.get("t")) for item in out) if span]
    for raw in tail:
        item = dict(raw)
        span = _time_span(item.get("t"))
        event = str(item.get("event") or "")
        if span and allowed_windows is not None and not _beat_inside_windows(span, allowed_windows):
            continue
        if span and _span_cover_ratio(span, existing_spans) >= 0.4:
            continue
        if any(_events_near_duplicate(event, str(prev.get("event") or "")) for prev in out):
            continue
        if span:
            dup = False
            for prev in out:
                prev_span = _time_span(prev.get("t"))
                if prev_span and _beats_time_conflict(span, prev_span):
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
        if span:
            existing_spans.append(span)
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
    pad_sec: float = MATCH_PACK_PAD_SEC,
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
    max_span_sec: float = 140.0,
    max_gap_sec: float = 48.0,
) -> list[list[dict[str, Any]]]:
    """Group beats for Match: small waves that stay near each other in source time.

    Count alone is not enough — packing 4 beats that span half an episode still
    dumps the whole middle of the film into one prompt and the model picks
    lookalike shots from the wrong act.
    """
    items = sorted(
        (dict(beat) for beat in beats),
        key=lambda item: (
            (_time_span(item.get("t")) or (0.0, 0.0))[0],
            int(item.get("id") or 0),
        ),
    )
    size = max(1, int(per_wave or MATCH_BEATS_PER_WAVE))
    span_cap = max(40.0, float(max_span_sec or 140.0))
    gap_cap = max(12.0, float(max_gap_sec or 48.0))
    if len(items) <= 1:
        return [items] if items else []

    waves: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    wave_lo: float | None = None
    wave_hi: float | None = None
    for beat in items:
        span = _time_span(beat.get("t"))
        if not current:
            current = [beat]
            if span:
                wave_lo, wave_hi = span[0], span[1]
            continue
        start_new = False
        if len(current) >= size:
            start_new = True
        elif span and wave_lo is not None and wave_hi is not None:
            if span[1] - wave_lo > span_cap:
                start_new = True
            elif span[0] - wave_hi > gap_cap:
                start_new = True
        if start_new:
            waves.append(current)
            current = [beat]
            wave_lo, wave_hi = (span[0], span[1]) if span else (None, None)
            continue
        current.append(beat)
        if span:
            wave_lo = span[0] if wave_lo is None else min(wave_lo, span[0])
            wave_hi = span[1] if wave_hi is None else max(wave_hi, span[1])
    if current:
        waves.append(current)
    return waves


def split_clips_for_captions(
    clips: Sequence[Mapping[str, Any]],
    *,
    per_wave: int = CAPTION_CLIPS_PER_WAVE,
) -> list[list[dict[str, Any]]]:
    """Pack caption waves by consecutive beat_id so one story beat stays in one LLM call."""
    items = [dict(clip) for clip in clips]
    size = max(1, int(per_wave or CAPTION_CLIPS_PER_WAVE))
    if len(items) <= size:
        return [items] if items else []

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_beat: Any = object()
    for clip in items:
        beat_id = clip.get("beat_id")
        if current and beat_id != current_beat:
            groups.append(current)
            current = []
        current.append(clip)
        current_beat = beat_id
    if current:
        groups.append(current)

    waves: list[list[dict[str, Any]]] = []
    wave: list[dict[str, Any]] = []
    for group in groups:
        if len(group) > size:
            if wave:
                waves.append(wave)
                wave = []
            for index in range(0, len(group), size):
                waves.append(group[index : index + size])
            continue
        if wave and len(wave) + len(group) > size:
            waves.append(wave)
            wave = []
        wave.extend(group)
    if wave:
        waves.append(wave)
    return waves


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
    evidence = " ".join(str(tag) for tag in (beat.get("evidence_required") or []))
    body = f"{beat.get('event') or ''} {beat.get('needed_visual') or ''} {evidence}"
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


def normalize_evidence_required(raw: Any) -> list[str]:
    """Keep Plan evidence tags in a small controlled vocabulary."""
    allowed = {tag: tag for tag in RECAP_EVIDENCE_REQUIRED_TAGS}
    aliases = {
        "角色": "人物",
        "人": "人物",
        "person": "人物",
        "people": "人物",
        "character": "人物",
        "characters": "人物",
        "行为": "动作",
        "动作结果": "动作",
        "action": "动作",
        "actions": "动作",
        "表情": "反应",
        "情绪": "反应",
        "reaction": "反应",
        "reactions": "反应",
        "道具": "物品",
        "线索": "物品",
        "信息": "物品",
        "object": "物品",
        "objects": "物品",
        "item": "物品",
        "items": "物品",
        "prop": "物品",
        "props": "物品",
        "台词": "对话",
        "对白": "对话",
        "asr": "对话",
        "dialogue": "对话",
        "dialog": "对话",
        "speech": "对话",
        "变化说明": "变化",
        "前后": "变化",
        "change": "变化",
        "changes": "变化",
        "场景": "场面",
        "换场": "场面",
        "空间": "场面",
        "scene": "场面",
        "scenes": "场面",
        "setting": "场面",
    }
    items: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        items = re.split(r"[,，、/\s]+", text)
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        items = list(raw)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        lowered = token.lower()
        tag = allowed.get(token) or allowed.get(lowered) or aliases.get(token) or aliases.get(lowered)
        if not tag:
            haystack = lowered
            for key, value in list(allowed.items()) + list(aliases.items()):
                needle = str(key).lower()
                if needle and (needle in haystack or haystack in needle):
                    tag = value if value in allowed else allowed.get(value, value)
                    break
        if tag and tag not in allowed:
            tag = allowed.get(tag)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 4:
            break
    return out


def sanitize_generic_role_labels(text: str) -> str:
    """Identity: story wording is left to LLM stages, not code patches."""
    return str(text or "")


def _has_japanese_kana(text: str) -> bool:
    return bool(_JP_KANA_RE.search(str(text or "")))


def _normalize_vo_compare(text: str) -> str:
    return _VO_WHITESPACE_RE.sub("", str(text or "").strip().lower())


def _vo_overlaps_source_line(vo: str, source: str, *, min_chars: int = 6) -> bool:
    left = _normalize_vo_compare(vo)
    right = _normalize_vo_compare(source)
    if len(left) < min_chars or len(right) < min_chars:
        return False
    if left in right or right in left:
        return True
    return _text_similarity(left, right) >= 0.72


def scrub_verbatim_source_dialogue_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Drop Japanese kana / near-verbatim ASR pasted into VO."""
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        row = dict(clip)
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue

        asr_texts: list[str] = []
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or src_in)
        except (TypeError, ValueError):
            src_in, src_out = 0.0, 0.0
        if pack is not None:
            evidence = _evidence_for_source_span(pack, src_in, src_out, asr_limit=12, cap_limit=1)
            asr_texts = [str(item.get("text") or "") for item in evidence.get("asr") or []]

        # Heavy Japanese → drop the whole line (source dialogue pasted as VO).
        kana_hits = _JP_KANA_RE.findall(vo)
        if len(kana_hits) >= 3 or (kana_hits and len(kana_hits) / max(len(vo), 1) >= 0.2):
            row["vo"] = ""
            out.append(row)
            continue

        def _keep_quote(match: re.Match[str]) -> str:
            quoted = str(match.group(1) or "").strip()
            if not quoted:
                return ""
            if _has_japanese_kana(quoted):
                return ""
            if any(_vo_overlaps_source_line(quoted, src) for src in asr_texts):
                return ""
            if len(quoted) > 6:
                return ""
            return match.group(0)

        cleaned = _VO_QUOTE_RE.sub(_keep_quote, vo)
        if _has_japanese_kana(cleaned):
            cleaned = _JP_KANA_RE.sub("", cleaned)
        # Strip leftover separators after kana/quote removal; keep sentence enders.
        cleaned = _VO_WHITESPACE_RE.sub(" ", cleaned).strip(" ，,.;；")
        if cleaned and any(_vo_overlaps_source_line(cleaned, src, min_chars=8) for src in asr_texts):
            cleaned = ""
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        elif cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        row["vo"] = cleaned
        out.append(row)
    return out


_SPEECH_ACT_RE = re.compile(
    r"(说|告诉|喊道|叫道|问道|答道|宣布|表示|低声|开口|下令|命令|提醒|警告|质问|反问|承认|否认|发誓)"
)


def _vo_source_span_for_scrub(
    clips: Sequence[Mapping[str, Any]],
    index: int,
) -> tuple[float, float]:
    """Widen to empty same-beat follow shots covered by spanning VO."""
    items = list(clips or [])
    clip = items[index]
    try:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or src_in)
    except (TypeError, ValueError):
        return 0.0, 0.0
    beat_id = clip.get("beat_id")
    for nxt in items[index + 1 :]:
        if beat_id is None or nxt.get("beat_id") != beat_id:
            break
        if str(nxt.get("vo") or "").strip():
            break
        try:
            nxt_out = float(nxt.get("src_out") or 0.0)
        except (TypeError, ValueError):
            break
        src_out = max(src_out, nxt_out)
    return src_in, src_out


def _vo_evidence_window(
    clips: Sequence[Mapping[str, Any]],
    index: int,
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    pad_sec: float = 8.0,
) -> tuple[float, float]:
    """Widen VO evidence to the beat time window so short cuts still see nearby dialogue."""
    src_in, src_out = _vo_source_span_for_scrub(clips, index)
    pad = max(0.0, float(pad_sec))
    lo, hi = src_in - pad, src_out + pad
    try:
        beat_id = int((clips[index] or {}).get("beat_id") or 0)
    except (TypeError, ValueError, IndexError):
        beat_id = 0
    beat = _beats_by_id(beats).get(beat_id) if beat_id else None
    span = _time_span((beat or {}).get("t")) if beat else None
    if span:
        lo = min(lo, span[0] - 2.0)
        hi = max(hi, span[1] + 2.0)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def scrub_unevidenced_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Drop VO that invents speech/plot without asr/caps in the picture span."""
    if pack is None:
        # Without a pack we cannot verify evidence; leave VO untouched.
        return [dict(clip) for clip in clips or []]
    items = [dict(clip) for clip in clips or []]
    by_id = _beats_by_id(beats)
    out: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue
        src_in, src_out = _vo_evidence_window(items, index, beats)
        evidence = _evidence_for_source_span(
            pack, src_in, src_out, pad_sec=0.0, asr_limit=24, cap_limit=10
        )
        asr_rows = list(evidence.get("asr") or [])
        cap_rows = list(evidence.get("caps") or [])
        asr_blob = " ".join(str(item.get("text") or "") for item in asr_rows)
        cap_blob = " ".join(str(item.get("cap") or "") for item in cap_rows)
        has_asr = bool(asr_blob.strip())
        has_caps = bool(cap_blob.strip())
        weak = is_weak_match_clip(row)

        if not has_asr and not has_caps:
            row["vo"] = ""
            out.append(row)
            continue

        # Outline parroting with no dialogue: drop if VO ≈ event and barely matches caps.
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        event = str(row.get("event") or (by_id.get(beat_id) or {}).get("event") or "").strip()
        if (
            not has_asr
            and event
            and _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(event)) >= 0.55
            and (
                not has_caps
                or _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(cap_blob)) < 0.28
            )
        ):
            row["vo"] = ""
            out.append(row)
            continue

        parts = [item for item in re.split(r"(?<=[。！？!?；;])", vo) if str(item or "").strip()]
        if not parts:
            parts = [vo]
        kept: list[str] = []
        for part in parts:
            body = str(part or "").strip()
            if not body:
                continue
            quoted = bool(_VO_QUOTE_RE.search(body))
            speechy = bool(_SPEECH_ACT_RE.search(body)) or quoted
            # No dialogue at all → cannot report speech.
            if speechy and not has_asr:
                continue
            # Quoted invention: must touch source lines. Bare「XX说」narrative with asr is OK
            # (Chinese paraphrase of JP dialogue must not be nuked).
            if quoted and has_asr:
                if not _vo_overlaps_source_line(body, asr_blob, min_chars=4):
                    if _text_similarity(_normalize_vo_compare(body), _normalize_vo_compare(asr_blob)) < 0.22:
                        continue
            if weak and quoted:
                continue
            kept.append(body)
        cleaned = "".join(kept).strip(" ，,")
        if cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        row["vo"] = cleaned
        out.append(row)
    return out


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
        event = sanitize_generic_role_labels(str(item.get("event") or "").strip())
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
        needed = sanitize_generic_role_labels(
            str(item.get("needed_visual") or item.get("needed") or "").strip()
        )[:80]
        evidence_required = normalize_evidence_required(
            item.get("evidence_required") or item.get("evidence") or item.get("needed_evidence")
        )
        if not evidence_required:
            # Legacy beats / thin LLM output: infer a minimal evidence ask from needed_visual.
            evidence_required = normalize_evidence_required(needed) or ["动作"]
        row = {
            "id": beat_id,
            "event": event[:120],
            "importance": round(importance, 3),
            "evidence_required": evidence_required,
            "needed_visual": needed,
            "t": [round(span[0], 2), round(span[1], 2)],
        }
        out.append(row)
    if not out:
        raise RuntimeError("LLM 剧情节拍没有可用条目。")
    return out


def normalize_story_people(raw: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    items = raw.get("people") if isinstance(raw, Mapping) else raw
    if not isinstance(items, list):
        return []
    bad_label = re.compile(
        r"^(男主|女主|主角|npc|语气助词.*|说话人\d*|声线\d*)$|"
        r"^(ed|op|bgm)$|.*(片头曲|片尾曲|主题曲)|^ed音乐$|^op音乐$|^bgm音乐$",
        re.IGNORECASE,
    )
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()[:40]
        if not label or bad_label.match(label):
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
    visual_nick = re.compile(
        r"(金发|蓝发|黑发|红发|白发|粉发|银发|绿发).{0,3}(青年|少女|少年|男子|女子|女孩|男孩|男人|女人)"
    )
    seeded_labels: set[str] = set()
    for index, group in enumerate(groups):
        for item in normalize_story_people({"people": list(group or [])}):
            key = str(item.get("label") or "").strip()
            if not key or key in seen:
                continue
            # Later LLM people often invent hair-color nicknames; keep dialogue names authoritative.
            if index > 0 and seeded_labels and visual_nick.fullmatch(key):
                continue
            seen.add(key)
            if index == 0:
                seeded_labels.add(key)
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
    """Keep every planned beat and scale quotas so each beat has room near target_sec."""
    items = drop_op_ed_beats(beats, duration_sec)
    if not items:
        raise RuntimeError("没有可分配的剧情节拍。")
    chunk_list = list(chunks or [])
    scored: list[tuple[dict[str, Any], float, float]] = []
    for beat in items:
        evidence = beat_evidence_sec(beat, chunk_list)
        evid_score = beat_evidence_score(evidence)
        importance = float(beat.get("importance") or 0.5)
        span = _time_span(beat.get("t")) or (0.0, 0.0)
        span_dur = max(0.0, span[1] - span[0])
        # High-importance beats: don't let thin/short source windows tank quota.
        if importance >= 0.8 and evid_score > 0.0:
            evid_score = max(evid_score, 0.75)
        weight = importance * (0.35 + 0.65 * evid_score)
        if importance >= 0.8:
            weight = max(weight, importance * 0.72)
        if importance >= 0.75 and span_dur <= 24.0:
            weight = max(weight, importance * 0.85)
        if importance >= 0.85 and span_dur <= 12.0:
            weight = max(weight, importance * 0.92)
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
        importance = float(out.get("importance") or 0.5)
        event = str(out.get("event") or "")
        # Enter→land needs ≥2 masters; climax beats often need a third beat of reaction.
        min_shots = 2
        if importance < 0.22 and not _TEXTURE_BEAT_RE.search(event):
            min_shots = 1
        if importance >= 0.75:
            min_shots = 3
        if any(token in event for token in ("进入", "赶到", "走进", "离开", "收束", "结局", "落点", "余波")):
            min_shots = max(min_shots, 2)
        out["shots"] = min(5, max(min_shots, int(round(budget / 5.5))))
        if str(beat.get("vo") or "").strip():
            out["vo"] = str(beat.get("vo") or "").strip()
        allocated.append(out)
    allocated.sort(key=lambda item: ((item.get("t") or [0.0, 0.0])[0], int(item.get("id") or 0)))
    return allocated


def recap_vo_draft_user_prompt(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]],
    *,
    prev_vo: str = "",
) -> str:
    rows: list[dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, Mapping):
            continue
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        span = _time_span(beat.get("t")) or (0.0, 0.0)
        budget = float(beat.get("budget_sec") or MIN_BEAT_BUDGET_SEC)
        evidence = _evidence_for_source_span(
            pack,
            span[0],
            span[1],
            pad_sec=2.0,
            asr_limit=14,
            cap_limit=8,
        )
        row: dict[str, Any] = {
            "id": beat_id,
            "event": str(beat.get("event") or "").strip()[:120],
            "needed_visual": str(beat.get("needed_visual") or "").strip()[:80],
            "importance": float(beat.get("importance") or 0.5),
            "budget_sec": round(budget, 1),
            "budget_chars": tts_char_budget(budget),
            "t": [round(span[0], 2), round(span[1], 2)],
            "asr": evidence.get("asr") or [],
            "caps": evidence.get("caps") or [],
        }
        required = normalize_evidence_required(beat.get("evidence_required"))
        if required:
            row["evidence_required"] = required
        if not evidence.get("asr") and not evidence.get("caps"):
            row["hint"] = "无 asr/caps：text 必须空着"
        elif not evidence.get("asr"):
            row["hint"] = "无 asr：只写 caps 可见动作；禁止转述台词"
        else:
            row["hint"] = "写进入→变化→落点；约 70–90% budget_chars"
        rows.append(row)
    return (
        "按 beats 写解说草稿。事实只来自该 beat 的 asr/caps；event 不是证据。\n"
        "有证据写完整小剧场；无证据空着。禁止掐头去尾式乱跳。\n"
        + (f"上一句旁白：{prev_vo}\n" if str(prev_vo or "").strip() else "")
        + "\n"
        + json.dumps(
            {
                "people": pack.get("people") or [],
                "beats": rows,
            },
            ensure_ascii=False,
        )
    )


def parse_vo_drafts(text: str, beats: Sequence[Mapping[str, Any]] | None = None) -> dict[int, str]:
    """Map beat id → narration draft. Bad JSON yields empty map (non-fatal)."""
    try:
        payload = json.loads(_extract_json(text))
    except (json.JSONDecodeError, TypeError, ValueError, RuntimeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    items = payload.get("drafts") or payload.get("vos") or payload.get("captions") or []
    if not isinstance(items, list):
        return {}
    known: set[int] = set()
    for beat in beats or []:
        try:
            known.add(int(beat.get("id") or 0))
        except (TypeError, ValueError):
            continue
    known.discard(0)
    out: dict[int, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        try:
            beat_id = int(item.get("id") or item.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0 or (known and beat_id not in known):
            continue
        body = sanitize_generic_role_labels(str(item.get("text") or item.get("vo") or "").strip())
        out[beat_id] = body
    return out


def draft_recap_vo_for_beats(
    pack: Mapping[str, Any],
    allocated: Sequence[Mapping[str, Any]],
    *,
    config=None,
    language: str | None = None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Write beat.vo from beat-window evidence before Match. Failures leave vo empty."""
    out = [dict(beat) for beat in allocated or []]
    if not out:
        return out
    pending = [
        beat
        for beat in out
        if force or not str(beat.get("vo") or "").strip()
    ]
    if not pending:
        return out
    system = resolve_recap_prompt(
        system_prompt,
        default_recap_vo_draft_prompt(language or resolve_recap_caption_language(config)),
    )
    by_id: dict[int, dict[str, Any]] = {}
    for beat in out:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id > 0:
            by_id[beat_id] = beat
    waves = split_beats_for_match(pending, per_wave=MATCH_BEATS_PER_WAVE)
    prev = ""
    for wave_i, wave in enumerate(waves):
        if progress_callback:
            progress_callback(48 + min(10, wave_i), "vo_draft")
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")
        try:
            text = call_remote_llm(
                system=system,
                user=recap_vo_draft_user_prompt(pack, wave, prev_vo=prev),
                config=config,
                temperature=0.3,
                max_tokens=4096,
                should_stop_callback=should_stop_callback,
            )
            drafts = parse_vo_drafts(text, wave)
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            drafts = {}
        for beat in wave:
            try:
                beat_id = int(beat.get("id") or 0)
            except (TypeError, ValueError):
                continue
            body = str(drafts.get(beat_id) or "").strip()
            target = by_id.get(beat_id)
            if target is not None:
                target["vo"] = body
            if body:
                prev = body
    return out


def stamp_beat_vo_onto_cuts(
    cuts: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Put each beat.vo on the first primary cut of that beat; clear child VO slots."""
    out = [dict(clip) for clip in cuts or []]
    if not out or not beats:
        return out
    by_id = _beats_by_id(beats)
    seen: set[int] = set()
    for clip in out:
        try:
            beat_id = int(clip.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        body = str((by_id.get(beat_id) or {}).get("vo") or "").strip()
        if not body:
            continue
        role = _clip_role(clip) or ("insert" if _looks_like_insert_cut(clip) else "")
        if role in {"insert", "bridge", "vo_hold"}:
            clip["vo"] = ""
            clip["vo_draft"] = ""
            continue
        if beat_id in seen:
            clip["vo"] = ""
            clip["vo_draft"] = ""
            continue
        clip["vo"] = body
        clip["vo_draft"] = body
        seen.add(beat_id)
    return out


def _fit_budgets_to_target(
    weights: Sequence[float],
    target_sec: float,
    *,
    min_sec: float = MIN_BEAT_BUDGET_SEC,
    max_sec: float = MAX_BEAT_BUDGET_SEC,
) -> list[float]:
    """Assign per-beat quotas up to ``target_sec`` by plot weight.

    Quotas themselves may fill the target so each beat has room for enter→land
    shots. Actual picture must not be padded just to spend leftover seconds
    (see ``apply_recap_duration`` trim-only).
    """
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


def recap_caption_user_prompt(
    clips: list[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]] | None = None,
    prev_caption: str = "",
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> str:
    rows = _caption_clip_rows(clips, beats=beats, pack=pack)
    seed = pack_captions_for_tts(clips, use_draft=True)
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    has_draft = any(
        str(clip.get("vo") or clip.get("vo_draft") or "").strip() for clip in clips or []
    )
    return (
        f"画面已锁定，本段 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍，不要真去合成语音。\n"
        f"1.0 倍约 {BASE_CHARS_PER_SEC:.0f} 字/秒，当前约 {CHARS_PER_SEC:.2f} 字/秒，fill={VO_FILL_RATIO}。\n"
        + (
            "seed/clips 已有解说草稿：只润色对齐 asr/caps，保留进入→变化→落点，禁止整段重写掐头去尾。\n"
            if has_draft
            else "无草稿的镜头才新写解说稿旁白。\n"
        )
        + "同一 beat_id 的连续主镜必须合并一条 caption（from=首 to=末），按合并总时长的 budget 写约 70–90% 字数。\n"
        "听起来要像在讲故事，不要写成「镜头1/镜头2」说明书，也不要复读 outline。\n"
        "【硬证据】事实只许来自该 span 的 asr[] 与 caps[]。outline/event/reason 不是证据，禁止用来补剧情或台词。\n"
        "有 asr/caps 时写进入→变化→落点；无 asr 禁止写任何人说过的话或转述；无 asr 且无 caps 则 text 空着。\n"
        "禁止为了「完整」编造未证实情节；禁止掐头去尾式乱跳，也禁止用大纲填洞。\n"
        "跨镜是为了把一件事讲完；禁止同拍主镜拆成一镜一句近义复读。\n"
        "role=insert 才 from=to 短句或空着；禁止同事实近义复读。\n"
        "asr 禁止照抄原文/日语假名/长引号对白；copy_ban=true 尤其禁止贴进口播，可提炼动作关系。\n"
        "people 只是称呼词典：本段 asr.speaker/对白没出现的人名禁止写进口播。禁止男主/女主。\n"
        "need_transition / role=bridge 才真换场：先收住上一场再开本场。\n"
        "weak_match：只写 caps 可见场面短句或空着，禁止编结果。\n"
        "上一句旁白是接榫，本句要接得上。只输出 captions。\n"
        + (f"上一句旁白：{prev_caption}\n" if str(prev_caption or "").strip() else "")
        + "\n"
        + json.dumps(
            {
                "people": list(people or []),
                "clips": rows,
                "seed": seed,
            },
            ensure_ascii=False,
        )
    )


def recap_gap_user_prompt(
    clips: list[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
    gap_indices: Sequence[int],
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> str:
    rows = _caption_clip_rows(clips, beats=beats, pack=pack)
    gaps = [index + 1 for index in gap_indices]
    for row in rows:
        row["gap"] = int(row["i"]) in gaps
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，成片 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍。已有字幕不要改。\n"
        "gaps 是目前没有字幕盖住、且整段 beat 仍真空的镜头。只给真正漏解说的镜头补 fills。\n"
        "同 beat 主线已有旁白时，后续空镜留给跨镜，不要补近义复读。\n"
        "只按本镜 asr（绝对）/ caps（辅助）写；outline/event/reason 不是证据。无 asr+caps 请 skip。\n"
        "纯无信息走路可 skip；换场/过场且 gaps 点名时才补短过渡，禁止直接扔结果。\n"
        "无 asr 禁止编台词/转述；有 caps 只写可见动作。\n"
        "谁说话只看 asr[].speaker；people 未在本段 asr 证实的人名禁止使用。\n"
        "match_status=weak_match：短句场面或 skip，禁止编结果。\n"
        "禁止把两个人写成同一个他，禁止男主/女主。\n\n"
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


def _beats_by_id(beats: Sequence[Mapping[str, Any]] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for beat in beats or []:
        if not isinstance(beat, Mapping):
            continue
        try:
            beat_id = int(beat.get("id"))
        except (TypeError, ValueError):
            continue
        if beat_id > 0:
            out[beat_id] = dict(beat)
    return out


def _caption_visual_role(clip: Mapping[str, Any]) -> str:
    """Discrete shot role for captions. Never pass raw VLM / reason text."""
    if _looks_like_insert_cut(clip):
        return "insert"
    if _clip_role(clip) == "bridge":
        return "bridge"
    blob = f"{clip.get('name') or ''} {clip.get('reason') or ''}"
    if re.search(r"换场|过场|过渡", blob):
        return "bridge"
    return ""


def _evidence_for_source_span(
    pack: Mapping[str, Any] | None,
    src_in: float,
    src_out: float,
    *,
    pad_sec: float = 1.25,
    asr_limit: int = 8,
    cap_limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    """ASR lines + VLM caps overlapping a source span (for caption rewrite)."""
    from src.services.understanding_tags import format_motion_cap_text

    if not pack:
        return {"asr": [], "caps": []}
    try:
        start = float(src_in)
        end = float(src_out)
    except (TypeError, ValueError):
        return {"asr": [], "caps": []}
    if end < start:
        start, end = end, start
    pad = max(0.0, float(pad_sec or 0.0))
    window = (start - pad, end + pad)
    asr_rows: list[dict[str, Any]] = []
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping):
            continue
        try:
            cue_start = float(row.get("start") or 0.0)
            cue_end = float(row.get("end") or cue_start)
        except (TypeError, ValueError):
            continue
        if _overlap_sec((cue_start, cue_end), window) <= 0.05:
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        item = {
            "t": [round(cue_start, 2), round(cue_end, 2)],
            "text": text[:100],
        }
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            item["speaker"] = speaker[:40]
        if _has_japanese_kana(text):
            # Hint for caption LLM: treat as evidence, never paste into VO.
            item["copy_ban"] = True
        asr_rows.append(item)
        if len(asr_rows) >= max(1, int(asr_limit or 8)):
            break
    cap_rows: list[dict[str, Any]] = []
    for chunk in pack.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        cap = format_motion_cap_text(
            str(chunk.get("visible") or ""),
            str(chunk.get("change") or ""),
        ) or str(chunk.get("cap") or "").strip()
        if not cap:
            continue
        span = _time_span(chunk.get("t"))
        if not span or _overlap_sec(span, window) <= 0.05:
            continue
        if str(chunk.get("skip") or "").strip():
            continue
        row = {
            "i": chunk.get("i"),
            "t": [round(span[0], 2), round(span[1], 2)],
            "cap": cap[:160],
        }
        # Soft signal only — never treat as hard fact in prompts that read caps.
        inferred = str(chunk.get("inferred") or "").strip()
        try:
            weight = float(chunk.get("inferred_weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if inferred and weight >= 0.55:
            row["inferred"] = inferred[:60]
            row["inferred_weight"] = round(min(1.0, weight), 2)
        cap_rows.append(row)
        if len(cap_rows) >= max(1, int(cap_limit or 6)):
            break
    return {"asr": asr_rows, "caps": cap_rows}


def _text_similarity(left: str, right: str) -> float:
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return 0.0
    ratio = float(SequenceMatcher(None, a, b).ratio())
    # CJK event↔cap often share keywords without long contiguous matches.
    a_chars = set(re.findall(r"[\u4e00-\u9fff]", a))
    b_chars = set(re.findall(r"[\u4e00-\u9fff]", b))
    if len(a_chars) >= 2 and len(b_chars) >= 2:
        inter = len(a_chars & b_chars)
        if inter:
            jaccard = inter / float(len(a_chars | b_chars))
            cover = inter / float(len(a_chars))
            ratio = max(ratio, 0.50 * jaccard + 0.50 * cover)
    return float(ratio)


def _beat_visual_anchor(beat: Mapping[str, Any] | None, clip: Mapping[str, Any] | None = None) -> str:
    beat = beat if isinstance(beat, Mapping) else {}
    clip = clip if isinstance(clip, Mapping) else {}
    parts = [
        str(clip.get("event") or beat.get("event") or "").strip(),
        str(beat.get("needed_visual") or clip.get("needed_visual") or "").strip(),
        " ".join(normalize_evidence_required(beat.get("evidence_required") or clip.get("evidence_required"))),
    ]
    return " ".join(part for part in parts if part).strip()


def _cap_match_score_for_anchor(anchor: str, cap: str, *, asr_blob: str = "") -> float:
    body = str(cap or "").strip()
    if not body:
        return 0.0
    score = _text_similarity(anchor, body)
    if asr_blob:
        score = max(score, 0.55 * score + 0.45 * _text_similarity(anchor, asr_blob))
    return float(score)


def _people_labels(people: Sequence[Mapping[str, Any]] | None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in people or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def is_weak_match_clip(clip: Mapping[str, Any] | None) -> bool:
    if not isinstance(clip, Mapping):
        return False
    status = str(clip.get("match_status") or "").strip().lower()
    return status in {MATCH_STATUS_WEAK, "weak", "low"}


def _clamp_match_threshold(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = float(default)
    return min(0.95, max(0.05, score))


def resolve_match_qc_thresholds(
    config: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve Match QC thresholds from config / env; defaults stay conservative."""
    weak = float(MATCH_WEAK_SCORE)
    weak_insert = float(MATCH_WEAK_SCORE_INSERT)
    raw: Mapping[str, Any] | None = None
    if isinstance(config, Mapping):
        understanding = config.get("understanding")
        if isinstance(understanding, Mapping):
            candidate = understanding.get("recap_match_qc")
            if isinstance(candidate, Mapping):
                raw = candidate
        if raw is None:
            candidate = config.get("recap_match_qc")
            if isinstance(candidate, Mapping):
                raw = candidate
    if raw is not None:
        if raw.get("weak") is not None:
            weak = _clamp_match_threshold(raw.get("weak"), weak)
        if raw.get("weak_insert") is not None:
            weak_insert = _clamp_match_threshold(raw.get("weak_insert"), weak_insert)
    env_weak = str(os.environ.get("VIDEOSEEK_RECAP_MATCH_WEAK") or "").strip()
    env_insert = str(os.environ.get("VIDEOSEEK_RECAP_MATCH_WEAK_INSERT") or "").strip()
    if env_weak:
        weak = _clamp_match_threshold(env_weak, weak)
    if env_insert:
        weak_insert = _clamp_match_threshold(env_insert, weak_insert)
    return {"weak": round(weak, 3), "weak_insert": round(weak_insert, 3)}


def list_weak_match_beat_ids(clips: Sequence[Mapping[str, Any]] | None) -> list[int]:
    """Unique beat ids that still have at least one weak-match cut, in timeline order."""
    ordered: list[int] = []
    seen: set[int] = set()
    for clip in clips or []:
        if not is_weak_match_clip(clip):
            continue
        try:
            beat_id = int(clip.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0 or beat_id in seen:
            continue
        seen.add(beat_id)
        ordered.append(beat_id)
    return ordered


def score_recap_cut_match(
    clip: Mapping[str, Any],
    *,
    beat: Mapping[str, Any] | None = None,
    pack: Mapping[str, Any] | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Heuristic Match QC: refuse auto-caption when evidence is too thin."""
    limits = resolve_match_qc_thresholds(None)
    if isinstance(thresholds, Mapping):
        if thresholds.get("weak") is not None:
            limits["weak"] = _clamp_match_threshold(thresholds.get("weak"), limits["weak"])
        if thresholds.get("weak_insert") is not None:
            limits["weak_insert"] = _clamp_match_threshold(
                thresholds.get("weak_insert"),
                limits["weak_insert"],
            )
    beat = beat if isinstance(beat, Mapping) else {}
    event = str(clip.get("event") or beat.get("event") or "").strip()
    needed = str(beat.get("needed_visual") or clip.get("needed_visual") or "").strip()
    required = normalize_evidence_required(
        beat.get("evidence_required") or clip.get("evidence_required")
    )
    reason = str(clip.get("reason") or "").strip()
    evidence = _evidence_for_source_span(
        pack,
        float(clip.get("src_in") or 0.0),
        float(clip.get("src_out") or 0.0),
    )
    asr_blob = " ".join(
        f"{item.get('speaker') or ''} {item.get('text') or ''}".strip()
        for item in evidence.get("asr") or []
    ).strip()
    cap_blob = " ".join(str(item.get("cap") or "") for item in evidence.get("caps") or []).strip()
    anchor = " ".join(part for part in (event, needed, " ".join(required)) if part).strip()
    vlm_score = max(_text_similarity(anchor, cap_blob), _text_similarity(event, cap_blob))
    asr_score = max(_text_similarity(anchor, asr_blob), _text_similarity(event, asr_blob))
    reason_score = max(_text_similarity(anchor, reason), _text_similarity(event, reason))

    labels = _people_labels(people)
    if not labels:
        labels = [token for token in re.findall(r"[\u4e00-\u9fff]{2,8}", event) if token]
    # Never score character hits from the beat event itself — LLM always writes the name there.
    hay = f"{cap_blob} {asr_blob} {reason}"
    if labels:
        hits = sum(1 for label in labels if label and label in hay)
        character_score = min(1.0, hits / max(1.0, min(3.0, float(len(labels)))))
    else:
        character_score = 0.35

    has_asr = bool(asr_blob)
    has_vlm = bool(cap_blob)
    coverage = 0.0
    if required:
        met = 0
        for tag in required:
            if tag == "对话" and has_asr:
                met += 1
            elif tag in {"动作", "变化"} and has_vlm:
                met += 1
            elif tag == "场面" and (has_vlm or _looks_like_scene_shift_text(reason, cap_blob)):
                met += 1
            elif tag == "反应" and (has_vlm or _looks_like_insert_cut(clip)):
                met += 1
            elif tag == "物品" and (has_vlm or has_asr):
                met += 1
            elif tag == "人物" and character_score >= 0.34:
                met += 1
        coverage = met / float(len(required))
    elif has_asr or has_vlm:
        coverage = 0.5

    insert = _looks_like_insert_cut(clip)
    bridge = _is_bridge_clip(clip) or _looks_like_scene_shift_text(reason, event, cap_blob)
    # Reason is self-justifying Match prose — do not let it alone prove the shot.
    if has_vlm:
        visual_score = max(vlm_score, reason_score * 0.35)
    elif has_asr:
        visual_score = max(vlm_score, reason_score * 0.25, asr_score * 0.45)
    else:
        visual_score = max(vlm_score, reason_score * 0.12)

    if insert:
        total = (
            0.30 * visual_score
            + 0.32 * vlm_score
            + 0.14 * asr_score
            + 0.12 * character_score
            + 0.12 * coverage
        )
        threshold = float(limits["weak_insert"])
    elif bridge:
        total = (
            0.28 * visual_score
            + 0.30 * vlm_score
            + 0.16 * asr_score
            + 0.10 * character_score
            + 0.16 * coverage
        )
        threshold = float(limits["weak_insert"])
    else:
        total = (
            0.24 * visual_score
            + 0.34 * vlm_score
            + 0.22 * asr_score
            + 0.10 * character_score
            + 0.10 * coverage
        )
        threshold = float(limits["weak"])

    # Time alignment: wrong-act lookalikes must lose even when reason prose looks good.
    time_score = 1.0
    beat_span = _time_span(beat.get("t"))
    try:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
    except (TypeError, ValueError):
        src_in, src_out = 0.0, 0.0
    if beat_span and src_out > src_in:
        pad = float(BEAT_SRC_PAD_SEC)
        expanded = (beat_span[0] - pad, beat_span[1] + pad)
        overlap = _overlap_sec((src_in, src_out), expanded)
        time_score = max(0.0, min(1.0, overlap / max(0.2, src_out - src_in)))
        total = 0.78 * total + 0.22 * time_score

    forced_weak = False
    if "弱证据" in reason:
        forced_weak = True
    # No real evidence on the span: refuse. Reason parroting the beat does not count.
    if not has_asr and not has_vlm:
        forced_weak = True
    if required and coverage < 0.34 and (not has_vlm or vlm_score < 0.22):
        forced_weak = True
    # High reason / low VLM = classic “semantic lookalike, wrong shot”.
    if reason_score >= 0.55 and vlm_score < 0.28 and asr_score < 0.28:
        forced_weak = True
    if time_score < 0.40:
        forced_weak = True
    # Better capped chunk exists in this beat → current pick is a lookalike.
    if beat_span and pack is not None and not insert:
        anchor = " ".join(part for part in (event, needed) if part).strip()
        if anchor:
            best_alt = 0.0
            duration = float(pack.get("duration_sec") or 0.0)
            for chunk in pack.get("chunks") or []:
                if not keep_chunk_for_recap(chunk, duration):
                    continue
                cap = str(chunk.get("cap") or "").strip()
                if not cap:
                    continue
                window = _time_span(chunk.get("t"))
                if not window or _overlap_sec(window, beat_span) <= 0.5:
                    continue
                best_alt = max(best_alt, _cap_match_score_for_anchor(anchor, cap))
            if best_alt >= 0.28 and vlm_score + 0.12 < best_alt:
                forced_weak = True

    status = MATCH_STATUS_WEAK if forced_weak or total < threshold else MATCH_STATUS_OK
    support = {
        "asr": has_asr and asr_score >= 0.18,
        "vlm": has_vlm and vlm_score >= 0.18,
        "character": character_score >= 0.34,
        "coverage": round(coverage, 3),
        "time": round(time_score, 3),
    }
    return {
        "match_score": round(float(total), 3),
        "match_status": status,
        "match_threshold": round(float(threshold), 3),
        "visual_score": round(visual_score, 3),
        "asr_score": round(asr_score, 3),
        "vlm_score": round(vlm_score, 3),
        "character_score": round(character_score, 3),
        "time_score": round(time_score, 3),
        "evidence_support": support,
    }


def annotate_recap_match_quality(
    cuts: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    limits = thresholds if isinstance(thresholds, Mapping) else resolve_match_qc_thresholds(config)
    by_id = _beats_by_id(beats)
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        row = dict(clip)
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        scored = score_recap_cut_match(
            row,
            beat=by_id.get(beat_id) or {},
            pack=pack,
            people=people,
            thresholds=limits,
        )
        row.update(scored)
        out.append(row)
    return out


def clear_vo_on_weak_matches(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deprecated no-op: weak_match is a rematch flag, not a VO wipe.

    Keeping the helper so older callers/tests stay import-safe.
    """
    return [dict(clip) for clip in clips or []]


def _looks_like_scene_shift_text(*parts: Any) -> bool:
    body = " ".join(str(part or "") for part in parts)
    return bool(
        re.search(
            r"换场|过场|过渡|赶到|赶来|离开|来到|进门|出门|转场|另一处|街道|室外|室内|回到|前往",
            body,
        )
    )


def _caption_clip_rows(
    clips: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_id = _beats_by_id(beats)
    items = list(clips or [])
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(items, 1):
        start = float(clip.get("tl_in") or 0.0)
        end = float(clip.get("tl_out") or 0.0)
        dur = max(0.0, end - start)
        try:
            beat_id = int(clip.get("beat_id"))
        except (TypeError, ValueError):
            beat_id = None
        beat = by_id.get(beat_id or 0) or {}
        event = str(clip.get("event") or beat.get("event") or "").strip()
        reason = str(clip.get("reason") or "").strip()
        role = _caption_visual_role(clip)
        budget = tts_char_budget(dur)
        if role == "insert":
            budget = max(4, min(budget, max(8, int(budget * 0.45))))
        row = {
            "i": index,
            "name": str(clip.get("name") or f"{index:02d}"),
            "tl": [round(start, 3), round(end, 3)],
            "src": [
                round(float(clip.get("src_in") or 0.0), 3),
                round(float(clip.get("src_out") or 0.0), 3),
            ],
            "dur": round(dur, 3),
            "budget": budget,
            "beat_id": beat_id,
            # Outline only — not factual evidence for VO.
            "outline": event,
            "outline_only": True,
        }
        if role:
            row["role"] = role
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or src_in)
        # Prefer the whole beat window so JP dialogue near the cut still reaches the writer.
        beat_span = _time_span(beat.get("t"))
        if beat_span and role not in {"insert"}:
            ev_in = min(src_in, beat_span[0])
            ev_out = max(src_out, beat_span[1])
            evidence = (
                _evidence_for_source_span(
                    pack, ev_in, ev_out, pad_sec=4.0, asr_limit=20, cap_limit=10
                )
                if pack is not None
                else {"asr": [], "caps": []}
            )
        else:
            evidence = (
                _evidence_for_source_span(
                    pack, src_in, src_out, pad_sec=8.0, asr_limit=16, cap_limit=8
                )
                if pack is not None
                else {"asr": [], "caps": []}
            )
        has_asr = bool(evidence.get("asr"))
        has_caps = bool(evidence.get("caps"))
        pack_known = pack is not None
        if has_asr:
            row["asr"] = evidence["asr"]
        if has_caps:
            row["caps"] = evidence["caps"]
        match_status = str(clip.get("match_status") or "").strip()
        if match_status:
            row["match_status"] = match_status
        if clip.get("match_score") is not None:
            row["match_score"] = clip.get("match_score")
        required = normalize_evidence_required(
            beat.get("evidence_required") or clip.get("evidence_required")
        )
        if required:
            row["evidence_required"] = required
        support = clip.get("evidence_support")
        if isinstance(support, Mapping):
            row["evidence_support"] = dict(support)
        cap_blob = " ".join(str(item.get("cap") or "") for item in evidence.get("caps") or [])
        need_transition = False
        if role == "bridge":
            need_transition = True
        elif role != "insert" and _looks_like_scene_shift_text(
            reason, event, cap_blob, clip.get("name")
        ):
            need_transition = True
        if pack_known and not has_asr and not has_caps:
            row["budget"] = min(int(row["budget"] or 0), 8)
            row["hint"] = "无 asr/caps：text 必须空着；禁止用 outline 编剧情/台词"
        elif need_transition:
            row["need_transition"] = True
            row["hint"] = "真换场承上启下：只用 asr/caps；禁止用 outline 编结果；禁止场面转到"
        elif is_weak_match_clip(clip):
            row["budget"] = min(int(row["budget"] or 0), max(8, int(budget * 0.45)))
            row["hint"] = "弱证据：只用 caps 短写场面或空着；禁止编台词/结果；禁止用 outline"
        elif pack_known and not has_asr:
            row["hint"] = "无 asr：只写 caps 可见动作；禁止说/告诉/宣布等转述台词；outline 非证据"
        elif role == "insert":
            row["hint"] = "同场反应短句或空着；禁止复述主事件；禁止XX说/觉得；禁止念 caps"
        else:
            row["hint"] = "同 beat 连续主镜请合并 from→to；事实只来自 asr/caps；禁止心里/觉得"
            row["min_chars"] = max(8, int(round(dur * CHARS_PER_SEC * MIN_VO_FILL)))
        rows.append(row)

    # Annotate merge spans so the LLM sees one budget for consecutive same-beat mainline.
    index = 0
    while index < len(rows):
        role = str(rows[index].get("role") or "")
        if role in {"insert", "bridge"}:
            index += 1
            continue
        beat_id = rows[index].get("beat_id")
        end = index
        total_dur = float(rows[index].get("dur") or 0.0)
        cursor = index + 1
        while cursor < len(rows):
            nxt_role = str(rows[cursor].get("role") or "")
            if nxt_role in {"insert", "bridge"}:
                break
            if beat_id is None or rows[cursor].get("beat_id") != beat_id:
                break
            total_dur += float(rows[cursor].get("dur") or 0.0)
            end = cursor
            cursor += 1
        if end > index:
            rows[index]["span_to"] = rows[end]["i"]
            # Merge evidence across the span so the caption LLM sees all asr/caps.
            span_asr: list[dict[str, Any]] = []
            span_caps: list[dict[str, Any]] = []
            seen_asr: set[str] = set()
            seen_cap: set[str] = set()
            for covered in range(index, end + 1):
                for item in rows[covered].get("asr") or []:
                    key = f"{item.get('t')}|{item.get('text')}"
                    if key in seen_asr:
                        continue
                    seen_asr.add(key)
                    span_asr.append(item)
                for item in rows[covered].get("caps") or []:
                    key = f"{item.get('i')}|{item.get('cap')}"
                    if key in seen_cap:
                        continue
                    seen_cap.add(key)
                    span_caps.append(item)
            if span_asr:
                rows[index]["asr"] = span_asr
            if span_caps:
                rows[index]["caps"] = span_caps
            has_asr = bool(span_asr)
            has_caps = bool(span_caps)
            rows[index]["budget"] = tts_char_budget(total_dur)
            if not has_asr and not has_caps:
                rows[index]["budget"] = min(int(rows[index]["budget"] or 0), 8)
                rows[index].pop("min_chars", None)
                rows[index]["hint"] = (
                    f"同 beat 主镜合并 from={rows[index]['i']} to={rows[end]['i']}；"
                    "无 asr/caps：text 必须空着；禁止用 outline 编剧情"
                )
            else:
                rows[index]["min_chars"] = max(
                    8,
                    int(round(total_dur * CHARS_PER_SEC * MIN_VO_FILL)),
                )
                rows[index]["hint"] = (
                    f"同 beat 主镜必须合并一条：from={rows[index]['i']} to={rows[end]['i']}；"
                    f"至少 {rows[index]['min_chars']} 字；事实只来自 asr/caps；禁止用 outline 编台词"
                )
            for covered in range(index + 1, end + 1):
                rows[covered]["covered_by"] = rows[index]["i"]
                rows[covered]["budget"] = 0
                rows[covered]["hint"] = f"已并进 caption from={rows[index]['i']}；本行不要单独写旁白"
        index = end + 1
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

    A shot that is already near the fill target does not absorb later empty cuts.
    Overflow still covers later empty bridges that were added for speaking time.
    """
    picture = max(0.0, float(picture_sec or 0.0))
    need = vo_needed_sec(text)
    if picture <= 0.08:
        return need > 0.08
    return need > picture * VO_COVER_RATIO + 0.08


def _vo_underfills_picture(text: str, picture_sec: float) -> bool:
    """True when speaking time is far shorter than the picture it claims to cover."""
    picture = max(0.0, float(picture_sec or 0.0))
    speak = vo_sec(text)
    if picture <= 0.35 or speak <= 0:
        return False
    return speak < picture * MIN_VO_FILL - 0.08


def _max_picture_for_vo(text: str) -> float:
    """Picture seconds this line should cover so fill stays near the TTS target."""
    speak = vo_sec(text)
    if speak <= 0:
        return 0.0
    return round(speak / MIN_VO_FILL, 2)


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
        if out[-1] not in "。！？!?…":
            out += "。"
        out += body
    return out


def _normalize_vo_key(text: str) -> str:
    body = re.sub(r"[\s，,。！？!?…；;：:、]+", "", str(text or "").strip())
    body = body.replace("番", "号").replace("兩", "两")
    return body


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
        kept.append(piece)
        used += take
        if used >= budget:
            break
    return "".join(kept).strip() or body


def _take_vo_chars(text: str, budget: int) -> str:
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    buf: list[str] = []
    count = 0
    for ch in body:
        step = 1 if ("\u4e00" <= ch <= "\u9fff" or ch.isalnum()) else 0
        if count + step > budget:
            break
        buf.append(ch)
        count += step
    return "".join(buf).strip()


def _punctuate_vo_sentence(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body[-1] not in "。！？!?…":
        return body + "。"
    return body


def _vo_sentence_pieces(text: str) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    parts = [item.strip() for item in re.split(r"(?<=[。！？!?；;])", body) if str(item or "").strip()]
    return parts or [body]


def _break_long_vo_sentence(text: str, max_chars: int = MAX_VO_SENTENCE_CHARS) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    if _counted_chars(body) <= max_chars:
        return [_punctuate_vo_sentence(body)]
    clauses = [item.strip() for item in re.split(r"[，、,]", body) if item.strip()]
    if len(clauses) <= 1:
        return [_punctuate_vo_sentence(_take_vo_chars(body, max_chars))]
    out: list[str] = []
    buf = ""
    for clause in clauses:
        cand = clause if not buf else f"{buf}，{clause}"
        if buf and _counted_chars(cand) > max_chars:
            out.append(_punctuate_vo_sentence(buf))
            buf = clause
            continue
        buf = cand
    if buf:
        if _counted_chars(buf) > max_chars:
            out.append(_punctuate_vo_sentence(_take_vo_chars(buf, max_chars)))
        else:
            out.append(_punctuate_vo_sentence(buf))
    return out


def tighten_vo_text(
    text: str,
    budget: int,
    *,
    max_sentence_chars: int = MAX_VO_SENTENCE_CHARS,
) -> str:
    """Keep short sentences that fit the speaking budget; drop leftover overflow."""
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    sentences: list[str] = []
    for piece in _vo_sentence_pieces(body):
        sentences.extend(_break_long_vo_sentence(piece, max_sentence_chars))
    if not sentences:
        return trim_vo_to_budget(body, budget)
    kept: list[str] = []
    used = 0
    for sent in sentences:
        take = _counted_chars(sent)
        if kept and used + take > budget:
            break
        if not kept and take > budget:
            return _punctuate_vo_sentence(_take_vo_chars(sent, budget))
        kept.append(sent)
        used += take
        if used >= budget:
            break
    return "".join(kept).strip()


def clamp_recap_vo_to_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]


def fit_recap_vo_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]


def _clip_vo_text(clip: Mapping[str, Any], *, use_draft: bool = False) -> str:
    if use_draft:
        return str(clip.get("vo_draft") or clip.get("vo") or "").strip()
    return str(clip.get("vo") or clip.get("vo_draft") or "").strip()


def _fold_short_captions(
    captions: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join flash-length captions into the previous (or next) line instead of chopping them."""
    items = [dict(cap) for cap in captions if str(cap.get("text") or "").strip()]
    if len(items) < 2:
        return items

    def _dur(cap: Mapping[str, Any]) -> float:
        return max(0.0, float(cap.get("tl_out") or 0.0) - float(cap.get("tl_in") or 0.0))

    def _is_insert_cap(cap: Mapping[str, Any]) -> bool:
        if not clips:
            return False
        try:
            start = int(cap.get("from") or 1) - 1
            end = int(cap.get("to") or start + 1) - 1
        except (TypeError, ValueError):
            return False
        if start < 0 or end >= len(clips) or start > end:
            return False
        return all(_looks_like_insert_cut(clips[index]) for index in range(start, end + 1))

    out: list[dict[str, Any]] = [items[0]]
    for cap in items[1:]:
        if _dur(cap) < MIN_STANDALONE_CLIP_SEC and not _is_insert_cap(cap):
            prev = out[-1]
            prev["text"] = _join_vo(str(prev.get("text") or ""), str(cap.get("text") or ""))
            prev["to"] = cap.get("to", prev.get("to"))
            prev["tl_out"] = round(float(cap.get("tl_out") or prev.get("tl_out") or 0.0), 3)
            continue
        out.append(cap)
    if len(out) >= 2 and _dur(out[0]) < MIN_STANDALONE_CLIP_SEC and not _is_insert_cap(out[0]):
        head, nxt = out[0], out[1]
        nxt["text"] = _join_vo(str(head.get("text") or ""), str(nxt.get("text") or ""))
        nxt["from"] = head.get("from", nxt.get("from"))
        nxt["tl_in"] = round(float(head.get("tl_in") or nxt.get("tl_in") or 0.0), 3)
        out = [nxt, *out[2:]]
    return out


def pack_captions_for_tts(
    clips: Sequence[Mapping[str, Any]],
    *,
    use_draft: bool = False,
) -> list[dict[str, Any]]:
    """Keep VO on its own shot.

    Later empty same-beat cuts are covered only while this line still overflows
    ~87% of the picture it already has. Distinct VO shots keep their own caption
    unless a line is shorter than MIN_STANDALONE_CLIP_SEC; those fold into a neighbor
    instead of becoming a chopped flash subtitle.
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
            if _looks_like_insert_cut(items[cursor]):
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
    return _fold_short_captions(captions, items)


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
        if start_i >= len(items):
            continue
        end_i = min(max(start_i, end_i if end_i is not None else start_i), len(items) - 1)
        # Same-beat mainline may span; stop before a different beat or a voiced insert.
        beat_id = items[start_i].get("beat_id")
        stop = start_i
        for index in range(start_i, end_i + 1):
            if beat_id is not None and items[index].get("beat_id") != beat_id:
                break
            if index > start_i and _looks_like_insert_cut(items[index]):
                break
            if index > start_i and _is_bridge_clip(items[index]):
                break
            stop = index
        end_i = stop
        start = float(items[start_i].get("tl_in") or 0.0)
        end = float(items[end_i].get("tl_out") or 0.0)
        clamped = clamp_caption_spans_to_vo(
            [
                {
                    "text": body,
                    "from": start_i + 1,
                    "to": end_i + 1,
                    "tl_in": round(start, 3),
                    "tl_out": round(end, 3),
                }
            ],
            items,
        )
        if not clamped:
            continue
        row = clamped[0]
        out.append(row)
        last_end = int(row["to"]) - 1
    if not out:
        raise RuntimeError("LLM 字幕没有可用条目。")
    return out


def clamp_caption_spans_to_vo(
    captions: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Shrink caption spans so short VO cannot pretend to cover long stretches of picture."""
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for cap in captions:
        if not isinstance(cap, Mapping):
            continue
        text = str(cap.get("text") or "").strip()
        if not text:
            continue
        start_i, end_i = _caption_index_span(cap, items)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i), len(items) - 1)
        budget = _max_picture_for_vo(text)
        if budget <= 0:
            continue
        covered = 0.0
        stop = start_i
        for index in range(start_i, end_i + 1):
            covered += _caption_clip_sec(items[index])
            stop = index
            if covered >= budget - 0.05:
                break
        start = float(items[start_i].get("tl_in") or 0.0)
        full_end = float(items[stop].get("tl_out") or 0.0)
        if stop == start_i and _caption_clip_sec(items[start_i]) > budget + 0.15:
            end = min(full_end, start + budget)
        else:
            end = full_end
        if end <= start + 0.04:
            continue
        out.append(
            {
                "text": text,
                "from": start_i + 1,
                "to": stop + 1,
                "tl_in": round(start, 3),
                "tl_out": round(end, 3),
            }
        )
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
        text = sanitize_generic_role_labels(str(cap.get("text") or "").strip())
        if not text:
            continue
        out[start_i]["vo"] = text
        start = float(out[start_i].get("tl_in") or 0.0)
        end = float(out[end_i].get("tl_out") or 0.0)
        if cap.get("tl_in") is not None:
            start = float(cap["tl_in"])
        if cap.get("tl_out") is not None:
            end = float(cap["tl_out"])
        # Keep subtitle window near speaking time across the spanned clips.
        speak_picture = _max_picture_for_vo(text)
        if speak_picture > 0:
            end = min(end, start + max(speak_picture, 0.5))
        span_end = float(out[end_i].get("tl_out") or end)
        end = min(end, span_end)
        if end > start + 0.04:
            out[start_i]["vo_tl_in"] = round(start, 3)
            out[start_i]["vo_tl_out"] = round(end, 3)
        for index in range(start_i + 1, end_i + 1):
            out[index]["vo"] = ""
    return out


def split_underfilled_vo_clips(
    clips: Sequence[Mapping[str, Any]],
    *,
    min_tail_sec: float = MIN_STANDALONE_CLIP_SEC,
) -> list[dict[str, Any]]:
    """Split long shots whose VO is much shorter than the picture, leaving an empty tail for gap-fill."""
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        row = dict(clip)
        text = str(row.get("vo") or "").strip()
        if not text or _looks_like_insert_cut(row) or _is_bridge_clip(row):
            out.append(row)
            continue
        picture = _caption_clip_sec(row)
        budget = _max_picture_for_vo(text)
        if budget <= 0 or not _vo_underfills_picture(text, picture):
            if text and budget > 0:
                start = float(row.get("tl_in") or 0.0)
                end = float(row.get("tl_out") or 0.0)
                vo_end = min(end, start + budget)
                if vo_end > start + 0.04:
                    row["vo_tl_in"] = round(start, 3)
                    row["vo_tl_out"] = round(vo_end, 3)
            out.append(row)
            continue
        tail = picture - budget
        if tail < float(min_tail_sec or 0.0):
            start = float(row.get("tl_in") or 0.0)
            end = float(row.get("tl_out") or 0.0)
            vo_end = min(end, start + budget)
            if vo_end > start + 0.04:
                row["vo_tl_in"] = round(start, 3)
                row["vo_tl_out"] = round(vo_end, 3)
            out.append(row)
            continue
        tl_in = float(row.get("tl_in") or 0.0)
        tl_out = float(row.get("tl_out") or 0.0)
        src_in = float(row.get("src_in") or 0.0)
        src_out = float(row.get("src_out") or 0.0)
        split_at = tl_in + budget
        ratio = budget / max(picture, 0.01)
        src_split = src_in + (src_out - src_in) * ratio
        head = dict(row)
        head["tl_out"] = round(split_at, 3)
        head["src_out"] = round(src_split, 3)
        head["duration"] = round(max(0.0, src_split - src_in), 3)
        head["vo_tl_in"] = round(tl_in, 3)
        head["vo_tl_out"] = round(split_at, 3)
        tail_clip = dict(row)
        tail_clip["tl_in"] = round(split_at, 3)
        tail_clip["tl_out"] = round(tl_out, 3)
        tail_clip["src_in"] = round(src_split, 3)
        tail_clip["src_out"] = round(src_out, 3)
        tail_clip["duration"] = round(max(0.0, src_out - src_split), 3)
        tail_clip["vo"] = ""
        if "vo_draft" in tail_clip:
            tail_clip["vo_draft"] = ""
        tail_clip.pop("vo_tl_in", None)
        tail_clip.pop("vo_tl_out", None)
        name = str(row.get("name") or "").strip()
        if name:
            tail_clip["name"] = f"{name}·续"
        out.append(head)
        out.append(tail_clip)
    return out


def _vo_restates_prior(prior: str, text: str) -> bool:
    left = str(prior or "").strip()
    right = str(text or "").strip()
    if not left or not right:
        return False
    if _vo_covers(left, right) or _vo_covers(right, left):
        return True
    a = _normalize_vo_key(left)
    b = _normalize_vo_key(right)
    if not a or not b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 8 and short in long:
        return True
    # Paraphrase restatement: high char-ngram overlap on short adjacent lines.
    if min(len(a), len(b)) < 10:
        return False
    size = 3
    grams_a = {a[i : i + size] for i in range(len(a) - size + 1)} or {a}
    grams_b = {b[i : i + size] for i in range(len(b) - size + 1)} or {b}
    overlap = len(grams_a & grams_b) / max(1, min(len(grams_a), len(grams_b)))
    return overlap >= 0.45


def scrub_generic_role_labels_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: label cleanup belongs in LLM prompts, not post-processing."""
    return [dict(clip) for clip in clips or []]


def _fallback_role_for_unattested_name(event: str = "", vo: str = "", *, replaced: str = "") -> str:
    del event, vo, replaced
    return "对方"


def attested_people_labels_for_span(
    pack: Mapping[str, Any] | None,
    src_in: float,
    src_out: float,
    people: Sequence[Mapping[str, Any]] | None,
    *,
    event: str = "",
    pad_sec: float = 2.0,
) -> set[str]:
    """People labels proved by ASR speaker/text (or already present in the beat event)."""
    labels = _people_labels(people)
    attested: set[str] = set()
    event_body = str(event or "")
    for label in labels:
        if label and label in event_body:
            attested.add(label)
    evidence = _evidence_for_source_span(
        pack,
        float(src_in or 0.0),
        float(src_out or 0.0),
        pad_sec=pad_sec,
        asr_limit=16,
        cap_limit=1,
    )
    for row in evidence.get("asr") or []:
        if not isinstance(row, Mapping):
            continue
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            attested.add(speaker)
        text = str(row.get("text") or "")
        for label in labels:
            if label and label in text:
                attested.add(label)
    return attested


def scrub_unattested_people_names(
    clips: Sequence[Mapping[str, Any]],
    *,
    people: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """No-op: unattested-name rewriting was a story patch."""
    del people, pack, beats
    return [dict(clip) for clip in clips or []]


def merge_same_beat_mainline_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: spanning VO is the caption/polish LLM's job."""
    return [dict(clip) for clip in clips or []]


def clear_redundant_insert_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: insert restatement cleanup belongs in LLM stages."""
    return [dict(clip) for clip in clips or []]


def finalize_recap_vo_density(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: keep LLM output as-is."""
    return [dict(clip) for clip in clips or []]


def scrub_intra_line_duplicate_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]


def recap_vo_polish_user_prompt(
    clips: Sequence[Mapping[str, Any]],
    *,
    people: Sequence[Mapping[str, Any]] | None = None,
    prev_caption: str = "",
) -> str:
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(clips, 1):
        dur = _caption_clip_sec(clip)
        vo = str(clip.get("vo") or "").strip()
        role = _caption_visual_role(clip) or "main"
        row: dict[str, Any] = {
            "i": index,
            "beat_id": clip.get("beat_id"),
            "role": role,
            "dur": round(dur, 3),
            "vo": vo,
            "budget": tts_char_budget(dur),
        }
        if vo:
            row["min_chars"] = max(8, int(round(dur * CHARS_PER_SEC * MIN_VO_FILL)))
        rows.append(row)
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，本段 {total:.0f} 秒。只润色旁白，不要改镜头。\n"
        "合并近义复读与句内重复，修好病句；可跨同 beat 空镜收成 from→to。\n"
        "不要发明新事实，不要给空镜硬编查漏。初稿偏密可以，方便用户删。\n"
        "没改动的句子也可重新输出以确认；未提到的 i 保持原文。\n"
        + (f"上一句旁白：{prev_caption}\n" if str(prev_caption or "").strip() else "")
        + "\n"
        + json.dumps({"people": list(people or []), "clips": rows}, ensure_ascii=False)
    )


def parse_vo_polish_cues(
    text: str,
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Parse polish edits; empty text is kept so duplicate lines can be cleared."""
    payload = _loads_json_object(text)
    raw = payload.get("captions") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise RuntimeError("LLM 没有返回润色 captions。")
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if "text" not in item and "vo" not in item:
            continue
        body = sanitize_generic_role_labels(str(item.get("text") if "text" in item else item.get("vo") or "").strip())
        start_i, end_i = _caption_index_span(item, items)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i if end_i is not None else start_i), len(items) - 1)
        out.append(
            {
                "text": body,
                "from": start_i + 1,
                "to": end_i + 1,
            }
        )
    return out


def apply_vo_polish_cues(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply polish edits without wiping clips the model did not mention."""
    out = [dict(clip) for clip in clips]
    if not captions:
        return out
    planned: list[tuple[int, int, str]] = []
    touched: set[int] = set()
    for cap in captions:
        if not isinstance(cap, Mapping):
            continue
        start_i, end_i = _caption_index_span(cap, out)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i), len(out) - 1)
        text = sanitize_generic_role_labels(str(cap.get("text") or "").strip())
        planned.append((start_i, end_i, text))
        for index in range(start_i, end_i + 1):
            touched.add(index)
    for index in touched:
        out[index]["vo"] = ""
        out[index].pop("vo_tl_in", None)
        out[index].pop("vo_tl_out", None)
    for start_i, end_i, text in planned:
        if not text:
            continue
        out[start_i]["vo"] = text
        start = float(out[start_i].get("tl_in") or 0.0)
        end = float(out[end_i].get("tl_out") or start)
        speak_picture = _max_picture_for_vo(text)
        if speak_picture > 0:
            end = min(end, start + max(speak_picture, 0.5))
        if end > start + 0.04:
            out[start_i]["vo_tl_in"] = round(start, 3)
            out[start_i]["vo_tl_out"] = round(end, 3)
    return out


def polish_recap_vo(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Final LLM pass: polish narration text only. Shots stay locked."""
    work = [dict(clip) for clip in clips]
    if not any(str(clip.get("vo") or "").strip() for clip in work):
        return work
    if progress_callback:
        progress_callback(91, "polish")
    polish_system = resolve_recap_prompt(
        system_prompt,
        default_recap_polish_prompt(resolve_recap_caption_language(config)),
    )
    prev = ""
    offset = 0
    for wave in split_clips_for_captions(work):
        if not any(str(clip.get("vo") or "").strip() for clip in wave):
            offset += len(wave)
            continue
        try:
            text = call_remote_llm(
                system=polish_system,
                user=recap_vo_polish_user_prompt(wave, people=people, prev_caption=prev),
                config=config,
                temperature=0.2,
                max_tokens=4096,
                should_stop_callback=should_stop_callback,
            )
            caps = parse_vo_polish_cues(text, wave)
            stamped = apply_vo_polish_cues(wave, caps)
            for local_i, row in enumerate(stamped):
                work[offset + local_i] = row
            for clip in stamped:
                body = str(clip.get("vo") or "").strip()
                if body:
                    prev = body
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            pass
        offset += len(wave)
    work = scrub_unattested_people_names(work, people=people, pack=pack, beats=beats)
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


def scrub_adjacent_duplicate_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]


def scrub_restated_insert_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]


def fit_recap_captions_to_tts(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    laid = [dict(clip) for clip in clips]
    # VO-first: land beat drafts before polish so a failed LLM wave cannot wipe narration.
    packed = pack_captions_for_tts(laid, use_draft=True)
    work = apply_caption_cues(laid, packed) if packed else laid
    if not laid:
        return work
    if progress_callback:
        progress_callback(86, "captions")
    rewritten: list[dict[str, Any]] = []
    prev = ""
    offset = 0
    waves = split_clips_for_captions(laid)
    for wave in waves:
        try:
            text = call_remote_llm(
                system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
                user=recap_caption_user_prompt(
                    wave,
                    people=people,
                    prev_caption=prev,
                    beats=beats,
                    pack=pack,
                ),
                config=config,
                temperature=0.3,
                max_tokens=4096,
                should_stop_callback=should_stop_callback,
            )
            caps = parse_caption_cues(text, wave)
            for cap in caps:
                start = int(cap.get("from") or 1) + offset
                end = int(cap.get("to") or start) + offset
                cap["from"] = start
                cap["to"] = end
                prev = str(cap.get("text") or prev)
            rewritten.extend(caps)
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            # One bad wave must not wipe the whole caption pass.
            pass
        offset += len(wave)
    if rewritten:
        polished = apply_caption_cues(laid, rewritten)
        # Keep draft when polish emptied a previously voiced unit.
        for index, clip in enumerate(polished):
            if str(clip.get("vo") or "").strip():
                continue
            seed = str(
                work[index].get("vo")
                or laid[index].get("vo")
                or laid[index].get("vo_draft")
                or ""
            ).strip()
            if seed:
                clip["vo"] = seed
                clip.setdefault("vo_draft", seed)
        work = polished
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


def _is_bridge_clip(clip: Mapping[str, Any]) -> bool:
    name = str(clip.get("name") or "").strip()
    reason = str(clip.get("reason") or "").strip()
    return name == "过渡" or reason == "过渡"


def recap_gap_clip_indices(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]] | None = None,
) -> list[int]:
    """True story holes only — not same-beat follow shots reserved for cross-shot VO."""
    items = list(clips or [])
    caps = list(captions if captions is not None else pack_captions_for_tts(items))
    covered: set[int] = set()
    for cap in caps:
        start_i, end_i = _caption_index_span(cap, items)
        if start_i is None:
            continue
        for index in range(start_i, min(end_i, len(items) - 1) + 1):
            covered.add(index)
    beat_has_main_vo: set[Any] = set()
    for clip in items:
        if _looks_like_insert_cut(clip) or _is_bridge_clip(clip):
            continue
        if str(clip.get("vo") or "").strip():
            beat_has_main_vo.add(clip.get("beat_id"))
    gaps: list[int] = []
    for index, clip in enumerate(items):
        if index in covered or _is_bridge_clip(clip):
            continue
        if str(clip.get("vo") or "").strip():
            continue
        if _caption_clip_sec(clip) < 1.6:
            continue
        beat_id = clip.get("beat_id")
        # Same-beat follow / insert after a voiced main: keep empty so prior VO can span.
        if beat_id is not None and beat_id in beat_has_main_vo:
            continue
        # Same-beat earlier clip already has VO: not a story hole.
        if beat_id is not None and any(
            str(items[pos].get("vo") or "").strip() and items[pos].get("beat_id") == beat_id
            for pos in range(index)
        ):
            continue
        gaps.append(index)
    return gaps


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
        picture = _caption_clip_sec(items[index])
        if picture < MIN_STANDALONE_CLIP_SEC and not _looks_like_insert_cut(items[index]):
            continue
        if picture < 1.6:
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
        text = sanitize_generic_role_labels(str(fill.get("text") or "").strip())
        if not text or str(out[index].get("vo") or "").strip():
            continue
        out[index]["vo"] = text
        if not str(out[index].get("vo_draft") or "").strip():
            out[index]["vo_draft"] = text
    return out


def fill_recap_vo_gaps(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Fill shots that still have no narration after the caption pass."""
    work = [dict(clip) for clip in clips]
    captions = pack_captions_for_tts(work)
    gap_indices = recap_gap_clip_indices(work, captions)
    if not gap_indices:
        return work
    if progress_callback:
        progress_callback(88, "gaps")
    try:
        text = call_remote_llm(
            system=default_recap_gap_prompt(resolve_recap_caption_language(config)),
            user=recap_gap_user_prompt(
                work,
                captions,
                gap_indices,
                people=people,
                beats=beats,
                pack=pack,
            ),
            config=config,
            temperature=0.3,
            max_tokens=2048,
            should_stop_callback=should_stop_callback,
        )
        fills = parse_gap_fills(text, work, allowed=set(gap_indices))
        if fills:
            work = apply_gap_fills(work, fills)
    except UnderstandingStoppedError:
        raise
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


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
        insert = _looks_like_insert_cut(item)
        floor = MIN_CLIP_SEC if vo else min(MIN_CLIP_SEC, max(2.4, span))
        if insert:
            floor = min(floor, max(2.0, span if span >= 2.0 else 2.0))
        if span > max_keep + 0.15:
            # Keep the establishing head (enter/setup); do not chop into a later stub.
            src_out = round(src_in + max_keep, 2)
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
        role = _clip_role(item)
        if not role and insert:
            role = "insert"
        row = {
            "name": name[:40],
            "beat_id": beat_id,
            "chunk_index": chunk_index_i,
            "src_in": round(src_in, 3),
            "src_out": round(src_out, 3),
            "duration": round(src_out - src_in, 3),
            "vo": vo,
            "reason": reason,
        }
        if role:
            row["role"] = role
        out.append(row)
    if not out:
        raise RuntimeError("LLM 剪辑表没有可用镜头。")
    return out


def stash_match_vo_as_draft(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep accidental match VO as caption seed; official narration is written later."""
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        item = dict(clip)
        seed = str(item.get("vo_draft") or item.get("vo") or "").strip()
        item["vo_draft"] = seed
        item["vo"] = ""
        out.append(item)
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


def _shrink_clip(
    clip: dict[str, Any],
    extra: float,
    min_len: float = MIN_CLIP_SEC,
    *,
    from_head: bool = False,
) -> float:
    """Trim picture. ``from_head=True`` keeps the landing tail; default keeps the enter head."""
    have = _clip_len(clip)
    take = min(max(0.0, extra), max(0.0, have - min_len))
    if take <= 0.05:
        return 0.0
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    if from_head:
        clip["src_in"] = round(src_in + take, 3)
        clip["duration"] = round(src_out - float(clip["src_in"]), 3)
    else:
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

    def _has_vo(clip: Mapping[str, Any]) -> bool:
        return bool(str(clip.get("vo") or clip.get("vo_draft") or "").strip())

    inserts = [clip for clip in group if _looks_like_insert_cut(clip)]
    masters = [clip for clip in group if clip not in inserts]
    # Never delete the first/last master — those are enter / land for the beat.
    head_id = id(masters[0]) if masters else None
    tail_id = id(masters[-1]) if masters else None
    edge_ids = {item for item in (head_id, tail_id) if item is not None}
    empties = [clip for clip in masters if not _has_vo(clip) and id(clip) not in edge_ids]
    voiced = [clip for clip in masters if _has_vo(clip)]
    # Floor for voiced masters: keep enough picture for the narration line.
    def _vo_floor(clip: Mapping[str, Any]) -> float:
        body = str(clip.get("vo") or clip.get("vo_draft") or "").strip()
        if not body:
            return MIN_CLIP_SEC
        return max(MIN_CLIP_SEC, min(MAX_CLIP_SEC, vo_needed_sec(body) * 0.85))

    # Shrink inserts first, then spare empty middles, then voiced — protect head/tail.
    for clip in inserts:
        if extra <= 0.05:
            return
        extra -= _shrink_clip(clip, extra, min_len=2.0)
    for clip in sorted(empties, key=_clip_len, reverse=True):
        if extra <= 0.05:
            return
        extra -= _shrink_clip(clip, extra, min_len=2.4)
    for clip in sorted(voiced, key=_clip_len, reverse=True):
        if extra <= 0.05:
            return
        if id(clip) in edge_ids and len(voiced) > 1:
            continue
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        extra -= _shrink_clip(clip, extra, min_len=_vo_floor(clip), from_head=from_head)
    for clip in voiced:
        if extra <= 0.05:
            return
        if id(clip) not in edge_ids:
            continue
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        # Never chop the sole/edge VO master below speak floor.
        extra -= _shrink_clip(clip, extra, min_len=_vo_floor(clip), from_head=from_head)
    # Still over: shrink edge masters (sole enter/land, or empty head/tail). Never delete them.
    for clip in masters:
        if extra <= 0.05:
            return
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        floor = _vo_floor(clip) if _has_vo(clip) else MIN_CLIP_SEC
        extra -= _shrink_clip(clip, extra, min_len=floor, from_head=from_head)
    while extra > 0.25 and len(group) > 1 and empties:
        victim = max(empties, key=_clip_len)
        extra -= _clip_len(victim)
        empties.remove(victim)
        group.remove(victim)
        out.remove(victim)


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

    Later empty same-beat shots count only while the line still overflows ~87%
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
    """If this line needs more time at configured TTS speed than its shot, extend that same shot forward."""
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


def _clip_src_span(clip: Mapping[str, Any]) -> tuple[float, float]:
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    if src_out <= src_in:
        duration = float(clip.get("duration") or 0.0)
        if duration > 0:
            src_out = src_in + duration
    return src_in, src_out


def _source_overlap_sec(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    return _overlap_sec(_clip_src_span(left), _clip_src_span(right))


def _source_gap_sec(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    a_in, a_out = _clip_src_span(left)
    b_in, b_out = _clip_src_span(right)
    if a_out < b_in:
        return b_in - a_out
    if b_out < a_in:
        return a_in - b_out
    return 0.0


def _source_adjacent_clips(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    gap_sec: float = SOURCE_MERGE_GAP_SEC,
) -> bool:
    if _source_overlap_sec(left, right) > 0.04:
        return True
    return _source_gap_sec(left, right) <= max(0.0, float(gap_sec))


_INSERT_ROLES = {
    "insert",
    "closeup",
    "close-up",
    "cu",
    "reaction",
    "特写",
    "反应",
    "近景",
    "表情",
}
_BRIDGE_ROLES = {"bridge", "transition", "换场", "过场", "过渡"}


def _clip_role(clip: Mapping[str, Any]) -> str:
    raw = str(clip.get("role") or "").strip().lower()
    if raw in _INSERT_ROLES:
        return "insert"
    if raw in _BRIDGE_ROLES:
        return "bridge"
    return raw


def _looks_like_insert_cut(clip: Mapping[str, Any]) -> bool:
    """Only trust explicit role=insert from the match LLM."""
    return _clip_role(clip) == "insert"


def _is_flash_cut(clip: Mapping[str, Any]) -> bool:
    if _looks_like_insert_cut(clip):
        return False
    return _clip_len(clip) < MIN_FLASH_CLIP_SEC or (
        _is_bridge_clip(clip) and _clip_len(clip) <= MIN_FLASH_CLIP_SEC + 0.05
    )


def _merge_cut_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    a_in, a_out = _clip_src_span(left)
    b_in, b_out = _clip_src_span(right)
    src_in = min(a_in, b_in)
    src_out = max(a_out, b_out)
    left_vo = _preferred_clip_vo(left)
    right_vo = _preferred_clip_vo(right)
    vo = _join_vo(left_vo, right_vo)
    head: Mapping[str, Any] = left
    if _is_bridge_clip(left) and not _is_bridge_clip(right):
        head = right
    elif not left_vo and right_vo:
        head = right
    out = dict(head)
    out["src_in"] = round(src_in, 3)
    out["src_out"] = round(src_out, 3)
    out["duration"] = round(src_out - src_in, 3)
    out["vo"] = vo
    draft = _join_vo(
        str(left.get("vo_draft") or ""),
        str(right.get("vo_draft") or ""),
        vo,
    )
    if draft:
        out["vo_draft"] = draft
    if vo and _is_bridge_clip(out):
        other = right if head is left else left
        out["name"] = str(other.get("name") or out.get("name") or "")
        out["reason"] = str(other.get("reason") or "")
    if not out.get("beat_id") and (left.get("beat_id") or right.get("beat_id")):
        out["beat_id"] = left.get("beat_id") or right.get("beat_id")
    out.pop("tl_in", None)
    out.pop("tl_out", None)
    out.pop("vo_tl_in", None)
    out.pop("vo_tl_out", None)
    return out


def _attach_cut_vo(target: dict[str, Any], victim: Mapping[str, Any]) -> None:
    vo = _join_vo(_preferred_clip_vo(target), _preferred_clip_vo(victim))
    target["vo"] = vo
    draft = _join_vo(
        str(target.get("vo_draft") or ""),
        str(victim.get("vo_draft") or ""),
        vo,
    )
    if draft:
        target["vo_draft"] = draft


def _cut_to_next_shot(prev: dict[str, Any], clip: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve overlapping neighbors. Same-beat masters: keep both enter and land when possible."""
    p_in, p_out = _clip_src_span(prev)
    c_in, c_out = _clip_src_span(clip)
    if c_in >= p_out - 0.04:
        return dict(clip)
    insert = _looks_like_insert_cut(clip)
    if insert:
        if c_in >= p_in + 0.8:
            prev["src_out"] = round(min(c_in, p_out), 3)
            prev["duration"] = round(float(prev["src_out"]) - p_in, 3)
            return dict(clip)
        return dict(clip)
    if c_in <= p_in + 0.25 and c_out <= p_out + 0.25:
        return None
    same_beat = (
        _clip_beat_id(prev) is not None
        and _clip_beat_id(prev) == _clip_beat_id(clip)
        and not _looks_like_insert_cut(prev)
    )
    if c_in >= p_in + 0.35 and (c_in - p_in) >= 1.6:
        prev["src_out"] = round(c_in, 3)
        prev["duration"] = round(c_in - p_in, 3)
        return dict(clip)
    remain = c_out - p_out
    if remain >= MIN_FLASH_CLIP_SEC:
        out = dict(clip)
        out["src_in"] = round(p_out, 3)
        out["src_out"] = round(c_out, 3)
        out["duration"] = round(remain, 3)
        return out
    # Same beat: do not drop the later land/enter shot just because overlap is messy.
    if same_beat and (c_in - p_in) >= MIN_FLASH_CLIP_SEC:
        prev["src_out"] = round(c_in, 3)
        prev["duration"] = round(c_in - p_in, 3)
        return dict(clip)
    if same_beat and (p_out - p_in) >= MIN_FLASH_CLIP_SEC + 0.8:
        keep_head = max(MIN_FLASH_CLIP_SEC, (p_out - p_in) - max(remain, MIN_FLASH_CLIP_SEC))
        split = p_in + keep_head
        if c_out - split >= MIN_FLASH_CLIP_SEC:
            prev["src_out"] = round(split, 3)
            prev["duration"] = round(split - p_in, 3)
            out = dict(clip)
            out["src_in"] = round(split, 3)
            out["src_out"] = round(c_out, 3)
            out["duration"] = round(c_out - split, 3)
            return out
    return None


def _should_merge_source_clips(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Only glue flash leftovers or the same line replayed over overlapping source."""
    overlap = _source_overlap_sec(left, right)
    adjacent = overlap >= SOURCE_OVERLAP_MERGE_SEC or _source_adjacent_clips(left, right)
    if not adjacent:
        return False
    if _looks_like_insert_cut(left) or _looks_like_insert_cut(right):
        return False
    if _is_flash_cut(left) or _is_flash_cut(right):
        return True
    left_vo = _preferred_clip_vo(left)
    right_vo = _preferred_clip_vo(right)
    if overlap >= SOURCE_OVERLAP_MERGE_SEC and left_vo and right_vo:
        return _vo_covers(left_vo, right_vo) or _vo_covers(right_vo, left_vo)
    return False


def dedupe_overlapping_recap_cuts(
    cuts: Sequence[Mapping[str, Any]],
    *,
    overlap_ratio: float = 0.45,
) -> list[dict[str, Any]]:
    """Drop near-duplicate source windows (same beat, heavy overlap). Keep inserts when distinct."""
    items = [dict(clip) for clip in cuts or []]
    if len(items) < 2:
        return items
    drop: set[int] = set()
    for i in range(len(items)):
        if i in drop:
            continue
        for j in range(i + 1, len(items)):
            if j in drop:
                continue
            left = items[i]
            right = items[j]
            left_beat = _clip_beat_id(left)
            right_beat = _clip_beat_id(right)
            if left_beat is not None and right_beat is not None and left_beat != right_beat:
                continue
            overlap = _source_overlap_sec(left, right)
            if overlap <= 0.08:
                continue
            left_len = max(0.01, _clip_len(left))
            right_len = max(0.01, _clip_len(right))
            ratio = overlap / min(left_len, right_len)
            if ratio < float(overlap_ratio):
                continue
            left_insert = _looks_like_insert_cut(left)
            right_insert = _looks_like_insert_cut(right)
            # Keep a short insert over a long master when ranges mostly nest.
            if left_insert != right_insert:
                if left_insert and left_len <= right_len * 0.75:
                    continue
                if right_insert and right_len <= left_len * 0.75:
                    continue
            # Drop the shorter / later duplicate.
            if right_len < left_len * 0.92:
                drop.add(j)
            elif left_len < right_len * 0.92:
                drop.add(i)
                break
            else:
                drop.add(j)
    return [clip for index, clip in enumerate(items) if index not in drop]


def coalesce_recap_cuts(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop replayed source, keep real cuts, absorb flash-length leftovers."""
    items = dedupe_overlapping_recap_cuts(
        [
            dict(clip)
            for clip in cuts or []
            if _clip_len(clip) > 0.04 or str(clip.get("vo") or clip.get("vo_draft") or "").strip()
        ]
    )
    items.sort(
        key=lambda clip: (
            float(clip.get("src_in") or 0.0),
            int(clip.get("beat_id") or 0),
        )
    )
    merged: list[dict[str, Any]] = []
    for clip in items:
        if merged and _should_merge_source_clips(merged[-1], clip):
            merged[-1] = _merge_cut_pair(merged[-1], clip)
            continue
        if merged:
            nxt = _cut_to_next_shot(merged[-1], clip)
            if nxt is None:
                _attach_cut_vo(merged[-1], clip)
                continue
            clip = nxt
        merged.append(dict(clip))
    index = 0
    while index < len(merged):
        clip = merged[index]
        if not _is_flash_cut(clip) or len(merged) == 1:
            index += 1
            continue
        prev = merged[index - 1] if index > 0 else None
        nxt = merged[index + 1] if index + 1 < len(merged) else None
        if prev is None and nxt is None:
            break
        into_next = prev is None
        if prev is not None and nxt is not None:
            prev_adj = _source_adjacent_clips(prev, clip)
            nxt_adj = _source_adjacent_clips(clip, nxt)
            into_next = nxt_adj and not prev_adj
        if into_next:
            target = nxt
            if target is None:
                index += 1
                continue
            if _source_adjacent_clips(clip, target):
                merged[index] = _merge_cut_pair(clip, target)
            else:
                _attach_cut_vo(target, clip)
                del merged[index]
                continue
            del merged[index + 1]
            continue
        if prev is None:
            index += 1
            continue
        if _source_adjacent_clips(prev, clip):
            merged[index - 1] = _merge_cut_pair(prev, clip)
        else:
            _attach_cut_vo(prev, clip)
        del merged[index]
        continue
    return merged


def ensure_main_cut_per_beat(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: each-beat main shot is a Match prompt rule, not a code patch."""
    return [dict(clip) for clip in cuts or []]


def refine_recap_cuts(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Keep cuts and grow picture if needed. Do not edit the script."""
    out = coalesce_recap_cuts(list(cuts or []))
    out = clamp_cuts_to_beat_window(out, pack, beats)
    out = snap_cuts_to_capped_chunks(out, pack, beats)
    out = clamp_insert_cuts_to_beat(out, pack, beats)
    out = pad_cuts_for_tts(out, pack, beats)
    return coalesce_recap_cuts(out)


def snap_cuts_to_capped_chunks(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    min_gain: float = 0.10,
) -> list[dict[str, Any]]:
    """Realign cuts to the best VLM-captioned chunk inside each beat.

    Having caps is not enough — Match still picks lookalike wrong scenes.
    Prefer the capped chunk whose ``cap`` best matches the beat event /
    needed_visual, and replace the current pick when the gain is clear.
    """
    items = [dict(clip) for clip in cuts or []]
    if not items or not beats:
        return items
    duration = float(pack.get("duration_sec") or 0.0)
    by_id = _beats_by_id(beats)
    capped: list[tuple[tuple[float, float], dict[str, Any]]] = []
    for chunk in pack.get("chunks") or []:
        if not keep_chunk_for_recap(chunk, duration):
            continue
        if not str(chunk.get("cap") or "").strip():
            continue
        span = _time_span(chunk.get("t"))
        if not span or span[1] - span[0] < MIN_FLASH_CLIP_SEC:
            continue
        capped.append((span, dict(chunk)))
    if not capped:
        return items

    gain = max(0.04, float(min_gain or 0.10))
    out: list[dict[str, Any]] = []
    for clip in items:
        row = dict(clip)
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if src_out <= src_in + 0.2:
            out.append(row)
            continue
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) if beat_id else None
        beat_span = _time_span((beat or {}).get("t")) if beat else None
        if not beat_span:
            out.append(row)
            continue

        anchor = _beat_visual_anchor(beat, row)
        current_ev = _evidence_for_source_span(
            pack, src_in, src_out, pad_sec=1.0, asr_limit=8, cap_limit=6
        )
        current_cap = " ".join(str(item.get("cap") or "") for item in current_ev.get("caps") or [])
        current_asr = " ".join(str(item.get("text") or "") for item in current_ev.get("asr") or [])
        current_score = _cap_match_score_for_anchor(anchor, current_cap, asr_blob=current_asr)

        want = max(MIN_FLASH_CLIP_SEC, min(src_out - src_in, MAX_CLIP_SEC))
        best: tuple[float, float, dict[str, Any], float] | None = None
        for span, chunk in capped:
            overlap = _overlap_sec(span, beat_span)
            if overlap <= 0.5:
                continue
            cap = str(chunk.get("cap") or "")
            # Local ASR on the candidate chunk helps when event is dialogue-shaped.
            cand_ev = _evidence_for_source_span(
                pack, span[0], span[1], pad_sec=0.5, asr_limit=8, cap_limit=1
            )
            cand_asr = " ".join(str(item.get("text") or "") for item in cand_ev.get("asr") or [])
            score = _cap_match_score_for_anchor(anchor, cap, asr_blob=cand_asr)
            # Slight preference for staying near the LLM pick when scores are close.
            score += 0.04 * min(1.0, _overlap_sec(span, (src_in, src_out)) / max(0.2, want))
            if best is None or score > best[3]:
                best = (span[0], span[1], chunk, score)

        if best is None:
            out.append(row)
            continue
        lo, hi, chunk, best_score = best
        should_move = False
        if not current_cap.strip() and best_score >= 0.12:
            should_move = True
        elif best_score >= current_score + gain and best_score >= 0.16:
            should_move = True
        elif current_score < 0.14 and best_score >= 0.22:
            should_move = True
        if not should_move:
            out.append(row)
            continue

        take = min(want, hi - lo)
        start = max(lo, min(0.5 * (lo + hi) - take * 0.5, hi - take))
        end = start + take
        # Avoid no-op rewrites.
        if abs(start - src_in) < 0.35 and abs(end - src_out) < 0.35:
            out.append(row)
            continue
        row["src_in"] = round(start, 3)
        row["src_out"] = round(end, 3)
        row["duration"] = round(end - start, 3)
        if chunk.get("i") is not None:
            row["chunk_index"] = chunk.get("i")
        reason = str(row.get("reason") or "").strip()
        tag = "已对齐最佳画面描述"
        if tag not in reason:
            row["reason"] = f"{reason}｜{tag}".strip("｜")
        out.append(row)
    return out


def _snap_src_into_beat_window(
    pack: Mapping[str, Any],
    beat_span: tuple[float, float],
    *,
    want_sec: float,
    pad_sec: float = BEAT_SRC_PAD_SEC,
    preferred: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Place a clip inside beat.t (±pad), preferring overlapping chunks / residual overlap."""
    pad = float(pad_sec)
    lo = float(beat_span[0]) - pad
    hi = float(beat_span[1]) + pad
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    lo = max(float(story_start or 0.0), lo)
    if duration > 0:
        hi = min(float(story_end or duration), hi, duration)
    if hi - lo < MIN_FLASH_CLIP_SEC:
        return None
    want = max(MIN_FLASH_CLIP_SEC, min(float(want_sec or MIN_CLIP_SEC), hi - lo, MAX_CLIP_SEC))

    if preferred:
        try:
            p_in, p_out = float(preferred[0]), float(preferred[1])
        except (TypeError, ValueError, IndexError):
            p_in, p_out = 0.0, 0.0
        if p_out > p_in:
            ov_lo = max(p_in, lo)
            ov_hi = min(p_out, hi)
            if ov_hi - ov_lo >= min(want, MIN_FLASH_CLIP_SEC):
                if ov_hi - ov_lo > want:
                    ov_hi = ov_lo + want
                return round(ov_lo, 3), round(ov_hi, 3)

    best: tuple[float, float] | None = None
    best_overlap = -1.0
    for item in pack.get("chunks") or []:
        if not keep_chunk_for_recap(item, duration):
            continue
        window = _time_span(item.get("t"))
        if not window:
            continue
        overlap = _overlap_sec(window, beat_span)
        if overlap <= 0.4:
            continue
        cand_lo = max(window[0], lo)
        cand_hi = min(window[1], hi)
        if cand_hi - cand_lo < MIN_FLASH_CLIP_SEC:
            continue
        take = min(want, cand_hi - cand_lo)
        # Prefer the middle of the overlapping chunk when room allows.
        mid = 0.5 * (cand_lo + cand_hi)
        start = max(cand_lo, min(mid - take * 0.5, cand_hi - take))
        end = start + take
        if overlap > best_overlap:
            best_overlap = overlap
            best = (round(start, 3), round(end, 3))
    if best:
        return best
    return round(lo, 3), round(min(hi, lo + want), 3)


def clamp_cuts_to_beat_window(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    pad_sec: float = BEAT_SRC_PAD_SEC,
) -> list[dict[str, Any]]:
    """Hard-clamp every cut into its beat.t window so Match cannot borrow later acts."""
    items = [dict(clip) for clip in cuts or []]
    if not items or not beats:
        return items
    by_id = _beats_by_id(beats)
    pad = float(pad_sec)
    out: list[dict[str, Any]] = []
    for clip in items:
        row = dict(clip)
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) if beat_id else None
        span = _time_span((beat or {}).get("t")) if beat else None
        if not span:
            out.append(row)
            continue
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if src_out <= src_in + 0.2:
            out.append(row)
            continue
        expanded = (span[0] - pad, span[1] + pad)
        overlap = _overlap_sec((src_in, src_out), expanded)
        clip_len = src_out - src_in
        if overlap >= min(clip_len * 0.85, clip_len - 0.05) and overlap > 0.4:
            # Mostly inside — trim any spill past the pad.
            trimmed_in = max(src_in, expanded[0])
            trimmed_out = min(src_out, expanded[1])
            if trimmed_out - trimmed_in >= MIN_FLASH_CLIP_SEC:
                row["src_in"] = round(trimmed_in, 3)
                row["src_out"] = round(trimmed_out, 3)
                row["duration"] = round(trimmed_out - trimmed_in, 3)
            out.append(row)
            continue
        placed = _snap_src_into_beat_window(
            pack,
            span,
            want_sec=max(MIN_FLASH_CLIP_SEC, min(clip_len, MAX_CLIP_SEC)),
            pad_sec=pad,
            preferred=(src_in, src_out) if overlap > 0.05 else None,
        )
        if placed is None:
            out.append(row)
            continue
        row["src_in"], row["src_out"] = placed
        row["duration"] = round(placed[1] - placed[0], 3)
        reason = str(row.get("reason") or "").strip()
        if "弱证据" not in reason:
            row["reason"] = f"{reason}｜已钳回拍时间窗".strip("｜")
        out.append(row)
    return out


def clamp_insert_cuts_to_beat(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    max_gap_sec: float = INSERT_MAX_GAP_FROM_MASTER_SEC,
) -> list[dict[str, Any]]:
    """Pull drifting insert cuts back next to the same-beat master, or drop them.

    Inserts more than ``max_gap_sec`` after the master, or completely outside the
    beat ``t`` window with no overlap, are snapped into the post-master window
    when possible. Otherwise they are discarded so late close-ups do not land
    on earlier beats.
    """
    items = [dict(clip) for clip in cuts or []]
    if not items:
        return items
    by_id = _beats_by_id(beats)
    groups: dict[Any, list[int]] = {}
    for index, clip in enumerate(items):
        groups.setdefault(clip.get("beat_id"), []).append(index)

    drop: set[int] = set()
    for beat_id, indices in groups.items():
        masters = [items[i] for i in indices if not _looks_like_insert_cut(items[i])]
        inserts = [i for i in indices if _looks_like_insert_cut(items[i])]
        if not inserts:
            continue
        if not masters:
            # No A-roll to anchor against — keep inserts as-is.
            continue
        master = max(masters, key=lambda clip: float(clip.get("src_out") or 0.0))
        master_end = float(master.get("src_out") or 0.0)
        beat = None
        if beat_id is not None:
            try:
                beat = by_id.get(int(beat_id))
            except (TypeError, ValueError):
                beat = None
        beat_span = _time_span((beat or {}).get("t"))
        for index in inserts:
            clip = items[index]
            try:
                src_in = float(clip.get("src_in") or 0.0)
                src_out = float(clip.get("src_out") or 0.0)
            except (TypeError, ValueError):
                drop.add(index)
                continue
            span = max(0.0, src_out - src_in)
            far_after = src_in > master_end + float(max_gap_sec)
            outside_beat = False
            if beat_span:
                pad = float(max_gap_sec)
                expanded = (beat_span[0] - pad, beat_span[1] + pad)
                outside_beat = _overlap_sec((src_in, src_out), expanded) <= 0.05
            if not far_after and not outside_beat:
                continue
            placed = _place_insert_after_master(
                clip,
                pack,
                master=master,
                beat_span=beat_span,
                want_sec=max(MIN_INSERT_CLIP_SEC, min(span or MIN_INSERT_CLIP_SEC, MAX_CLIP_SEC)),
            )
            if placed is None:
                drop.add(index)
            else:
                items[index] = placed
    return [clip for index, clip in enumerate(items) if index not in drop]


def _place_insert_after_master(
    clip: Mapping[str, Any],
    pack: Mapping[str, Any],
    *,
    master: Mapping[str, Any],
    beat_span: tuple[float, float] | None,
    want_sec: float,
) -> dict[str, Any] | None:
    """Snap an insert into the source window right after the master shot."""
    master_end = float(master.get("src_out") or 0.0)
    window = _neighbor_source_window(
        pack,
        master.get("chunk_index"),
        beat_span,
        strict=False,
    )
    if not window:
        window = _chunk_window(pack, int(master.get("chunk_index") or 0)) if master.get("chunk_index") is not None else None
    if not window:
        return None
    lo, hi = window
    lo, hi = _clamp_window_away_from_op_ed(
        pack,
        lo,
        hi,
        src_in=master_end,
        src_out=master_end,
    )
    start = max(lo, master_end)
    if beat_span:
        start = max(start, beat_span[0])
        hi = min(hi, beat_span[1] + 2.0)
    avail = hi - start
    if avail < MIN_INSERT_CLIP_SEC:
        return None
    dur = min(max(MIN_INSERT_CLIP_SEC, float(want_sec or MIN_INSERT_CLIP_SEC)), avail, MAX_CLIP_SEC)
    end = start + dur
    if _source_hits_op_ed(pack, start, end):
        return None
    out = dict(clip)
    out["src_in"] = round(start, 3)
    out["src_out"] = round(end, 3)
    out["duration"] = round(end - start, 3)
    out["role"] = "insert"
    if out.get("chunk_index") is None and master.get("chunk_index") is not None:
        out["chunk_index"] = master.get("chunk_index")
    out.pop("tl_in", None)
    out.pop("tl_out", None)
    out.pop("vo_tl_in", None)
    out.pop("vo_tl_out", None)
    return out


def apply_recap_duration(
    cuts: list[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
    *,
    target_sec: float = TARGET_RECAP_SEC,
    min_sec: float = MIN_RECAP_SEC,
) -> list[dict[str, Any]]:
    """Fit picture to VO speak time (grow) then trim budget overshoots. Never pad empty beats."""
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
        vo_text = str((beat or {}).get("vo") or "").strip()
        if not vo_text:
            for clip in group:
                vo_text = str(clip.get("vo") or clip.get("vo_draft") or "").strip()
                if vo_text:
                    break
        need = vo_needed_sec(vo_text) if vo_text else 0.0
        have = sum(_clip_len(clip) for clip in group)
        beat_span = _time_span((beat or {}).get("t")) if beat else None
        # Grow toward speak time (capped by budget), not toward empty quota.
        want = min(budget, need) if need > 0.05 else 0.0
        if want > have + 0.25:
            room = want - have
            masters = [clip for clip in group if not _looks_like_insert_cut(clip)]
            targets = masters or list(group)
            for clip in targets:
                if room <= 0.05:
                    break
                grown = _expand_clip(
                    clip,
                    pack,
                    room,
                    beat_span,
                    forward_only=False,
                    max_len=MAX_TTS_CLIP_SEC,
                )
                room -= grown
            have = sum(_clip_len(clip) for clip in group)
        if have > budget + 0.25:
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


def resolve_recap_caption_language(config=None) -> str:
    cfg = config if isinstance(config, Mapping) else load_config()
    understanding = cfg.get("understanding") if isinstance(cfg, Mapping) else None
    remote = understanding.get("remote_vlm") if isinstance(understanding, Mapping) else None
    if isinstance(remote, Mapping):
        return normalize_caption_language(remote.get("caption_language"))
    return CAPTION_LANGUAGE_ZH


def resolve_recap_system_prompt(text: str | None, language: str | None = None) -> str:
    return resolve_recap_prompt(text, default_recap_match_prompt(language))


def _try_story_plan_llm(
    *,
    system: str,
    user: str,
    config,
    should_stop_callback: Callable[[], bool] | None,
    temperature: float,
    max_tokens: int,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
    try:
        text = call_remote_llm(
            system=system,
            user=user,
            config=config,
            temperature=temperature,
            max_tokens=max_tokens,
            should_stop_callback=should_stop_callback,
        )
        return parse_story_plan(text)
    except RuntimeError:
        return None


def normalize_recap_start_from(value: str | None) -> str:
    key = str(value or RECAP_START_PLAN).strip().lower()
    if key in {RECAP_START_MATCH, "matching", "match_only", "match-only", "2"}:
        return RECAP_START_MATCH
    if key in {RECAP_START_CAPTIONS, "caption", "gaps", "3"}:
        return RECAP_START_CAPTIONS
    if key in {RECAP_START_PLAN_ONLY, "plan-only", "planonly"}:
        return RECAP_START_PLAN_ONLY
    return RECAP_START_PLAN


def recap_beats_path_for_video(video_path: str) -> Path:
    return _recap_sidecar_path(video_path, "_recap_beats.json")


def recap_cuts_path_for_video(video_path: str) -> Path:
    return _recap_sidecar_path(video_path, "_recap_cuts.json")


def _recap_sidecar_path(video_path: str, suffix: str) -> Path:
    video = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    return video.parent / f"{video.stem}{suffix}"


def _read_recap_sidecar(path: Path, required_key: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get(required_key), list):
        return None
    if not payload.get(required_key):
        return None
    return payload


def _load_recap_sidecar(
    video_path: str,
    *,
    suffix: str,
    required_key: str,
    video_id: str = "",
) -> dict[str, Any] | None:
    primary = _recap_sidecar_path(video_path, suffix)
    payload = _read_recap_sidecar(primary, required_key)
    if payload is not None:
        return payload
    vid = str(video_id or "").strip()
    parent = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip()))).parent
    if not vid or not parent.is_dir():
        return None
    found: list[tuple[float, dict[str, Any]]] = []
    for path in parent.glob(f"*{suffix}"):
        if path == primary:
            continue
        item = _read_recap_sidecar(path, required_key)
        if item is None or str(item.get("video_id") or "").strip() != vid:
            continue
        try:
            mtime = float(path.stat().st_mtime)
        except OSError:
            mtime = 0.0
        found.append((mtime, item))
    if not found:
        return None
    found.sort(key=lambda row: row[0], reverse=True)
    return found[0][1]


def load_recap_beats(video_path: str, *, video_id: str = "") -> dict[str, Any] | None:
    return _load_recap_sidecar(
        video_path,
        suffix="_recap_beats.json",
        required_key="beats",
        video_id=video_id,
    )


def load_recap_cuts(video_path: str, *, video_id: str = "") -> dict[str, Any] | None:
    return _load_recap_sidecar(
        video_path,
        suffix="_recap_cuts.json",
        required_key="clips",
        video_id=video_id,
    )


def save_recap_clip_vo(
    video_path: str,
    clip_index: int,
    text: str,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Hand-edit one clip's narration and rewrite cuts (+ optional SRT). Not an NLE trim."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    try:
        index = int(clip_index)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的镜头序号。") from exc
    if index < 0 or index >= len(clips):
        raise RuntimeError("镜头序号超出范围。")
    body = str(text or "").strip()
    clip = clips[index]
    clip["vo"] = body
    clip["vo_draft"] = body
    tl_in = float(clip.get("tl_in") or 0.0)
    tl_out = float(clip.get("tl_out") or tl_in)
    if body:
        budget = _max_picture_for_vo(body)
        vo_end = min(tl_out, tl_in + max(budget, 0.5)) if budget > 0 else tl_out
        if vo_end > tl_in + 0.04:
            clip["vo_tl_in"] = round(tl_in, 3)
            clip["vo_tl_out"] = round(vo_end, 3)
        else:
            clip.pop("vo_tl_in", None)
            clip.pop("vo_tl_out", None)
    else:
        clip.pop("vo_tl_in", None)
        clip.pop("vo_tl_out", None)
    clips[index] = clip
    dest = recap_cuts_path_for_video(media)
    next_payload = dict(payload)
    next_payload["clips"] = _recap_clip_records(clips)
    next_payload["clip_count"] = len(clips)
    if clips:
        next_payload["duration_sec"] = float(clips[-1].get("tl_out") or next_payload.get("duration_sec") or 0.0)
    cuts_path = write_cuts_json(next_payload, dest)
    srt_path = ""
    if rewrite_srt:
        stem = Path(os.path.abspath(os.path.expanduser(media))).stem
        srt_dest = Path(os.path.abspath(os.path.expanduser(media))).parent / f"{stem}_recap.srt"
        srt_path = str(write_srt(clips, srt_dest))
    return {
        "ok": True,
        "cuts_path": str(cuts_path),
        "srt_path": srt_path,
        "clip_index": index,
        "vo": body,
        "clips": clips,
    }


def rewrite_recap_clip_caption(
    video_path: str,
    clip_index: int,
    *,
    video_id: str = "",
    config=None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """LLM-rewrite narration for one locked shot; writes cuts + SRT. Does not rematch."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    try:
        index = int(clip_index)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的镜头序号。") from exc
    if index < 0 or index >= len(clips):
        raise RuntimeError("镜头序号超出范围。")

    cfg = config if config is not None else load_config()
    vid = str(video_id or payload.get("video_id") or "").strip()
    beats_payload = load_recap_beats(media, video_id=vid) or {}
    beats = list(beats_payload.get("beats") or [])
    people = list(beats_payload.get("people") or [])
    pack: dict[str, Any] | None = None
    if vid:
        try:
            pack = build_recap_pack(vid, config=cfg)
        except Exception:
            pack = None
    prev = ""
    for cursor in range(index - 1, -1, -1):
        body = str(clips[cursor].get("vo") or "").strip()
        if body:
            prev = body
            break
    wave = [dict(clips[index])]
    text = call_remote_llm(
        system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
        user=recap_caption_user_prompt(
            wave,
            people=people,
            prev_caption=prev,
            beats=beats,
            pack=pack,
        ),
        config=cfg,
        temperature=0.3,
        max_tokens=1024,
        should_stop_callback=should_stop_callback,
    )
    caps = parse_caption_cues(text, wave)
    if not caps:
        raise RuntimeError("LLM 没有返回可用旁白。")
    new_vo = str(caps[0].get("text") or "").strip()
    if not new_vo:
        raise RuntimeError("LLM 返回的旁白为空。")
    saved = save_recap_clip_vo(
        media,
        index,
        new_vo,
        video_id=vid,
        rewrite_srt=True,
    )
    saved["rewritten"] = True
    return saved


def _clip_beat_id(clip: Mapping[str, Any] | None) -> int | None:
    if not isinstance(clip, Mapping):
        return None
    try:
        return int(clip.get("beat_id"))
    except (TypeError, ValueError):
        return None


def _splice_recap_beat_cuts(
    existing: Sequence[Mapping[str, Any]],
    new_cuts: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> list[dict[str, Any]]:
    """Replace every clip for ``beat_id`` with ``new_cuts``, keeping other beats intact.

    Removes *all* clips of the target beat (even if non-contiguous), then inserts the
    new block at the first removed position so neighbors stay in narrative order.
    """
    target = int(beat_id)
    kept: list[dict[str, Any]] = []
    insert_at: int | None = None
    for clip in existing or []:
        row = dict(clip)
        if _clip_beat_id(row) == target:
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(row)
    mid: list[dict[str, Any]] = []
    for clip in new_cuts or []:
        row = dict(clip)
        row["beat_id"] = target
        mid.append(row)
    if not mid:
        return kept
    if insert_at is None:
        # No prior clips for this beat — place by ascending beat id among neighbors.
        insert_at = len(kept)
        for index, clip in enumerate(kept):
            bid = _clip_beat_id(clip)
            if bid is not None and bid > target:
                insert_at = index
                break
    return kept[:insert_at] + mid + kept[insert_at:]


def _neighbor_beats_for_rematch(
    allocated: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    ordered = [dict(item) for item in allocated or []]
    target_index = None
    for index, item in enumerate(ordered):
        try:
            if int(item.get("id")) == int(beat_id):
                target_index = index
                break
        except (TypeError, ValueError):
            continue
    if target_index is None:
        raise RuntimeError(f"规划里没有拍 #{beat_id}。")
    prev_beat = ordered[target_index - 1] if target_index > 0 else None
    next_beat = ordered[target_index + 1] if target_index + 1 < len(ordered) else None
    return prev_beat, ordered[target_index], next_beat


def _locked_vo_context(
    clips: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return (prev VO lines, next VO lines, old cuts for this beat)."""
    target = int(beat_id)
    prev: list[str] = []
    nxt: list[str] = []
    old: list[dict[str, Any]] = []
    phase = "before"
    for clip in clips or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        vo = str(row.get("vo") or "").strip()
        if bid == target:
            phase = "after"
            old.append(row)
            continue
        if phase == "before":
            if vo:
                prev.append(vo)
        else:
            if vo:
                nxt.append(vo)
    return prev[-3:], nxt[:3], old


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


def _filter_rematch_cuts_to_beat(
    cuts: Sequence[Mapping[str, Any]],
    beat: Mapping[str, Any],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep only target-beat clips that still touch the beat time window."""
    target = int(beat.get("id"))
    span = _time_span(beat.get("t"))
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        if bid not in (None, 0, target):
            continue
        row["beat_id"] = target
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            continue
        if src_out <= src_in + 0.4:
            continue
        pad = float(BEAT_SRC_PAD_SEC)
        if span and _overlap_sec((src_in, src_out), (span[0] - pad, span[1] + pad)) <= 0.05:
            # Far outside beat window — try snap, else drop.
            placed = None
            if pack is not None:
                placed = _snap_src_into_beat_window(
                    pack,
                    span,
                    want_sec=max(MIN_FLASH_CLIP_SEC, min(src_out - src_in, MAX_CLIP_SEC)),
                    pad_sec=pad,
                )
            if placed is None:
                continue
            row["src_in"], row["src_out"] = placed
            row["duration"] = round(placed[1] - placed[0], 3)
            src_in, src_out = placed
        if pack is not None and _source_hits_op_ed(pack, src_in, src_out):
            continue
        out.append(row)
    return out


def caption_recap_clip_indices(
    clips: list[Mapping[str, Any]],
    indices: Sequence[int],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Caption selected clips in place without splitting underfilled shots."""
    work = [dict(clip) for clip in clips]
    ordered = sorted({int(index) for index in indices if 0 <= int(index) < len(work)})
    if not ordered:
        return work
    wave = [dict(work[index]) for index in ordered]
    prev = ""
    first = ordered[0]
    for cursor in range(first - 1, -1, -1):
        body = str(work[cursor].get("vo") or "").strip()
        if body:
            prev = body
            break
    text = call_remote_llm(
        system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
        user=recap_caption_user_prompt(
            wave,
            people=people,
            prev_caption=prev,
            beats=beats,
            pack=pack,
        ),
        config=config,
        temperature=0.3,
        max_tokens=2048,
        should_stop_callback=should_stop_callback,
    )
    caps = parse_caption_cues(text, wave)
    stamped = apply_caption_cues(wave, caps)
    for local_i, global_i in enumerate(ordered):
        row = dict(work[global_i])
        row["vo"] = str(stamped[local_i].get("vo") or "").strip()
        row["vo_draft"] = str(
            stamped[local_i].get("vo_draft")
            or stamped[local_i].get("vo")
            or row.get("vo_draft")
            or ""
        ).strip()
        if stamped[local_i].get("vo_tl_in") is not None:
            row["vo_tl_in"] = stamped[local_i].get("vo_tl_in")
        else:
            row.pop("vo_tl_in", None)
        if stamped[local_i].get("vo_tl_out") is not None:
            row["vo_tl_out"] = stamped[local_i].get("vo_tl_out")
        else:
            row.pop("vo_tl_out", None)
        work[global_i] = row
    return work


def rematch_recap_beat(
    video_id: str,
    beat_id: int,
    *,
    video_path: str = "",
    config=None,
    system_prompt: str | None = None,
    caption_prompt: str | None = None,
    fill_captions: bool = True,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Rematch shots for one beat, splice into saved cuts, optionally caption those shots."""
    cfg = config if config is not None else load_config()
    vid = str(video_id or "").strip()
    if not vid:
        raise RuntimeError("缺少 video_id。")
    try:
        target_beat_id = int(beat_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的节拍 id。") from exc
    if target_beat_id <= 0:
        raise RuntimeError("无效的节拍 id。")

    def _progress(value: int, stage: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(stage))

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("Recap stopped by user")

    pack = build_recap_pack(vid, config=cfg)
    from src.services.understanding_service import resolve_current_media_path

    media = resolve_current_media_path(
        vid,
        stored=str(video_path or pack.get("video_path") or ""),
        config=cfg,
    )
    pack["video_path"] = media
    if not media or not os.path.isfile(media):
        raise RuntimeError(f"找不到原片：{media or '(空路径)'}")

    beats_payload = load_recap_beats(media, video_id=vid)
    if not beats_payload:
        raise RuntimeError("没有已保存的剧情规划。")
    allocated = list(beats_payload.get("beats") or [])
    people = normalize_story_people(beats_payload)
    pack["people"] = people
    prev_beat, beat, next_beat = _neighbor_beats_for_rematch(allocated, target_beat_id)

    saved_cuts = load_recap_cuts(media, video_id=vid)
    if not saved_cuts:
        raise RuntimeError("还没有选镜表。")
    existing = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
    title = str(saved_cuts.get("title") or beats_payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    prev_vo, next_vo, old_cuts = _locked_vo_context(existing, target_beat_id)
    other_before = [dict(clip) for clip in existing if _clip_beat_id(clip) != target_beat_id]

    _raise_if_stopped()
    _progress(20, "motion_gaps")
    # Include neighbor beat windows so ASR/caps around the cut are visible to the matcher.
    context_beats = [item for item in (prev_beat, beat, next_beat) if item]
    pack, _motion_warns, motion_filled = fill_recap_motion_for_beats(
        vid,
        pack,
        context_beats,
        config=cfg,
        should_stop_callback=should_stop_callback,
    )
    pack["video_path"] = media

    _raise_if_stopped()
    _progress(45, "matching")
    match_system = resolve_recap_system_prompt(system_prompt, resolve_recap_caption_language(cfg))
    wave_pack = pack_for_beats(pack, context_beats, pad_sec=36.0)
    match_text = call_remote_llm(
        system=match_system,
        user=rematch_recap_user_prompt(
            wave_pack,
            beat=beat,
            prev_beat=prev_beat,
            next_beat=next_beat,
            prev_vo=prev_vo,
            next_vo=next_vo,
            old_cuts=old_cuts,
        ),
        config=cfg,
        temperature=0.35,
        max_tokens=4096,
        should_stop_callback=should_stop_callback,
    )
    _wave_title, wave_cuts = parse_cut_list(match_text, pack)
    del _wave_title
    normalized = _filter_rematch_cuts_to_beat(
        stash_match_vo_as_draft(wave_cuts),
        beat,
        pack=pack,
    )
    if not normalized:
        raise RuntimeError("选镜没有返回可用镜头（或不在该拍时间窗内）。")
    # Light refine only: avoid coalesce sorting/dropping that can erase rematch shots.
    normalized = clamp_cuts_to_beat_window(normalized, pack, [beat])
    normalized = snap_cuts_to_capped_chunks(normalized, pack, [beat])
    normalized = clamp_insert_cuts_to_beat(normalized, pack, [beat])
    normalized = dedupe_overlapping_recap_cuts(normalized)
    normalized = _filter_rematch_cuts_to_beat(normalized, beat, pack=pack)
    if not normalized:
        raise RuntimeError("选镜结果无效。")
    normalized = annotate_recap_match_quality(
        normalized, [beat], pack, people, config=cfg
    )

    merged = _splice_recap_beat_cuts(existing, normalized, target_beat_id)
    other_after = [clip for clip in merged if _clip_beat_id(clip) != target_beat_id]
    if len(other_after) != len(other_before):
        raise RuntimeError(
            f"重选镜保护失败：其它拍镜头数从 {len(other_before)} 变成 {len(other_after)}，已中止写入。"
        )
    for left, right in zip(other_before, other_after):
        if round(float(left.get("src_in") or 0.0), 3) != round(float(right.get("src_in") or 0.0), 3):
            raise RuntimeError("重选镜保护失败：其它拍原片起点被改动，已中止写入。")
        if str(left.get("vo") or "") != str(right.get("vo") or ""):
            raise RuntimeError("重选镜保护失败：其它拍旁白被改动，已中止写入。")

    info = _probe_media(media)
    laid = layout_clips_on_timeline(
        merged,
        fps=float(info.get("fps") or saved_cuts.get("fps") or 24.0),
    )
    beat_indices = [
        index
        for index, clip in enumerate(laid)
        if _clip_beat_id(clip) == target_beat_id
    ]

    if fill_captions and beat_indices:
        _raise_if_stopped()
        _progress(75, "captions")
        laid = caption_recap_clip_indices(
            laid,
            beat_indices,
            config=cfg,
            system_prompt=caption_prompt,
            people=people,
            beats=allocated,
            pack=pack,
            should_stop_callback=should_stop_callback,
        )

    _progress(90, "writing")
    cuts_path = write_recap_cuts_file(
        recap_cuts_path_for_video(media),
        title=title,
        video_path=media,
        video_id=vid,
        info=info,
        laid_out=laid,
        beats_path=recap_beats_path_for_video(media),
        stage=RECAP_START_CAPTIONS if fill_captions else RECAP_START_MATCH,
    )
    stem = Path(media).stem
    srt_path = write_srt(laid, Path(media).parent / f"{stem}_recap.srt")
    return {
        "ok": True,
        "title": title,
        "video_id": vid,
        "beat_id": target_beat_id,
        "clip_count": len(laid),
        "beat_clip_count": len(beat_indices),
        "duration_sec": laid[-1]["tl_out"] if laid else 0,
        "cuts_path": str(cuts_path),
        "srt_path": str(srt_path),
        "motion_filled": int(motion_filled),
        "clips": laid,
    }


def rematch_weak_recap_beats(
    video_id: str,
    *,
    video_path: str = "",
    beat_ids: Sequence[int] | None = None,
    max_beats: int = MAX_WEAK_REMATCH_BEATS,
    config=None,
    system_prompt: str | None = None,
    caption_prompt: str | None = None,
    fill_captions: bool = True,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Rematch every weak-match beat (or an explicit beat id list), sequentially."""
    cfg = config if config is not None else load_config()
    vid = str(video_id or "").strip()
    if not vid:
        raise RuntimeError("缺少 video_id。")
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")

    def _progress(value: int, stage: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(stage))

    payload = load_recap_cuts(media, video_id=vid)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = list(payload.get("clips") or [])
    targets = [int(item) for item in (beat_ids or list_weak_match_beat_ids(clips)) if int(item) > 0]
    # De-dupe while preserving order.
    ordered: list[int] = []
    seen: set[int] = set()
    for beat_id in targets:
        if beat_id in seen:
            continue
        seen.add(beat_id)
        ordered.append(beat_id)
    limit = max(1, int(max_beats or MAX_WEAK_REMATCH_BEATS))
    skipped = max(0, len(ordered) - limit)
    ordered = ordered[:limit]
    if not ordered:
        raise RuntimeError("没有弱证据拍需要重选。")

    rematched: list[int] = []
    failed: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    total = len(ordered)
    for index, beat_id in enumerate(ordered):
        _raise_if_stopped()
        pct = 8 + int(round(84.0 * float(index) / float(max(total, 1))))
        _progress(min(90, pct), f"weak_rematch:{index + 1}/{total}:{beat_id}")
        try:
            last = rematch_recap_beat(
                vid,
                beat_id,
                video_path=media,
                config=cfg,
                system_prompt=system_prompt,
                caption_prompt=caption_prompt,
                fill_captions=fill_captions,
                should_stop_callback=should_stop_callback,
                progress_callback=None,
            )
            rematched.append(beat_id)
        except UnderstandingStoppedError:
            raise
        except Exception as exc:
            failed.append({"beat_id": beat_id, "error": str(exc)})
    _progress(100, "writing")
    refreshed = load_recap_cuts(media, video_id=vid) or last
    remaining = list_weak_match_beat_ids(list((refreshed or {}).get("clips") or []))
    return {
        "ok": True,
        "video_id": vid,
        "beat_ids": rematched,
        "failed": failed,
        "skipped": skipped,
        "requested": total,
        "remaining_weak": remaining,
        "clip_count": len(list((refreshed or {}).get("clips") or [])),
        "cuts_path": str((refreshed or {}).get("cuts_path") or last.get("cuts_path") or ""),
        "srt_path": str(last.get("srt_path") or ""),
        "duration_sec": float((refreshed or {}).get("duration_sec") or last.get("duration_sec") or 0.0),
    }


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


def save_recap_plan_edits(
    video_path: str,
    *,
    video_id: str,
    title: str,
    beats: Sequence[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]] | None = None,
    duration_sec: float = 0.0,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    target_sec: float | None = None,
) -> Path:
    duration = float(duration_sec or 0.0)
    target = float(target_sec) if target_sec is not None else recap_target_sec(duration)
    allocated = allocate_beat_budgets(
        list(beats),
        chunks=list(chunks or []),
        target_sec=target,
        duration_sec=duration,
    )
    return write_recap_beats_file(
        recap_beats_path_for_video(video_path),
        title=str(title or "").strip() or "解说剪辑",
        video_id=str(video_id or "").strip(),
        allocated=allocated,
        people=normalize_story_people({"people": list(people or [])}),
    )


def _recap_clip_records(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clip in clips:
        row = {
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
            "role": str(clip.get("role") or "").strip(),
        }
        match_status = str(clip.get("match_status") or "").strip()
        if match_status:
            row["match_status"] = match_status
        if clip.get("match_score") is not None:
            try:
                row["match_score"] = round(float(clip.get("match_score")), 3)
            except (TypeError, ValueError):
                pass
        if clip.get("match_threshold") is not None:
            try:
                row["match_threshold"] = round(float(clip.get("match_threshold")), 3)
            except (TypeError, ValueError):
                pass
        support = clip.get("evidence_support")
        if isinstance(support, Mapping):
            row["evidence_support"] = dict(support)
        for key in ("visual_score", "asr_score", "vlm_score", "character_score"):
            if clip.get(key) is None:
                continue
            try:
                row[key] = round(float(clip.get(key)), 3)
            except (TypeError, ValueError):
                pass
        rows.append(row)
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
    polish_prompt: str | None = None,
    start_from: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[..., None] | None = None,
    chunk_completed_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    cfg = config if config is not None else load_config()
    llm = get_remote_llm_settings(cfg)
    if not str(llm.get("model") or "").strip():
        raise RuntimeError("尚未配置语言模型。请先在模型服务 → LLM 里填写并保存。")
    pack = build_recap_pack(video_id, config=cfg)
    from src.services.understanding_service import resolve_current_media_path

    video_path = resolve_current_media_path(
        video_id,
        stored=str(pack.get("video_path") or ""),
        config=cfg,
    )
    pack["video_path"] = video_path
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"找不到原片：{video_path or '(空路径)'}")

    def _progress(value: int, stage: str, extra: Mapping[str, Any] | None = None) -> None:
        if not progress_callback:
            return
        payload = dict(extra or {})
        try:
            progress_callback(int(value), str(stage), payload)
        except TypeError:
            progress_callback(int(value), str(stage))

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("Recap stopped by user")

    _raise_if_stopped()
    stage = normalize_recap_start_from(start_from)
    caption_language = resolve_recap_caption_language(cfg)
    plan_system = resolve_recap_prompt(plan_prompt, default_recap_plan_prompt(caption_language))
    match_system = resolve_recap_system_prompt(system_prompt, caption_language)
    caption_raw = str(caption_prompt or "").strip()
    if caption_raw in {
        str(RECAP_GAP_SYSTEM).strip(),
        str(RECAP_GAP_SYSTEM_EN).strip(),
    }:
        caption_raw = ""
    caption_system = resolve_recap_prompt(caption_raw, default_recap_caption_prompt(caption_language))
    polish_system = resolve_recap_prompt(polish_prompt, default_recap_polish_prompt(caption_language))
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
    warnings: list[str] = []
    motion_needed = 0
    motion_filled = 0
    motion_checked = False
    target_sec = recap_target_sec(duration)

    if stage == RECAP_START_CAPTIONS:
        saved_cuts = load_recap_cuts(video_path, video_id=video_id)
        if not saved_cuts:
            raise RuntimeError("没有已保存的选镜表。请先跑第二阶段，或从第一阶段开始。")
        title = str(saved_cuts.get("title") or "").strip() or plan_title
        saved_beats = load_recap_beats(video_path, video_id=video_id)
        if saved_beats:
            plan_title = str(saved_beats.get("title") or plan_title)
            beats_path = recap_beats_path_for_video(video_path)
            people = normalize_story_people(saved_beats)
            allocated = list(saved_beats.get("beats") or [])
        cuts = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
        cuts = refine_recap_cuts(cuts, pack)
        pack["people"] = people
    else:
        if stage == RECAP_START_MATCH:
            saved = load_recap_beats(video_path, video_id=video_id)
            if not saved:
                raise RuntimeError("没有已保存的剧情规划。请先跑第一阶段，或从第一阶段开始。")
            plan_title = str(saved.get("title") or "").strip() or plan_title
            beats = list(saved.get("beats") or [])
            people = normalize_story_people(saved)
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=float(saved.get("target_sec") or target_sec),
                duration_sec=duration,
            )
            _raise_if_stopped()
            _progress(46, "vo_draft")
            allocated = draft_recap_vo_for_beats(
                pack,
                allocated,
                config=cfg,
                language=caption_language,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
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
            plan_title, beats, people, act_warns = plan_story_beats_by_acts(
                pack,
                video_id=video_id,
                config=cfg,
                language=caption_language,
                system_prompt=None,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            warnings.extend(act_warns)
            if not beats:
                # Fallback: single-shot plan if every act call failed.
                plan_text = call_remote_llm(
                    system=plan_system,
                    user=recap_plan_user_prompt(pack),
                    config=cfg,
                    temperature=0.25,
                    max_tokens=8192,
                    should_stop_callback=should_stop_callback,
                )
                plan_title, beats, people = parse_story_plan(plan_text)
            beats = drop_op_ed_beats(beats, duration)
            beats = scrub_unevidenced_beats(beats, pack)
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
                head_parsed = _try_story_plan_llm(
                    system=default_recap_plan_head_prompt(caption_language),
                    user=recap_plan_head_user_prompt(head_pack, beats),
                    config=cfg,
                    should_stop_callback=should_stop_callback,
                    temperature=0.3,
                    max_tokens=2048,
                )
                if head_parsed is None:
                    warnings.append("recap_warn_plan_head")
                    _progress(22, "plan_head_failed")
                else:
                    _head_title, head_beats, head_people = head_parsed
                    del _head_title
                    beats = drop_op_ed_beats(merge_story_beats(head_beats, beats), duration)
                    people = merge_story_people(head_people, people)
                    pack["people"] = people
            if duration > 1.0 and not beats_cover_ending(beats, duration):
                last_end = 0.0
                for beat in beats:
                    span = _time_span(beat.get("t"))
                    if span:
                        last_end = max(last_end, min(span[1], story_end))
                _raise_if_stopped()
                _progress(32, "closing")
                tail_pack = filter_pack_to_span(pack, last_end, story_end, pad_sec=8.0)
                tail_parsed = _try_story_plan_llm(
                    system=default_recap_plan_tail_prompt(caption_language),
                    user=recap_plan_tail_user_prompt(tail_pack, beats),
                    config=cfg,
                    should_stop_callback=should_stop_callback,
                    temperature=0.3,
                    max_tokens=2048,
                )
                if tail_parsed is None:
                    warnings.append("recap_warn_plan_tail")
                    _progress(32, "plan_tail_failed")
                else:
                    _tail_title, tail_beats, tail_people = tail_parsed
                    del _tail_title
                    beats = drop_op_ed_beats(merge_story_beats(beats, tail_beats), duration)
                    people = merge_story_people(people, tail_people)
            gaps = (
                prioritize_story_gaps(
                    story_beat_gaps(beats, duration),
                    pin=activity_shift_gaps(
                        beats,
                        min_gap_sec=story_gap_min_sec(duration),
                    ),
                )
                if duration > 1.0
                else []
            )
            gap_failed = False
            for gap in gaps:
                if len(beats) >= MAX_STORY_BEATS:
                    break
                _raise_if_stopped()
                _progress(38, "plot_gaps")
                gap_pack = filter_pack_to_spans(pack, [gap], pad_sec=16.0)
                gap_parsed = _try_story_plan_llm(
                    system=default_recap_plan_gap_prompt(caption_language),
                    user=recap_plan_gap_user_prompt(gap_pack, beats, [gap]),
                    config=cfg,
                    should_stop_callback=should_stop_callback,
                    temperature=0.3,
                    max_tokens=2048,
                )
                if gap_parsed is None:
                    gap_failed = True
                    continue
                _gap_title, gap_beats, gap_people = gap_parsed
                del _gap_title
                room = max(0, MAX_STORY_BEATS - len(beats))
                if room <= 0:
                    break
                if len(gap_beats) > room:
                    gap_beats = sorted(
                        gap_beats,
                        key=lambda item: float(item.get("importance") or 0.5),
                        reverse=True,
                    )[:room]
                beats = drop_op_ed_beats(
                    merge_story_beats(beats, gap_beats, allowed_windows=[gap]),
                    duration,
                )
                people = merge_story_people(people, gap_people)
            if gap_failed:
                warnings.append("recap_warn_plan_gaps")
                _progress(38, "plot_gaps_failed")
            beats = trim_story_beats_to_limit(beats, limit=MAX_STORY_BEATS)
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=target_sec,
                duration_sec=duration,
            )
            _raise_if_stopped()
            _progress(48, "vo_draft")
            allocated = draft_recap_vo_for_beats(
                pack,
                allocated,
                config=cfg,
                language=caption_language,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            beats_path = write_recap_beats_file(
                beats_path,
                title=plan_title,
                video_id=video_id,
                allocated=allocated,
                people=people,
            )
            if stage == RECAP_START_PLAN_ONLY:
                return {
                    "title": plan_title,
                    "video_id": video_id,
                    "stage": RECAP_START_PLAN,
                    "clip_count": 0,
                    "beat_count": len(allocated),
                    "duration_sec": round(sum(float(item.get("budget_sec") or 0.0) for item in allocated), 1),
                    "beats_path": str(beats_path),
                    "cuts_path": "",
                    "srt_path": "",
                    "warnings": list(warnings),
                    "motion_needed": 0,
                    "motion_filled": 0,
                    "motion_checked": False,
                }

        motion_checked = True
        gap_indices = recap_motion_gap_chunk_indices(pack, allocated)
        motion_needed = len(gap_indices)
        if gap_indices:
            _raise_if_stopped()
            _progress(44, "motion_gaps", {"done": 0, "total": motion_needed})

            def _on_motion_progress(done: int, total: int) -> None:
                pct = 44 + int(round(3.0 * float(done) / float(max(total, 1))))
                _progress(min(47, pct), "motion_gaps", {"done": int(done), "total": int(total)})

            pack, motion_warns, motion_filled = fill_recap_motion_for_beats(
                video_id,
                pack,
                allocated,
                config=cfg,
                should_stop_callback=should_stop_callback,
                on_progress=_on_motion_progress,
                chunk_completed_callback=chunk_completed_callback,
            )
            warnings.extend(motion_warns)
            pack["video_path"] = video_path
        else:
            _progress(46, "motion_gaps_skip")

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
                temperature=0.25,
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
            _progress(82, "matching")
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
                warnings.append("recap_warn_match_close")
                _progress(82, "match_close_failed")
        cuts.sort(key=lambda item: (float(item.get("src_in") or 0.0), int(item.get("beat_id") or 0)))
        cuts = stash_match_vo_as_draft(cuts)
        cuts = stamp_beat_vo_onto_cuts(cuts, allocated)
        min_sec, _max_sec = recap_duration_bounds(target_sec)
        cuts = apply_recap_duration(cuts, pack, allocated, target_sec=target_sec, min_sec=min_sec)
        cuts = refine_recap_cuts(cuts, pack, allocated)
        cuts = annotate_recap_match_quality(cuts, allocated, pack, people, config=cfg)
        title = str(match_title or "").strip() or plan_title
        if title == "解说剪辑" and plan_title and plan_title != "解说剪辑":
            title = plan_title
        _raise_if_stopped()
        info = _probe_media(video_path)
        laid_match = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
        cuts_path = write_recap_cuts_file(
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
        if stage == RECAP_START_MATCH:
            _progress(90, "writing")
            return {
                "title": title,
                "video_id": video_id,
                "stage": RECAP_START_MATCH,
                "clip_count": len(laid_match),
                "duration_sec": laid_match[-1]["tl_out"] if laid_match else 0,
                "beats_path": str(beats_path),
                "cuts_path": str(cuts_path),
                "srt_path": "",
                "warnings": list(warnings),
                "motion_needed": int(motion_needed),
                "motion_filled": int(motion_filled),
                "motion_checked": bool(motion_checked),
            }

    _raise_if_stopped()
    if info is None:
        info = _probe_media(video_path)
    if stage == RECAP_START_CAPTIONS:
        cuts = annotate_recap_match_quality(cuts, allocated, pack, people, config=cfg)
    laid_out = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
    _progress(84, "captions")
    laid_out = fit_recap_captions_to_tts(
        laid_out,
        config=cfg,
        system_prompt=caption_system,
        people=people,
        beats=allocated,
        pack=pack,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    _raise_if_stopped()
    laid_out = fill_recap_vo_gaps(
        laid_out,
        config=cfg,
        people=people,
        beats=allocated,
        pack=pack,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    _raise_if_stopped()
    # Second chance only for true story holes (same rule as gap-fill).
    # Do NOT refill same-beat inserts/follow shots left empty for spanning VO —
    # that was the main source of near-duplicate narration.
    retry_indices = recap_gap_clip_indices(laid_out)
    if retry_indices:
        _progress(89, "captions")
        try:
            laid_out = caption_recap_clip_indices(
                laid_out,
                retry_indices,
                config=cfg,
                system_prompt=caption_system,
                people=people,
                beats=allocated,
                pack=pack,
                should_stop_callback=should_stop_callback,
            )
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            pass
    _raise_if_stopped()
    laid_out = polish_recap_vo(
        laid_out,
        config=cfg,
        system_prompt=polish_system,
        people=people,
        beats=allocated,
        pack=pack,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    _raise_if_stopped()
    _progress(92, "writing")
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
        "warnings": list(warnings),
        "motion_needed": int(motion_needed),
        "motion_filled": int(motion_filled),
        "motion_checked": bool(motion_checked),
    }


def export_saved_recap_fcpxml(
    payload: Mapping[str, Any],
    dest_path: str | Path,
    *,
    video_path: str = "",
) -> Path:
    video = str(video_path or payload.get("video") or "").strip()
    video_id = str(payload.get("video_id") or "").strip()
    if video_id:
        from src.services.understanding_service import resolve_current_media_path

        video = resolve_current_media_path(video_id, stored=video)
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

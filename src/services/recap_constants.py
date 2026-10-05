"""Tunable knobs and shared match patterns for the recap job.

Values started as top-level literals in ``recap_service``; keep them here so the
runner does not keep growing a magic-number header. Patterns used by more than
one stage live here too, instead of being private imports between stages.
``recap_service`` re-exports these names for existing callers.
"""

from __future__ import annotations

import re

BASE_CHARS_PER_SEC = 5.0
TTS_SPEED = 1.25
CHARS_PER_SEC = BASE_CHARS_PER_SEC * TTS_SPEED
MIN_CLIP_SEC = 4.0
MAX_CLIP_SEC = 12.0
MAX_TTS_CLIP_SEC = 36.0
TARGET_RECAP_SEC = 330
MIN_RECAP_SEC = 180
MAX_RECAP_SEC = 720
RECAP_STORY_RATIO = 0.38
VO_FILL_RATIO = 0.82
VO_COVER_RATIO = 0.82
MIN_VO_FILL = 0.70
MAX_VO_FILL = 0.90
MIN_BEAT_BUDGET_SEC = 8.0
MAX_BEAT_BUDGET_SEC = 24.0
HARD_MIN_BEAT_SEC = 6.0
MAX_STORY_BEATS = 120
MAX_GAP_FILL_WINDOWS = 8
MAX_PLAN_BEATS = MAX_STORY_BEATS
RECAP_START_PLAN = "plan"
RECAP_START_PLAN_ONLY = "plan_only"
RECAP_START_MATCH = "match"
RECAP_START_CAPTIONS = "captions"
MATCH_BEATS_PER_WAVE = 5
VO_DRAFT_BEATS_PER_WAVE = 8
CAPTION_CLIPS_PER_WAVE = 12
ENDING_COVER_RATIO = 0.97
RECAP_OCR_LIMIT = 420
PLAN_ACT_ASR_LIMIT = 160
PLAN_ACT_TARGET_SEC = 480.0
MAX_CAPTION_SEC = 18.0
MIN_BRIDGE_SEC = 2.4
SOURCE_MERGE_GAP_SEC = 1.25
SOURCE_OVERLAP_MERGE_SEC = 0.2
SOURCE_REUSE_RATIO = 0.42
SOURCE_ADJACENT_REUSE_RATIO = 0.30
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

RECAP_FOCUS_GENERIC = "generic"
RECAP_FOCUS_FLEX = "flex"
RECAP_FOCUS_ORDEAL = "ordeal"
RECAP_FOCUS_BOND = "bond"
RECAP_FOCUS_MODES = (
    RECAP_FOCUS_GENERIC,
    RECAP_FOCUS_FLEX,
    RECAP_FOCUS_ORDEAL,
    RECAP_FOCUS_BOND,
)
RECAP_FOCUS_SOFT_MIN = 0.55

RECAP_VISUAL_EVIDENCE_TAGS = frozenset({"动作", "反应", "物品", "变化", "场面"})
RECAP_CLIMAX_IMPORTANCE = 0.85

DIALOGUE_OUTCOME_RE = re.compile(
    r"(不行|不可以|别再|不许|拒绝|拒收|拒了|收下|接住|答应|同意|成交|决定|胜负|赢了|输了|揭穿|识破|"
    r"坦白|承认|否认|推回|还回去|交给你|就这样|算了|滚|走开|回去吧|走吧|没事了|放过|"
    r"原谅|解决|搞定|到此为止|就到这|回头见|离开|真相|结果出来|全勾完|结束了|完了|完蛋|成立|不成立|"
    r"refuse|reject|accept|deal|decide|won|lost|confess|deny)",
    re.IGNORECASE,
)
TEXTURE_BEAT_RE = re.compile(
    r"(设定|世界观|规则说明|能力说明|教室|空间|角色侧面|性格|态度|习惯|表情|换场|过渡|气氛|环境)"
)

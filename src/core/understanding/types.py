from __future__ import annotations

from enum import Enum


class UnderstandingModality(str, Enum):
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


class UnderstandingTask(str, Enum):
    OBJECT_DETECTION = "object_detection"
    IMAGE_CAPTION = "image_caption"
    SPEECH_TO_TEXT = "speech_to_text"


class UnderstandingInputKind(str, Enum):
    CHUNK_KEYFRAME = "chunk_keyframe"
    CHUNK_AUDIO = "chunk_audio"


class UnderstandingOutputKind(str, Enum):
    OBJECTS = "objects"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"


def normalize_enum_value(enum_cls: type[Enum], raw_value: object, field_name: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    allowed = {item.value for item in enum_cls}
    if text not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}, got {text!r}")
    return text

"""ASR core helpers (audio extract, VAD, SenseVoice).

Heavy engines are imported lazily so optional deps (e.g. PyYAML) are not required
just to use VAD / extract helpers.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SenseVoiceOnnxEngine",
    "SpeechSegment",
    "extract_audio_wav",
    "get_silero_vad_engine",
    "resolve_silero_vad_model_path",
    "segment_media_speech",
    "segment_speech",
]


def __getattr__(name: str) -> Any:
    if name == "extract_audio_wav":
        from src.core.asr.audio_extract import extract_audio_wav

        return extract_audio_wav
    if name in {
        "SpeechSegment",
        "get_silero_vad_engine",
        "resolve_silero_vad_model_path",
        "segment_media_speech",
        "segment_speech",
    }:
        from src.core.asr import vad_segment

        return getattr(vad_segment, name)
    if name == "SenseVoiceOnnxEngine":
        from src.core.asr.sensevoice_engine import SenseVoiceOnnxEngine

        return SenseVoiceOnnxEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Understanding component wrapper for imported faster-whisper-medium weights."""

from __future__ import annotations

import os
from typing import Any, Mapping

import numpy as np

from src.core.asr.faster_whisper_engine import ASR_SOURCE_ID, transcribe_wav
from src.core.understanding.base import UnderstandingComponent, merge_params


class FasterWhisperMediumSpeechToTextComponent(UnderstandingComponent):
    def __init__(
        self,
        manifest: Mapping[str, Any],
        component_dir: str,
        params: Mapping[str, Any] | None = None,
        runtime: Mapping[str, Any] | None = None,
    ):
        self.component_id = str(manifest.get("id", "") or "").strip() or ASR_SOURCE_ID
        self._manifest = dict(manifest)
        self._component_dir = os.path.normpath(os.path.abspath(component_dir))
        self._params = merge_params(manifest, params)
        self._runtime = dict(runtime or manifest.get("runtime") or {})
        model_bin = os.path.join(self._component_dir, "model.bin")
        if not os.path.isfile(model_bin):
            raise RuntimeError(f"Faster-Whisper model.bin not found under {self._component_dir}")

    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        raise TypeError(
            "Faster-Whisper speech_to_text expects audio input. "
            "Use transcribe() or transcribe_file() instead of infer(image_bgr)."
        )

    def transcribe_file(
        self,
        wav_path: str,
        *,
        language: str | None = None,
    ) -> dict[str, Any]:
        return self.transcribe(
            wav_path,
            language=language or str(self._params.get("language", "auto")),
        )

    def transcribe(
        self,
        audio: str | np.ndarray,
        *,
        language: str = "auto",
    ) -> dict[str, Any]:
        if not isinstance(audio, str):
            raise TypeError("Faster-Whisper component currently expects a WAV file path")
        rows = transcribe_wav(
            audio,
            language=language,
            model_dir=self._component_dir,
        )
        text = " ".join(str(row.get("text", "") or "").strip() for row in rows).strip()
        language_out = ""
        if rows:
            language_out = str(rows[0].get("language", "") or "").strip()
        return {
            "source": self.component_id,
            "text": text,
            "language": language_out,
            "segments": rows,
            "meaningful": bool(text),
        }

    def close(self) -> None:
        return None

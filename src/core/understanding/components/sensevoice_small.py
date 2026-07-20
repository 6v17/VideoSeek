from __future__ import annotations

import os
from typing import Any, Mapping

import numpy as np

from src.core.asr.sensevoice_engine import get_sensevoice_engine
from src.core.understanding.base import UnderstandingComponent, merge_params


def _resolve_model_path(component_dir: str, files_map: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    files_map = dict(files_map or manifest.get("files") or {})
    model_name = str(files_map.get("model", "") or "").strip()
    if not model_name:
        required = list(manifest.get("required_files") or [])
        for candidate in required:
            if str(candidate).endswith(".onnx"):
                model_name = str(candidate)
                break
    if not model_name:
        raise RuntimeError("Missing ONNX model mapping for SenseVoice component")
    model_path = os.path.join(component_dir, model_name)
    if not os.path.isfile(model_path):
        raise RuntimeError(f"Model file not found: {model_path}")
    return model_path


class SenseVoiceSmallSpeechToTextComponent(UnderstandingComponent):
    def __init__(
        self,
        manifest: Mapping[str, Any],
        component_dir: str,
        params: Mapping[str, Any] | None = None,
        runtime: Mapping[str, Any] | None = None,
    ):
        self.component_id = str(manifest.get("id", "") or "").strip()
        self._manifest = dict(manifest)
        self._component_dir = component_dir
        self._params = merge_params(manifest, params)
        self._runtime = dict(runtime or manifest.get("runtime") or {})
        self._quantize = bool(self._params.get("quantize", False))
        _resolve_model_path(component_dir, dict(manifest.get("files") or {}), manifest)
        self._engine = get_sensevoice_engine(
            component_dir,
            quantize=self._quantize,
            prefer_gpu=bool(self._runtime.get("prefer_gpu", False)),
            provider_hints=list(self._runtime.get("provider_hints") or []),
            runtime=self._runtime,
        )

    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        raise TypeError(
            "SenseVoice speech_to_text expects audio input. "
            "Use transcribe() or transcribe_file() instead of infer(image_bgr)."
        )

    def transcribe_file(
        self,
        wav_path: str,
        *,
        language: str | None = None,
        use_itn: bool | None = None,
    ) -> dict[str, Any]:
        return self.transcribe(
            wav_path,
            language=language or str(self._params.get("language", "auto")),
            use_itn=bool(self._params.get("use_itn", True) if use_itn is None else use_itn),
        )

    def transcribe(
        self,
        audio: str | np.ndarray,
        *,
        language: str = "auto",
        use_itn: bool = True,
    ) -> dict[str, Any]:
        result = self._engine.transcribe(audio, language=language, use_itn=use_itn)
        return {
            "source": self.component_id,
            "raw": result.get("raw", ""),
            "text": result.get("text", ""),
            "language": result.get("language", ""),
            "tags": list(result.get("tags") or []),
            "meaningful": bool(result.get("meaningful")),
        }

    def close(self) -> None:
        return None

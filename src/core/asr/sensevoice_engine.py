from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

import numpy as np
import onnxruntime as ort
import yaml

from src.core.asr.audio_io import load_wav_mono
from src.core.asr.sensevoice_frontend import SenseVoiceFrontend
from src.core.asr.sensevoice_postprocess import is_meaningful_transcript, normalize_transcript
from src.core.onnx_session import build_session_options

_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, "SenseVoiceOnnxEngine"] = {}

LANGUAGE_IDS = {
    "auto": 0,
    "zh": 3,
    "en": 4,
    "yue": 7,
    "ja": 11,
    "ko": 12,
    "nospeech": 13,
}
TEXTNORM_IDS = {
    "withitn": 14,
    "woitn": 15,
}
MAX_SUPPORTED_ONNX_IR = 11


class SenseVoiceOnnxEngine:
    def __init__(
        self,
        model_dir: str,
        *,
        quantize: bool = True,
        intra_op_num_threads: int = 4,
        prefer_gpu: bool = False,
        provider_hints: Sequence[str] | None = None,
    ) -> None:
        self.model_dir = os.path.normpath(str(model_dir))
        self.quantize = bool(quantize)
        self.model_path = self._resolve_model_path(self.model_dir, quantize=self.quantize)
        self._validate_model_runtime(self.model_path)
        self.frontend = self._build_frontend(self.model_dir)
        self.token_list = self._load_token_list(self.model_dir)
        self.blank_id = 0
        self._session = self._create_session(
            self.model_path,
            prefer_gpu=prefer_gpu,
            provider_hints=provider_hints,
            intra_op_num_threads=intra_op_num_threads,
        )

    def transcribe(
        self,
        audio: Union[str, np.ndarray],
        *,
        language: str = "auto",
        use_itn: bool = True,
    ) -> dict[str, Any]:
        waveform = self._load_audio(audio)
        feat, feat_len = self.frontend.extract(waveform)
        feats = self._pad_feats([feat], feat_len)
        feats_len = np.array([feat_len], dtype=np.int32)
        language_id = self._resolve_language_id(language)
        textnorm_id = TEXTNORM_IDS["withitn" if use_itn else "woitn"]
        language_arr = np.array([language_id], dtype=np.int32)
        textnorm_arr = np.array([textnorm_id], dtype=np.int32)

        with _ENGINE_LOCK:
            outputs = self._session.run(
                None,
                {
                    self._session.get_inputs()[0].name: feats,
                    self._session.get_inputs()[1].name: feats_len,
                    self._session.get_inputs()[2].name: language_arr,
                    self._session.get_inputs()[3].name: textnorm_arr,
                },
            )

        logits = outputs[0]
        encoder_out_lens = outputs[1]
        raw_text = self._decode_logits(logits[0], int(encoder_out_lens[0]))
        normalized = normalize_transcript(raw_text, use_itn=use_itn)
        normalized["meaningful"] = is_meaningful_transcript(normalized)
        return normalized

    def close(self) -> None:
        return None

    @staticmethod
    def _resolve_model_path(model_dir: str, *, quantize: bool) -> str:
        preferred = "model_quant.onnx" if quantize else "model.onnx"
        preferred_path = os.path.join(model_dir, preferred)
        if os.path.isfile(preferred_path):
            return preferred_path
        if quantize:
            fallback = os.path.join(model_dir, "model.onnx")
            if os.path.isfile(fallback):
                return fallback
        raise FileNotFoundError(
            f"SenseVoice ONNX model not found under {model_dir}. "
            f"Expected {preferred!r}."
        )

    @staticmethod
    def _validate_model_runtime(model_path: str) -> None:
        try:
            import onnx
        except ImportError:
            return

        model = onnx.load(model_path, load_external_data=False)
        ir_version = int(getattr(model, "ir_version", 0) or 0)
        if ir_version > MAX_SUPPORTED_ONNX_IR:
            raise RuntimeError(
                f"{os.path.basename(model_path)} uses ONNX IR {ir_version}, "
                f"but VideoSeek onnxruntime 1.23 supports <= {MAX_SUPPORTED_ONNX_IR}. "
                "Re-export with sensevoice/export_onnx.py in adaframe, or use the int8 package."
            )
        data_path = f"{model_path}.data"
        if os.path.getsize(model_path) < 5 * 1024 * 1024 and not os.path.isfile(data_path):
            raise FileNotFoundError(f"Missing external ONNX weights: {data_path}")

    @staticmethod
    def _build_frontend(model_dir: str) -> SenseVoiceFrontend:
        config_path = os.path.join(model_dir, "config.yaml")
        cmvn_path = os.path.join(model_dir, "am.mvn")
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"SenseVoice config.yaml not found: {config_path}")
        if not os.path.isfile(cmvn_path):
            raise FileNotFoundError(f"SenseVoice am.mvn not found: {cmvn_path}")

        with open(config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        frontend_conf = dict(config.get("frontend_conf") or {})
        frontend_conf["cmvn_file"] = cmvn_path
        return SenseVoiceFrontend(**frontend_conf)

    @staticmethod
    def _load_token_list(model_dir: str) -> list[str]:
        tokens_path = os.path.join(model_dir, "tokens.json")
        if not os.path.isfile(tokens_path):
            raise FileNotFoundError(f"SenseVoice tokens.json not found: {tokens_path}")
        with open(tokens_path, "r", encoding="utf-8") as handle:
            token_list = json.load(handle)
        if not isinstance(token_list, list) or not token_list:
            raise ValueError(f"Invalid tokens.json under {model_dir}")
        return [str(item) for item in token_list]

    @staticmethod
    def _create_session(
        model_path: str,
        *,
        prefer_gpu: bool,
        provider_hints: Sequence[str] | None,
        intra_op_num_threads: int,
    ) -> ort.InferenceSession:
        hints = [str(item or "").strip() for item in (provider_hints or []) if str(item or "").strip()]
        available = set(ort.get_available_providers())
        if prefer_gpu:
            providers = [provider for provider in (hints or ["DmlExecutionProvider", "CPUExecutionProvider"]) if provider in available]
        else:
            providers = ["CPUExecutionProvider"]
        if not providers:
            providers = ["CPUExecutionProvider"]

        session_options = build_session_options(prefer_gpu and providers[0] != "CPUExecutionProvider")
        session_options.intra_op_num_threads = max(1, int(intra_op_num_threads))
        return ort.InferenceSession(model_path, sess_options=session_options, providers=providers)

    def _load_audio(self, audio: Union[str, np.ndarray]) -> np.ndarray:
        if isinstance(audio, np.ndarray):
            return np.ascontiguousarray(audio.astype(np.float32))
        return load_wav_mono(str(audio), target_sr=self.frontend.sample_rate)

    @staticmethod
    def _pad_feats(feats: list[np.ndarray], max_feat_len: int) -> np.ndarray:
        padded = []
        for feat in feats:
            cur_len = feat.shape[0]
            if cur_len < max_feat_len:
                pad_width = ((0, max_feat_len - cur_len), (0, 0))
                feat = np.pad(feat, pad_width, mode="constant")
            padded.append(feat)
        return np.asarray(padded, dtype=np.float32)

    def _resolve_language_id(self, language: str) -> int:
        key = str(language or "auto").strip().lower()
        if key not in LANGUAGE_IDS:
            raise ValueError(f"Unsupported language: {language!r}")
        return LANGUAGE_IDS[key]

    def _decode_logits(self, logits: np.ndarray, length: int) -> str:
        if length <= 0:
            return ""
        frame_logits = logits[:length]
        token_ids = frame_logits.argmax(axis=-1)
        token_ids = self._unique_consecutive(token_ids)
        token_ids = token_ids[token_ids != self.blank_id]
        pieces = [self.token_list[int(token_id)] for token_id in token_ids if 0 <= int(token_id) < len(self.token_list)]
        return "".join(pieces)

    @staticmethod
    def _unique_consecutive(token_ids: np.ndarray) -> np.ndarray:
        if token_ids.size == 0:
            return token_ids
        mask = np.concatenate(([True], token_ids[1:] != token_ids[:-1]))
        return token_ids[mask]


def get_sensevoice_engine(
    model_dir: str,
    *,
    quantize: bool = False,
    prefer_gpu: bool = False,
    provider_hints: Sequence[str] | None = None,
    runtime: Mapping[str, Any] | None = None,
) -> SenseVoiceOnnxEngine:
    runtime_payload = dict(runtime or {})
    if "quantize" in runtime_payload:
        quantize = bool(runtime_payload.get("quantize"))
    resolved_dir = os.path.normpath(str(model_dir))
    cache_key = "|".join(
        [
            resolved_dir,
            "1" if quantize else "0",
            "1" if bool(runtime_payload.get("prefer_gpu", prefer_gpu)) else "0",
            str(runtime_payload.get("intra_op_num_threads", 4)),
        ]
    )
    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        engine = SenseVoiceOnnxEngine(
            resolved_dir,
            quantize=quantize,
            prefer_gpu=bool(runtime_payload.get("prefer_gpu", prefer_gpu)),
            provider_hints=list(runtime_payload.get("provider_hints") or provider_hints or []),
            intra_op_num_threads=int(runtime_payload.get("intra_op_num_threads", 4)),
        )
        _ENGINE_CACHE[cache_key] = engine
        return engine


def clear_sensevoice_engine_cache() -> None:
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()

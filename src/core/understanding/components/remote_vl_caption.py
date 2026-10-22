from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from src.core.understanding.base import UnderstandingComponent, UnderstandingStoppedError, merge_params
from src.services.cancellable_http import urlopen_json_with_stop

# Upload policy before base64 (composite keyframes can be 2x–4x source width).
VLM_UPLOAD_MAX_LONG_EDGE_CLOUD = 1280
VLM_UPLOAD_MAX_LONG_EDGE_LOCAL = 1920
VLM_UPLOAD_JPEG_QUALITY_CLOUD = 80
VLM_UPLOAD_JPEG_QUALITY_LOCAL = 85


def limit_image_long_edge(image_bgr: np.ndarray, max_long_edge: int) -> np.ndarray:
    """Shrink so max(height, width) <= max_long_edge; no-op when limit <= 0."""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return image_bgr
    limit = int(max_long_edge)
    if limit <= 0:
        return image_bgr
    height, width = int(image_bgr.shape[0]), int(image_bgr.shape[1])
    long_edge = max(height, width)
    if long_edge <= limit:
        return image_bgr
    scale = limit / float(long_edge)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    return cv2.resize(image_bgr, (new_width, new_height), interpolation=cv2.INTER_AREA)


def resolve_vlm_upload_limits(
    settings: Mapping[str, Any],
    params: Mapping[str, Any],
) -> tuple[int, int]:
    """Return (max_long_edge, jpeg_quality) for the next VLM image upload."""
    from src.services.understanding_resource_service import (
        REMOTE_VLM_MODE_CLOUD,
        normalize_remote_vlm_provider_mode,
    )

    mode = normalize_remote_vlm_provider_mode(settings.get("provider_mode"))
    cloud = mode == REMOTE_VLM_MODE_CLOUD

    default_edge = VLM_UPLOAD_MAX_LONG_EDGE_CLOUD if cloud else VLM_UPLOAD_MAX_LONG_EDGE_LOCAL
    edge_raw = settings.get("upload_max_long_edge", params.get("upload_max_long_edge"))
    if edge_raw is not None and str(edge_raw).strip() != "":
        max_long_edge = int(edge_raw)
        if max_long_edge <= 0:
            max_long_edge = default_edge
    else:
        max_long_edge = default_edge

    quality_raw = settings.get("upload_jpeg_quality")
    if quality_raw is None or str(quality_raw).strip() == "":
        quality_raw = params.get("upload_jpeg_quality")
    if quality_raw is not None and str(quality_raw).strip() != "":
        jpeg_quality = int(quality_raw)
    elif cloud:
        jpeg_quality = VLM_UPLOAD_JPEG_QUALITY_CLOUD
    else:
        jpeg_quality = int(params.get("jpeg_quality") or VLM_UPLOAD_JPEG_QUALITY_LOCAL)

    jpeg_quality = max(50, min(95, int(jpeg_quality)))
    return int(max_long_edge), jpeg_quality


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise ValueError("remote VLM base_url is required")
    if text.endswith("/v1"):
        return text
    if text.endswith("/v1/"):
        return text.rstrip("/")
    return f"{text}/v1"


def probe_remote_vl_vision(
    settings: Mapping[str, Any],
    *,
    timeout_sec: float = 15.0,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One minimal chat+image request to verify the model accepts vision input."""
    import urllib.error
    import urllib.request

    from src.services.understanding_resource_service import (
        build_remote_vlm_auth_headers,
    )

    empty = {"ok": False, "error": "", "http_status": 0, "detail": ""}
    try:
        base_url = _normalize_base_url(str(settings.get("base_url", "") or ""))
    except ValueError as exc:
        empty["error"] = str(exc)
        return empty
    model = str(settings.get("model", "") or "").strip()
    if not model:
        empty["error"] = "model is not configured"
        return empty

    probe_bgr = np.zeros((64, 64, 3), dtype=np.uint8)
    probe_bgr[26:38, 26:38] = (220, 220, 220)
    merged_params = dict(params or {})
    _, jpeg_quality = resolve_vlm_upload_limits(settings, merged_params)
    image_b64 = _encode_image_jpeg_base64(probe_bgr, jpeg_quality=min(int(jpeg_quality), 78))

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Reply with exactly: OK"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 16,
        "temperature": 0.0,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **build_remote_vlm_auth_headers(settings),
        },
        method="POST",
    )
    try:
        body = _post_json_with_stop(
            request,
            timeout_sec=max(5.0, float(timeout_sec)),
            should_stop_callback=None,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return {
            "ok": False,
            "error": f"HTTP {exc.code}: {detail[:320] or exc.reason}",
            "http_status": int(exc.code),
            "detail": detail[:320],
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "error": str(getattr(exc, "reason", exc) or exc),
            "http_status": 0,
            "detail": "",
        }
    except TimeoutError:
        return {
            "ok": False,
            "error": f"vision probe timed out after {timeout_sec:.0f}s",
            "http_status": 0,
            "detail": "",
        }
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "http_status": 0, "detail": ""}

    choices = body.get("choices") or []
    if not choices:
        return {"ok": False, "error": "vision probe returned no choices", "http_status": 200, "detail": ""}
    message = choices[0].get("message") or {}
    text = str(message.get("content", "") or message.get("reasoning_content", "") or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "vision probe returned empty content (model may be text-only)",
            "http_status": 200,
            "detail": "",
        }
    return {"ok": True, "error": "", "http_status": 200, "detail": text[:80]}


def _encode_image_jpeg_base64(image_bgr: np.ndarray, *, jpeg_quality: int = 85) -> str:
    ok, encoded = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise RuntimeError("Failed to encode frame as JPEG")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _post_json_with_stop(
    request: urllib.request.Request,
    *,
    timeout_sec: float,
    should_stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    return urlopen_json_with_stop(
        request,
        timeout_sec=timeout_sec,
        should_stop_callback=should_stop_callback,
        stop_message="Evidence generation stopped by user",
    )


class RemoteVlCaptionComponent(UnderstandingComponent):
    """Image caption via an OpenAI-compatible local VLM server (e.g. LM Studio + Qwen3-VL)."""

    def __init__(
        self,
        manifest: Mapping[str, Any],
        component_dir: str,
        params: Mapping[str, Any] | None = None,
        runtime: Mapping[str, Any] | None = None,
        *,
        config=None,
    ):
        self.component_id = str(manifest.get("id", "") or "").strip()
        self._manifest = dict(manifest)
        self._component_dir = component_dir
        self._params = merge_params(manifest, params)
        self._runtime = dict(runtime or manifest.get("runtime") or {})
        self._config = config
        self._should_stop_callback: Callable[[], bool] | None = None

    def bind_should_stop_callback(self, should_stop_callback: Callable[[], bool] | None) -> None:
        self._should_stop_callback = should_stop_callback

    def infer(self, image_bgr: np.ndarray, prompt_suffix: str = "") -> dict[str, Any]:
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return {"text": ""}

        if self._should_stop_callback and self._should_stop_callback():
            raise UnderstandingStoppedError("Evidence generation stopped by user")

        from src.services.understanding_resource_service import (
            build_remote_vlm_auth_headers,
            get_remote_vlm_settings,
        )

        if self._config is None:
            raise RuntimeError("remote VLM component requires caller-supplied config")
        settings = get_remote_vlm_settings(self._config)
        base_url = _normalize_base_url(settings["base_url"])
        model = str(settings.get("model", "") or "").strip()
        if not model:
            raise RuntimeError("remote VLM model is not configured")

        prompt = str(
            settings.get("prompt")
            or self._params.get("prompt")
            or "Describe this video frame in one or two concise sentences."
        ).strip()
        extra = str(prompt_suffix or "").strip()
        if extra:
            prompt = f"{prompt}\n\n{extra}"
        timeout_sec = float(settings.get("timeout_sec", 120) or 120)
        max_tokens = int(settings.get("max_tokens", self._params.get("max_tokens", 128)) or 128)
        max_long_edge, jpeg_quality = resolve_vlm_upload_limits(settings, self._params)
        upload_bgr = limit_image_long_edge(image_bgr, max_long_edge)

        image_b64 = _encode_image_jpeg_base64(upload_bgr, jpeg_quality=jpeg_quality)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": max(16, min(512, max_tokens)),
            "temperature": float(self._params.get("temperature", 0.2) or 0.2),
        }

        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **build_remote_vlm_auth_headers(settings),
            },
            method="POST",
        )
        try:
            body = _post_json_with_stop(
                request,
                timeout_sec=timeout_sec,
                should_stop_callback=self._should_stop_callback,
            )
        except UnderstandingStoppedError:
            raise
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"remote VLM HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"remote VLM unreachable at {base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"remote VLM timed out after {timeout_sec:.0f}s") from exc

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("remote VLM returned no choices")
        message = choices[0].get("message") or {}
        text = str(message.get("content", "") or "").strip()
        if not text and message.get("reasoning_content"):
            text = str(message.get("reasoning_content", "") or "").strip()
        return {"text": text}

    def close(self) -> None:
        return None


def call_remote_vlm_text_completion(
    *,
    prompt: str,
    config=None,
    max_tokens: int = 256,
    temperature: float = 0.3,
    should_stop_callback=None,
) -> str:
    """Text-only chat completion against the configured remote VLM."""
    if should_stop_callback and should_stop_callback():
        raise UnderstandingStoppedError("Evidence generation stopped by user")

    from src.services.understanding_resource_service import (
        build_remote_vlm_auth_headers,
        get_remote_vlm_settings,
    )

    if config is None:
        from src.app.config import load_config

        config = load_config()
    settings = get_remote_vlm_settings(config)
    base_url = _normalize_base_url(settings["base_url"])
    model = str(settings.get("model", "") or "").strip()
    if not model:
        raise RuntimeError("remote VLM model is not configured")

    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return ""

    timeout_sec = float(settings.get("timeout_sec", 120) or 120)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": max(32, min(1024, int(max_tokens))),
        "temperature": float(temperature),
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **build_remote_vlm_auth_headers(settings),
        },
        method="POST",
    )
    try:
        body = _post_json_with_stop(
            request,
            timeout_sec=timeout_sec,
            should_stop_callback=should_stop_callback,
        )
    except UnderstandingStoppedError:
        raise
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"remote VLM HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"remote VLM unreachable at {base_url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"remote VLM timed out after {timeout_sec:.0f}s") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("remote VLM returned no choices")
    message = choices[0].get("message") or {}
    text = str(message.get("content", "") or "").strip()
    if not text and message.get("reasoning_content"):
        text = str(message.get("reasoning_content", "") or "").strip()
    return text

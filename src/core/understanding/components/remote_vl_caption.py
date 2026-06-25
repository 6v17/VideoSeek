from __future__ import annotations

import base64
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from src.app.config import load_config
from src.core.understanding.base import UnderstandingComponent, UnderstandingStoppedError, merge_params


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise ValueError("remote VLM base_url is required")
    if text.endswith("/v1"):
        return text
    if text.endswith("/v1/"):
        return text.rstrip("/")
    return f"{text}/v1"


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
    def _do_post() -> dict[str, Any]:
        with urllib.request.urlopen(request, timeout=max(5.0, timeout_sec)) as response:
            return json.loads(response.read().decode("utf-8"))

    deadline = time.monotonic() + max(5.0, float(timeout_sec))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_post)
        while True:
            if should_stop_callback and should_stop_callback():
                raise UnderstandingStoppedError("Evidence generation stopped by user")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"remote VLM timed out after {timeout_sec:.0f}s")
            try:
                return future.result(timeout=min(0.25, remaining))
            except concurrent.futures.TimeoutError:
                continue


class RemoteVlCaptionComponent(UnderstandingComponent):
    """Image caption via an OpenAI-compatible local VLM server (e.g. LM Studio + Qwen3-VL)."""

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
        self._should_stop_callback: Callable[[], bool] | None = None

    def bind_should_stop_callback(self, should_stop_callback: Callable[[], bool] | None) -> None:
        self._should_stop_callback = should_stop_callback

    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return {"text": ""}

        if self._should_stop_callback and self._should_stop_callback():
            raise UnderstandingStoppedError("Evidence generation stopped by user")

        from src.services.understanding_resource_service import get_remote_vlm_settings

        settings = get_remote_vlm_settings(load_config())
        base_url = _normalize_base_url(settings["base_url"])
        model = str(settings.get("model", "") or "").strip()
        if not model:
            raise RuntimeError("remote VLM model is not configured")

        prompt = str(
            settings.get("prompt")
            or self._params.get("prompt")
            or "Describe this video frame in one or two concise sentences."
        ).strip()
        timeout_sec = float(settings.get("timeout_sec", 120) or 120)
        max_tokens = int(settings.get("max_tokens", self._params.get("max_tokens", 128)) or 128)
        jpeg_quality = int(self._params.get("jpeg_quality", 85) or 85)

        image_b64 = _encode_image_jpeg_base64(image_bgr, jpeg_quality=jpeg_quality)
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
            headers={"Content-Type": "application/json"},
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

    from src.services.understanding_resource_service import get_remote_vlm_settings

    settings = get_remote_vlm_settings(load_config() if config is None else config)
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
        headers={"Content-Type": "application/json"},
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

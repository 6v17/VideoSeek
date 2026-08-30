"""OpenAI-compatible POST /v1/audio/transcriptions (multipart, stdlib only)."""

from __future__ import annotations

import base64
import json
import time
import uuid
import urllib.error
import urllib.request
from typing import Any, Mapping

from src.services.asr_settings import (
    ASR_SOURCE_ID,
    build_remote_asr_auth_headers,
    finalize_remote_asr_settings,
    get_active_remote_asr_api_key,
)

_MAX_ERROR_CHARS = 400
_TRANSIENT_ERRNOS = {10054, 10053, 10060, 10061, 104, 110, 111}
_EMPTY_ASR_NEEDLES = (
    "ASR_RESPONSE_HAVE_NO_WORDS",
    "HAVE_NO_WORDS",
)
_TRANSIENT_NEEDLES = (
    "10054",
    "10053",
    "10060",
    "10061",
    "econnreset",
    "econnaborted",
    "etimedout",
    "econnrefused",
    "forcibly closed",
    "connection reset",
    "broken pipe",
    "incomplete read",
    "remote end closed",
    "timed out",
    "timeout",
    "强迫关闭",
    "远程主机",
)


def parse_transcription_payload(
    payload: Mapping[str, Any] | None,
    *,
    offset_sec: float = 0.0,
    duration_sec: float = 0.0,
    asr_source: str = ASR_SOURCE_ID,
) -> list[dict[str, Any]]:
    """Turn verbose_json, plain json, or DashScope chat-ASR into dialogue rows."""
    data = dict(payload or {})
    offset = float(offset_sec or 0.0)
    source = str(asr_source or ASR_SOURCE_ID).strip() or ASR_SOURCE_ID
    language = str(data.get("language") or "").strip()
    rows: list[dict[str, Any]] = []
    for item in data.get("segments") or []:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = offset + float(item.get("start") or 0.0)
        end = offset + float(item.get("end") or start)
        if end < start:
            end = start
        rows.append(
            {
                "start": start,
                "end": max(end, start + 0.05),
                "text": text,
                "language": str(item.get("language") or language or "").strip(),
                "asr_source": source,
            }
        )
    if rows:
        return rows
    native_rows = _extract_dashscope_native_rows(
        data,
        offset_sec=offset,
        duration_sec=float(duration_sec or 0.0),
        asr_source=source,
        language=language,
    )
    if native_rows:
        return native_rows
    text, chat_language = _extract_chat_asr_text(data)
    if not text:
        text = str(data.get("text") or "").strip()
    if not text:
        return []
    duration = float(duration_sec or 0.0)
    if duration <= 0:
        usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
        duration = float((usage or {}).get("seconds") or data.get("duration") or 0.0)
    return [
        {
            "start": offset,
            "end": offset + max(duration, 0.4),
            "text": text,
            "language": chat_language or language,
            "asr_source": source,
        }
    ]


def _extract_dashscope_native_rows(
    payload: Mapping[str, Any],
    *,
    offset_sec: float,
    duration_sec: float,
    asr_source: str,
    language: str,
) -> list[dict[str, Any]]:
    output = payload.get("output")
    if not isinstance(output, Mapping):
        return []
    text = ""
    start = float(offset_sec or 0.0)
    end = start
    sentence = output.get("sentence")
    if isinstance(sentence, Mapping):
        text = str(sentence.get("text") or output.get("text") or "").strip()
        begin_ms = sentence.get("begin_time")
        end_ms = sentence.get("end_time")
        if begin_ms is not None:
            start = float(offset_sec or 0.0) + (float(begin_ms) / 1000.0)
        if end_ms is not None:
            end = float(offset_sec or 0.0) + (float(end_ms) / 1000.0)
    if not text:
        text = str(output.get("text") or "").strip()
    if not text:
        return []
    duration = float(duration_sec or 0.0)
    if duration <= 0:
        usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
        duration = float((usage or {}).get("duration") or 0.0)
    if end <= start:
        end = start + max(duration, 0.4)
    return [
        {
            "start": start,
            "end": max(end, start + 0.05),
            "text": text,
            "language": str(language or "").strip(),
            "asr_source": asr_source,
        }
    ]


def _extract_chat_asr_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    message = first.get("message") if isinstance(first.get("message"), Mapping) else {}
    content = message.get("content")
    text = ""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                parts.append(str(item.get("text") or item.get("content") or "").strip())
        text = "".join(parts).strip()
    language = ""
    for bucket in (message.get("annotations"), first.get("annotations")):
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, Mapping) and item.get("language"):
                language = str(item.get("language") or "").strip()
                break
        if language:
            break
    return text, language


def uses_dashscope_chat_asr(settings: Mapping[str, Any] | None) -> bool:
    payload = dict(settings or {})
    preset = str(payload.get("provider_preset") or "").strip().lower()
    if preset == "dashscope":
        return True
    host = str(payload.get("base_url") or "").lower()
    return "dashscope.aliyuncs.com" in host or "dashscope-intl.aliyuncs.com" in host


def uses_dashscope_native_audio_asr(settings: Mapping[str, Any] | None) -> bool:
    """qwen-audio-3.0-asr-flash requires DashScope multimodal-generation, not chat/completions."""
    payload = dict(settings or {})
    model = str(payload.get("model") or "").strip().lower()
    if "qwen-audio-3.0" in model:
        return True
    return uses_dashscope_chat_asr(payload) and model.startswith("qwen-audio-")


def dashscope_native_generation_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if text.endswith("/v1"):
        text = text[:-3].rstrip("/")
    if text.endswith("/compatible-mode"):
        text = text[: -len("/compatible-mode")].rstrip("/")
    if not text:
        raise RuntimeError("remote ASR base_url is required")
    return f"{text}/api/v1/services/aigc/multimodal-generation/generation"


def dashscope_audio_format(filename: str = "", content_type: str = "") -> str:
    name = str(filename or "").strip().lower()
    mime = str(content_type or "").strip().lower()
    if "wav" in mime or name.endswith(".wav"):
        return "wav"
    if "mpeg" in mime or "mp3" in mime or name.endswith(".mp3"):
        return "mp3"
    return "wav"


def build_dashscope_input_audio(
    raw: bytes,
    *,
    filename: str = "",
    content_type: str = "",
    data_url: bool = True,
) -> dict[str, str]:
    fmt = dashscope_audio_format(filename, content_type)
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    mime = "audio/wav" if fmt == "wav" else "audio/mpeg"
    data = f"data:{mime};base64,{encoded}" if data_url else encoded
    return {"data": data, "format": fmt}


def build_dashscope_native_payload(
    raw: bytes,
    *,
    model: str,
    filename: str = "",
    content_type: str = "",
    language: str = "",
    sample_rate: int = 16000,
) -> dict[str, Any]:
    fmt = dashscope_audio_format(filename, content_type)
    audio = build_dashscope_input_audio(
        raw,
        filename=filename,
        content_type=content_type,
        data_url=True,
    )
    parameters: dict[str, Any] = {
        "format": fmt,
        "sample_rate": str(int(sample_rate or 16000)),
    }
    lang = str(language or "").strip().lower()
    if lang:
        parameters["language_hints"] = [lang]
    return {
        "model": str(model or "").strip(),
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio["data"]},
                        }
                    ],
                }
            ]
        },
        "parameters": parameters,
    }


def is_empty_asr_result(exc: BaseException | str) -> bool:
    """DashScope reports silence / music as HTTP 400 CLIENT_ERROR, not an empty transcript."""
    text = str(exc or "")
    return any(needle in text for needle in _EMPTY_ASR_NEEDLES)


def is_transient_asr_error(exc: BaseException | str) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, "code", 0) or 0) in {408, 429, 502, 503, 504}:
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return True
        errno = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
        if errno in _TRANSIENT_ERRNOS:
            return True
    text = str(exc or "").lower()
    return any(needle in text for needle in _TRANSIENT_NEEDLES)


def format_asr_error(exc: BaseException | str) -> str:
    detail = str(exc or "").strip() or "ASR transcription failed"
    if is_transient_asr_error(exc):
        return (
            "语音服务把连接掐了（不是整段视频一次上传，每次大约 20 秒）。"
            "常见原因：网络/代理不稳定，或国内访问 OpenAI 被重置。"
            "请重试；若一直失败，改用通义千问 ASR。"
            f" 原始错误：{detail[:_MAX_ERROR_CHARS]}"
        )
    return detail[:_MAX_ERROR_CHARS]


def transcribe_wav_bytes(
    wav_bytes: bytes,
    *,
    settings: Mapping[str, Any],
    filename: str = "clip.wav",
    content_type: str = "audio/wav",
    language: str = "",
    timeout_sec: float | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    """Upload a short audio clip and return the parsed JSON payload."""
    remote = finalize_remote_asr_settings(settings)
    base_url = _normalize_base_url(str(remote.get("base_url") or ""))
    model = str(remote.get("model") or "").strip()
    if not model:
        raise RuntimeError("remote ASR model is not configured")
    provider_mode = str(remote.get("provider_mode") or "").strip().lower()
    if provider_mode == "cloud" and not get_active_remote_asr_api_key(remote):
        raise RuntimeError("API Key is required for cloud ASR providers")
    if not wav_bytes:
        raise ValueError("wav payload is empty")

    if uses_dashscope_native_audio_asr(remote):
        return _transcribe_dashscope_native(
            wav_bytes,
            settings=remote,
            filename=filename,
            content_type=content_type,
            language=language,
            timeout_sec=timeout_sec,
            attempts=attempts,
        )
    if uses_dashscope_chat_asr(remote):
        return _transcribe_dashscope_chat(
            wav_bytes,
            settings=remote,
            filename=filename,
            content_type=content_type,
            language=language,
            timeout_sec=timeout_sec,
            attempts=attempts,
        )

    fields = {
        "model": model,
        "response_format": "verbose_json",
    }
    lang = str(language or remote.get("language") or "").strip().lower()
    if lang in {"zh", "en"}:
        fields["language"] = lang
    timeout = float(timeout_sec if timeout_sec is not None else remote.get("timeout_sec") or 120)
    last_error: BaseException | None = None
    formats = ("verbose_json", "json")
    for response_format in formats:
        fields["response_format"] = response_format
        body, multipart_type = _encode_multipart(
            fields,
            files=[
                (
                    "file",
                    str(filename or "clip.wav"),
                    bytes(wav_bytes),
                    str(content_type or "audio/wav"),
                )
            ],
        )
        tries = max(1, int(attempts))
        for attempt in range(tries):
            try:
                return _post_transcription(
                    f"{base_url}/audio/transcriptions",
                    body=body,
                    content_type=multipart_type,
                    headers=build_remote_asr_auth_headers(remote),
                    timeout_sec=timeout,
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                last_error = RuntimeError(_http_error_message(exc.code, detail, url=f"{base_url}/audio/transcriptions"))
                if exc.code == 400 and response_format == "verbose_json":
                    break
                if is_transient_asr_error(exc) and attempt + 1 < tries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise last_error from exc
            except Exception as exc:
                last_error = exc
                if is_transient_asr_error(exc) and attempt + 1 < tries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise RuntimeError(format_asr_error(exc)) from exc
    raise RuntimeError(format_asr_error(last_error or "ASR transcription failed"))


def _transcribe_dashscope_native(
    wav_bytes: bytes,
    *,
    settings: Mapping[str, Any],
    filename: str,
    content_type: str,
    language: str,
    timeout_sec: float | None,
    attempts: int,
) -> dict[str, Any]:
    """qwen-audio-3.0-asr-flash: POST multimodal-generation with required parameters.format."""
    url = dashscope_native_generation_url(str(settings.get("base_url") or ""))
    model = str(settings.get("model") or "").strip()
    lang = str(language or settings.get("language") or "").strip().lower()
    payload = build_dashscope_native_payload(
        wav_bytes,
        model=model,
        filename=filename,
        content_type=content_type,
        language=lang,
    )
    timeout = float(timeout_sec if timeout_sec is not None else settings.get("timeout_sec") or 120)
    headers = {
        **build_remote_asr_auth_headers(settings),
        "X-DashScope-SSE": "disable",
    }
    last_error: BaseException | None = None
    tries = max(1, int(attempts))
    for attempt in range(tries):
        try:
            parsed = _post_json(url, payload, headers=headers, timeout_sec=timeout)
            return _ensure_asr_success(parsed)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if is_empty_asr_result(detail):
                return {"output": {"text": ""}, "usage": {"duration": 0}}
            last_error = RuntimeError(_http_error_message(exc.code, detail, url=url, model=model))
            if is_transient_asr_error(exc) and attempt + 1 < tries:
                time.sleep(min(8.0, 1.2 * (2**attempt)))
                continue
            raise last_error from exc
        except Exception as exc:
            last_error = exc
            if is_empty_asr_result(exc):
                return {"output": {"text": ""}, "usage": {"duration": 0}}
            if is_transient_asr_error(exc) and attempt + 1 < tries:
                time.sleep(min(8.0, 1.2 * (2**attempt)))
                continue
            raise RuntimeError(format_asr_error(exc)) from exc
    raise RuntimeError(format_asr_error(last_error or "ASR transcription failed"))


def _transcribe_dashscope_chat(
    wav_bytes: bytes,
    *,
    settings: Mapping[str, Any],
    filename: str,
    content_type: str,
    language: str,
    timeout_sec: float | None,
    attempts: int,
) -> dict[str, Any]:
    """DashScope Qwen3-ASR uses chat/completions + input_audio, not /audio/transcriptions."""
    base_url = _normalize_base_url(str(settings.get("base_url") or ""))
    model = str(settings.get("model") or "").strip()
    mime = str(content_type or "audio/wav").split(";")[0].strip() or "audio/wav"
    if mime in {"audio/mp3", "audio/mpeg3"}:
        mime = "audio/mpeg"
    fmt = dashscope_audio_format(filename, mime)
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {},
                    }
                ],
            }
        ],
        "parameters": {"format": fmt, "sample_rate": "16000"},
    }
    lang = str(language or settings.get("language") or "").strip().lower()
    asr_options: dict[str, Any] = {"enable_itn": False}
    if lang in {"zh", "en"}:
        asr_options["language"] = lang
    payload["asr_options"] = asr_options
    url = f"{base_url}/chat/completions"
    timeout = float(timeout_sec if timeout_sec is not None else settings.get("timeout_sec") or 120)
    last_error: BaseException | None = None
    tries = max(1, int(attempts))
    variants = (True, False)
    for data_url in variants:
        payload["messages"][0]["content"][0]["input_audio"] = build_dashscope_input_audio(
            wav_bytes,
            filename=filename,
            content_type=mime,
            data_url=data_url,
        )
        for attempt in range(tries):
            try:
                parsed = _post_json(url, payload, headers=build_remote_asr_auth_headers(settings), timeout_sec=timeout)
                return _ensure_asr_success(parsed)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                if is_empty_asr_result(detail):
                    return {"output": {"text": ""}, "usage": {"duration": 0}}
                last_error = RuntimeError(_http_error_message(exc.code, detail, url=url, model=model))
                if exc.code == 400 and "UNSUPPORTED_FORMAT" in detail and data_url:
                    break
                if is_transient_asr_error(exc) and attempt + 1 < tries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise last_error from exc
            except Exception as exc:
                last_error = exc
                if is_empty_asr_result(exc):
                    return {"output": {"text": ""}, "usage": {"duration": 0}}
                if is_transient_asr_error(exc) and attempt + 1 < tries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise RuntimeError(format_asr_error(exc)) from exc
    raise RuntimeError(format_asr_error(last_error or "ASR transcription failed"))


def _http_error_message(code: int, detail: str, *, url: str = "", model: str = "") -> str:
    body = str(detail or "").strip()
    if int(code) == 404:
        if "/audio/transcriptions" in url:
            return (
                "通义千问 ASR 没有 /v1/audio/transcriptions（所以 404）。"
                "请使用「通义千问 ASR」预设，走 chat/completions。"
            )
        hint = f"模型 {model} " if model else ""
        return (
            f"语音接口 404：{hint}在该地址不存在。通义千问请用 qwen-audio-3.0-asr-flash。"
            + (f" {body[:220]}" if body else "")
        )
    if "HAVE_NO_WORDS" in body:
        return "这一段没有识别到语音（静音或纯音乐），已跳过。"
    if "UNSUPPORTED_FORMAT" in body or "format is empty" in body.lower():
        return (
            "通义千问 ASR 需要音频格式（format=wav）。"
            "qwen-audio-3.0-asr-flash 已改走官方 multimodal-generation 接口。"
            f" {body[:180]}"
        )
    return (body or f"HTTP {code}")[:_MAX_ERROR_CHARS]


def _ensure_asr_success(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    if is_empty_asr_result(json.dumps(data, ensure_ascii=False)):
        return {"output": {"text": ""}, "usage": {"duration": 0}}
    if data.get("output") or data.get("choices") or data.get("text") or data.get("segments"):
        return data
    error = data.get("error")
    if isinstance(error, Mapping):
        message = str(error.get("message") or error.get("code") or "").strip()
        if message:
            raise RuntimeError(_http_error_message(400, json.dumps(error, ensure_ascii=False)))
    code = str(data.get("code") or "").strip()
    if code and code.upper() not in {"SUCCESS", "OK"}:
        raise RuntimeError(_http_error_message(400, str(data.get("message") or code)))
    return data


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str],
    timeout_sec: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Connection": "close",
            **dict(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(15.0, float(timeout_sec))) as response:
        raw = response.read().decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ASR response is not JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("ASR response is not an object")
    return parsed


def _post_transcription(
    url: str,
    *,
    body: bytes,
    content_type: str,
    headers: Mapping[str, str],
    timeout_sec: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "Connection": "close",
            **dict(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(15.0, float(timeout_sec))) as response:
        raw = response.read().decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ASR response is not JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ASR response is not an object")
    return payload


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise RuntimeError("remote ASR base_url is required")
    if not text.endswith("/v1"):
        text = f"{text}/v1" if not text.endswith("/v1/") else text.rstrip("/")
    return text


def _encode_multipart(
    fields: Mapping[str, str],
    *,
    files: list[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for field, filename, content, content_type in files:
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        chunks.append(header + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

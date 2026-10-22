"""Shared OpenAI-compatible /v1 probe helpers (LLM, ASR, VLM catalog)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


def uses_light_models_catalog(base_url: str, preset: str = "") -> bool:
    preset_text = str(preset or "").strip().lower()
    if preset_text in {"dashscope", "siliconflow", "deepseek"}:
        return True
    host = str(base_url or "").lower()
    return any(
        token in host
        for token in (
            "dashscope.aliyuncs.com",
            "siliconflow.cn",
            "deepseek.com",
        )
    )


def parse_models_catalog_body(body: bytes) -> list[str]:
    if not body.strip().startswith(b"{"):
        return []
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    model_ids = {
        str(item.get("id", "") or "").strip()
        for item in (payload.get("data") or [])
        if isinstance(item, dict)
    }
    return sorted(model_ids)


def fetch_models_catalog(
    *,
    base_url: str,
    headers: Mapping[str, str],
    timeout_sec: float,
    light: bool,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Accept": "application/json", **dict(headers)},
        method="GET",
    )
    try:
        if light:
            from src.services.cancellable_http import urlopen_read_with_deadline

            status, body = urlopen_read_with_deadline(
                request,
                timeout_sec=max(1.0, float(timeout_sec)),
                max_bytes=8192,
            )
        else:
            with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_sec))) as response:
                status = int(getattr(response, "status", 200) or 200)
                body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(8192).decode("utf-8", errors="replace").strip()
        if exc.code in {401, 403}:
            return {
                "auth_ok": False,
                "reachable": False,
                "error_code": "auth_failed",
                "error": f"HTTP {exc.code}: API Key invalid or unauthorized",
                "available_models": [],
                "http_status": int(exc.code),
                "http_detail": detail[:240],
            }
        return {
            "auth_ok": False,
            "reachable": False,
            "error_code": "http_error",
            "error": f"HTTP {exc.code}: {detail[:240] or exc.reason}",
            "available_models": [],
            "http_status": int(exc.code),
        }
    except urllib.error.URLError as exc:
        return {
            "auth_ok": False,
            "reachable": False,
            "error_code": "unreachable",
            "error": str(getattr(exc, "reason", exc) or exc),
            "available_models": [],
        }
    except TimeoutError:
        return {
            "auth_ok": False,
            "reachable": False,
            "error_code": "timeout",
            "error": f"timed out after {timeout_sec:.0f}s",
            "available_models": [],
        }

    if status in {401, 403}:
        detail = body.decode("utf-8", errors="replace").strip()
        return {
            "auth_ok": False,
            "reachable": False,
            "error_code": "auth_failed",
            "error": f"HTTP {status}: API Key invalid or unauthorized",
            "available_models": [],
            "http_status": int(status),
            "http_detail": detail[:240],
        }
    if status < 200 or status >= 300:
        detail = body.decode("utf-8", errors="replace").strip()
        return {
            "auth_ok": False,
            "reachable": False,
            "error_code": "http_error",
            "error": f"HTTP {status}: {detail[:240] or 'request failed'}",
            "available_models": [],
            "http_status": int(status),
        }

    available = parse_models_catalog_body(body)
    return {
        "auth_ok": True,
        "reachable": True,
        "error_code": "",
        "error": "",
        "available_models": available,
        "http_status": int(status),
        "catalog_partial": bool(light),
    }


def probe_minimal_text_chat(
    *,
    base_url: str,
    headers: Mapping[str, str],
    model: str,
    timeout_sec: float,
    payload_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": str(model or "").strip(),
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
        "temperature": 0.0,
    }
    if payload_extra:
        payload.update(dict(payload_extra))
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        from src.services.cancellable_http import urlopen_json_with_stop

        body = urlopen_json_with_stop(
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
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "error": str(getattr(exc, "reason", exc) or exc), "http_status": 0}
    except TimeoutError:
        return {"ok": False, "error": f"timed out after {timeout_sec:.0f}s", "http_status": 0}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "http_status": 0}

    choices = body.get("choices") or []
    if not choices:
        return {"ok": False, "error": "chat probe returned no choices", "http_status": 200}
    message = choices[0].get("message") or {}
    text = str(message.get("content", "") or message.get("reasoning_content", "") or "").strip()
    if not text:
        return {"ok": False, "error": "chat probe returned empty content", "http_status": 200}
    return {"ok": True, "error": "", "http_status": 200, "detail": text[:80]}


def finalize_openai_compat_probe(
    *,
    catalog: Mapping[str, Any],
    model: str,
    cloud: bool,
    chat_probe: bool,
    chat_probe_fn: Callable[[], dict[str, Any]] | None,
    probe_label: str = "chat",
    capability_key: str = "chat_probed",
    capability_failed_code: str = "chat_probe_failed",
    capability_detail_key: str = "chat_probe_detail",
) -> dict[str, Any]:
    if not catalog.get("auth_ok"):
        return {
            "reachable": bool(catalog.get("reachable")),
            "model_available": False,
            "auth_ok": False,
            "error_code": str(catalog.get("error_code", "") or "http_error"),
            "error": str(catalog.get("error", "") or "catalog probe failed"),
            "available_models": list(catalog.get("available_models") or []),
        }

    available = list(catalog.get("available_models") or [])
    in_catalog = bool(model and model in available)
    if not chat_probe:
        if in_catalog or (cloud and not available):
            return {
                "reachable": True,
                "model_available": True,
                "auth_ok": True,
                "model_unlisted": cloud and available and not in_catalog,
                "error_code": "model_unlisted" if cloud and available and not in_catalog else "",
                "error": (
                    f"model {model!r} is not in the server catalog; requests still use this name."
                )
                if cloud and available and not in_catalog
                else "",
                "available_models": available,
            }
        if cloud:
            return {
                "reachable": True,
                "model_available": True,
                "auth_ok": True,
                "model_unlisted": True,
                "error_code": "model_unlisted",
                "error": f"model {model!r} is not in the server catalog; requests still use this name.",
                "available_models": available,
            }
        sample = ", ".join(available[:8])
        suffix = f" (+{len(available) - 8} more)" if len(available) > 8 else ""
        return {
            "reachable": True,
            "model_available": False,
            "auth_ok": True,
            "error_code": "model_not_found",
            "error": f"model {model!r} not listed by server. Available: {sample}{suffix}".strip(),
            "available_models": available,
        }

    if chat_probe_fn is None:
        def _missing_probe() -> dict[str, Any]:
            return {"ok": False, "error": f"{probe_label} probe unavailable"}

        chat_probe_fn = _missing_probe

    chat = chat_probe_fn()
    if chat.get("ok"):
        unlisted = not in_catalog
        result: dict[str, Any] = {
            "reachable": True,
            "model_available": True,
            "auth_ok": True,
            capability_key: True,
            "model_unlisted": unlisted,
            "error_code": "model_unlisted" if unlisted else "",
            "error": (
                f"model {model!r} is not in the account catalog preview, "
                f"but the {probe_label} probe succeeded."
            )
            if unlisted
            else "",
            "available_models": available,
            capability_detail_key: str(chat.get("detail", "") or ""),
        }
        return result

    sample = ", ".join(available[:8])
    if len(available) > 8:
        sample = f"{sample} (+{len(available) - 8})"
    detail = str(chat.get("error", "") or f"{probe_label} probe failed")
    return {
        "reachable": True,
        "model_available": False,
        "auth_ok": True,
        capability_key: True,
        "error_code": capability_failed_code,
        "error": detail,
        "available_models": available,
        capability_detail_key: detail,
        "catalog_hint": sample,
    }

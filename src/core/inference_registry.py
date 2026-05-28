from __future__ import annotations

from typing import Callable, Dict

from src.app.logging_utils import get_logger

logger = get_logger("inference_registry")

_ENGINE_FACTORIES: Dict[str, Callable[[], object]] = {}


def register_inference_engine(provider_id: str, factory: Callable[[], object]) -> None:
    pid = str(provider_id or "").strip()
    if not pid:
        raise ValueError("provider_id is required")
    _ENGINE_FACTORIES[pid] = factory
    logger.debug("Registered inference engine factory: %s", pid)


def build_inference_engine(provider_id: str) -> object:
    """Resolve a provider string to a fresh engine instance (used by get_engine)."""
    pid = str(provider_id or "").strip() or "clip_onnx"
    factory = _ENGINE_FACTORIES.get(pid)
    if factory is None:
        if pid != "clip_onnx":
            raise RuntimeError(
                f"Unsupported inference provider '{pid}'. "
                "Install/register the provider engine or switch the active model profile."
            )
        factory = _ENGINE_FACTORIES.get("clip_onnx")
    if factory is None:
        raise RuntimeError("No inference engine registered (missing clip_onnx default)")
    return factory()

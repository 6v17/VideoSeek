from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import numpy as np


class UnderstandingStoppedError(Exception):
    """Raised when the user requests stop during evidence generation."""


class UnderstandingComponent(ABC):
    component_id: str

    @abstractmethod
    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        """Run inference on a single BGR uint8 image."""

    def close(self) -> None:
        return None


def merge_params(manifest: Mapping[str, Any], params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(manifest.get("params") or {})
    if params:
        merged.update(dict(params))
    return merged

"""Quick recall diagnostics for frame search fetch limits."""
from __future__ import annotations

import numpy as np

from src.app.config import load_config
from src.services.search_service import _resolve_frame_fetch_top_k, load_search_assets
from src.storage.config_store import get_search_top_k


def main() -> None:
    cfg = load_config()
    top_k = get_search_top_k(cfg)
    idx, ts, paths = load_search_assets(cfg)
    print("search_mode", cfg.get("search_mode"))
    print("sampling", cfg.get("sampling_fps_mode"), cfg.get("sampling_fps_rules"))
    print("index_total", int(idx.ntotal) if idx else 0)
    if idx and ts is not None:
        arr = np.asarray(ts, dtype=float)
        window = (arr >= 210) & (arr <= 220)
        print("frames_210_220", int(window.sum()))
        if window.any():
            print("sample_210_220", arr[window][:12])
    for scoped in (False, True):
        for precise in (False, True):
            fk = _resolve_frame_fetch_top_k(top_k, scoped, False, cfg, precise_image=precise)
            print(f"fetch_k scoped={scoped} precise={precise} -> {fk}")


if __name__ == "__main__":
    main()

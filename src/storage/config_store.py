import os

from typing import List

from src.app.config import CONFIG_ENUMS, DEFAULT_CONFIG, get_data_storage_paths, load_config, save_config
from src.utils import canonicalize_library_path

_PROVIDER_DEFAULT_DIMENSION = {
    "clip_onnx": 512,
    "chinese_clip_onnx": 512,
    "siglip2_onnx": 768,
}


def resolve_provider_dir(provider):
    provider = str(provider or "").strip()
    if provider == "clip_onnx":
        return "openai-clip"
    if provider == "siglip2_onnx":
        return "siglip2"
    if provider == "chinese_clip_onnx":
        return "chinese-clip"
    return provider.replace("_", "-")


def iter_provider_resource_dir_candidates(provider):
    primary = resolve_provider_dir(provider)
    yield primary
    # Early imports used provider.replace("_", "-") -> chinese-clip-onnx.
    if provider == "chinese_clip_onnx" and primary != "chinese-clip-onnx":
        yield "chinese-clip-onnx"


def resolve_model_resource_dir(model_root, provider, variant):
    root = os.path.normpath(os.path.abspath(os.fspath(str(model_root or "").strip())))
    variant_text = str(variant or "").strip() or "vit-base-patch32"
    last_candidate = os.path.join(root, resolve_provider_dir(provider), variant_text)
    if not root:
        return last_candidate
    for provider_dir in iter_provider_resource_dir_candidates(provider):
        candidate = os.path.join(root, provider_dir, variant_text)
        last_candidate = candidate
        if os.path.isdir(candidate):
            return candidate
    return last_candidate


def get_app_config():
    return load_config()


def save_app_config(config):
    save_config(config)


def get_data_paths(config=None):
    return get_data_storage_paths(config=config)


def get_config_schema_version(config=None):
    cfg = dict(config or load_config())
    try:
        return int(cfg.get("schema_version", 1))
    except (TypeError, ValueError):
        return 1


def _default_fallback_model_profile(cfg):
    fallback_model_dir = str(cfg.get("model_dir", "") or "").strip()
    return {
        "id": "clip_onnx_default",
        "provider": "clip_onnx",
        "display_name": "CLIP ONNX",
        "enabled": True,
        "runtime": {
            "prefer_gpu": bool(cfg.get("prefer_gpu", True)),
            "model_dir": fallback_model_dir,
            "model_variant": "vit-base-patch32",
        },
        "files": {
            "visual_model": "clip_visual.onnx",
            "text_model": "clip_text.onnx",
            "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
        },
        "capabilities": {
            "text_query": True,
            "image_query": True,
            "video_embedding": True,
            "cross_modal_search": True,
        },
    }


def get_active_model_profile(config=None):
    cfg = dict(config or load_config())
    schema_version = get_config_schema_version(cfg)
    if schema_version < 2:
        return _default_fallback_model_profile(cfg)
    models = cfg.get("models")
    if not isinstance(models, dict):
        models = {}
    profiles = models.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return _default_fallback_model_profile(cfg)
    active_profile_id = str(models.get("active_profile", "") or "").strip()
    if not active_profile_id and profiles:
        first = profiles[0]
        if isinstance(first, dict):
            active_profile_id = str(first.get("id", "") or "").strip()
    for profile in profiles:
        if isinstance(profile, dict) and str(profile.get("id", "") or "").strip() == active_profile_id:
            return dict(profile)
    if profiles and isinstance(profiles[0], dict):
        return dict(profiles[0])
    raise RuntimeError(f"Active model profile not found: {active_profile_id}")


def get_active_model_runtime(config=None):
    profile = get_active_model_profile(config=config)
    runtime = profile.get("runtime")
    if not isinstance(runtime, dict):
        raise RuntimeError("Missing runtime section in active model profile")
    return dict(runtime)


def get_effective_prefer_gpu(config=None):
    runtime = get_active_model_runtime(config=config)
    if "prefer_gpu" not in runtime:
        raise RuntimeError("Missing runtime.prefer_gpu in active model profile")
    return bool(runtime.get("prefer_gpu"))


def get_effective_model_dir(config=None):
    runtime = get_active_model_runtime(config=config)
    if "model_dir" not in runtime:
        raise RuntimeError("Missing runtime.model_dir in active model profile")
    return str(runtime.get("model_dir", "") or "").strip()


def get_local_model_asset_dirs(config=None):
    cfg = dict(config or load_config())
    data_paths = get_data_storage_paths(config=cfg)
    profile = get_active_model_profile(config=cfg)
    provider = str(profile.get("provider", "") or "").strip()
    if not provider:
        raise RuntimeError("Missing active model profile provider for local asset dirs")
    runtime = dict(profile.get("runtime") or {})
    model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
    if not model_variant:
        model_variant = "vit-base-patch32"
    provider_dir = resolve_provider_dir(provider)
    base_dir = os.path.join(data_paths["data_dir"], "model_assets", provider_dir, model_variant)
    return {
        "base_dir": base_dir,
        "meta_file": os.path.join(base_dir, "meta.json"),
        "vector_dir": os.path.join(base_dir, "vector"),
        "index_dir": os.path.join(base_dir, "index"),
    }


def get_global_model_asset_paths(config=None):
    model_dirs = get_local_model_asset_dirs(config=config)
    global_dir = os.path.join(model_dirs["base_dir"], "global")
    return {
        "global_dir": global_dir,
        "cross_index_file": os.path.join(global_dir, "cross_video_index.faiss"),
        "cross_vector_file": os.path.join(global_dir, "cross_video_vectors.npy"),
        "cross_chunk_index_file": os.path.join(global_dir, "cross_chunk_index.faiss"),
        "cross_chunk_vector_file": os.path.join(global_dir, "cross_chunk_vectors.npy"),
    }


def get_remote_model_asset_paths(config=None):
    model_dirs = get_local_model_asset_dirs(config=config)
    remote_dir = os.path.join(model_dirs["base_dir"], "remote")
    return {
        "remote_dir": remote_dir,
        "remote_index_file": os.path.join(remote_dir, "remote_index.faiss"),
        "remote_vector_file": os.path.join(remote_dir, "remote_vectors.npy"),
    }


def get_model_profile_storage_paths(config=None):
    model_dirs = get_local_model_asset_dirs(config=config)
    global_paths = get_global_model_asset_paths(config=config)
    remote_paths = get_remote_model_asset_paths(config=config)
    merged = dict(model_dirs)
    merged.update(global_paths)
    merged.update(remote_paths)
    return merged


def get_active_model_resource_dir(config=None):
    profile = get_active_model_profile(config=config)
    runtime = dict(profile.get("runtime") or {})
    model_root = str(runtime.get("model_dir", "") or "").strip()
    if not model_root:
        raise RuntimeError("Missing runtime.model_dir in active model profile")
    provider = str(profile.get("provider", "") or "").strip()
    if not provider:
        raise RuntimeError("Missing profile provider for model resource directory")
    model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
    if not model_variant:
        model_variant = "vit-base-patch32"
    return resolve_model_resource_dir(model_root, provider, model_variant)


def get_active_embedding_spec(config=None):
    cfg = dict(config or load_config())
    profile = get_active_model_profile(config=cfg)
    runtime = dict(profile.get("runtime") or {})
    capabilities = dict(profile.get("capabilities") or {})
    profile_id = str(profile.get("id", "") or "").strip() or "clip_onnx_default"
    provider = str(profile.get("provider", "") or "").strip() or "clip_onnx"

    embedding_space = str(
        runtime.get("embedding_space")
        or profile.get("embedding_space")
        or capabilities.get("embedding_space")
        or profile_id
    ).strip() or profile_id
    metric = str(
        runtime.get("metric")
        or profile.get("metric")
        or capabilities.get("metric")
        or "ip"
    ).strip().lower() or "ip"
    raw_dimension = (
        runtime.get("embedding_dimension")
        or runtime.get("dimension")
        or profile.get("embedding_dimension")
        or profile.get("dimension")
        or capabilities.get("embedding_dimension")
        or capabilities.get("dimension")
        or _PROVIDER_DEFAULT_DIMENSION.get(provider, 0)
    )
    try:
        dimension = int(raw_dimension)
    except (TypeError, ValueError):
        dimension = 0

    return {
        "model_id": profile_id,
        "provider": provider,
        "embedding_space": embedding_space,
        "dimension": dimension,
        "metric": metric,
    }


def _app_cfg(config=None):
    return dict(config or load_config())


def get_search_top_k(config=None) -> int:
    cfg = _app_cfg(config)
    try:
        return int(cfg.get("search_top_k", DEFAULT_CONFIG["search_top_k"]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG["search_top_k"])


def get_search_mode(config=None) -> str:
    cfg = _app_cfg(config)
    mode = str(cfg.get("search_mode", DEFAULT_CONFIG["search_mode"]) or "").strip().lower()
    allowed = CONFIG_ENUMS["search_mode"]
    return mode if mode in allowed else str(DEFAULT_CONFIG["search_mode"])


def get_frame_neighbor_rerank_enabled(config=None) -> bool:
    return bool(_app_cfg(config).get("frame_neighbor_rerank_enabled", DEFAULT_CONFIG["frame_neighbor_rerank_enabled"]))


def get_frame_neighbor_rerank_top_n(config=None) -> int:
    cfg = _app_cfg(config)
    try:
        return int(cfg.get("frame_neighbor_rerank_top_n", DEFAULT_CONFIG["frame_neighbor_rerank_top_n"]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])


def get_frame_neighbor_rerank_window(config=None) -> int:
    cfg = _app_cfg(config)
    try:
        return int(cfg.get("frame_neighbor_rerank_window", DEFAULT_CONFIG["frame_neighbor_rerank_window"]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG["frame_neighbor_rerank_window"])


def get_remote_max_frames(config=None) -> int:
    cfg = _app_cfg(config)
    try:
        return int(cfg.get("remote_max_frames", DEFAULT_CONFIG["remote_max_frames"]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG["remote_max_frames"])


def get_config_fps(config=None) -> float:
    cfg = _app_cfg(config)
    try:
        v = float(cfg.get("fps", DEFAULT_CONFIG["fps"]))
        return v if v >= 0.01 else float(DEFAULT_CONFIG["fps"])
    except (TypeError, ValueError):
        return float(DEFAULT_CONFIG["fps"])


def get_similarity_threshold(config=None) -> float:
    cfg = _app_cfg(config)
    try:
        return float(cfg.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"]))
    except (TypeError, ValueError):
        return float(DEFAULT_CONFIG["similarity_threshold"])


def get_max_chunk_duration(config=None) -> float:
    cfg = _app_cfg(config)
    try:
        return float(cfg.get("max_chunk_duration", DEFAULT_CONFIG["max_chunk_duration"]))
    except (TypeError, ValueError):
        return float(DEFAULT_CONFIG["max_chunk_duration"])


def get_min_chunk_size(config=None) -> int:
    cfg = _app_cfg(config)
    try:
        return int(cfg.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"]))
    except (TypeError, ValueError):
        return int(DEFAULT_CONFIG["min_chunk_size"])


def get_chunk_similarity_mode(config=None) -> str:
    cfg = _app_cfg(config)
    mode = str(cfg.get("chunk_similarity_mode", DEFAULT_CONFIG["chunk_similarity_mode"]) or "").strip().lower()
    allowed = CONFIG_ENUMS["chunk_similarity_mode"]
    return mode if mode in allowed else str(DEFAULT_CONFIG["chunk_similarity_mode"])


def get_search_scope_mode(config=None) -> str:
    cfg = _app_cfg(config)
    mode = str(cfg.get("search_scope_mode", DEFAULT_CONFIG["search_scope_mode"]) or "").strip().lower()
    allowed = CONFIG_ENUMS["search_scope_mode"]
    return mode if mode in allowed else str(DEFAULT_CONFIG["search_scope_mode"])


def get_search_scope_library_paths(config=None) -> List[str]:
    cfg = _app_cfg(config)
    raw_paths = cfg.get("search_scope_library_paths", DEFAULT_CONFIG["search_scope_library_paths"])
    if not isinstance(raw_paths, list):
        return []
    paths = []
    for item in raw_paths:
        text = str(item or "").strip()
        if text:
            paths.append(canonicalize_library_path(text))
    return paths


def save_search_scope(mode, library_paths, config=None) -> dict:
    cfg = dict(config or load_config())
    normalized_mode = str(mode or "").strip().lower()
    cfg["search_scope_mode"] = normalized_mode if normalized_mode in CONFIG_ENUMS["search_scope_mode"] else "all"
    normalized_paths = []
    for item in library_paths or []:
        text = str(item or "").strip()
        if text:
            normalized_paths.append(canonicalize_library_path(text))
    cfg["search_scope_library_paths"] = normalized_paths
    save_config(cfg)
    return cfg

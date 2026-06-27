"""Shared mixed search presets with per-model-profile query vector caches."""

from __future__ import annotations

from src.app.config import get_configured_data_root, load_config
from src.services.search_preset_constants import (
    BUILTIN_SEARCH_PRESETS,
    BUILTIN_SEARCH_PRESET_IDS,
    PRESET_SCHEMA_VERSION,
    PRESET_TYPE_MIXED,
)
from src.services.search_preset_crud import create_preset, delete_preset, update_preset
from src.services.search_preset_model import (
    describe_preset_content,
    ensure_builtin_search_presets,
    get_preset,
    list_presets,
    normalize_fusion,
    normalize_preset_record,
    preset_has_content,
)
from src.services.search_preset_plan import build_compose_search_plan, build_preset_search_plan
from src.services.search_preset_query import (
    encode_mixed_query_vector,
    encode_preset_query_vector,
    invalidate_all_preset_query_caches,
    invalidate_preset_query_cache,
    resolve_preset_query_vector,
)
from src.services.search_preset_storage import (
    get_active_profile_id,
    get_preset_query_cache_dir,
    get_preset_query_cache_root,
    get_preset_ref_path,
    get_preset_refs_dir,
    get_presets_file,
    get_search_preset_root,
    get_search_presets_base_dir,
    load_presets_document,
    query_cache_path,
    resolve_preset_ref_paths,
    save_presets_document,
)
from src.storage.config_store import get_active_embedding_spec, get_active_model_profile

# Backward-compatible private aliases for tests and internal callers.
_normalize_fusion = normalize_fusion
_encode_preset_query_vector = encode_preset_query_vector
_query_cache_path = query_cache_path

__all__ = [
    "BUILTIN_SEARCH_PRESETS",
    "BUILTIN_SEARCH_PRESET_IDS",
    "PRESET_SCHEMA_VERSION",
    "PRESET_TYPE_MIXED",
    "build_compose_search_plan",
    "build_preset_search_plan",
    "create_preset",
    "delete_preset",
    "describe_preset_content",
    "encode_mixed_query_vector",
    "ensure_builtin_search_presets",
    "get_active_profile_id",
    "get_preset",
    "get_preset_query_cache_dir",
    "get_preset_query_cache_root",
    "get_preset_ref_path",
    "get_preset_refs_dir",
    "get_presets_file",
    "get_search_preset_root",
    "get_search_presets_base_dir",
    "invalidate_all_preset_query_caches",
    "invalidate_preset_query_cache",
    "list_presets",
    "load_presets_document",
    "normalize_preset_record",
    "preset_has_content",
    "resolve_preset_query_vector",
    "resolve_preset_ref_paths",
    "save_presets_document",
    "update_preset",
    "get_configured_data_root",
    "get_active_embedding_spec",
    "get_active_model_profile",
    "load_config",
]

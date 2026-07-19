import os

import numpy as np

from src.storage.config_store import get_model_profile_storage_paths
from src.storage.meta_io import load_meta, save_meta


def _profile_base_from_meta_file(meta_file: str) -> str | None:
    path = os.path.normpath(str(meta_file or ""))
    if not path:
        return None
    if os.path.basename(path).lower() != "meta.json":
        return None
    return os.path.dirname(path)


def load_metadata(meta_file):
    profile_base = _profile_base_from_meta_file(meta_file)
    if profile_base:
        from src.storage.profile_library_store import load_profile_meta

        return load_profile_meta(profile_base)
    return load_meta(meta_file)


def save_metadata(meta, meta_file, *, pretty: bool = True):
    profile_base = _profile_base_from_meta_file(meta_file)
    if profile_base:
        from src.storage.profile_library_store import save_profile_meta

        del pretty  # SQLite path ignores pretty formatting
        save_profile_meta(profile_base, meta)
        return
    save_meta(meta, meta_file, pretty=pretty)


def load_model_metadata(config=None):
    paths = get_model_profile_storage_paths(config=config)
    return load_metadata(paths["meta_file"])


def save_model_metadata(meta, config=None, *, pretty: bool = True, invalidate_path_index: bool = True):
    paths = get_model_profile_storage_paths(config=config)
    save_metadata(meta, paths["meta_file"], pretty=pretty)
    if not invalidate_path_index:
        return
    try:
        from src.services.search_scope import invalidate_searchable_path_index_cache

        invalidate_searchable_path_index_cache()
    except Exception:
        pass


def load_vector_payload(vector_file):
    from src.core.faiss_index import load_vectors

    return load_vectors(vector_file)


def save_vector_payload(vectors, timestamps, vector_file, chunks=None, chunk_config=None, embedding_spec=None):
    from src.core.faiss_index import save_vectors

    return save_vectors(
        vectors,
        timestamps,
        vector_file,
        chunks=chunks,
        chunk_config=chunk_config,
        embedding_spec=embedding_spec,
    )


def load_numpy_payload(npy_file):
    return np.load(npy_file, allow_pickle=True).item()


def save_numpy_payload(npy_file, payload):
    from src.core.faiss_index import atomic_save_numpy

    atomic_save_numpy(npy_file, payload)

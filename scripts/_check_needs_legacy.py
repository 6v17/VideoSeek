import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.app import config as c

with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    legacy_root = root / "legacy_app"
    legacy_data_dir = legacy_root / "data"
    legacy_data_dir.mkdir(parents=True)
    (legacy_data_dir / "meta.json").write_text('{"libraries": {"D:/lib": {}}}', encoding="utf-8")

    legacy_config_file = legacy_root / "config.json"
    legacy_config_file.write_text(
        json.dumps(
            {
                "meta_file": "data/meta.json",
                "vector_dir": "data/vector",
                "index_dir": "data/index",
                "cross_index_file": "data/global/cross_video_index.faiss",
                "cross_vector_file": "data/global/cross_video_vectors.npy",
                "cross_chunk_index_file": "data/global/cross_chunk_index.faiss",
                "cross_chunk_vector_file": "data/global/cross_chunk_vectors.npy",
                "remote_index_file": "data/remote/remote_index.faiss",
                "remote_vector_file": "data/remote/remote_vectors.npy",
            }
        ),
        encoding="utf-8",
    )

    user_root = root / "user_app"
    user_data_dir = user_root / "data"
    user_data_dir.mkdir(parents=True)
    (user_data_dir / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")

    user_config_file = user_root / "config.json"
    default_config = {
        **c.DEFAULT_CONFIG,
        "data_root": str(user_root),
        "meta_file": str(user_data_dir / "meta.json"),
        "vector_dir": str(user_data_dir / "vector"),
        "index_dir": str(user_data_dir / "index"),
        "cross_index_file": str(user_data_dir / "global" / "cross_video_index.faiss"),
        "cross_vector_file": str(user_data_dir / "global" / "cross_video_vectors.npy"),
        "cross_chunk_index_file": str(user_data_dir / "global" / "cross_chunk_index.faiss"),
        "cross_chunk_vector_file": str(user_data_dir / "global" / "cross_chunk_vectors.npy"),
        "remote_index_file": str(user_data_dir / "remote" / "remote_index.faiss"),
        "remote_vector_file": str(user_data_dir / "remote" / "remote_vectors.npy"),
    }
    legacy_default_config = {
        **default_config,
        "meta_file": str(legacy_data_dir / "meta.json"),
        "vector_dir": str(legacy_data_dir / "vector"),
        "index_dir": str(legacy_data_dir / "index"),
        "cross_index_file": str(legacy_data_dir / "global" / "cross_video_index.faiss"),
        "cross_vector_file": str(legacy_data_dir / "global" / "cross_video_vectors.npy"),
        "cross_chunk_index_file": str(legacy_data_dir / "global" / "cross_chunk_index.faiss"),
        "cross_chunk_vector_file": str(legacy_data_dir / "global" / "cross_chunk_vectors.npy"),
        "remote_index_file": str(legacy_data_dir / "remote" / "remote_index.faiss"),
        "remote_vector_file": str(legacy_data_dir / "remote" / "remote_vectors.npy"),
    }

    with (
        patch.object(c, "CONFIG_FILE", str(user_config_file)),
        patch.object(c, "LEGACY_CONFIG_FILE", str(legacy_config_file)),
        patch.object(c, "DATA_DIR", str(user_data_dir)),
        patch.object(c, "LEGACY_DATA_DIR", str(legacy_data_dir)),
        patch.object(c, "DEFAULT_CONFIG", default_config),
        patch.object(c, "LEGACY_DEFAULT_CONFIG", legacy_default_config),
    ):
        print("before load", c.needs_legacy_storage_data_copy())
        loaded = c.load_config()
        print("after load", c.needs_legacy_storage_data_copy(loaded))
        print("legacy", c._read_meta_libraries(os.path.join(c.LEGACY_DATA_DIR, "meta.json")))
        print("user", c._read_meta_libraries(os.path.join(c.DATA_DIR, "meta.json")))
        print("user migrated?", c._user_profile_has_migrated_library())

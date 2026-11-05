import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.core.fgclip2_preprocess import (
    naflex_pixel_size,
    patchify_bgr,
    resize_bilinear_aa,
    resize_positional_embeddings,
)
from src.core.fgclip2_provider import (
    Fgclip2OnnxEngine,
    assert_text_seq_len,
    configure_fgclip2_tokenizer,
)


def test_naflex_size_keeps_aspect_and_patch_budget():
    height, width = naflex_pixel_size(1080, 1920)
    assert height % 16 == 0
    assert width % 16 == 0
    assert (height // 16) * (width // 16) <= 256
    assert height != width
    assert abs((height / width) - (1080 / 1920)) < 0.05
    # The search uses as many patches as the cap allows, including upscaling a square.
    assert naflex_pixel_size(256, 256) == (256, 256)
    assert naflex_pixel_size(512, 512) == (256, 256)


def test_antialias_resize_matches_torch_bilinear():
    src = np.arange(16 * 16, dtype=np.float32).reshape(1, 16, 16)
    out = resize_bilinear_aa(src, 12, 21)
    assert out.shape == (1, 12, 21)
    assert abs(float(out[0, 0, 0]) - 4.8) < 1e-4
    assert abs(float(out[0, 5, 10]) - 116.59091186523438) < 1e-4
    assert abs(float(out[0, -1, -1]) - 250.2) < 1e-4


def test_positional_embeddings_pad_with_the_first_patch():
    table = np.arange(16 * 16 * 2, dtype=np.float32).reshape(16, 16, 2)
    identity = resize_positional_embeddings(table, [[16, 16]], max_length=256)
    assert identity.shape == (1, 256, 2)
    assert np.allclose(identity[0], table.reshape(256, 2))

    padded = resize_positional_embeddings(table, [[2, 2]], max_length=6)
    assert padded.shape == (1, 6, 2)
    assert np.allclose(padded[0, 4], padded[0, 0])
    assert np.allclose(padded[0, 5], padded[0, 0])


def test_patchify_keeps_small_frame_aspect():
    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    height, width = naflex_pixel_size(32, 48)
    pixels, mask, spatial = patchify_bgr(frame)
    assert pixels.shape == (256, 768)
    assert spatial.tolist() == [height // 16, width // 16]
    assert int(mask.sum()) == (height // 16) * (width // 16)
    assert height != width
    assert pixels.dtype == np.float32
    assert mask.dtype == np.int32


def test_tokenizer_pads_to_fixed_length_and_keeps_eos():
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from tokenizers.processors import TemplateProcessing

    tokenizer = Tokenizer(WordLevel({"<pad>": 0, "<eos>": 1, "hello": 2}, unk_token="<pad>"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.post_processor = TemplateProcessing(
        single="$A <eos>",
        special_tokens=[("<eos>", 1)],
    )
    configure_fgclip2_tokenizer(tokenizer, seq_len=8)
    ids = tokenizer.encode("hello hello").ids
    assert ids == [2, 2, 1, 0, 0, 0, 0, 0]


class _Node:
    def __init__(self, name, type_name):
        self.name = name
        self.type = type_name


def test_encode_images_follows_embedding_batch_size():
    engine = Fgclip2OnnxEngine.__new__(Fgclip2OnnxEngine)
    engine.embedding_batch_size = 2
    engine._feature_dim = None
    engine._position_table = np.zeros((16, 16, 4), dtype=np.float32)
    engine._vision_inputs = [
        _Node("pixel_values", "tensor(float16)"),
        _Node("pos_emb", "tensor(float16)"),
        _Node("pixel_attention_mask", "tensor(int32)"),
    ]
    engine.using_gpu = False
    engine._visual_force_cpu = False
    seen = []

    class _Session:
        def run(self, _unused, feed):
            batch = int(feed["pixel_values"].shape[0])
            seen.append(batch)
            assert feed["pixel_values"].dtype == np.float16
            assert feed["pos_emb"].shape[0] == batch
            assert feed["pixel_attention_mask"].dtype == np.int32
            return [np.full((batch, 768), 2.0, dtype=np.float32)]

    engine._get_visual_session_for_run = lambda: _Session()
    frames = [np.zeros((32, 48, 3), dtype=np.uint8) for _ in range(5)]
    vectors = engine.encode_images(frames)
    assert seen == [2, 2, 1]
    assert vectors.shape == (5, 768)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_encode_images_does_not_drop_a_bad_frame():
    engine = Fgclip2OnnxEngine.__new__(Fgclip2OnnxEngine)
    engine.embedding_batch_size = 4
    good = np.zeros((32, 48, 3), dtype=np.uint8)
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    try:
        engine.encode_images([good, empty])
    except RuntimeError as exc:
        assert "frame 1" in str(exc)
    else:
        raise AssertionError("bad frame was dropped")


def test_square_preprocess_is_rejected():
    engine = Fgclip2OnnxEngine.__new__(Fgclip2OnnxEngine)
    try:
        engine.preprocess_into(np.zeros((8, 8, 3), dtype=np.uint8), np.zeros((3, 16, 16), np.float32))
    except RuntimeError as exc:
        assert "NaFlex" in str(exc)
    else:
        raise AssertionError("square preprocess ran")


def test_text_seq_len_must_match_the_graph():
    class _Node:
        def __init__(self, name, shape):
            self.name = name
            self.shape = shape

    assert_text_seq_len([_Node("input_ids", ["batch", 64])])
    assert_text_seq_len([_Node("input_ids", ["batch", "sequence"])])
    try:
        assert_text_seq_len([_Node("input_ids", [1, 77])])
    except RuntimeError as exc:
        assert "77" in str(exc)
    else:
        raise AssertionError("wrong text length was accepted")


def test_zip_without_manifest_imports_as_fgclip2_profile():
    from src.services import model_package_service

    with tempfile.TemporaryDirectory() as model_root:
        zip_root = Path(model_root) / "packages"
        nested = {
            "fgclip2-onnx/models/fgclip2_vision_fp16.onnx": b"vision",
            "fgclip2-onnx/models/fgclip2_text_fp16.onnx": b"text",
            "fgclip2-onnx/assets/position_embedding_weight.npz": b"pos",
            "fgclip2-onnx/processor/tokenizer.json": b"tok",
        }
        zip_path = zip_root / "fgclip2-onnx.zip"
        zip_root.mkdir()
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name, payload in nested.items():
                archive.writestr(name, payload)

        config = {
            "schema_version": 2,
            "models": {"active_profile": "clip_onnx_default", "profiles": []},
        }
        with (
            patch("src.services.model_package_service.load_config", return_value=config),
            patch("src.services.model_package_service.save_config"),
            patch("src.services.model_package_service.get_config_schema_version", return_value=2),
        ):
            result = model_package_service.import_model_package_zip(model_root, str(zip_path))

        assert result["imported"] == 1
        assert result["errors"] == []
        installed = Path(model_root) / "fgclip2-onnx" / "base"
        assert (installed / "model_manifest.json").is_file()
        manifest = json.loads((installed / "model_manifest.json").read_text(encoding="utf-8"))
        assert manifest["provider"] == "fgclip2_onnx"
        assert manifest["embedding_dimension"] == 768
        for name in (
            "fgclip2_vision_fp16.onnx",
            "fgclip2_text_fp16.onnx",
            "position_embedding_weight.npz",
            "tokenizer.json",
        ):
            assert (installed / name).is_file()


def test_fgclip2_frame_layout_is_not_a_square_crop():
    from src.core.extract_frames import _resolve_frame_layout

    config = {
        "schema_version": 2,
        "models": {
            "active_profile": "fgclip2_base",
            "profiles": [{"id": "fgclip2_base", "provider": "fgclip2_onnx", "runtime": {}}],
        },
    }
    with patch(
        "src.core.extract_frames.get_video_stream_info",
        return_value={"width": 1920, "height": 1080},
    ):
        height, width, vf = _resolve_frame_layout("D:/video.mp4", 2.0, config)
    assert (height, width) == naflex_pixel_size(1080, 1920)
    assert f"scale={width}:{height}:flags=bilinear" in vf
    assert "crop=" not in vf

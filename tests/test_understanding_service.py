import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.understanding.pipeline import UnderstandingPipeline
from src.domain.evidence_bundle import validate_evidence_bundle
from src.services.understanding_service import (
    build_evidence_bundle_payload,
    resolve_video_context,
    write_evidence_bundle,
)


PROFILE_MANIFEST = {
    "kind": "understanding_profile",
    "manifest_version": 1,
    "id": "vision_baseline_v1",
    "display_name": "视觉基础版",
    "install_relpath": "profiles/vision_baseline_v1",
    "requires": {
        "components": [
            "vision/object_detection/yolo11n",
            "vision/image_caption/qwen3-vl-remote",
        ]
    },
    "pipeline": [
        {
            "step": "object_detection",
            "component": "vision/object_detection/yolo11n",
            "enabled": True,
        },
        {
            "step": "image_caption",
            "component": "vision/image_caption/qwen3-vl-remote",
            "enabled": True,
        },
    ],
    "defaults": {"keyframe_strategy": "midpoint"},
}


class UnderstandingPipelineTests(unittest.TestCase):
    def test_run_chunk_uses_shared_keyframe_for_all_steps(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        fake_detection = MagicMock()
        fake_detection.infer.return_value = {
            "objects": [{"label": "person", "confidence": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4]}],
        }
        fake_caption = MagicMock()
        fake_caption.infer.return_value = {"text": "a person standing"}

        pipeline = UnderstandingPipeline(PROFILE_MANIFEST)
        with (
            patch("src.core.understanding.pipeline.get_single_thumbnail", return_value=frame) as mock_thumb,
            patch.object(pipeline, "_get_component", side_effect=[fake_detection, fake_caption]),
        ):
            result = pipeline.run_chunk(
                video_path="D:/Videos/demo.mp4",
                chunk={"start": 0.0, "end": 4.0},
                chunk_index=0,
            )

        mock_thumb.assert_called_once_with("D:/Videos/demo.mp4", 2.0)
        self.assertAlmostEqual(result["sample"]["timestamp_sec"], 2.0)
        self.assertEqual(result["sample"]["strategy"], "midpoint")
        self.assertEqual(result["evidence"]["vision"]["object_detection"]["source"], "vision/object_detection/yolo11n")
        self.assertEqual(result["evidence"]["vision"]["image_caption"]["text"], "a person standing")
        fake_detection.infer.assert_called_once()
        fake_caption.infer.assert_called_once()


    def test_run_video_chunks_invokes_chunk_callback(self):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        pipeline = UnderstandingPipeline(PROFILE_MANIFEST)
        seen = []

        def _fake_run_chunk(**kwargs):
            return {
                "chunk_index": kwargs["chunk_index"],
                "start_sec": float(kwargs["chunk"].get("start", 0.0)),
                "end_sec": float(kwargs["chunk"].get("end", 0.0)),
                "sample": {"timestamp_sec": 1.0, "strategy": "midpoint"},
                "evidence": {"vision": {}, "audio": {}},
            }

        chunks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
        with patch.object(pipeline, "run_chunk", side_effect=_fake_run_chunk):
            results = pipeline.run_video_chunks(
                video_path="D:/Videos/demo.mp4",
                chunks=chunks,
                chunk_completed_callback=lambda index, total, payload: seen.append((index, total)),
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(seen, [(0, 2), (1, 2)])


class UnderstandingServiceTests(unittest.TestCase):
    def test_resolve_video_context_from_meta(self):
        meta = {
            "libraries": {
                "D:/Videos/AnimeS1": {
                    "files": {
                        "ep01.mp4": {"vid": "abc123", "asset_state": "ready"},
                    }
                }
            }
        }
        config = {"meta_file": "D:/VideoSeek/data/meta.json"}
        with (
            patch("src.services.understanding_service.load_model_metadata", return_value=meta),
            patch("src.services.understanding_service.get_video_duration_seconds", return_value=3600.0),
            patch("src.services.understanding_service.os.path.isfile", return_value=True),
        ):
            context = resolve_video_context("abc123", config=config)

        self.assertEqual(context["video_id"], "abc123")
        self.assertEqual(context["video_path"], os.path.normpath("D:/Videos/AnimeS1/ep01.mp4"))
        self.assertEqual(context["video_rel_path"], "ep01.mp4")
        self.assertEqual(context["library_path"], os.path.normpath("D:/Videos/AnimeS1"))

    def test_build_and_write_evidence_bundle(self):
        video_context = {
            "video_id": "abc123",
            "video_path": "D:/Videos/AnimeS1/ep01.mp4",
            "video_rel_path": "ep01.mp4",
            "library_path": "D:/Videos/AnimeS1",
            "duration_sec": 10.0,
            "source_exists": True,
        }
        chunks = [{"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}]
        fake_pipeline = MagicMock()
        fake_pipeline.run_video_chunks.return_value = [
            {
                "chunk_index": 0,
                "start_sec": 0.0,
                "end_sec": 5.0,
                "sample": {"timestamp_sec": 2.5, "strategy": "midpoint"},
                "evidence": {"vision": {}, "audio": {}},
            }
        ]
        fake_pipeline.component_map.return_value = {
            "object_detection": "vision/object_detection/yolo11n",
            "image_caption": "vision/image_caption/qwen3-vl-remote",
        }
        fake_pipeline.keyframe_strategy = "midpoint"
        fake_pipeline.close = MagicMock()

        config = {
            "models": {
                "active_profile": "clip_onnx_default",
                "profiles": [
                    {
                        "id": "clip_onnx_default",
                        "provider": "clip_onnx",
                        "runtime": {"model_variant": "vit-base-patch32"},
                    }
                ],
            }
        }

        with (
            patch("src.services.understanding_service.UnderstandingPipeline", return_value=fake_pipeline),
            patch(
                "src.services.understanding_service.generate_video_summary_from_chunks",
                return_value={"text": "Overall the clip shows a quiet workspace.", "source": "remote_vlm"},
            ),
            patch(
                "src.services.understanding_service.get_active_embedding_spec",
                return_value={"model_id": "clip_onnx_default", "provider": "clip_onnx"},
            ),
            patch(
                "src.services.understanding_service.get_active_model_profile",
                return_value={
                    "id": "clip_onnx_default",
                    "provider": "clip_onnx",
                    "runtime": {"model_variant": "vit-base-patch32"},
                },
            ),
        ):
            payload = build_evidence_bundle_payload(
                video_context=video_context,
                chunks=chunks,
                profile_manifest=PROFILE_MANIFEST,
                profile_id="vision_baseline_v1",
                config=config,
            )

        bundle = validate_evidence_bundle(payload)
        self.assertEqual(bundle.video.video_id, "abc123")
        self.assertEqual(bundle.provenance.understanding_profile_id, "vision_baseline_v1")
        self.assertEqual(len(bundle.chunks), 1)
        self.assertIsNotNone(bundle.summary)
        self.assertEqual(bundle.summary.text, "Overall the clip shows a quiet workspace.")

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = os.path.join(temp_dir, "data", "evidence", "videos", "abc123.json")
            with patch(
                "src.services.understanding_service.get_evidence_path",
                return_value=evidence_path,
            ):
                written_path = write_evidence_bundle("abc123", payload, config={"data_root": temp_dir})
            self.assertEqual(written_path, evidence_path)
            self.assertTrue(os.path.isfile(evidence_path))
            loaded = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
            validate_evidence_bundle(loaded)

    def test_list_local_evidence_details_reads_provenance(self):
        from src.services.understanding_service import list_local_evidence_details

        evidence_payload = {
            "schema_version": 1,
            "video": {
                "video_id": "vid001",
                "video_path": "D:/lib/a.mp4",
                "video_rel_path": "a.mp4",
                "library_path": "D:/lib",
                "source_exists": True,
            },
            "provenance": {
                "understanding_profile_id": "vision_baseline_v1",
                "components": {
                    "object_detection": "vision/object_detection/yolo11n",
                    "image_caption": "vision/image_caption/qwen3-vl-remote",
                },
                "chunk_source": {
                    "search_profile_id": "clip_default",
                    "search_provider": "clip_onnx",
                    "search_variant": "vit-base-patch32",
                },
                "keyframe_strategy": "midpoint",
                "generated_at": "2026-06-23T12:00:00Z",
            },
            "chunks": [{"chunk_index": 0, "start_sec": 0.0, "end_sec": 1.0, "sample": {"timestamp_sec": 0.5, "strategy": "midpoint"}, "evidence": {"vision": {}, "audio": {}}}],
        }
        vector_detail = {
            "entries": [
                {
                    "library_path": "D:/lib",
                    "video_rel_path": "a.mp4",
                    "video_id": "vid001",
                    "source_exists": True,
                    "asset_state": "ready",
                },
                {
                    "library_path": "D:/lib",
                    "video_rel_path": "b.mp4",
                    "video_id": "vid002",
                    "source_exists": True,
                    "asset_state": "ready",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_dir = os.path.join(temp_dir, "data", "evidence", "videos")
            os.makedirs(evidence_dir, exist_ok=True)
            evidence_path = os.path.join(evidence_dir, "vid001.json")
            Path(evidence_path).write_text(json.dumps(evidence_payload), encoding="utf-8")
            with patch("src.services.library_service.list_local_vector_details", return_value=vector_detail), patch(
                "src.services.understanding_service.get_evidence_videos_dir",
                return_value=evidence_dir,
            ):
                detail = list_local_evidence_details(config={"data_root": temp_dir})

        self.assertEqual(detail["total_entries"], 1)
        self.assertEqual(detail["evidence_count"], 1)
        entry = detail["entries"][0]
        self.assertEqual(entry["yolo_model"], "yolo11n")
        self.assertEqual(entry["caption_model"], "qwen3-vl-remote")
        self.assertEqual(entry["clip_model"], "vit-base-patch32")
        self.assertEqual(entry["chunk_count"], 1)
        self.assertEqual(entry["evidence_state"], "ready")

    def test_delete_and_clear_evidence_files(self):
        from src.services.understanding_service import clear_all_evidence, delete_evidence_for_video

        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_dir = os.path.join(temp_dir, "data", "evidence", "videos")
            os.makedirs(evidence_dir, exist_ok=True)
            first_path = os.path.join(evidence_dir, "vid001.json")
            first_tmp = f"{first_path}.tmp"
            second_path = os.path.join(evidence_dir, "vid002.json")
            Path(first_path).write_text("{}", encoding="utf-8")
            Path(first_tmp).write_text("{}", encoding="utf-8")
            Path(second_path).write_text("{}", encoding="utf-8")
            config = {"data_root": temp_dir}
            with patch(
                "src.services.understanding_service.get_evidence_path",
                side_effect=lambda video_id, config=None: os.path.join(evidence_dir, f"{video_id}.json"),
            ), patch(
                "src.services.understanding_service.get_evidence_videos_dir",
                return_value=evidence_dir,
            ), patch(
                "src.services.understanding_service.get_evidence_root",
                return_value=os.path.dirname(evidence_dir),
            ):
                self.assertTrue(delete_evidence_for_video("vid001", config=config))
                self.assertFalse(os.path.isfile(first_path))
                self.assertFalse(os.path.isfile(first_tmp))
                cleared = clear_all_evidence(config=config)
            self.assertEqual(cleared["deleted_count"], 1)
            self.assertFalse(os.path.isfile(second_path))


if __name__ == "__main__":
    unittest.main()

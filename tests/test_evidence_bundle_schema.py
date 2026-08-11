import unittest

from src.domain.evidence_bundle import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EvidenceBundleValidationError,
    chunks_overlapping_time_window,
    evidence_bundle_to_dict,
    validate_evidence_bundle,
)


def sample_evidence_bundle_payload() -> dict:
    return {
        "schema_version": 1,
        "video": {
            "video_id": "abc123",
            "video_path": "D:/Videos/AnimeS1/ep01.mp4",
            "video_rel_path": "ep01.mp4",
            "library_path": "D:/Videos/AnimeS1",
            "duration_sec": 3600.0,
            "source_exists": True,
        },
        "provenance": {
            "understanding_profile_id": "vision_baseline_v1",
            "components": {
                "object_detection": "vision/object_detection/yolo11n",
                "image_caption": "vision/image_caption/qwen3-vl-remote",
            },
            "chunk_source": {
                "search_profile_id": "clip_onnx_default",
                "search_provider": "clip_onnx",
                "search_variant": "vit-base-patch32",
            },
            "keyframe_strategy": "midpoint",
            "generated_at": "2026-06-22T12:00:00Z",
        },
        "chunks": [
            {
                "chunk_index": 0,
                "start_sec": 0.0,
                "end_sec": 4.5,
                "sample": {
                    "timestamp_sec": 2.25,
                    "strategy": "midpoint",
                },
                "evidence": {
                    "vision": {
                        "object_detection": {
                            "source": "vision/object_detection/yolo11n",
                            "objects": [
                                {
                                    "label": "person",
                                    "confidence": 0.91,
                                    "bbox": [0.1, 0.08, 0.55, 0.92],
                                }
                            ],
                        },
                        "image_caption": {
                            "source": "vision/image_caption/qwen3-vl-remote",
                            "text": "person · table",
                        },
                    },
                    "audio": {},
                },
                "tags": ["person", "table"],
            }
        ],
    }


class EvidenceBundleSchemaTests(unittest.TestCase):
    def test_validate_sample_payload(self):
        bundle = validate_evidence_bundle(sample_evidence_bundle_payload())

        self.assertEqual(bundle.schema_version, EVIDENCE_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(bundle.video.video_id, "abc123")
        self.assertEqual(bundle.video.video_path, "D:/Videos/AnimeS1/ep01.mp4")
        self.assertEqual(bundle.provenance.understanding_profile_id, "vision_baseline_v1")
        self.assertEqual(len(bundle.chunks), 1)

        chunk = bundle.chunks[0]
        self.assertEqual(chunk.chunk_index, 0)
        self.assertAlmostEqual(chunk.start_sec, 0.0)
        self.assertAlmostEqual(chunk.end_sec, 4.5)
        self.assertIsNotNone(chunk.evidence.vision.object_detection)
        self.assertEqual(len(chunk.evidence.vision.object_detection.objects), 1)
        detected = chunk.evidence.vision.object_detection.objects[0]
        self.assertEqual(detected.label, "person")
        self.assertAlmostEqual(detected.confidence, 0.91)
        self.assertEqual(detected.bbox, (0.1, 0.08, 0.55, 0.92))
        self.assertIsNotNone(chunk.evidence.vision.image_caption)
        self.assertEqual(chunk.evidence.vision.image_caption.text, "person · table")
        self.assertEqual(chunk.tags, ("person", "table"))

    def test_round_trip_to_dict(self):
        payload = sample_evidence_bundle_payload()
        bundle = validate_evidence_bundle(payload)
        restored = validate_evidence_bundle(evidence_bundle_to_dict(bundle))
        self.assertEqual(restored.video.video_id, bundle.video.video_id)
        self.assertEqual(restored.provenance.components, bundle.provenance.components)
        self.assertEqual(len(restored.chunks), len(bundle.chunks))

    def test_optional_video_summary_round_trip(self):
        payload = sample_evidence_bundle_payload()
        payload["summary"] = {
            "text": "A person works at a desk throughout the clip.",
            "source": "remote_vlm",
        }
        bundle = validate_evidence_bundle(payload)
        self.assertIsNotNone(bundle.summary)
        self.assertEqual(bundle.summary.text, "A person works at a desk throughout the clip.")
        restored = validate_evidence_bundle(evidence_bundle_to_dict(bundle))
        self.assertIsNotNone(restored.summary)
        self.assertEqual(restored.summary.text, bundle.summary.text)

    def test_rejects_unsupported_schema_version(self):
        payload = sample_evidence_bundle_payload()
        payload["schema_version"] = 2
        with self.assertRaises(EvidenceBundleValidationError):
            validate_evidence_bundle(payload)

    def test_rejects_missing_video_path(self):
        payload = sample_evidence_bundle_payload()
        payload["video"].pop("video_path")
        with self.assertRaises(EvidenceBundleValidationError):
            validate_evidence_bundle(payload)

    def test_rejects_invalid_bbox_length(self):
        payload = sample_evidence_bundle_payload()
        payload["chunks"][0]["evidence"]["vision"]["object_detection"]["objects"][0]["bbox"] = [0.1, 0.2]
        with self.assertRaises(EvidenceBundleValidationError):
            validate_evidence_bundle(payload)

    def test_chunks_overlapping_time_window(self):
        bundle = validate_evidence_bundle(sample_evidence_bundle_payload())

        self.assertEqual(len(chunks_overlapping_time_window(bundle, 0.0, 1.0)), 1)
        self.assertEqual(len(chunks_overlapping_time_window(bundle, 10.0, 20.0)), 0)
        self.assertEqual(len(chunks_overlapping_time_window(bundle)), 1)

    def test_chunks_overlapping_time_window_rejects_invalid_range(self):
        bundle = validate_evidence_bundle(sample_evidence_bundle_payload())
        with self.assertRaises(ValueError):
            chunks_overlapping_time_window(bundle, 5.0, 1.0)


if __name__ == "__main__":
    unittest.main()

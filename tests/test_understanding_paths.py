import os
import tempfile
import unittest
from unittest.mock import patch

from src.core.understanding.types import (
    UnderstandingInputKind,
    UnderstandingModality,
    UnderstandingOutputKind,
    UnderstandingTask,
    normalize_enum_value,
)
from src.services.understanding_paths import (
    build_component_id,
    build_component_install_relpath,
    get_builtin_profiles_dir,
    get_component_dir,
    get_component_manifest_path,
    get_evidence_path,
    get_evidence_root,
    get_evidence_videos_dir,
    get_profile_dir,
    get_profile_manifest_path,
    get_understanding_components_root,
    get_understanding_profiles_root,
    get_understanding_root,
    parse_component_id,
)


class UnderstandingPathsTests(unittest.TestCase):
    def setUp(self):
        self.model_dir = os.path.normpath("D:/VideoSeek/models")
        self.config = {"data_root": os.path.normpath("D:/VideoSeek")}

    def test_parse_and_build_component_id(self):
        component_id = "vision/image_caption/qwen3-vl-remote"
        parsed = parse_component_id(component_id)
        self.assertEqual(parsed, ("vision", "image_caption", "qwen3-vl-remote"))
        self.assertEqual(
            build_component_id("vision", "image_caption", "qwen3-vl-remote"),
            component_id,
        )
        self.assertEqual(
            build_component_install_relpath("vision", "image_caption", "qwen3-vl-remote"),
            os.path.join("components", "vision", "image_caption", "qwen3-vl-remote"),
        )

    def test_parse_component_id_rejects_invalid_format(self):
        with self.assertRaises(ValueError):
            parse_component_id("vision/image_caption")

    def test_understanding_model_paths(self):
        self.assertEqual(
            get_understanding_root(self.model_dir),
            os.path.join(self.model_dir, "understanding"),
        )
        self.assertEqual(
            get_understanding_components_root(self.model_dir),
            os.path.join(self.model_dir, "understanding", "components"),
        )
        self.assertEqual(
            get_understanding_profiles_root(self.model_dir),
            os.path.join(self.model_dir, "understanding", "profiles"),
        )
        self.assertEqual(
            get_component_dir("vision/image_caption/qwen3-vl-remote", model_dir=self.model_dir),
            os.path.join(
                self.model_dir,
                "understanding",
                "components",
                "vision",
                "image_caption",
                "qwen3-vl-remote",
            ),
        )
        self.assertEqual(
            get_component_manifest_path("vision/image_caption/qwen3-vl-remote", model_dir=self.model_dir),
            os.path.join(
                self.model_dir,
                "understanding",
                "components",
                "vision",
                "image_caption",
                "qwen3-vl-remote",
                "understanding_manifest.json",
            ),
        )
        self.assertEqual(
            get_profile_dir("vision_baseline_v1", model_dir=self.model_dir),
            os.path.join(self.model_dir, "understanding", "profiles", "vision_baseline_v1"),
        )
        self.assertEqual(
            get_profile_manifest_path("vision_baseline_v1", model_dir=self.model_dir),
            os.path.join(
                self.model_dir,
                "understanding",
                "profiles",
                "vision_baseline_v1",
                "profile_manifest.json",
            ),
        )

    @patch("src.services.understanding_paths.get_data_storage_paths")
    def test_evidence_paths(self, mock_get_data_storage_paths):
        from src.services.understanding_paths import (
            get_evidence_motion_dir,
            get_evidence_summaries_dir,
            get_evidence_tags_dir,
            get_legacy_evidence_path,
        )

        mock_get_data_storage_paths.return_value = {
            "data_dir": os.path.join(self.config["data_root"], "data"),
        }
        self.assertEqual(
            get_evidence_root(config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence"),
        )
        self.assertEqual(
            get_evidence_videos_dir(config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence", "videos"),
        )
        self.assertEqual(
            get_evidence_tags_dir(config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence", "tags"),
        )
        self.assertEqual(
            get_evidence_summaries_dir(config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence", "summaries"),
        )
        self.assertEqual(
            get_evidence_motion_dir(config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence", "motion"),
        )
        self.assertEqual(
            get_evidence_path("abc123", config=self.config, mode="tags"),
            os.path.join(self.config["data_root"], "data", "evidence", "tags", "abc123.json"),
        )
        self.assertEqual(
            get_evidence_path("abc123", config=self.config, mode="summary"),
            os.path.join(self.config["data_root"], "data", "evidence", "summaries", "abc123.json"),
        )
        self.assertEqual(
            get_evidence_path("abc123", config=self.config, mode="motion"),
            os.path.join(self.config["data_root"], "data", "evidence", "motion", "abc123.json"),
        )
        self.assertEqual(
            get_legacy_evidence_path("abc123", config=self.config),
            os.path.join(self.config["data_root"], "data", "evidence", "videos", "abc123.json"),
        )

    def test_get_evidence_path_rejects_invalid_video_id(self):
        with patch(
            "src.services.understanding_paths.get_data_storage_paths",
            return_value={"data_dir": "D:/VideoSeek/data"},
        ):
            with self.assertRaises(ValueError):
                get_evidence_path("../escape")

    def test_get_understanding_root_requires_model_dir(self):
        with patch("src.services.understanding_paths.get_configured_model_dir", return_value=""):
            with self.assertRaises(ValueError):
                get_understanding_root()

    def test_builtin_profiles_dir_points_to_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = os.path.join(temp_dir, "resources", "understanding_profiles")
            os.makedirs(profiles_dir, exist_ok=True)
            with patch("src.services.understanding_paths.get_resource_path", return_value=profiles_dir):
                self.assertEqual(get_builtin_profiles_dir(), os.path.normpath(profiles_dir))

    def test_understanding_enums(self):
        self.assertEqual(normalize_enum_value(UnderstandingModality, "vision", "modality"), "vision")
        self.assertEqual(
            normalize_enum_value(UnderstandingTask, "image_caption", "task"),
            "image_caption",
        )
        # Legacy task still accepted for old manifests / evidence validation.
        self.assertEqual(
            normalize_enum_value(UnderstandingTask, "object_detection", "task"),
            "object_detection",
        )
        self.assertEqual(
            normalize_enum_value(UnderstandingInputKind, "chunk_keyframe", "input_kind"),
            "chunk_keyframe",
        )
        self.assertEqual(
            normalize_enum_value(UnderstandingOutputKind, "caption", "output_kind"),
            "caption",
        )


if __name__ == "__main__":
    unittest.main()

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
        component_id = "vision/object_detection/yolov8n"
        parsed = parse_component_id(component_id)
        self.assertEqual(parsed, ("vision", "object_detection", "yolov8n"))
        self.assertEqual(
            build_component_id("vision", "object_detection", "yolov8n"),
            component_id,
        )
        self.assertEqual(
            build_component_install_relpath("vision", "object_detection", "yolov8n"),
            os.path.join("components", "vision", "object_detection", "yolov8n"),
        )

    def test_parse_component_id_rejects_invalid_format(self):
        with self.assertRaises(ValueError):
            parse_component_id("vision/object_detection")

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
            get_component_dir("vision/object_detection/yolov8n", model_dir=self.model_dir),
            os.path.join(
                self.model_dir,
                "understanding",
                "components",
                "vision",
                "object_detection",
                "yolov8n",
            ),
        )
        self.assertEqual(
            get_component_manifest_path("vision/object_detection/yolov8n", model_dir=self.model_dir),
            os.path.join(
                self.model_dir,
                "understanding",
                "components",
                "vision",
                "object_detection",
                "yolov8n",
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
            get_evidence_path("abc123", config=self.config),
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
            normalize_enum_value(UnderstandingTask, "object_detection", "task"),
            "object_detection",
        )
        self.assertEqual(
            normalize_enum_value(UnderstandingInputKind, "chunk_keyframe", "input_kind"),
            "chunk_keyframe",
        )
        self.assertEqual(
            normalize_enum_value(UnderstandingOutputKind, "objects", "output_kind"),
            "objects",
        )


if __name__ == "__main__":
    unittest.main()

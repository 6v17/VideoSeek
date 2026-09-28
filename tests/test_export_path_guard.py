"""Export path guards for Agent / team mode."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.clip_export_service import (
    default_agent_export_root,
    export_path_guard_strict,
    list_export_allowed_roots,
    output_path_allowed,
)


class ExportPathGuardTests(unittest.TestCase):
    def test_localhost_allows_any_path_outside_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "exports", "a.mp4")
            with (
                patch("src.services.clip_export_service.export_path_guard_strict", return_value=False),
                patch("src.services.clip_export_service.list_export_allowed_roots", return_value=[]),
                patch("src.services.library_service.list_libraries", return_value={}),
            ):
                self.assertTrue(output_path_allowed(outside, config={}))

    def test_team_strict_requires_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = os.path.join(tmp, "allowed")
            os.makedirs(allowed, exist_ok=True)
            good = os.path.join(allowed, "clip.mp4")
            bad = os.path.join(tmp, "elsewhere", "clip.mp4")
            with (
                patch.dict("os.environ", {"VIDEOSEEK_AGENT_EXPORT_STRICT": "1"}, clear=False),
                patch(
                    "src.services.clip_export_service.default_agent_export_root",
                    return_value=allowed,
                ),
                patch("src.services.library_service.list_libraries", return_value={}),
            ):
                self.assertTrue(export_path_guard_strict({}))
                roots = list_export_allowed_roots({})
                self.assertTrue(any(os.path.normcase(r) == os.path.normcase(allowed) for r in roots))
                self.assertTrue(output_path_allowed(good, config={}))
                self.assertFalse(output_path_allowed(bad, config={}))

    def test_configured_roots_enforced_even_when_not_team(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = os.path.join(tmp, "out")
            os.makedirs(allowed, exist_ok=True)
            cfg = {"agent_export_allowed_roots": [allowed]}
            with (
                patch.dict("os.environ", {"VIDEOSEEK_AGENT_EXPORT_STRICT": "0"}, clear=False),
                patch(
                    "src.services.clip_export_service.default_agent_export_root",
                    return_value=os.path.join(tmp, "app_exports"),
                ),
                patch("src.services.library_service.list_libraries", return_value={}),
            ):
                self.assertTrue(output_path_allowed(os.path.join(allowed, "m.json"), config=cfg))
                self.assertFalse(output_path_allowed(os.path.join(tmp, "nope.json"), config=cfg))


if __name__ == "__main__":
    unittest.main()

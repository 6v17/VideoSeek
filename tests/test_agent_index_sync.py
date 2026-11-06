import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.services.agent_index_sync import (
    AgentIndexSyncRejected,
    execute_agent_add_library,
    execute_agent_include_videos,
    execute_agent_index_sync,
    execute_agent_library_refresh,
    plan_include_videos,
    register_agent_include_handler,
    register_agent_index_sync_handler,
    register_agent_library_refresh_handler,
    unregister_agent_include_handler,
    unregister_agent_index_sync_handler,
    unregister_agent_library_refresh_handler,
)
from src.services.indexing_runtime_status import (
    clear_index_sync_running,
    get_index_sync_status,
    set_index_prepare_running,
    try_acquire_index_sync,
)
from src.services.search_scope import normalize_scope_path


class IndexPrepareTests(unittest.TestCase):
    def tearDown(self):
        clear_index_sync_running()

    def test_prepare_reports_syncing_without_holding_the_slot(self):
        set_index_prepare_running(True, "D:/lib")
        self.assertTrue(get_index_sync_status()["index_sync_in_progress"])
        self.assertEqual(get_index_sync_status()["index_sync_target_library_path"], "D:/lib")
        self.assertTrue(try_acquire_index_sync("D:/lib"))
        self.assertTrue(get_index_sync_status()["index_sync_in_progress"])


class AgentIndexSyncServiceTests(unittest.TestCase):
    def tearDown(self):
        clear_index_sync_running()

    def test_unknown_library_is_rejected(self):
        with patch("src.services.library_service.list_libraries", return_value={"D:/Anime": {}}):
            with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                with self.assertRaises(AgentIndexSyncRejected) as caught:
                    execute_agent_index_sync("D:/Other")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.code, "unknown_library")

    def test_syncs_the_matching_library(self):
        seen = {}

        def handler(paths, video_ids=None):
            seen["paths"] = list(paths)
            seen["video_ids"] = video_ids
            return {"accepted": True, "reason": "started", "library_paths": list(paths)}

        register_agent_index_sync_handler(handler)
        try:
            with patch("src.services.library_service.list_libraries", return_value={"D:/Anime": {}}):
                with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                    payload = execute_agent_index_sync("d:/anime")
        finally:
            unregister_agent_index_sync_handler(handler)
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["reason"], "started")
        self.assertEqual(seen["paths"], ["D:/Anime"])
        self.assertEqual(
            normalize_scope_path(payload["library_paths"][0]),
            normalize_scope_path("D:/Anime"),
        )

    def test_desktop_unavailable_without_a_window(self):
        with patch("src.services.library_service.list_libraries", return_value={"D:/Anime": {}}):
            with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                with self.assertRaises(AgentIndexSyncRejected) as caught:
                    execute_agent_index_sync(None)
        self.assertEqual(caught.exception.code, "desktop_unavailable")


class AgentAddLibraryTests(unittest.TestCase):
    def test_rejects_a_path_that_is_not_a_folder(self):
        with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
            with self.assertRaises(AgentIndexSyncRejected) as caught:
                execute_agent_add_library("D:/missing-folder")
        self.assertEqual(caught.exception.code, "invalid_library_path")

    def test_adds_an_existing_folder(self):
        import tempfile

        seen = {}

        def handler(path):
            seen["path"] = path
            return {"accepted": True, "reason": "started", "added": True, "library_path": path}

        from src.services.agent_index_sync import register_agent_add_library_handler, unregister_agent_add_library_handler

        register_agent_add_library_handler(handler)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                    payload = execute_agent_add_library(folder)
        finally:
            unregister_agent_add_library_handler(handler)
        self.assertTrue(payload["added"])
        self.assertTrue(payload["accepted"])
        self.assertEqual(seen["path"], payload["library_path"])

    def test_existing_library_tells_the_agent_to_sync(self):
        import tempfile

        from src.services.agent_index_sync import register_agent_add_library_handler, unregister_agent_add_library_handler

        def handler(path):
            return {"accepted": False, "reason": "exists", "library_path": path}

        register_agent_add_library_handler(handler)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                    with self.assertRaises(AgentIndexSyncRejected) as caught:
                        execute_agent_add_library(folder)
        finally:
            unregister_agent_add_library_handler(handler)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "library_exists")


class AgentIndexSyncRouteTests(unittest.TestCase):
    def test_route_returns_503_when_desktop_is_not_registered(self):
        from src.web.agent_api import AgentApiService

        client = TestClient(AgentApiService(host="127.0.0.1", port=8765).app)
        with patch("src.services.library_service.list_libraries", return_value={"D:/Anime": {}}):
            with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                response = client.post("/api/v1/index/sync", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "desktop_unavailable")

    def test_add_route_rejects_a_missing_folder(self):
        from src.web.agent_api import AgentApiService

        client = TestClient(AgentApiService(host="127.0.0.1", port=8765).app)
        with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
            response = client.post("/api/v1/libraries", json={"library_path": "D:/missing-folder"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_library_path")


class AgentVideoSyncTests(unittest.TestCase):
    def tearDown(self):
        unregister_agent_index_sync_handler(self._handler) if getattr(self, "_handler", None) else None

    def _libraries(self):
        return {
            "D:/Anime": {
                "files": {
                    "ep01.mp4": {"vid": "vid-1"},
                    "ep02.mp4": {"vid": "vid-2"},
                }
            }
        }

    def test_syncs_one_video_id(self):
        seen = {}

        def handler(paths, video_ids=None):
            seen["paths"] = list(paths)
            seen["video_ids"] = list(video_ids or [])
            return {"accepted": True, "reason": "started", "library_paths": list(paths), "video_ids": list(video_ids or [])}

        self._handler = handler
        register_agent_index_sync_handler(handler)
        with patch("src.services.library_service.list_libraries", return_value=self._libraries()):
            with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                payload = execute_agent_index_sync(video_ids=["vid-2"])
        self.assertEqual(payload["video_ids"], ["vid-2"])
        self.assertEqual(seen["paths"], ["D:/Anime"])
        self.assertEqual(seen["video_ids"], ["vid-2"])

    def test_unknown_video_asks_for_a_refresh(self):
        with patch("src.services.library_service.list_libraries", return_value=self._libraries()):
            with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                with self.assertRaises(AgentIndexSyncRejected) as caught:
                    execute_agent_index_sync(video_ids=["missing"])
        self.assertEqual(caught.exception.code, "unknown_video")

    def test_refresh_rescans_without_indexing(self):
        seen = {}

        def handler(paths):
            seen["paths"] = list(paths)
            return {"accepted": True, "reason": "started", "library_paths": list(paths)}

        register_agent_library_refresh_handler(handler)
        try:
            with patch("src.services.library_service.list_libraries", return_value=self._libraries()):
                with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                    payload = execute_agent_library_refresh("D:/Anime")
        finally:
            unregister_agent_library_refresh_handler(handler)
        self.assertTrue(payload["accepted"])
        self.assertEqual(seen["paths"], ["D:/Anime"])
        self.assertNotIn("video_ids", payload)


class IncludeVideosPlanTests(unittest.TestCase):
    def test_splits_known_refresh_add_and_overlap(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            library = os.path.join(root, "lib")
            nested = os.path.join(root, "parent", "nested")
            outside = os.path.join(root, "outside")
            outer = os.path.join(root, "outer")
            inner = os.path.join(outer, "inner")
            for folder in (library, nested, outside, outer, inner):
                os.makedirs(folder, exist_ok=True)
            known = os.path.join(library, "known.mp4")
            fresh = os.path.join(library, "fresh.mp4")
            loose = os.path.join(root, "parent", "loose.mp4")
            added = os.path.join(outside, "new.mp4")
            top = os.path.join(outer, "a.mp4")
            child = os.path.join(inner, "b.mp4")
            for path in (known, fresh, loose, added, top, child):
                with open(path, "wb") as handle:
                    handle.write(b"x")
            libraries = {
                library: {"files": {os.path.basename(known): {"vid": "known-id"}}},
                nested: {"files": {}},
            }
            with patch("src.services.library_service.list_libraries", return_value=libraries):
                plan = plan_include_videos([known, fresh, loose, added, top, child, os.path.join(root, "missing.mp4")])
        actions = {item["video_path"]: item["action"] for item in plan["accepted_videos"]}
        self.assertEqual(actions[os.path.normpath(known)], "index")
        self.assertEqual(actions[os.path.normpath(fresh)], "refresh")
        self.assertEqual(actions[os.path.normpath(added)], "add")
        self.assertEqual(actions[os.path.normpath(top)], "add")
        self.assertEqual(actions[os.path.normpath(child)], "add")
        self.assertEqual(
            os.path.normpath(next(item["library_path"] for item in plan["accepted_videos"] if item["video_path"] == os.path.normpath(child))),
            os.path.normpath(outer),
        )
        self.assertEqual(plan["libraries_to_add"], [os.path.normpath(outside), os.path.normpath(outer)] or plan["libraries_to_add"])
        self.assertIn(os.path.normpath(outside), plan["libraries_to_add"])
        self.assertIn(os.path.normpath(outer), plan["libraries_to_add"])
        self.assertNotIn(os.path.normpath(inner), plan["libraries_to_add"])
        reasons = {item["video_path"]: item["reason"] for item in plan["rejected"]}
        self.assertEqual(reasons[os.path.normpath(loose)], "library_overlap")
        self.assertEqual(reasons[os.path.join(root, "missing.mp4")], "invalid_video_path")

    def test_execute_returns_rejections_without_starting(self):
        with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
            payload = execute_agent_include_videos(["D:/missing-file.mp4"])
        self.assertFalse(payload["accepted"])
        self.assertEqual(payload["reason"], "rejected")
        self.assertEqual(payload["rejected"][0]["reason"], "invalid_video_path")

    def test_execute_sends_the_plan_to_the_desktop(self):
        import os
        import tempfile

        seen = {}

        def handler(plan):
            seen["plan"] = plan
            return {
                "accepted": True,
                "reason": "started",
                "video_paths": plan["video_paths"],
                "library_paths": plan["libraries_to_add"],
                "libraries_added": plan["libraries_to_add"],
                "rejected": plan["rejected"],
            }

        register_agent_include_handler(handler)
        try:
            with tempfile.TemporaryDirectory() as root:
                video = os.path.join(root, "clip.mp4")
                with open(video, "wb") as handle:
                    handle.write(b"x")
                with patch("src.services.library_service.list_libraries", return_value={}):
                    with patch("src.services.team_mode_service.is_team_client_mode", return_value=False):
                        payload = execute_agent_include_videos([video])
        finally:
            unregister_agent_include_handler(handler)
        self.assertTrue(payload["accepted"])
        self.assertEqual(seen["plan"]["libraries_to_add"], [os.path.normpath(os.path.dirname(seen["plan"]["video_paths"][0]))])

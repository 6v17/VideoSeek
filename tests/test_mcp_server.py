import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

from src.web.mcp_server import (
    AgentApiUnreachable,
    AgentHttpClient,
    _MSG_API_OFF,
    _MSG_HEALTH,
    _MSG_TIMEOUT,
    cursor_mcp_config,
    handle_message,
    recover_local_api,
    serve,
)


class FakeApi(AgentHttpClient):
    def __init__(self):
        super().__init__("http://127.0.0.1:8765")
        self.calls = []
        self.next_status = 200
        self.next_payload = {"ok": True}

    def request_json(self, method, path, *, query=None, body=None, timeout=60):
        self.calls.append(
            {"method": method, "path": path, "query": query, "body": body, "timeout": timeout}
        )
        return self.next_status, self.next_payload


class McpProtocolTests(unittest.TestCase):
    def test_initialize_lists_tools_and_resources(self):
        api = FakeApi()
        init = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, api)
        self.assertEqual(init["result"]["serverInfo"]["name"], "videoseek")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIn("resources", init["result"]["capabilities"])

        tools = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, api)
        names = [item["name"] for item in tools["result"]["tools"]]
        self.assertEqual(
            names,
            ["list_libraries", "sync_library", "search", "extract_frames", "export_clips", "export_timeline"],
        )

        resources = handle_message({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}, api)
        uris = [item["uri"] for item in resources["result"]["resources"]]
        self.assertEqual(uris, ["videoseek://status", "videoseek://presets"])

    def test_notification_has_no_response(self):
        stdout = io.StringIO()
        serve(FakeApi(), io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'), stdout)
        self.assertEqual(stdout.getvalue(), "")

    def test_cursor_config_launches_this_module(self):
        config = cursor_mcp_config()
        server = config["mcpServers"]["videoseek"]
        self.assertEqual(server["args"], ["-m", "src.web.mcp_server"])
        self.assertTrue(server["cwd"])

    def test_packaged_cursor_config_calls_the_exe(self):
        with patch("src.infra.paths.is_standalone_app", return_value=True):
            with patch("src.infra.paths.get_app_install_dir", return_value="D:/VideoSeek"):
                server = cursor_mcp_config()["mcpServers"]["videoseek"]
        self.assertEqual(server["args"], ["--mcp-stdio"])
        self.assertNotIn("-m", server["args"])
        self.assertEqual(server["cwd"], "D:/VideoSeek")
        self.assertTrue(server["command"])


class McpToolRoutingTests(unittest.TestCase):
    def _call(self, api, name, arguments):
        return handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            api,
        )

    def test_search_one_query_posts_single_endpoint(self):
        api = FakeApi()
        api.next_payload = {"ok": True, "hits": []}
        result = self._call(api, "search", {"query": "雨夜", "search_kind": "visual"})
        self.assertNotIn("isError", result["result"])
        call = api.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/api/v1/search")
        self.assertEqual(call["body"]["query"], "雨夜")

    def test_search_queries_posts_batch_endpoint(self):
        api = FakeApi()
        self._call(api, "search", {"queries": [{"query": "a"}, {"query": "b"}]})
        self.assertEqual(api.calls[0]["path"], "/api/v1/search/batch")
        self.assertEqual(len(api.calls[0]["body"]["queries"]), 2)

    def test_list_videos_uses_query_string(self):
        api = FakeApi()
        self._call(
            api,
            "list_libraries",
            {"kind": "videos", "library_path": "D:/Videos", "ready_only": True},
        )
        call = api.calls[0]
        self.assertEqual(call["path"], "/api/v1/videos")
        self.assertEqual(call["query"]["library_path"], "D:/Videos")
        self.assertIs(call["query"]["ready_only"], True)

    def test_sync_add_posts_library_path(self):
        api = FakeApi()
        self._call(api, "sync_library", {"action": "add", "library_path": "D:/Videos"})
        self.assertEqual(api.calls[0]["path"], "/api/v1/libraries")
        self.assertEqual(api.calls[0]["body"], {"library_path": "D:/Videos"})

    def test_one_frame_and_many_frames_use_different_routes(self):
        api = FakeApi()
        self._call(api, "extract_frames", {"items": [{"video_path": "D:/a.mp4", "time_sec": 1.5}]})
        self.assertEqual(api.calls[0]["path"], "/api/v1/frames/extract")
        self._call(
            api,
            "extract_frames",
            {
                "items": [
                    {"video_path": "D:/a.mp4", "time_sec": 1},
                    {"video_path": "D:/a.mp4", "time_sec": 2},
                ]
            },
        )
        self.assertEqual(api.calls[1]["path"], "/api/v1/frames/extract/batch")

    def test_frame_image_is_lifted_out_of_the_text(self):
        api = FakeApi()
        api.next_payload = {
            "ok": True,
            "video_path": "D:/a.mp4",
            "mime": "image/jpeg",
            "image_base64": "abcd",
        }
        result = self._call(api, "extract_frames", {"items": [{"video_path": "D:/a.mp4", "time_sec": 1}]})
        text = result["result"]["content"][0]["text"]
        self.assertIn("[image]", text)
        self.assertNotIn("abcd", text)
        self.assertEqual(result["result"]["content"][1]["type"], "image")
        self.assertEqual(result["result"]["content"][1]["data"], "abcd")

    def test_manifest_and_timeline_use_different_routes(self):
        api = FakeApi()
        items = [{"video_path": "D:/a.mp4", "start_sec": 1, "end_sec": 3}]
        self._call(api, "export_timeline", {"output": "manifest", "items": items})
        self.assertEqual(api.calls[0]["path"], "/api/v1/export/manifest")
        self._call(api, "export_timeline", {"format": "jianying", "items": items})
        self.assertEqual(api.calls[1]["path"], "/api/v1/export/timeline")
        self.assertEqual(api.calls[1]["body"]["format"], "jianying")

    def test_http_error_is_a_tool_error(self):
        api = FakeApi()
        api.next_status = 409
        api.next_payload = {"ok": False, "error": {"code": "index_not_ready", "message": "not ready"}}
        result = self._call(api, "search", {"query": "雨"})
        self.assertTrue(result["result"]["isError"])
        self.assertIn("index_not_ready", result["result"]["content"][0]["text"])

    def test_unreachable_api_is_a_tool_error(self):
        class Down(FakeApi):
            def request_json(self, *args, **kwargs):
                from src.web.mcp_server import AgentApiUnreachable

                raise AgentApiUnreachable("连不上")

        result = self._call(Down(), "search", {"query": "雨"})
        self.assertTrue(result["result"]["isError"])
        self.assertIn("连不上", result["result"]["content"][0]["text"])

    def test_status_resource_keeps_a_short_snapshot(self):
        api = FakeApi()
        api.next_payload = {
            "ok": True,
            "api_version": "1",
            "index_ready": True,
            "dialogue_index_ready": False,
            "capabilities": {"frame_search": True, "chunk_search": False, "export_clip": True},
            "max_batch_queries": 64,
            "max_batch_frame_extract": 16,
            "search_timeout_sec": 90,
            "ffmpeg": {"ffmpeg_path": "C:/ffmpeg/ffmpeg.exe"},
            "indexed_video_paths": ["D:/a.mp4"] * 40,
            "team": {"api_base_url": ""},
        }
        result = handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "videoseek://status"}},
            api,
        )
        self.assertEqual(api.calls[0]["path"], "/api/v1/health")
        body = json.loads(result["result"]["contents"][0]["text"])
        self.assertTrue(body["ready"])
        self.assertTrue(body["frame_search_ready"])
        self.assertFalse(body["chunk_index_ready"])
        self.assertEqual(body["limits"]["batch_search"], 64)
        self.assertEqual(body["limits"]["frames_per_call"], 16)
        self.assertEqual(body["limits"]["timeout_sec"], 90)
        self.assertEqual(body["api_base_url"], api.base_url)
        self.assertNotIn("ffmpeg", body)
        self.assertNotIn("indexed_video_paths", body)

    def test_sync_timeouts_match_accept_not_full_index(self):
        api = FakeApi()
        self._call(api, "sync_library", {"action": "sync"})
        self._call(api, "sync_library", {"action": "add", "library_path": "D:/Videos"})
        self._call(api, "sync_library", {"action": "refresh"})
        self.assertEqual(api.calls[0]["timeout"], 60)
        self.assertEqual(api.calls[1]["timeout"], 180)
        self.assertEqual(api.calls[2]["timeout"], 180)

    def test_timeline_engine_busy_tells_the_model_not_to_retry_blindly(self):
        api = FakeApi()
        api.next_status = 503
        api.next_payload = {"ok": False, "error": {"code": "engine_busy", "message": "timed out"}}
        items = [{"video_path": "D:/a.mp4", "start_sec": 1, "end_sec": 3}]
        result = self._call(api, "export_timeline", {"format": "jianying", "items": items})
        text = result["result"]["content"][0]["text"]
        self.assertTrue(result["result"]["isError"])
        self.assertIn("60", text)
        self.assertIn("manifest", text)

    def test_bool_query_uses_lowercase_true(self):
        captured = {}

        class _Response:
            status = 200

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def _urlopen(request, timeout=0):
            captured["url"] = request.full_url
            return _Response()

        with patch("src.web.mcp_server.urllib.request.urlopen", _urlopen):
            AgentHttpClient("http://127.0.0.1:8765").request_json(
                "GET",
                "/api/v1/videos",
                query={"ready_only": True},
            )
        self.assertIn("ready_only=true", captured["url"])


class InstanceLockTests(unittest.TestCase):
    def test_dead_pid_is_ignored(self):
        from src.app.instance_lock import pid_alive, read_instance_lock

        self.assertTrue(pid_alive(os.getpid()))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "agent_api.dev.lock")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"pid": 424242, "port": 8765, "api_enabled": True}, handle)
            with patch("src.app.instance_lock.instance_lock_path", return_value=path):
                with patch("src.app.instance_lock.pid_alive", return_value=False):
                    self.assertIsNone(read_instance_lock())


class RecoverLocalApiTests(unittest.TestCase):
    def test_running_app_with_api_off_does_not_launch(self):
        client = AgentHttpClient("http://127.0.0.1:9")
        with patch(
            "src.app.instance_lock.read_instance_lock",
            return_value={"pid": 1, "api_enabled": False},
        ):
            with patch("src.web.mcp_server.subprocess.Popen") as popen:
                with patch(
                    "src.web.mcp_server.urllib.request.urlopen",
                    side_effect=urllib.error.URLError("refused"),
                ):
                    with self.assertRaises(AgentApiUnreachable) as caught:
                        client.request_json("GET", "/api/v1/health", timeout=1)
        popen.assert_not_called()
        self.assertIn("本机 Agent API", str(caught.exception))
        self.assertEqual(str(caught.exception), _MSG_API_OFF)

    def test_health_failure_is_not_a_closed_port(self):
        client = AgentHttpClient("http://127.0.0.1:8765")

        class _Response:
            status = 500

            def read(self):
                return b'{"ok": false}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch(
            "src.app.instance_lock.read_instance_lock",
            return_value={"pid": 1, "api_enabled": True},
        ):
            with patch("src.web.mcp_server.urllib.request.urlopen", return_value=_Response()):
                self.assertEqual(recover_local_api(client), _MSG_HEALTH)

    def test_launch_timeout_message(self):
        client = AgentHttpClient("http://127.0.0.1:9")
        with patch("src.app.instance_lock.read_instance_lock", return_value=None):
            with patch("src.web.mcp_server.subprocess.Popen", return_value=unittest.mock.Mock()):
                with patch("src.web.mcp_server._HEALTH_WAIT_SEC", 0):
                    with patch(
                        "src.web.mcp_server.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("refused"),
                    ):
                        self.assertEqual(recover_local_api(client), _MSG_TIMEOUT)

    def test_parallel_callers_launch_once(self):
        calls = []

        def _slow(*_args, **_kwargs):
            calls.append(1)
            time.sleep(0.3)
            return "ready"

        barrier = threading.Barrier(2)
        results = []

        def _worker():
            barrier.wait(timeout=2)
            results.append(recover_local_api(AgentHttpClient("http://127.0.0.1:9")))

        with patch("src.app.instance_lock.read_instance_lock", return_value=None):
            with patch("src.web.mcp_server._launch_and_wait", side_effect=_slow):
                threads = [threading.Thread(target=_worker) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
        self.assertEqual(calls, [1])
        self.assertEqual(results, ["ready", "ready"])


if __name__ == "__main__":
    unittest.main()

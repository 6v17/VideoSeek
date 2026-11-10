import io
import json
import unittest
from unittest.mock import patch

from src.web.mcp_server import AgentHttpClient, cursor_mcp_config, handle_message, serve


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

    def test_status_resource_reads_health(self):
        api = FakeApi()
        api.next_payload = {"ok": True, "index_ready": True}
        result = handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "videoseek://status"}},
            api,
        )
        self.assertEqual(api.calls[0]["path"], "/api/v1/health")
        body = json.loads(result["result"]["contents"][0]["text"])
        self.assertTrue(body["index_ready"])

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


if __name__ == "__main__":
    unittest.main()

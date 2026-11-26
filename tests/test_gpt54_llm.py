import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from unittest.mock import patch

import pytest

from src.services.llm_settings import call_remote_llm, finalize_remote_llm_settings
from src.services.openai_compat_probe import probe_minimal_text_chat, text_chat_generation_options


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-2026-03-05"])
@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh"])
def test_gpt54_parameter_compatibility(model, effort):
    options = text_chat_generation_options(model, token_limit=2048, temperature=0.3, reasoning_effort=effort)
    assert options["max_completion_tokens"] == 2048
    assert "max_tokens" not in options
    assert options["reasoning_effort"] == effort
    assert ("temperature" in options) == (effort == "none")


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "gpt-4o-mini", "local-model"])
def test_other_provider_parameters_are_unchanged(model):
    assert text_chat_generation_options(model, token_limit=500, temperature=0.2) == {
        "max_tokens": 500, "temperature": 0.2,
    }


def test_openai_settings_preserve_explicit_gpt54_selection():
    settings = finalize_remote_llm_settings({
        "provider_mode": "cloud", "provider_preset": "openai",
        "model": "gpt-5.4", "reasoning_effort": "medium",
    })
    assert settings["base_url"] == "https://api.openai.com/v1"
    assert settings["model"] == "gpt-5.4"
    assert settings["reasoning_effort"] == "medium"


def test_probe_uses_gpt54_options():
    with patch("src.services.cancellable_http.urlopen_json_with_stop", return_value={
        "choices": [{"message": {"content": "OK"}}],
    }) as transport:
        assert probe_minimal_text_chat(
            base_url="https://api.openai.com/v1", headers={}, model="gpt-5.4", timeout_sec=5,
        )["ok"]
    payload = json.loads(transport.call_args.args[0].data)
    assert payload["max_completion_tokens"] == 8
    assert payload["reasoning_effort"] == "none"
    assert "max_tokens" not in payload


def test_truncated_model_response_is_not_returned_as_a_draft():
    config = {"understanding": {"remote_llm": {
        "provider_mode": "cloud", "provider_preset": "openai", "model": "gpt-5.4",
    }}}
    with patch("src.services.cancellable_http.urlopen_json_with_stop", return_value={
        "choices": [{"finish_reason": "length", "message": {"content": '{"drafts":['}}],
    }):
        with pytest.raises(RuntimeError, match="truncated"):
            call_remote_llm(system="JSON only", user="test", config=config, attempts=1)


@pytest.mark.parametrize("effort", ["none", "medium"])
def test_real_http_serialization_to_local_fixture(effort):
    """Real urllib transport to a fixture; this does not contact OpenAI."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, payload))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": '{"drafts":[{"id":1,"text":"Dữ liệu mẫu, không phải đầu ra model."}]}',
            }}]}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = {"understanding": {"remote_llm": {
            "provider_mode": "cloud", "provider_preset": "custom", "model": "gpt-5.4",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1", "reasoning_effort": effort,
        }}}
        text = call_remote_llm(system="JSON only", user="Test fixture", config=config, attempts=1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert json.loads(text)["drafts"][0]["id"] == 1
    path, payload = received[0]
    assert path == "/v1/chat/completions"
    assert payload["model"] == "gpt-5.4"
    assert payload["reasoning_effort"] == effort
    assert payload["max_completion_tokens"] == 4096
    assert "max_tokens" not in payload
    assert ("temperature" in payload) == (effort == "none")

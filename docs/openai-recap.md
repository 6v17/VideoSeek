# OpenAI GPT-5.4 for recap narration

VideoSeek can call OpenAI through the same configurable text-LLM client used
for other providers. Its default provider is not evidence of the provider used
by a particular installation.

In the app's text LLM settings select the cloud OpenAI preset, enter the API
key there, and set the model to `gpt-5.4` (not the ChatGPT display label).
The corresponding non-secret configuration is:

```json
{
  "understanding": {
    "remote_llm": {
      "provider_mode": "cloud",
      "provider_preset": "openai",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-5.4",
      "reasoning_effort": "none",
      "timeout_sec": 180,
      "max_tokens": 4096
    }
  }
}
```

This is a partial configuration example, not a replacement for the user's full
config. The API key is stored by the app under `api_keys.openai`; do not commit it.
This client does not read `OPENAI_API_KEY` or load `.env` files. The application
supports `VIDEOSEEK_CONFIG_PATH` to select another config file.

The request goes to `/v1/chat/completions`, preserving the configured model.
For `gpt-5.4` and its dated snapshots the client maps its internal `max_tokens`
budget to the wire field `max_completion_tokens`. With `reasoning_effort=none`
it keeps the stage's temperature. With `low`, `medium`, `high`, or `xhigh` it
omits temperature, as required by GPT-5.4 parameter compatibility. The default
remains `none`; no existing installation's model or reasoning budget is changed
automatically. Advanced configuration may set a higher effort, but stage-level
budgets still apply and also include reasoning tokens. Evaluate output quality,
latency and cost before increasing those budgets.

The connection probe uses a small non-reasoning request. Successful probing
does not prove that a long recap fits its output budget. Truncated generation
responses (`finish_reason=length`) raise an error rather than returning partial
JSON as a completed result; recap callers may still fall back to their drafts.

These compatibility rules cover standard GPT-5.4 and dated snapshots, not every
GPT-5 variant or arbitrary gateway alias. This documentation and offline tests
do not prove that any particular account can access the model or that a live
OpenAI request succeeded.

Official references checked 2026-11-26:

- [GPT-5.4 compatibility and Chat Completions examples](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4)
- [Chat Completions token parameters](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

"""Final narration polish must receive source facts, not only its own draft."""
import json
from unittest.mock import patch

from src.services.recap_vo_pipeline import polish_recap_vo
from src.services.recap_vo_post import recap_vo_polish_user_prompt


def evidence():
    return {
        "ocr": [
            {"start": 10, "end": 12, "speaker": "Mai", "text": "I will return the key."},
            {"start": 60, "end": 62, "speaker": "Other", "text": "Unrelated scene."},
        ],
        "chunks": [
            {"i": 1, "t": [9, 14], "cap": "Mai places the key on the table."},
            {"i": 2, "t": [60, 64], "cap": "Unrelated scene."},
        ],
    }


def clips():
    return [
        {"src_in": 9, "src_out": 14, "tl_in": 0, "tl_out": 5,
         "beat_id": 1, "vo": "Mai keeps the key."},
        {"src_in": 20, "src_out": 25, "tl_in": 5, "tl_out": 10,
         "beat_id": 2, "vo": ""},
    ]


def prompt_payload(prompt):
    return json.loads(prompt[prompt.index("{"):])


def test_polish_prompt_has_matching_source_facts():
    payload = prompt_payload(recap_vo_polish_user_prompt(clips(), pack=evidence()))
    row = payload["clips"][0]
    assert row["source_t"] == [9, 14]
    assert row["asr"][0]["speaker"] == "Mai"
    assert row["asr"][0]["text"] == "I will return the key."
    assert row["caps"][0]["cap"] == "Mai places the key on the table."
    assert "Unrelated scene" not in json.dumps(row)


def test_polish_pipeline_forwards_evidence_to_model():
    with patch("src.services.recap_service.call_remote_llm", return_value='{"captions":[]}') as call:
        polish_recap_vo(clips(), pack=evidence(), config={})
    row = prompt_payload(call.call_args.kwargs["user"])["clips"][0]
    assert row["asr"][0]["text"] == "I will return the key."


def test_polish_prompt_still_accepts_no_evidence_pack():
    row = prompt_payload(recap_vo_polish_user_prompt(clips()))["clips"][0]
    assert row["vo"] == "Mai keeps the key."
    assert "asr" not in row

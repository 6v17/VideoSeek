import logging

import pytest

from src.core import pipeline_profiler as pp


@pytest.fixture(autouse=True)
def _reset_profiler():
    pp.reset_for_tests()
    yield
    pp.reset_for_tests()


def test_profiling_disabled_for_stable_dml(monkeypatch):
    monkeypatch.delenv("VIDEOSEEK_PIPELINE_PROFILE", raising=False)
    monkeypatch.delenv("VIDEOSEEK_INFERENCE_EP", raising=False)

    assert not pp.is_pipeline_profiling_enabled()
    with pp.pipeline_profile_run():
        pp.record_decode(1.0)
        pp.record_preprocess(0.5)
        pp.record_ort(0.25)
    assert pp.snapshot() is None


def test_profiling_enabled_in_cuda_mode(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    assert pp.is_pipeline_profiling_enabled()


def test_profiling_env_override_without_cuda(monkeypatch):
    monkeypatch.delenv("VIDEOSEEK_INFERENCE_EP", raising=False)
    monkeypatch.setenv("VIDEOSEEK_PIPELINE_PROFILE", "1")
    assert pp.is_pipeline_profiling_enabled()


def test_counters_accumulate_within_run(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_PIPELINE_PROFILE", "1")

    with pp.pipeline_profile_run():
        pp.record_decode(2.0, frames=3)
        pp.record_preprocess(1.0, frames=3)
        pp.record_ort(0.75)

    stats = pp.snapshot()
    assert stats is not None
    assert stats["t_decode"] == pytest.approx(2.0)
    assert stats["t_preprocess"] == pytest.approx(1.0)
    assert stats["t_ort"] == pytest.approx(0.75)
    assert stats["frames_decoded"] == 3
    assert stats["frames_encoded"] == 3


def test_log_pipeline_summary_emits_breakdown(monkeypatch, caplog):
    monkeypatch.setenv("VIDEOSEEK_PIPELINE_PROFILE", "1")
    caplog.set_level(logging.INFO)

    with pp.pipeline_profile_run():
        pp.record_decode(4.0, frames=10)
        pp.record_preprocess(1.5, frames=10)
        pp.record_ort(2.0)

    logger = logging.getLogger("test_pipeline_profiler")
    pp.log_pipeline_summary(
        logger,
        log_tag="vid test.mp4",
        wall_pipe_sec=5.0,
        decode_backend="d3d11va",
    )

    assert any("Pipeline profile" in record.message for record in caplog.records)
    line = next(record.message for record in caplog.records if "Pipeline profile" in record.message)
    assert "decode=4.000s" in line
    assert "preprocess=1.500s" in line
    assert "ort=2.000s" in line
    assert "backend=d3d11va" in line

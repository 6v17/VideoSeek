from src.core.inference_providers import (
    ensure_cuda_runtime_dll_paths,
    get_inference_ep_mode,
    is_cuda_inference_mode,
    preferred_gpu_provider_name,
    resolve_ort_providers,
)


def test_default_mode_uses_directml(monkeypatch):
    monkeypatch.delenv("VIDEOSEEK_INFERENCE_EP", raising=False)
    assert get_inference_ep_mode() == "dml"
    assert not is_cuda_inference_mode()
    assert preferred_gpu_provider_name() == "DmlExecutionProvider"
    assert resolve_ort_providers(prefer_gpu=True) == [
        "DmlExecutionProvider",
        "CPUExecutionProvider",
    ]
    assert resolve_ort_providers(prefer_gpu=False) == ["CPUExecutionProvider"]


def test_cuda_mode_uses_cuda_ep(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    assert is_cuda_inference_mode()
    assert preferred_gpu_provider_name() == "CUDAExecutionProvider"
    assert resolve_ort_providers(prefer_gpu=True) == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_ensure_cuda_runtime_dll_paths_is_idempotent(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    first = ensure_cuda_runtime_dll_paths()
    second = ensure_cuda_runtime_dll_paths()
    assert second == []
    assert isinstance(first, list)

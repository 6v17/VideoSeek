import os

import onnxruntime as ort


def build_session_options(prefer_gpu, disable_optimizations=False):
    """ONNX Runtime session tuning.

    DirectML keeps sequential execution and mem_pattern off for stability. Graph optimizations are
    enabled by default unless ``disable_optimizations`` is set.

    When ``prefer_gpu`` is true, ``intra_op_num_threads`` is capped so ORT's CPU-side work does not
    starve FFmpeg frame decoding. Override with env ``VIDEOSEEK_ORT_INTRA_OP_THREADS`` (integer 1–32).
    """
    session_options = ort.SessionOptions()
    if not disable_optimizations:
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    if prefer_gpu:
        session_options.enable_mem_pattern = False
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.inter_op_num_threads = 1
        raw_threads = os.environ.get("VIDEOSEEK_ORT_INTRA_OP_THREADS", "").strip()
        if raw_threads:
            try:
                intra = int(raw_threads)
                intra = max(1, min(32, intra))
            except ValueError:
                cores = os.cpu_count() or 4
                intra = max(1, min(4, cores // 4))
        else:
            cores = os.cpu_count() or 4
            intra = max(1, min(4, cores // 4))
        session_options.intra_op_num_threads = intra
    if disable_optimizations:
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    return session_options


def resolve_embedding_batch_size(config=None):
    runtime_config = dict(config or {})
    try:
        batch_size = int(runtime_config.get("embedding_batch_size", 16))
    except (TypeError, ValueError):
        return 16
    return max(1, batch_size)

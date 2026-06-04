# CUDA 实验室版（NVDEC 零拷贝建索）

**实验性质**：仅适用于自建 `VideoSeek-CUDA` conda 环境 + NVIDIA GPU，不是默认 Release 路径。

## 环境

```powershell
conda create -n VideoSeek-CUDA python=3.10
conda activate VideoSeek-CUDA
pip install -r requirements.txt
pip install -r requirements-cuda-experiment.txt
conda install "faiss=*=*cuda130*"   # Windows：pip 无 faiss-gpu
```

## 运行前

```powershell
$env:VIDEOSEEK_INFERENCE_EP='cuda'
$env:VIDEOSEEK_CUDA_ZERO_COPY='1'    # 默认 cuda 模式下 auto=开
$env:VIDEOSEEK_FULL_GPU_INDEX='1'   # ORT 输出/GPU 向量/FAISS-GPU，auto=开
$env:CUDA_PATH='C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2'  # 可选，消 CuPy 警告
```

PyNvVideoCodec 需要 CUDA 12 运行时（`nvidia-cuda-runtime-cu12`）；应用内 `nvdec_dll_bootstrap` 会自动 `add_dll_directory`，**不必**手动改 PATH。

## 验证

```powershell
python scripts/cuda_zero_copy_smoke_test.py "path\to\short.mp4" --frames 8
```

期望：`gpu_output=True`，`encoded vectors gpu shape=(8, 512)`。

## 链路

```
PyNvVideoCodec(NVDEC→GPU RGB) → retain → CuPy preprocess → ORT CUDA in/out → GPU L2 → 末尾 D2H → FAISS-GPU
```

失败时自动回退 FFmpeg `nvdec_cuda_scale` → CPU。

## 回退

```powershell
$env:VIDEOSEEK_CUDA_ZERO_COPY='0'
$env:VIDEOSEEK_FULL_GPU_INDEX='0'
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `VIDEOSEEK_INFERENCE_EP=cuda` | ONNX Runtime CUDA EP |
| `VIDEOSEEK_CUDA_ZERO_COPY` | NVDEC native + GPU 预处理 |
| `VIDEOSEEK_FULL_GPU_INDEX` | ORT 输出绑 GPU、向量留显存、FAISS-GPU |
| `VIDEOSEEK_DECODE_BACKEND` | `auto` / `nvdec_cuda_native` / `nvdec_cuda_scale` / `cpu` |

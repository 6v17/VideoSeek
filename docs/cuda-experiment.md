# CUDA 实验室版（NVDEC 零拷贝建索）

**实验性质**：本分支默认 CUDA 全链路。需要 NVIDIA GPU + 自建 `VideoSeek-CUDA` conda 环境，不是 Release/DirectML 路径。

## 环境

```powershell
conda create -n VideoSeek-CUDA python=3.10
conda activate VideoSeek-CUDA
powershell -ExecutionPolicy Bypass -File scripts/install_cuda_deps.ps1
```

或手动：

```powershell
pip install -r requirements.txt
pip install rapidocr-onnxruntime==1.4.4 --no-deps
pip uninstall -y onnxruntime
pip install --force-reinstall --no-deps onnxruntime-gpu
```

验证：

```powershell
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# 期望含 CUDAExecutionProvider；若只有 CPU/Azure，说明又被 CPU 版 onnxruntime 盖掉了
```

## 运行前

本分支**默认即为 CUDA 全链路**（无需再手动设 `VIDEOSEEK_INFERENCE_EP`）。若需临时关掉某些段：

```powershell
$env:VIDEOSEEK_INFERENCE_EP='cpu'      # 强制 CPU
$env:VIDEOSEEK_CUDA_ZERO_COPY='0'      # 关闭 NVDEC 零拷贝
$env:VIDEOSEEK_FULL_GPU_INDEX='0'      # 关闭 ORT 输出/GPU 向量留显存
```

可选环境变量（一般不用改，默认 auto=开）：

```powershell
$env:VIDEOSEEK_CUDA_ZERO_COPY='1'
$env:VIDEOSEEK_FULL_GPU_INDEX='1'
$env:CUDA_PATH='C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2'  # 可选，消 CuPy 警告
```

PyNvVideoCodec 需要 CUDA 12 运行时（`nvidia-cuda-runtime-cu12`）；应用内 `nvdec_dll_bootstrap` 会自动 `add_dll_directory`，**不必**手动改 PATH。

## 验证

```powershell
python scripts/cuda_zero_copy_smoke_test.py "path\to\short.mp4" --frames 8
```

期望：`gpu_output=True`，`encoded vectors gpu shape=(8, 512)`。

## 链路

视觉建索：

```
PyNvVideoCodec(NVDEC→GPU RGB) → retain → CuPy preprocess → ORT CUDA in/out → GPU L2 → 末尾 D2H → Lance
```

失败时自动回退 FFmpeg `nvdec_cuda_scale` → CPU。

字幕 OCR（VAD 仍为 CPU）：

```
OpenCV 连续稀疏抽帧（默认，快） → ROI crop → RapidOCR CUDA EP → 字幕 JSON
```

OCR 拼合 batch 走设置项 `subtitle_ocr_batch_size`（默认 4）。不要开 `VIDEOSEEK_OCR_CUDA_DECODE=1`（会每帧起一次 FFmpeg，极慢）。

## 回退

```powershell
$env:VIDEOSEEK_CUDA_ZERO_COPY='0'
$env:VIDEOSEEK_FULL_GPU_INDEX='0'
$env:VIDEOSEEK_OCR_CUDA_DECODE='0'
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `VIDEOSEEK_INFERENCE_EP=cuda` | ONNX Runtime CUDA EP（本分支默认） |
| `VIDEOSEEK_CUDA_ZERO_COPY` | NVDEC native + GPU 预处理 |
| `VIDEOSEEK_FULL_GPU_INDEX` | ORT 输出绑 GPU、向量留显存至末尾 D2H |
| `VIDEOSEEK_OCR_CUDA_DECODE` | 字幕 OCR 稀疏抽帧改用「每帧一次 FFmpeg CUDA」（**默认关**；很慢，仅调试） |
| `VIDEOSEEK_DECODE_BACKEND` | `auto` / `nvdec_cuda_native` / `nvdec_cuda_scale` / `cpu` |

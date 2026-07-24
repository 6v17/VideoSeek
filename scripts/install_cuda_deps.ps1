# CUDA experiment deps (Windows / PowerShell).
# Keeps onnxruntime-gpu; installs RapidOCR without its CPU onnxruntime dependency.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install -r requirements.txt
python -m pip install "rapidocr-onnxruntime==1.4.4" --no-deps
python -m pip uninstall -y onnxruntime 2>$null
python -m pip install --force-reinstall --no-deps onnxruntime-gpu

python -c "import onnxruntime as ort; print(ort.get_available_providers())"
python -c "import rapidocr_onnxruntime; print('rapidocr_ok')"

import importlib.util as u

pkgs = ["onnxruntime", "cv2", "numpy", "cupy", "PyNvVideoCodec"]
for p in pkgs:
    print(p, "YES" if u.find_spec(p) else "NO")

try:
    import onnxruntime as ort

    print("ort providers:", ort.get_available_providers())
except Exception as exc:
    print("ort error:", exc)

try:
    import PyNvVideoCodec as nvc

    print("PyNvVideoCodec version:", getattr(nvc, "__version__", "?"))
    print("PyNvVideoCodec attrs sample:", [a for a in dir(nvc) if "Decoder" in a or "Output" in a][:12])
except Exception as exc:
    print("PyNvVideoCodec error:", exc)

try:
    import cupy as cp

    print("cupy version:", cp.__version__)
    print("cupy device:", cp.cuda.runtime.getDeviceCount())
except Exception as exc:
    print("cupy error:", exc)

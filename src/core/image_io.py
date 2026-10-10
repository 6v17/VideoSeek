"""Load query/upload images (JPEG/PNG/HEIC/WEBP, etc.) for OpenCV and Qt."""

from __future__ import annotations

import os

import cv2
import numpy as np

from src.app.logging_utils import get_logger

logger = get_logger("image_io")

_HEIF_REGISTERED = False

_HEIC_EXTENSIONS = {".heic", ".heif", ".heics", ".heifs"}
_CONVERT_ON_LOAD_EXTENSIONS = _HEIC_EXTENSIONS | {".avif"}


def _register_heif_opener() -> None:
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    _HEIF_REGISTERED = True


def _load_image_bgr_pillow(path: str):
    try:
        from PIL import Image
    except ImportError:
        return None
    _register_heif_opener()
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"))
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/core/image_io.py:load_image_bgr_pillow")
        return None
    if rgb.size == 0:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_image_bgr(path: str):
    """Return BGR uint8 ndarray, or None if the file cannot be decoded."""
    if not path or not os.path.isfile(path):
        return None
    try:
        buffer = np.fromfile(path, dtype=np.uint8)
        if buffer.size > 0:
            image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if image is not None:
                return image
    except Exception as exc:
        logger.debug("OpenCV failed to load image %s: %s", path, exc)
    return _load_image_bgr_pillow(path)


def normalize_image_upload(path: str) -> str:
    """Convert formats Qt/OpenCV cannot use directly (e.g. HEIC) to JPEG beside the upload."""
    if not path or not os.path.isfile(path):
        return path
    ext = os.path.splitext(path)[1].lower()
    if ext not in _CONVERT_ON_LOAD_EXTENSIONS:
        return path
    image = load_image_bgr(path)
    if image is None:
        raise ValueError(
            "Could not decode HEIC/HEIF/AVIF image. Install pillow-heif, or send JPG/PNG from the phone."
        )
    jpg_path = f"{os.path.splitext(path)[0]}.jpg"
    try:
        ok = cv2.imwrite(jpg_path, image)
    except Exception as exc:
        logger.warning("Failed to normalize uploaded image %s: %s", path, exc)
        return path
    if not ok:
        return path
    if os.path.abspath(jpg_path) != os.path.abspath(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Failed to remove original upload %s: %s", path, exc)
    return jpg_path


def encode_preview_jpeg(path: str, *, quality: int = 85) -> bytes:
    """JPEG bytes for mobile-browser preview (HEIC and other formats)."""
    image = load_image_bgr(path)
    if image is None:
        raise ValueError("Could not decode image for preview.")
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("Could not encode preview JPEG.")
    return buffer.tobytes()


def pixmap_from_image_path(path: str, width: int, height: int):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    image = load_image_bgr(path)
    if image is None:
        return QPixmap()
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    h, w, channels = rgb.shape
    qimage = QImage(rgb.data, w, h, channels * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage).scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

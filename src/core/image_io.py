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


def extended_length_path(path: str) -> str:
    """Open past the legacy 260-character limit on Windows. Other platforms are unchanged."""
    text = os.path.abspath(str(path or ""))
    if os.name != "nt" or not text:
        return text
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    if len(text) == 2 and text[1] == ":":
        text += "\\"
    return "\\\\?\\" + text


def from_extended_length_path(path: str) -> str:
    text = str(path or "")
    if os.name != "nt":
        return text
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def existing_file_path(path: str) -> str:
    """Return a path ``isfile`` accepts, including a Windows extended path when needed."""
    text = str(path or "").strip()
    if not text:
        return ""
    if os.path.isfile(text):
        return text
    extended = extended_length_path(text)
    if extended and extended != text and os.path.isfile(extended):
        return extended
    return ""


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


def image_pixel_size(path: str) -> tuple[int, int] | None:
    """Read width and height from the file header. Does not decode the pixels."""
    target = existing_file_path(path)
    if not target:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    _register_heif_opener()
    try:
        with Image.open(target) as image:
            width, height = image.size
    except Exception:
        return None
    if int(width) <= 0 or int(height) <= 0:
        return None
    return int(width), int(height)


def load_image_bgr(path: str):
    """Return BGR uint8 ndarray, or None if the file cannot be decoded."""
    target = existing_file_path(path)
    if not target:
        return None
    try:
        buffer = np.fromfile(target, dtype=np.uint8)
        if buffer.size > 0:
            image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if image is not None:
                return image
    except Exception as exc:
        logger.debug("OpenCV failed to load image %s: %s", path, exc)
    return _load_image_bgr_pillow(target)


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


def qimage_from_image_path(path: str, max_edge: int):
    """Scaled RGB ``QImage`` for gallery thumbs and preview. Empty if the file cannot be decoded."""
    from PySide6.QtGui import QImage

    image = load_image_bgr(path)
    if image is None:
        return QImage()
    height, width = int(image.shape[0]), int(image.shape[1])
    limit = max(1, int(max_edge))
    long_side = max(height, width)
    if long_side > limit:
        scale = float(limit) / float(long_side)
        image = cv2.resize(
            image,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    rows, cols, channels = rgb.shape
    qimage = QImage(rgb.data, cols, rows, channels * cols, QImage.Format.Format_RGB888)
    return qimage.copy()


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

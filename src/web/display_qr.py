import os
import tempfile

from PySide6.QtGui import QPixmap


def generate_qr_image(url):
    try:
        import qrcode
    except ImportError:
        return None

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def build_qr_pixmap(url):
    image = generate_qr_image(url)
    if image is None:
        return None

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, "videoseek_mobile_qr.png")
    image.save(file_path)
    pixmap = QPixmap(file_path)
    return pixmap if not pixmap.isNull() else None

import webbrowser

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from src.app.logging_utils import get_logger
from src.services.remote_html_assets import download_url_to_temp_file, is_probably_image_url

logger = get_logger("html_links")


def open_html_link(url):
    url_text = str(url.toString() if isinstance(url, QUrl) else url or "").strip()
    if not url_text or url_text.startswith("#"):
        return

    if is_probably_image_url(url_text):
        try:
            temp_path = download_url_to_temp_file(url_text)
        except Exception as exc:
            logger.warning("Failed to open linked image %s: %s", url_text, exc)
            temp_path = ""
        if temp_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(temp_path))
            return

    webbrowser.open(url_text)

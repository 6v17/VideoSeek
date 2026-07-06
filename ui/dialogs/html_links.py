import webbrowser

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

from src.app.logging_utils import get_logger
from src.services.remote_html_assets import download_url_to_temp_file, is_probably_image_url

logger = get_logger("html_links")

_EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto", "ftp"})


def is_external_link(url) -> bool:
    parsed = url if isinstance(url, QUrl) else QUrl(str(url or ""))
    url_text = parsed.toString().strip()
    if not url_text or url_text.startswith("#"):
        return False

    scheme = parsed.scheme().lower()
    if scheme in _EXTERNAL_SCHEMES:
        return True
    if url_text.startswith("//"):
        return True

    lowered = url_text.lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("mailto:")


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


class ExternalLinkTextBrowser(QTextBrowser):
    """Rich-text view for dialogs; links open externally without in-widget navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # openLinks=False stops QTextBrowser from calling setSource() on click (Qt 6).
        # openExternalLinks alone is not enough and still clears http(s) content.
        self.setOpenLinks(False)
        self.anchorClicked.connect(open_html_link)

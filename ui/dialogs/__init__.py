"""Dialog widgets; split from the former monolithic ui/dialogs.py."""
from .about import AboutDialog
from .app_message import AppMessageDialog
from .common import SortableTableWidgetItem, dialog_palette
from .mobile_bridge import MobileBridgeDialog
from .model_download import ModelDownloadDialog
from .donate import DonateDialog
from .notice import NoticeDialog
from .resource_table import ResourceTableDialog
from .sampling_rules import SamplingRulesDialog

__all__ = [
    "AboutDialog",
    "AppMessageDialog",
    "MobileBridgeDialog",
    "ModelDownloadDialog",
    "DonateDialog",
    "NoticeDialog",
    "ResourceTableDialog",
    "SamplingRulesDialog",
    "SortableTableWidgetItem",
    "dialog_palette",
]

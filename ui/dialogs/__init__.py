"""Dialog widgets; split from the former monolithic ui/dialogs.py."""
from .about import AboutDialog
from .app_message import AppMessageDialog
from .busy_progress import AppBusyDialog
from .common import SortableTableWidgetItem, dialog_palette
from .mobile_bridge import MobileBridgeDialog
from .model_download import ModelDownloadDialog
from .donate import DonateDialog
from .notice import NoticeDialog
from .resource_table import ResourceTableDialog
from .sampling_rules import SamplingRulesDialog
from .shell import VSDialogShell

__all__ = [
    "AboutDialog",
    "AppBusyDialog",
    "AppMessageDialog",
    "MobileBridgeDialog",
    "ModelDownloadDialog",
    "DonateDialog",
    "NoticeDialog",
    "ResourceTableDialog",
    "SamplingRulesDialog",
    "SortableTableWidgetItem",
    "VSDialogShell",
    "dialog_palette",
]

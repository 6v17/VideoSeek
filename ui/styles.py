STYLE_TEMPLATE = """
QMainWindow {
    background: __WINDOW__;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QWidget {
    color: __TEXT__;
    background: transparent;
}
#AppRoot, #ContentArea {
    background: __WINDOW__;
}
#NavSidebar, #PageHeader, #PanelCard {
    background: __SIDEBAR__;
    border: 1px solid __LINE__;
    border-radius: 18px;
}
#PageHeader, #PanelCard {
    background: __PANEL__;
}
#BrandTitle {
    color: __HEADLINE__;
    font-size: 28px;
    font-weight: 700;
}
#BrandSubtitle, #HeroBody, #PageSubtitle, #CardHint, #StatusLabel {
    color: __MUTED__;
}
#StatusLabel {
    font-size: 12px;
}
#HeroCard {
    background: __HERO__;
    border: 1px solid __HERO_LINE__;
    border-radius: 16px;
}
#HeroTag {
    color: __ACCENT__;
    font-size: 11px;
    font-weight: 700;
}
#HeroTitle, #PageTitle, #CardTitle {
    color: __HEADLINE__;
    font-weight: 700;
}
#PageTitle {
    font-size: 24px;
}
#CardTitle {
    font-size: 16px;
}
QPushButton {
    border-radius: 10px;
    border: 1px solid __LINE__;
    padding: 8px 12px;
    background: __BUTTON_SOFT__;
    color: __HEADLINE__;
}
QPushButton:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#PrimaryButton {
    background: __ACCENT__;
    border-color: __ACCENT__;
    color: white;
}
#PrimaryButton:hover {
    background: __ACCENT_HOVER__;
}
#UpdateButton {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __ACCENT__;
    font-weight: 700;
}
#UpdateButton:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchButton {
    background: __SUCCESS__;
    border-color: __SUCCESS__;
    color: white;
    font-weight: 700;
}
#SearchButton:hover {
    background: __SUCCESS_HOVER__;
}
#GhostButton {
    background: transparent;
}
#NavButton {
    text-align: left;
    padding-left: 14px;
    font-weight: 600;
}
#NavButton:checked {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __HEADLINE__;
}
QLineEdit, QSpinBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 10px;
    padding: 8px 10px;
    color: __TEXT__;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid __ACCENT__;
}
#ImageDropZone, #PreviewPlaceholder {
    background: __FIELD__;
    border: 1px dashed __LINE_STRONG__;
    border-radius: 14px;
    padding: 12px;
}
#PreviewPlaceholder {
    min-height: 260px;
}
#VideoContainer {
    background: __VIDEO_BG__;
    border: 1px solid __LINE__;
    border-radius: 16px;
}
#LibTable, #ResultTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 14px;
    gridline-color: __LINE__;
}
QHeaderView::section {
    background: transparent;
    border: none;
    color: __MUTED__;
    padding: 8px;
    font-weight: 700;
}
QTableCornerButton::section {
    background: transparent;
    border: none;
}
QProgressBar {
    background: __FIELD__;
    border: none;
    border-radius: 4px;
    height: 8px;
}
QProgressBar::chunk {
    background: __ACCENT__;
    border-radius: 4px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: __SCROLL__;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: __SCROLL__;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    width: 0;
    height: 0;
}
QPushButton[class="TableBtn"], QPushButton[class="TableLocateBtn"], QPushButton[class="TableDeleteBtn"] {
    background: transparent;
    border: 1px solid transparent;
    padding: 6px 8px;
    border-radius: 8px;
}
QPushButton[class="TableBtn"] {
    color: __ACCENT__;
}
QPushButton[class="TableBtn"]:hover {
    background: __ACCENT_SOFT__;
}
QPushButton[class="TableLocateBtn"] {
    color: __SUCCESS__;
}
QPushButton[class="TableLocateBtn"]:hover {
    background: __SUCCESS_SOFT__;
}
QPushButton[class="TableDeleteBtn"] {
    color: __DANGER__;
}
QPushButton[class="TableDeleteBtn"]:hover {
    background: __DANGER_SOFT__;
}
QToolTip, QMessageBox, QDialog {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
}
"""


def build_style(colors):
    style = STYLE_TEMPLATE
    for key, value in colors.items():
        style = style.replace(f"__{key}__", value)
    return style


DARK_STYLE = build_style({
    "WINDOW": "#0b1220",
    "TEXT": "#d7deea",
    "HEADLINE": "#f5f8ff",
    "MUTED": "#91a0ba",
    "ACCENT": "#4e8cff",
    "ACCENT_HOVER": "#6ba0ff",
    "ACCENT_SOFT": "#1d3158",
    "SUCCESS": "#2ec27e",
    "SUCCESS_HOVER": "#45d690",
    "SUCCESS_SOFT": "#173d30",
    "DANGER": "#ff6b6b",
    "DANGER_SOFT": "#432326",
    "SIDEBAR": "#121a2a",
    "PANEL": "#172235",
    "FIELD": "#0f1a2b",
    "HERO": "#1a2a45",
    "HERO_LINE": "#294267",
    "LINE": "#283752",
    "LINE_STRONG": "#40557f",
    "TRACK": "#22314a",
    "SCROLL": "#41567c",
    "BUTTON_SOFT": "#1b2940",
    "BUTTON_SOFT_HOVER": "#24385b",
    "VIDEO_BG": "#060c16",
})

LIGHT_STYLE = build_style({
    "WINDOW": "#f3f6fb",
    "TEXT": "#223047",
    "HEADLINE": "#121826",
    "MUTED": "#65758b",
    "ACCENT": "#2f6df6",
    "ACCENT_HOVER": "#4a82fb",
    "ACCENT_SOFT": "#dfeaff",
    "SUCCESS": "#198754",
    "SUCCESS_HOVER": "#28a068",
    "SUCCESS_SOFT": "#def4e8",
    "DANGER": "#d9534f",
    "DANGER_SOFT": "#fbe2e1",
    "SIDEBAR": "#eaf0f9",
    "PANEL": "#ffffff",
    "FIELD": "#f7f9fd",
    "HERO": "#dfe9ff",
    "HERO_LINE": "#c6d8ff",
    "LINE": "#d5ddea",
    "LINE_STRONG": "#afbed8",
    "TRACK": "#dbe3ef",
    "SCROLL": "#afbdd3",
    "BUTTON_SOFT": "#f6f8fc",
    "BUTTON_SOFT_HOVER": "#e7eef9",
    "VIDEO_BG": "#e3ebf8",
})

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
/* Opaque menus: global QWidget transparency otherwise bleeds into QMenu on
   Windows and can cause doubled / ghosted text on line-edit context menus. */
QMenu {
    background-color: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 10px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px 6px 12px;
    background-color: __PANEL__;
    color: __HEADLINE__;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: __ACCENT_SOFT__;
    color: __HEADLINE__;
}
QMenu::item:disabled {
    color: __MUTED__;
    background-color: __PANEL__;
}
QMenu::separator {
    height: 1px;
    margin: 4px 10px;
    background: __LINE__;
}
#AppRoot, #ContentArea {
    background: __WINDOW__;
}
#NavSidebar {
    background: __SIDEBAR__;
    border: none;
    border-right: 1px solid __LINE__;
    border-radius: 0px;
}
#PageHeader, #PanelCard, #SubPanelCard {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 10px;
}
#NoticeCard {
    background: __NOTICE_BG__;
    border: 1px solid __NOTICE_LINE__;
    border-radius: 10px;
}
#NoticeUpdateHint {
    color: __ACCENT__;
    font-size: 12px;
    font-weight: 600;
    padding: 0;
}
/* Runtime / indexing strip: info tone uses accent-soft so it reads as a highlight strip; ``bannerTone=warn`` when resources missing */
#RuntimeBanner {
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT__;
    border-radius: 8px;
}
#RuntimeBanner #RuntimeBannerText {
    color: __TEXT__;
    font-size: 12px;
    font-weight: 600;
}
#RuntimeBanner[bannerTone="warn"] {
    background: __WARN_SOFT__;
    border: 1px solid __WARN__;
    border-radius: 8px;
}
#RuntimeBanner[bannerTone="warn"] #RuntimeBannerText {
    color: __WARN__;
    font-size: 12px;
    font-weight: 700;
}
#NoticeTitle {
    color: __NOTICE_TEXT__;
    font-size: 14px;
    font-weight: 800;
}
#NoticeBody {
    color: __NOTICE_TEXT__;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.5em;
}
#SettingsSectionHeader {
    background: __FIELD__;
    border-bottom: 1px solid __LINE__;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
#SettingsSectionHeader #CardTitle {
    font-size: 14px;
    font-weight: 700;
    color: __HEADLINE__;
}
#BrandTitle {
    color: __HEADLINE__;
    font-size: 22px;
    font-weight: 700;
}
#BrandSubtitle, #HeroBody, #PageSubtitle, #CardHint {
    color: __MUTED__;
}
#CardHint {
    line-height: 1.45em;
}
QRadioButton {
    color: __HEADLINE__;
    spacing: 10px;
    background: transparent;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid __LINE_STRONG__;
    background: __FIELD__;
}
QRadioButton::indicator:unchecked:hover {
    border-color: __ACCENT__;
    background: __TRACK__;
}
QRadioButton::indicator:checked {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid __ACCENT_HOVER__;
    background-color: __ACCENT__;
}
QRadioButton::indicator:checked:hover {
    border: 2px solid __ACCENT__;
    background-color: __ACCENT_HOVER__;
}
QRadioButton:disabled {
    color: __MUTED__;
}
QRadioButton::indicator:disabled {
    border-color: __LINE__;
    background: __FIELD__;
}
QCheckBox {
    color: __HEADLINE__;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator,
QTableView::indicator,
QTreeView::indicator,
QListView::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid __LINE_STRONG__;
    background: __FIELD__;
}
QCheckBox::indicator:unchecked:hover,
QTableView::indicator:unchecked:hover,
QTreeView::indicator:unchecked:hover,
QListView::indicator:unchecked:hover {
    border-color: __ACCENT__;
    background: __TRACK__;
}
QCheckBox::indicator:checked,
QTableView::indicator:checked,
QTreeView::indicator:checked,
QListView::indicator:checked {
    border: 1px solid __ACCENT_HOVER__;
    background: __ACCENT__;
    image: url("__CHECK_ICON__");
}
QCheckBox::indicator:checked:hover,
QTableView::indicator:checked:hover,
QTreeView::indicator:checked:hover,
QListView::indicator:checked:hover {
    border-color: __ACCENT__;
    background: __ACCENT_HOVER__;
}
QCheckBox::indicator:indeterminate,
QTableView::indicator:indeterminate,
QTreeView::indicator:indeterminate,
QListView::indicator:indeterminate {
    border: 1px solid __ACCENT_HOVER__;
    background: __ACCENT__;
    image: url("__CHECK_PARTIAL_ICON__");
}
QCheckBox::indicator:disabled,
QTableView::indicator:disabled,
QTreeView::indicator:disabled,
QListView::indicator:disabled {
    border-color: __LINE__;
    background: __BUTTON_SOFT__;
    image: none;
}
QCheckBox:disabled {
    color: __MUTED__;
}
#LibraryLibCheck::indicator {
    width: 16px;
    height: 16px;
}
#StatusHint {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    padding: 0;
}
#StatusHint[state="ok"] {
    color: __SUCCESS__;
}
#StatusHint[state="warn"] {
    color: __WARN__;
}
#StatusHint[state="neutral"] {
    color: __MUTED__;
}
#StatusLabel {
    color: __HEADLINE__;
    font-size: 12px;
    font-weight: 600;
    background: __ACCENT_SOFT__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    padding: 8px 12px;
    line-height: 1.35em;
    min-height: 18px;
}
#HeroCard {
    background: __HERO__;
    border: 1px solid __HERO_LINE__;
    border-radius: 8px;
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
    font-size: 20px;
}
#PageTitleBadge {
    color: __WARN__;
    background: __WARN_SOFT__;
    border: 1px solid __WARN__;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 700;
    min-height: 22px;
}
#CardTitle {
    font-size: 16px;
}
#UnderstandingChunkTimeLabel {
    color: __SUCCESS__;
    font-size: 14px;
    font-weight: 700;
    padding: 2px 0 4px 0;
}
QPushButton {
    border-radius: 7px;
    border: 1px solid __LINE__;
    padding: 7px 12px;
    background: __BUTTON_SOFT__;
    color: __HEADLINE__;
}
QPushButton:hover {
    background: __BUTTON_SOFT_HOVER__;
}
QPushButton:pressed {
    background: __TRACK__;
    border-color: __LINE_STRONG__;
    padding-top: 9px;
    padding-bottom: 7px;
}
QPushButton:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: __FIELD__;
}
#PrimaryButton {
    background: __ACCENT__;
    border-color: __ACCENT__;
    color: __INVERSE_TEXT__;
}
#PrimaryButton:hover {
    background: __ACCENT_HOVER__;
}
#PrimaryButton:pressed {
    background: __ACCENT__;
    border-color: __LINE_STRONG__;
}
#PrimaryButton:disabled {
    background: __FIELD__;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
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
#UpdateButton:pressed {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#WarningButton {
    background: __WARN_SOFT__;
    border-color: __WARN__;
    color: __WARN__;
    font-weight: 700;
}
#WarningButton:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchButton {
    background: __SUCCESS__;
    border-color: __SUCCESS__;
    color: __INVERSE_TEXT__;
    font-weight: 700;
}
#SearchButton:hover {
    background: __SUCCESS_HOVER__;
}
#SearchButton:pressed {
    background: __SUCCESS__;
    border-color: __LINE_STRONG__;
}
#MobileBridgeToggle {
    min-width: 52px;
    max-width: 52px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border-radius: 15px;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __MUTED__;
    font-weight: 700;
    text-align: center;
}
#MobileBridgeToggle[bridgeState="off"] {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    color: __MUTED__;
}
#MobileBridgeToggle[bridgeState="on"] {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
}
#MobileBridgeToggle:hover {
    border-color: currentColor;
    background: __BUTTON_SOFT_HOVER__;
}
#MobileBridgeToggle[bridgeState="on"]:hover {
    background: __SUCCESS_SOFT__;
}
#MobileBridgeToggle[bridgeState="off"]:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchPrecisionToggle {
    min-width: 52px;
    max-width: 52px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border-radius: 15px;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __MUTED__;
    font-weight: 700;
    text-align: center;
}
#SearchPrecisionToggle[precisionState="off"] {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    color: __MUTED__;
}
#SearchPrecisionToggle[precisionState="on"] {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
}
#SearchPrecisionToggle:hover {
    border-color: currentColor;
    background: __BUTTON_SOFT_HOVER__;
}
#SearchPrecisionToggle[precisionState="on"]:hover {
    background: __SUCCESS_SOFT__;
}
#SearchPrecisionToggle[precisionState="off"]:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchPrecisionToggle:disabled {
    opacity: 0.45;
}
#MobileBridgeQrButton {
    min-width: 56px;
    max-width: 56px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT_HOVER__;
    color: __ACCENT__;
    font-weight: 700;
    text-align: center;
}
#MobileBridgeQrButton[qrState="hidden"] {
    background: transparent;
    border: none;
    color: transparent;
    padding: 0;
}
#MobileBridgeQrButton[qrState="hidden"]:hover {
    background: transparent;
    border: none;
}
#MobileBridgeQrButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __ACCENT__;
}
#MobileBridgeQrButton:disabled {
    background: __FIELD__;
    border: 1px solid __LINE__;
    color: __MUTED__;
}
#LinkUtilityButton {
    background: __ACCENT_SOFT__;
    border-color: __LINE_STRONG__;
    color: __HEADLINE__;
    font-weight: 600;
}
#LinkUtilityButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __ACCENT__;
}
#GhostButton {
    background: transparent;
    border-color: __LINE__;
}
#GhostButton:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#GhostButton:pressed {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE__;
}
#PresetChipButton {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __HEADLINE__;
    font-weight: 600;
    font-size: 12px;
    padding: 0 10px;
    min-height: 22px;
    max-height: 24px;
}
#PresetChipButton:hover {
    background: __ACCENT__;
    color: __INVERSE_TEXT__;
}
#SearchPresetsTrack {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 6px;
}
#SearchPresetsScroll {
    background: transparent;
    border: none;
}
#SearchPresetsViewport {
    background: transparent;
}
#SearchPresetsHost {
    background: transparent;
}
#SearchPresetsScroll QScrollBar:horizontal {
    height: 0px;
    background: transparent;
    margin: 0 2px;
}
#SearchPresetsScroll QScrollBar::handle:horizontal {
    background: transparent;
    min-width: 0px;
}
#SearchPresetsScroll[trackHover="true"] QScrollBar:horizontal {
    height: 4px;
}
#SearchPresetsScroll[trackHover="true"] QScrollBar::handle:horizontal {
    background: __SCROLL__;
    border-radius: 2px;
    min-width: 28px;
    margin: 0 1px;
}
#SearchPresetsScroll QScrollBar::add-line, #SearchPresetsScroll QScrollBar::sub-line {
    width: 0;
    height: 0;
    border: none;
}
#PresetChip {
    background: transparent;
    border: 1px solid __LINE_STRONG__;
    border-radius: 999px;
}
#PresetChip:hover {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#PresetChipLabel {
    color: __HEADLINE__;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
#PresetTrackEmpty {
    color: __MUTED__;
    font-size: 12px;
    background: transparent;
}
#PresetManageButton {
    background: transparent;
    color: __ACCENT__;
    border: 1px solid __ACCENT__;
    font-weight: 600;
}
#PresetManageButton:hover {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT_HOVER__;
    color: __ACCENT_HOVER__;
}
#PresetManageButton:pressed {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#SearchResultsActions {
    background: transparent;
}
#SearchResultsPager {
    background: transparent;
}
QPushButton#SearchResultsPagerButton {
    background-color: transparent;
    border: 1px solid __ACCENT__;
    border-radius: 6px;
    color: __ACCENT__;
    font-weight: 600;
    font-size: 11px;
    padding: 0 8px;
    min-height: 22px;
    max-height: 24px;
}
QPushButton#SearchResultsPagerButton:hover:enabled {
    background-color: __ACCENT_SOFT__;
    border-color: __ACCENT_HOVER__;
    color: __ACCENT_HOVER__;
}
QPushButton#SearchResultsPagerButton:pressed:enabled {
    background-color: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    padding-top: 1px;
}
QPushButton#SearchResultsPagerButton:disabled {
    background-color: transparent;
    border-color: __ACCENT__;
    color: __MUTED__;
    font-weight: 600;
}
#SearchResultsPagerInfo {
    background-color: transparent;
    border: 1px solid __ACCENT__;
    border-radius: 6px;
    padding: 0 10px;
    min-height: 22px;
    max-height: 24px;
    color: __HEADLINE__;
    font-weight: 600;
    font-size: 11px;
}
#PresetImageThumb {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#PresetImageThumb[compact="true"] {
    border-radius: 6px;
}
#PresetImageThumb[selected="true"] {
    background: __ACCENT_SOFT__;
    border: 2px solid __ACCENT__;
}
#PresetImageThumb[compact="true"][selected="true"] {
    border-width: 1px;
}
#PresetImagePreview {
    background: transparent;
    border: none;
}
#AccentGhostButton {
    background: transparent;
    border-color: __ACCENT__;
    color: __ACCENT__;
    font-weight: 700;
}
#AccentGhostButton:hover {
    background: __ACCENT_SOFT__;
}
#AccentGhostButton:pressed {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#AccentGhostButton:disabled {
    background: transparent;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#SuccessGhostButton {
    background: transparent;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
    font-weight: 700;
}
#SuccessGhostButton:hover {
    background: __SUCCESS_SOFT__;
}
#SuccessGhostButton:pressed {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
}
#SuccessGhostButton:disabled {
    background: transparent;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#DangerGhostButton {
    background: transparent;
    border-color: __DANGER__;
    color: __DANGER__;
    font-weight: 700;
}
#DangerGhostButton:hover {
    background: __DANGER_SOFT__;
}
#DangerGhostButton:pressed {
    background: __DANGER_SOFT__;
    border-color: __DANGER__;
}
#DangerGhostButton:disabled {
    background: transparent;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#ToolbarDivider {
    color: __LINE__;
    background: __LINE__;
    min-width: 1px;
    max-width: 1px;
    margin: 6px 2px;
}
#NavButton {
    text-align: left;
    padding: 8px 12px 8px 14px;
    font-weight: 600;
    border-radius: 6px;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    background: transparent;
    color: __HEADLINE__;
}
#NavButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
}
#NavButton:pressed {
    background: __TRACK__;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    padding-top: 9px;
    padding-bottom: 7px;
}
#NavButton:checked {
    background: __ACCENT_SOFT__;
    border: 1px solid transparent;
    border-left: 3px solid __ACCENT__;
    color: __HEADLINE__;
}
#NavButton:checked:hover {
    background: __ACCENT_SOFT__;
    border-left: 3px solid __ACCENT_HOVER__;
}
/* Sidebar bottom row + link-page file/cache utilities: visible on light panels (avoid four identical AccentGhost). */
#SidebarFooterButton, #NeutralToolButton {
    border-radius: 6px;
    border: 1px solid __LINE__;
    background: transparent;
    color: __HEADLINE__;
    padding: 7px 12px;
    font-weight: 600;
}
#SidebarFooterButton:hover, #NeutralToolButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE__;
}
#SidebarFooterButton:pressed, #NeutralToolButton:pressed {
    background: __TRACK__;
    border-color: __LINE__;
    padding-top: 8px;
    padding-bottom: 6px;
}
#SidebarFooterButton:disabled, #NeutralToolButton:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: __FIELD__;
    font-weight: 600;
}
#SidebarFooterGhost {
    border-radius: 6px;
    border: 1px solid __LINE__;
    background: transparent;
    color: __HEADLINE__;
    padding: 7px 12px;
    font-weight: 600;
}
#SidebarFooterGhost:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE__;
}
#SidebarFooterGhost:pressed {
    background: __TRACK__;
    border-color: __LINE__;
    padding-top: 8px;
    padding-bottom: 6px;
}
#SidebarFooterGhost:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: transparent;
    font-weight: 600;
}
#SidebarIconButton {
    border-radius: 6px;
    border: 1px solid __LINE__;
    background: transparent;
    color: __HEADLINE__;
    font-weight: 700;
    padding: 0px;
}
#SidebarIconButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE__;
}
#SidebarIconButton:pressed {
    background: __TRACK__;
    border-color: __LINE__;
}
#SidebarDonateButton {
    border-radius: 6px;
    border: 1px solid __LINE__;
    background: transparent;
    color: #e81123;
    font-weight: 700;
    padding: 0px;
}
#SidebarDonateButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: #e81123;
    color: #ff4d4f;
}
#SidebarDonateButton:pressed {
    background: __BUTTON_SOFT__;
    border-color: #e81123;
    color: #c50f1f;
}
#DonateImageLabel {
    min-height: 380px;
    padding: 8px 0;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    padding: 7px 10px;
    color: __TEXT__;
}
QTextEdit#SearchInput {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    padding: 8px 10px;
    color: __TEXT__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
QTextEdit#SearchInput:focus {
    border: 1px solid __ACCENT__;
}
#SearchModeSelect {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    /* Keep padding modest; fixed widget height must leave room for both border edges. */
    padding: 2px 8px;
    min-height: 22px;
}
#SearchModeSelect QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
    outline: 0;
}
#SearchableIdComboPopup {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 10px;
}
#SearchableIdComboFilter {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 6px 8px;
}
#SearchableIdComboView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    outline: 0;
}
#SearchableIdComboView::item {
    padding: 6px 8px;
    min-height: 28px;
}
#SearchableIdComboView::item:selected {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid __ACCENT__;
}
QComboBox QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
    outline: 0;
}
QLabel[settingLabel="true"] {
    color: __HEADLINE__;
    font-weight: 600;
    line-height: 1.35em;
}
#SubPanelCard QLabel[settingLabel="true"] {
    padding-top: 4px;
    font-size: 13px;
}
QLabel[settingLabel="true"][detailActive="true"] {
    color: __ACCENT__;
}
#SettingHintButton {
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    max-height: 18px;
    border: 1px solid __LINE__;
    border-radius: 6px;
    color: __MUTED__;
    background: __FIELD__;
    font-weight: 700;
    font-size: 11px;
}
#SettingHintButton:hover {
    border-color: __ACCENT__;
    color: __ACCENT__;
    background: __ACCENT_SOFT__;
}
QSpinBox[settingField="true"], QDoubleSpinBox[settingField="true"], QComboBox[settingField="true"], QLineEdit[settingField="true"] {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 32px;
    color: __HEADLINE__;
}
QSpinBox[settingField="true"]:hover, QDoubleSpinBox[settingField="true"]:hover, QComboBox[settingField="true"]:hover, QLineEdit[settingField="true"]:hover {
    border-color: __LINE_STRONG__;
    background: __PANEL__;
}
QSpinBox[settingField="true"]:focus, QDoubleSpinBox[settingField="true"]:focus, QComboBox[settingField="true"]:focus, QLineEdit[settingField="true"]:focus {
    border-color: __ACCENT__;
    background: __PANEL__;
}
QComboBox[settingField="true"]::drop-down {
    border: none;
    width: 24px;
}
QComboBox[settingField="true"] QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
QComboBox[settingField="true"] QAbstractItemView::item {
    min-height: 28px;
    padding: 4px 8px;
    border-radius: 4px;
}
QComboBox[settingField="true"] QAbstractItemView::item:hover {
    background: __BUTTON_SOFT_HOVER__;
}
QSpinBox[settingField="true"]::up-button, QDoubleSpinBox[settingField="true"]::up-button, QSpinBox[settingField="true"]::down-button, QDoubleSpinBox[settingField="true"]::down-button {
    border: none;
    width: 20px;
    background: transparent;
}
#SettingRowContainer {
    background: transparent;
    border-bottom: 1px solid __LINE__;
}
#SettingRowContainer:hover {
    background: __BUTTON_SOFT__;
}
#SettingRow {
    background: transparent;
}
#SettingLabelBlock {
    background: transparent;
}
#SamplingBundle {
    background: transparent;
}
#InlineFieldLabel {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    padding: 0 2px 0 0;
}
#SearchQueryTabs::pane {
    border: 1px solid __LINE__;
    border-radius: 8px;
    background: __FIELD__;
    top: -1px;
}
#SearchQueryTabs QTabBar::tab {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE__;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 4px;
    color: __MUTED__;
    font-weight: 600;
}
#SearchQueryTabs QTabBar::tab:selected {
    background: __FIELD__;
    color: __TEXT__;
    border-color: __LINE_STRONG__;
}
#SearchQueryTabs QTabBar::tab:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#LibraryTabs::pane {
    border: none;
    background: transparent;
    top: 0;
    padding-top: 8px;
}
#LibraryTabs QTabBar::tab {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE__;
    border-radius: 6px;
    min-width: 112px;
    min-height: 34px;
    padding: 8px 22px;
    margin-right: 6px;
    color: __MUTED__;
    font-size: 13px;
    font-weight: 600;
}
#LibraryTabs QTabBar::tab:selected {
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT__;
    color: __ACCENT__;
}
#LibraryTabs QTabBar::tab:hover:!selected {
    background: __BUTTON_SOFT_HOVER__;
    color: __TEXT__;
    border-color: __LINE_STRONG__;
}
#LibrarySharedStrip {
    background: transparent;
    border: none;
}
/* Same family as 添加库 / 删除库; never set max-height (clips bottom borders). */
#LibrarySharedStrip #SuccessGhostButton,
#LibrarySharedStrip #DangerGhostButton {
    min-height: 32px;
    padding: 5px 14px;
    border-radius: 6px;
}
#LibraryStack {
    background: transparent;
    border: none;
}
#LibraryModeSegment {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 6px;
}
#LibraryModeBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: __MUTED__;
    font-size: 13px;
    font-weight: 700;
    min-height: 26px;
    padding: 3px 14px;
}
#LibraryModeBtn:hover:!checked {
    background: __BUTTON_SOFT_HOVER__;
    color: __TEXT__;
}
#LibraryModeBtn:checked {
    background: __ACCENT_SOFT__;
    color: __ACCENT__;
    border: 1px solid __ACCENT__;
}
#LibraryGroupedVideoTree, #LibraryGroupedScroll {
    background: transparent;
    border: none;
}
#LibraryGroupedList {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#LibraryLibCard {
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
}
#LibraryLibCard[rowStripe="odd"] {
    background: __FIELD__;
}
#LibraryLibCard[rowStripe="even"] {
    background: __PANEL__;
}
#LibraryLibHeader {
    background: transparent;
    min-height: 36px;
    max-height: 36px;
}
#LibraryLibCard[expanded="true"] #LibraryLibHeader {
    border-bottom: 1px solid __LINE__;
    background: __BUTTON_SOFT__;
}
#LibraryLibTitle {
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 600;
}
#LibraryLibCount {
    color: __MUTED__;
    background: transparent;
    border: 1px solid __LINE__;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
    min-height: 20px;
}
#LibraryLibCollapseBtn {
    background: transparent;
    border: none;
    padding: 0;
}
#LibraryLibAction {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 6px;
    min-height: 22px;
    border-radius: 4px;
}
#LibraryLibAction:hover {
    background: __BUTTON_SOFT__;
    color: __TEXT__;
}
#LibraryLibSyncStatus {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 6px;
    min-height: 22px;
}
#LibraryLibBody {
    background: transparent;
    border: none;
}
#LibraryTreeColumnHeader {
    background: __FIELD__;
    border: none;
    border-bottom: 1px solid __LINE__;
    min-height: 32px;
    max-height: 34px;
}
#LibraryTreeHeaderLabel,
#LibraryTreeHeaderCount,
#LibraryTreeHeaderStatus,
#LibraryTreeHeaderAction {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    padding: 0 2px;
}
#LibraryTreeHeaderCount {
    min-width: 36px;
}
#LibraryTreeHeaderStatus {
    min-width: 88px;
}
#LibraryTreeHeaderAction {
    min-width: 40px;
}
QTableView#LibraryGroupedLibTree {
    outline: none;
    border: none;
    border-left: 2px solid __LINE__;
    border-top: none;
    background: __PANEL__;
    alternate-background-color: __FIELD__;
    padding: 0;
    gridline-color: __LINE__;
    border-radius: 0;
}
QTableView#LibraryGroupedLibTree::item {
    min-height: 28px;
    padding: 4px 10px 4px 10px;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
    font-size: 13px;
    color: __TEXT__;
}
QTableView#LibraryGroupedLibTree::item:hover {
    background: __ACCENT_SOFT__;
}
QTableView#LibraryGroupedLibTree::item:selected {
    background: transparent;
    color: __TEXT__;
}
#SearchMobileRow {
    background: transparent;
}
#SearchOptionsBlock {
    background: transparent;
}
#DownloadOptionsRow, #DownloadFieldGroup {
    background: transparent;
}
#SearchImageOptionsRow {
    background: transparent;
}
#SearchVideoDiscoveryToggle {
    min-width: 52px;
    max-width: 52px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border-radius: 15px;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __MUTED__;
    font-weight: 700;
    text-align: center;
}
#SearchVideoDiscoveryToggle[videoDiscoveryState="off"] {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    color: __MUTED__;
}
#SearchVideoDiscoveryToggle[videoDiscoveryState="on"] {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
}
#SearchVideoDiscoveryToggle:hover {
    border-color: currentColor;
    background: __BUTTON_SOFT_HOVER__;
}
#SearchVideoDiscoveryToggle[videoDiscoveryState="on"]:hover {
    background: __SUCCESS_SOFT__;
}
#SearchVideoDiscoveryToggle[videoDiscoveryState="off"]:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchVideoDiscoveryToggle:disabled {
    opacity: 0.45;
}
#ImageDropZone, #PreviewPlaceholder {
    background: __FIELD__;
    border: 1px dashed __LINE_STRONG__;
    border-radius: 8px;
    padding: 12px;
}
#PreviewPlaceholder {
    min-height: 260px;
}
#ThumbPreview {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 4px;
}
#ThumbPreview:hover {
    border-color: __ACCENT__;
}
#VideoContainer {
    background: __VIDEO_BG__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#PreviewTimeLabel {
    color: __HEADLINE__;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 14px;
    font-weight: 700;
    padding: 5px 10px;
    background: __TRACK__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    min-width: 102px;
}
#PreviewSegmentQueueHint {
    color: #38bdf8;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
    padding: 0 4px 2px 4px;
}
#ResultTable, #DataTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
#ResultTable::item, #DataTable::item {
    border-left: none;
    border-right: none;
    border-top: none;
    border-bottom: 1px solid __LINE__;
    padding: 7px 10px;
    color: __TEXT__;
}
#ResultTable::item:hover, #DataTable::item:hover {
    background: __BUTTON_SOFT__;
    color: __TEXT__;
}
#ResultTable::item:selected, #DataTable::item:selected {
    background: __TRACK__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#ResultTable::item:selected:active, #DataTable::item:selected:active {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
}
#ResultTable::item:selected:!active, #DataTable::item:selected:!active {
    background: __TRACK__;
    color: __HEADLINE__;
}
#DownloadListTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}
#DownloadListTable::item {
    border: none;
    border-bottom: 1px solid __LINE__;
    padding: 10px 8px;
    color: __TEXT__;
}
#DownloadListTable::item:hover {
    background: __ACCENT_SOFT__;
}
#DownloadListTable::item:selected {
    background: __TRACK__;
    color: __HEADLINE__;
}
#DownloadListTable::item:selected:active {
    background: __ACCENT_SOFT__;
}
#DownloadListTable QHeaderView::section {
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-right: 1px solid __LINE__;
    padding: 8px 10px;
    color: __MUTED__;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
}
#DownloadCellHost {
    background: transparent;
}
#DownloadRowCombo {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 0 8px;
    min-height: 28px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 600;
}
#DownloadRowCombo:hover:enabled {
    border-color: __LINE_STRONG__;
    background: __BUTTON_SOFT_HOVER__;
}
#DownloadRowCombo:focus {
    border-color: __ACCENT__;
}
#DownloadRowCombo:disabled {
    color: __MUTED__;
    background: __FIELD__;
}
#DownloadRowCombo QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
    outline: 0;
}
#DownloadRowButton {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    color: __HEADLINE__;
    font-size: 12px;
    font-weight: 700;
    padding: 0;
}
#DownloadRowButton:hover:enabled {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __HEADLINE__;
}
#DownloadRowButton:pressed:enabled {
    background: __TRACK__;
}
#DownloadRowButton:disabled {
    color: __MUTED__;
    background: __FIELD__;
    border-color: __LINE__;
}
#DownloadRowProgress {
    background: __TRACK__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    min-height: 22px;
    max-height: 22px;
    text-align: center;
    color: __MUTED__;
    font-size: 11px;
    font-weight: 600;
    padding: 1px;
}
#DownloadRowProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 __ACCENT__, stop:1 __ACCENT_HOVER__);
    border-radius: 6px;
    margin: 1px;
}
#ThumbPreview[gapFrameRow="true"] {
    background: __WARN_SOFT__;
    border: 2px solid __ACCENT__;
    border-radius: 10px;
    color: __ACCENT__;
    font-weight: 700;
}
#ThumbPreview[gapChainRow="true"] {
    background: __WARN_SOFT__;
    border: 2px solid __WARN__;
    border-radius: 10px;
    color: __WARN__;
    font-weight: 700;
}
QWidget[gapFrameRow="true"] {
    background: __WARN_SOFT__;
    border-radius: 10px;
}
QWidget[gapChainRow="true"] {
    background: __WARN_SOFT__;
    border-radius: 10px;
}
#ThumbPreview[strongCoherentRow="true"] {
    background: __SUCCESS_SOFT__;
    border: 2px solid __SUCCESS__;
    border-radius: 10px;
    color: __SUCCESS__;
    font-weight: 700;
}
#ThumbPreview[strongJumpRow="true"] {
    background: __DANGER_SOFT__;
    border: 2px solid __DANGER__;
    border-radius: 10px;
    color: __DANGER__;
    font-weight: 700;
}
QWidget[strongCoherentRow="true"] {
    background: __SUCCESS_SOFT__;
    border-radius: 10px;
}
QWidget[strongJumpRow="true"] {
    background: __DANGER_SOFT__;
    border-radius: 10px;
}
#ResultTable QHeaderView::section, #DataTable QHeaderView::section {
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-right: 1px solid __LINE__;
    padding: 8px 10px;
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
}
#LibraryListScroll {
    background: transparent;
    border: none;
}
#LibraryListHost {
    background: transparent;
}
#LibraryListColumnHeader {
    background: transparent;
    border: none;
}
#LibraryListHeaderCell {
    color: __MUTED__;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.02em;
}
#LibraryCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#LibraryCard:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#LibraryCardIndex {
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 700;
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}
#LibraryCardTitle {
    color: __HEADLINE__;
    font-size: 15px;
    font-weight: 700;
}
#LibraryCardSubpath {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 500;
}
#LibraryEmptyHint {
    color: __MUTED__;
    font-size: 13px;
    font-weight: 600;
    padding: 28px 16px;
}
/* --- Dialog & popup chrome (object names + theme tokens) --- */
QFrame#Card, #DialogCard {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 10px;
}
#ToolbarCard, #DetailsCard, #StatusCard, #PreviewCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#SummaryCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 8px 10px;
}
#SummaryValue {
    color: __HEADLINE__;
    font-size: 16px;
    font-weight: 800;
    background: transparent;
}
#SummaryLabel {
    color: __MUTED__;
    font-size: 11px;
    background: transparent;
}
#DialogHeroTitle {
    font-size: 18px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogPageTitle {
    font-size: 17px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogHeadline {
    font-size: 20px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogSectionTitle {
    font-size: 18px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogInlineTitle {
    font-size: 14px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#Hint {
    color: __MUTED__;
    font-size: 12px;
    background: transparent;
}
#DialogMetaLabel {
    color: __MUTED__;
    font-size: 12px;
    background: transparent;
}
#DialogBodyLabel {
    color: __MUTED__;
    font-size: 13px;
    font-weight: 400;
    background: transparent;
    line-height: 1.45em;
}
QFrame#ExportModeOptionCard {
    border: 1px solid __LINE__;
    border-radius: 8px;
    background: __FIELD__;
}
QFrame#ExportModeOptionCard:hover {
    border-color: __ACCENT__;
}
QFrame#ExportModeOptionCard[selected="true"] {
    border: 2px solid __ACCENT__;
    background: __ACCENT_SOFT__;
}
#ExportModeTitle {
    font-size: 15px;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#ExportModeSubtitle {
    font-size: 12px;
    color: __MUTED__;
    background: transparent;
}
#SectionTitle {
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}
#DialogBodyBrowser {
    background: __FIELD__;
    color: __MUTED__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 12px;
    font-size: 13px;
}
#DialogCodeBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    padding: 10px 12px;
    color: __HEADLINE__;
    font-weight: 600;
}
#DialogDivider {
    color: __LINE__;
    background: __LINE__;
    border: none;
    max-height: 1px;
    min-height: 1px;
    margin: 8px 0;
}
#DialogPlainBody {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 10px;
    padding: 10px;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 12px;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
#MessageBadge {
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 6px;
    color: __INVERSE_TEXT__;
    font-size: 12px;
    font-weight: 700;
    background: __ACCENT__;
}
#MessageBadge[kind="success"] {
    background: __SUCCESS__;
}
#MessageBadge[kind="warning"] {
    background: __WARN__;
    color: __HEADLINE__;
}
#MessageBadge[kind="error"] {
    background: __DANGER__;
}
#ModelUploadArea {
    text-align: center;
    border: 1px dashed __LINE_STRONG__;
    border-radius: 8px;
    padding: 18px;
    background: __PANEL__;
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 600;
    min-height: 96px;
}
#ModelUploadArea:hover {
    border-color: __ACCENT__;
    background: __FIELD__;
}
QListWidget#ModelFileList {
    border: 1px solid __LINE__;
    border-radius: 8px;
    background: __PANEL__;
    padding: 6px;
    outline: 0;
}
QListWidget#ModelFileList::item {
    padding: 8px 10px;
    border-radius: 8px;
    margin: 2px 0;
    border: 1px solid transparent;
}
QListWidget#ModelFileList::item:hover {
    background: __FIELD__;
    border-color: __LINE__;
}
QListWidget#ModelFileList::item:selected {
    background: __FIELD__;
    color: __HEADLINE__;
    border-color: __ACCENT__;
}
QListWidget#DialogueLibraryList {
    border: none;
    background: transparent;
    padding: 2px 0;
    outline: 0;
}
QListWidget#DialogueLibraryList::item {
    padding: 0;
    margin: 0 0 8px 0;
    border: none;
    background: transparent;
}
QListWidget#DialogueLibraryList::item:selected {
    background: transparent;
}
#DialogueLibraryRow {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#DialogueLibraryRow[selected="true"] {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#DialogueLibraryRow:hover {
    border-color: __LINE_STRONG__;
}
#DialogueLibraryRowTitle {
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 700;
}
#DialogueLibraryRowMeta {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
}
#DialogueLibraryRowBadge {
    color: __MUTED__;
    font-size: 11px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 999px;
    background: __PANEL__;
    border: 1px solid __LINE__;
}
#DialogueLibraryRowBadge[ready="true"] {
    color: __ACCENT__;
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#SolidDangerButton {
    background: __DANGER__;
    border: 1px solid __DANGER__;
    color: __INVERSE_TEXT__;
    font-weight: 700;
    border-radius: 7px;
    padding: 8px 14px;
}
#DialogRulesTable, #ResourceDialogTable {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}
#DialogRulesTable::item, #ResourceDialogTable::item {
    background: __FIELD__;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid __LINE__;
}
#DialogRulesTable::item:hover, #ResourceDialogTable::item:hover {
    background: __LINE_STRONG__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#DialogRulesTable::item:selected, #ResourceDialogTable::item:selected,
#DialogRulesTable::item:selected:active, #ResourceDialogTable::item:selected:active {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#DialogRulesTable::item:selected:hover, #ResourceDialogTable::item:selected:hover {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#DialogRulesTable QLineEdit {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __ACCENT__;
    border-radius: 6px;
    padding: 2px 6px;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
#DialogRulesTable QHeaderView::section, #ResourceDialogTable QHeaderView::section {
    color: __MUTED__;
    background: __FIELD__;
    border: none;
    border-bottom: 1px solid __LINE__;
    padding: 10px 8px;
    font-weight: 700;
}
QDialog QCheckBox {
    color: __MUTED__;
    spacing: 6px;
    background: transparent;
}
QDialog QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
ClickableLabel[detailActive="true"] {
    color: __ACCENT__;
    font-weight: 700;
}
#StatusHint[state="error"] {
    color: __DANGER__;
}
#LibraryCardStatus {
    background: transparent;
    border: none;
    padding: 0 4px;
    font-size: 13px;
    font-weight: 600;
}
#LibraryCardStatus[libState="ready"] {
    color: __SUCCESS__;
}
#LibraryCardStatus[libState="pending"] {
    color: __WARN__;
}
#LibraryCardStatus[libState="partial"] {
    color: __ACCENT__;
}
#LibraryCardStatus[libState="offline"] {
    color: __MUTED__;
}
#SettingDetailPopup {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#SettingDetailPopupTitle {
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}
#SettingDetailPopupBody {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.45em;
    background: transparent;
}
#SearchScopeEditorDialog {
    background: __WINDOW__;
}
#SearchScopeScroll {
    background: transparent;
    border: none;
}
#SearchScopeList {
    background: transparent;
}
#SearchScopeLibRow {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#SearchScopeLibRow:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#SearchScopeLibRow[selectedRow="true"] {
    border-color: __ACCENT__;
    background: __FIELD__;
}
#SearchScopeLibTitle {
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 700;
    background: transparent;
}
#SearchScopeLibPath {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
#SearchScopeLibBadge {
    background: transparent;
    border: none;
    padding: 0 4px;
    font-size: 12px;
    font-weight: 700;
}
#SearchScopeLibBadge[libState="ready"] {
    color: __SUCCESS__;
}
#SearchScopeLibBadge[libState="offline"] {
    color: __MUTED__;
}
#SearchPresetManageScroll {
    background: transparent;
    border: none;
}
#SearchPresetManageList {
    background: transparent;
}
#SearchPresetManageRow {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#SearchPresetManageRow:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#SearchPresetManageAccent {
    background: __ACCENT__;
    border-radius: 2px;
}
#SearchPresetManageTitle {
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 700;
    background: transparent;
}
#SearchPresetManageDesc {
    color: __MUTED__;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
#SearchPresetManageBadge {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}
#SearchPresetManageBadge[kind="text"] {
    color: __ACCENT__;
    border-color: __ACCENT__;
    background: __ACCENT_SOFT__;
}
#SearchPresetManageBadge[kind="image"] {
    color: __SUCCESS__;
    border-color: __SUCCESS__;
    background: transparent;
}
#SearchPresetManageBadge[kind="fusion"] {
    color: __MUTED__;
}
#VideoScopeScroll {
    background: transparent;
    border: none;
}
#VideoScopeList {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 8px;
}
#VideoScopeLibCard {
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
}
#VideoScopeLibCard[rowStripe="odd"] {
    background: __FIELD__;
}
#VideoScopeLibCard[rowStripe="even"] {
    background: __PANEL__;
}
#VideoScopeLibHeader {
    background: transparent;
    min-height: 36px;
    max-height: 36px;
}
#VideoScopeLibCard[expanded="true"] #VideoScopeLibHeader {
    border-bottom: 1px solid __LINE__;
    background: __BUTTON_SOFT__;
}
#VideoScopeLibTitle {
    color: __HEADLINE__;
    font-size: 13px;
    font-weight: 600;
}
#VideoScopeCollapseBtn {
    background: transparent;
    border: none;
    padding: 0;
}
QTableView#VideoScopeLibTree {
    outline: none;
    border: none;
    border-left: 2px solid __LINE__;
    padding: 0;
    background: __PANEL__;
    alternate-background-color: __FIELD__;
    border-radius: 0;
}
QTableView#VideoScopeLibTree::item {
    min-height: 28px;
    padding: 4px 10px 4px 10px;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
    font-size: 13px;
    color: __TEXT__;
}
QTableView#VideoScopeLibTree::item:hover {
    background: __ACCENT_SOFT__;
}
QTableView#VideoScopeLibTree::item:selected {
    background: transparent;
    color: __TEXT__;
}
#VideoScopeLibBody {
    background: transparent;
    border: none;
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
    width: 8px;
    margin: 2px 1px 2px 1px;
}
QScrollBar::handle:vertical {
    background: __SCROLL__;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: __LINE_STRONG__;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 1px 2px 1px 2px;
}
QScrollBar::handle:horizontal {
    background: __SCROLL__;
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: __LINE_STRONG__;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    width: 0;
    height: 0;
}
QPushButton[class="TableBtn"], QPushButton[class="TableLocateBtn"], QPushButton[class="TableDeleteBtn"] {
    background: transparent;
    border: 1px solid transparent;
    padding: 5px 8px;
    border-radius: 6px;
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
QDialog {
    border-radius: 8px;
}
QToolTip {
    /* Width/wrapping handled by ui.widgets.tooltip_utils (QSS max-width clips CJK). */
    padding: 6px 8px;
    border-radius: 6px;
}
"""


def _qss_url(path: str) -> str:
    """Qt stylesheet url() path: forward slashes, escaped for Windows."""
    import os

    text = os.path.normpath(str(path or "")).replace("\\", "/")
    return text.replace("'", "\\'")


def build_style(colors):
    from src.infra.paths import get_resource_path

    style = STYLE_TEMPLATE
    for key, value in colors.items():
        style = style.replace(f"__{key}__", value)
    check_icon = _qss_url(get_resource_path("resources/icons/check.png"))
    partial_icon = _qss_url(get_resource_path("resources/icons/check_partial.png"))
    style = style.replace("__CHECK_ICON__", check_icon)
    style = style.replace("__CHECK_PARTIAL_ICON__", partial_icon)
    return style


from ui.widgets.theme_tokens import load_merged_theme_colors

THEME_COLORS_DARK_BASE = {
    # Win11-like neutral layers (less cold blue-black).
    "WINDOW": "#202020",
    "TEXT": "#e5e5e5",
    "HEADLINE": "#ffffff",
    "MUTED": "#a3a3a3",
    "ACCENT": "#60a5fa",
    "ACCENT_HOVER": "#93c5fd",
    "ACCENT_SOFT": "#1e3a5f",
    "SUCCESS": "#3dd68c",
    "SUCCESS_HOVER": "#56e0a0",
    "SUCCESS_SOFT": "#0f3d2a",
    "WARN": "#fbbf24",
    "WARN_SOFT": "#4a3510",
    "DANGER": "#f87171",
    "DANGER_SOFT": "#4c1d1d",
    "SIDEBAR": "#1b1b1b",
    "PANEL": "#2b2b2b",
    "FIELD": "#242424",
    "HERO": "#262626",
    "HERO_LINE": "#3a3a3a",
    "LINE": "#3a3a3a",
    "LINE_STRONG": "#525252",
    "TRACK": "#2f2f2f",
    "SCROLL": "#6b6b6b",
    "BUTTON_SOFT": "#323232",
    "BUTTON_SOFT_HOVER": "#3a3a3a",
    "VIDEO_BG": "#141414",
    "NOTICE_BG": "#1e3a5f",
    "NOTICE_LINE": "#60a5fa",
    "NOTICE_TEXT": "#e8f1ff",
    "INVERSE_TEXT": "#ffffff",
}

THEME_COLORS_LIGHT_BASE = {
    # Win11-like gray shell; accent stays product blue.
    "WINDOW": "#f3f3f3",
    "TEXT": "#2b2b2b",
    "HEADLINE": "#1a1a1a",
    "MUTED": "#6b6b6b",
    "ACCENT": "#0078d4",
    "ACCENT_HOVER": "#1a86d9",
    "ACCENT_SOFT": "#e8f3fc",
    "SUCCESS": "#0f7b3a",
    "SUCCESS_HOVER": "#159345",
    "SUCCESS_SOFT": "#e6f5ec",
    "WARN": "#9a6700",
    "WARN_SOFT": "#fff4ce",
    "DANGER": "#c42b1c",
    "DANGER_SOFT": "#fde7e9",
    "SIDEBAR": "#f9f9f9",
    "PANEL": "#ffffff",
    "FIELD": "#ffffff",
    "HERO": "#f0f0f0",
    "HERO_LINE": "#e5e5e5",
    "LINE": "#e5e5e5",
    "LINE_STRONG": "#d1d1d1",
    "TRACK": "#ebebeb",
    "SCROLL": "#c4c4c4",
    "BUTTON_SOFT": "#f5f5f5",
    "BUTTON_SOFT_HOVER": "#ebebeb",
    "VIDEO_BG": "#ececec",
    "NOTICE_BG": "#e8f3fc",
    "NOTICE_LINE": "#0078d4",
    "NOTICE_TEXT": "#0b3b66",
    "INVERSE_TEXT": "#ffffff",
}

THEME_COLORS_DARK = load_merged_theme_colors(True, THEME_COLORS_DARK_BASE)
THEME_COLORS_LIGHT = load_merged_theme_colors(False, THEME_COLORS_LIGHT_BASE)

DARK_STYLE = build_style(THEME_COLORS_DARK)
LIGHT_STYLE = build_style(THEME_COLORS_LIGHT)


def theme_color_map(is_dark: bool):
    return THEME_COLORS_DARK if is_dark else THEME_COLORS_LIGHT


def repolish_widget(widget):
    """Re-apply the application stylesheet after changing dynamic Qt properties."""
    if widget is None:
        return
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def set_runtime_banner_warn(banner, warn: bool) -> None:
    """``warn=True``: missing-model / FFmpeg strip (amber). ``False``: default accent info strip."""
    if banner is None:
        return
    banner.setProperty("bannerTone", "warn" if warn else "")
    repolish_widget(banner)
    try:
        from PySide6.QtWidgets import QLabel, QPushButton
    except ImportError:
        return
    for child in banner.findChildren(QLabel):
        repolish_widget(child)
    for child in banner.findChildren(QPushButton):
        repolish_widget(child)

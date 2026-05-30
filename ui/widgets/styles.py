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
#NavSidebar, #PageHeader, #PanelCard, #SubPanelCard, #NoticeCard {
    background: __SIDEBAR__;
    border: 1px solid __LINE__;
    border-radius: 18px;
}
#PageHeader, #PanelCard, #SubPanelCard {
    background: __PANEL__;
}
#NoticeCard {
    background: __NOTICE_BG__;
    border: 1px solid __NOTICE_LINE__;
}
/* Runtime / indexing strip: info tone uses accent-soft so it reads as a highlight strip; ``bannerTone=warn`` when resources missing */
#RuntimeBanner {
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT__;
    border-radius: 18px;
}
#RuntimeBanner #RuntimeBannerText {
    color: __TEXT__;
    font-size: 12px;
    font-weight: 600;
}
#RuntimeBanner[bannerTone="warn"] {
    background: __WARN_SOFT__;
    border: 1px solid __WARN__;
    border-radius: 18px;
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
    border-top-left-radius: 18px;
    border-top-right-radius: 18px;
}
#BrandTitle {
    color: __HEADLINE__;
    font-size: 28px;
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
    border: 1px solid __LINE_STRONG__;
    border-radius: 10px;
    padding: 8px 10px;
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
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT_HOVER__;
    color: __ACCENT__;
    font-weight: 700;
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
}
#GhostButton:pressed {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
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
    border-radius: 10px;
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
#PresetImageThumb {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 12px;
}
#PresetImageThumb[selected="true"] {
    background: __ACCENT_SOFT__;
    border: 2px solid __ACCENT__;
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
    padding: 8px 12px;
    padding-left: 14px;
    font-weight: 600;
    border-radius: 10px;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __HEADLINE__;
}
#NavButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#NavButton:pressed {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    padding-top: 9px;
    padding-bottom: 7px;
}
#NavButton:checked {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __HEADLINE__;
}
/* Sidebar bottom row + link-page file/cache utilities: visible on light panels (avoid four identical AccentGhost). */
#SidebarFooterButton, #NeutralToolButton {
    border-radius: 10px;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __HEADLINE__;
    padding: 8px 12px;
    font-weight: 600;
}
#SidebarFooterButton:hover, #NeutralToolButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#SidebarFooterButton:pressed, #NeutralToolButton:pressed {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    padding-top: 9px;
    padding-bottom: 7px;
}
#SidebarFooterButton:disabled, #NeutralToolButton:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: __FIELD__;
    font-weight: 600;
}
#SidebarFooterGhost {
    border-radius: 10px;
    border: 1px solid __LINE_STRONG__;
    background: transparent;
    color: __HEADLINE__;
    padding: 8px 12px;
    font-weight: 600;
}
#SidebarFooterGhost:hover {
    background: __TRACK__;
    border-color: __LINE_STRONG__;
}
#SidebarFooterGhost:pressed {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
    padding-top: 9px;
    padding-bottom: 7px;
}
#SidebarFooterGhost:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: transparent;
    font-weight: 600;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 10px;
    padding: 8px 10px;
    color: __TEXT__;
}
#SearchModeSelect {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
}
#SearchModeSelect QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
    outline: 0;
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
    padding-top: 6px;
}
#SettingHintButton {
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    max-height: 18px;
    border: 1px solid __LINE_STRONG__;
    border-radius: 9px;
    color: __MUTED__;
    background: __FIELD__;
    font-weight: 700;
    font-size: 11px;
}
#SettingHintButton:hover {
    border-color: __ACCENT__;
    color: __ACCENT__;
}
QSpinBox[settingField="true"], QDoubleSpinBox[settingField="true"], QComboBox[settingField="true"], QLineEdit[settingField="true"] {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 12px;
    padding: 7px 10px;
    min-height: 34px;
    color: __HEADLINE__;
}
QSpinBox[settingField="true"]:hover, QDoubleSpinBox[settingField="true"]:hover, QComboBox[settingField="true"]:hover, QLineEdit[settingField="true"]:hover {
    border-color: __LINE_STRONG__;
}
QSpinBox[settingField="true"]:focus, QDoubleSpinBox[settingField="true"]:focus, QComboBox[settingField="true"]:focus, QLineEdit[settingField="true"]:focus {
    border-color: __ACCENT__;
}
QComboBox[settingField="true"]::drop-down {
    border: none;
    width: 24px;
}
QComboBox[settingField="true"] QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 10px;
    padding: 4px;
    outline: 0;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
QComboBox[settingField="true"] QAbstractItemView::item {
    min-height: 30px;
    padding: 4px 8px;
    border-radius: 6px;
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
    padding: 0 2px;
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
    border-radius: 16px;
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
#ResultTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 14px;
    gridline-color: __LINE__;
    outline: none;
}
#ResultTable::item {
    border-left: none;
    border-right: none;
    border-top: none;
    border-bottom: 1px solid __LINE__;
    padding: 8px 8px;
}
#ResultTable::item:hover {
    background: __ACCENT_SOFT__;
}
#ResultTable::item:selected {
    background: __TRACK__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#ResultTable::item:selected:active {
    background: __ACCENT_SOFT__;
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
#ResultTable QHeaderView::section {
    background: __PANEL__;
    border: none;
    border-bottom: 2px solid __LINE_STRONG__;
    border-right: 1px solid __LINE__;
    padding: 9px 10px;
    color: __MUTED__;
    font-weight: 700;
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
    border-radius: 14px;
}
#LibraryCard:hover {
    background: __ACCENT_SOFT__;
    border-color: __LINE_STRONG__;
}
#LibraryCardIndex {
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 800;
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: 20px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
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
    border-radius: 20px;
}
#ToolbarCard, #DetailsCard, #StatusCard, #PreviewCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 14px;
}
#SummaryCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 12px;
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
    font-size: 22px;
    font-weight: 800;
    color: __HEADLINE__;
    background: transparent;
}
#DialogPageTitle {
    font-size: 20px;
    font-weight: 800;
    color: __HEADLINE__;
    background: transparent;
}
#DialogHeadline {
    font-size: 24px;
    font-weight: 800;
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
    border-radius: 16px;
    padding: 12px;
    font-size: 13px;
}
#DialogCodeBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 12px;
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
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 17px;
    color: __INVERSE_TEXT__;
    font-weight: 800;
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
    border: 2px dashed __LINE_STRONG__;
    border-radius: 16px;
    padding: 20px;
    background: __PANEL__;
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 600;
    min-height: 96px;
}
#ModelUploadArea:hover {
    border-color: __ACCENT__;
    background: __FIELD__;
}
QListWidget#ModelFileList {
    border: 1px solid __LINE__;
    border-radius: 12px;
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
#SolidDangerButton {
    background: __DANGER__;
    border: 1px solid __DANGER__;
    color: __INVERSE_TEXT__;
    font-weight: 700;
    border-radius: 10px;
    padding: 10px 16px;
}
#DialogRulesTable, #ResourceDialogTable {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: 12px;
    gridline-color: __LINE__;
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
    border: 1px solid __LINE_STRONG__;
    border-radius: 12px;
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
    border-radius: 12px;
}
#SearchScopeLibRow:hover {
    background: __ACCENT_SOFT__;
    border-color: __LINE_STRONG__;
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
    border-radius: 12px;
}
#SearchPresetManageRow:hover {
    background: __ACCENT_SOFT__;
    border-color: __LINE_STRONG__;
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
    background: transparent;
}
#VideoScopeLibCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: 14px;
}
#VideoScopeLibTitle {
    color: __HEADLINE__;
    font-size: 14px;
    font-weight: 700;
}
#VideoScopeCollapseBtn {
    background: transparent;
    border: none;
    padding: 4px;
}
#VideoScopeLibTree {
    outline: none;
    border: 1px solid __LINE__;
    border-radius: 12px;
    padding: 4px 2px 8px 2px;
    background: __PANEL__;
}
#VideoScopeLibTree QHeaderView::section {
    background: __PANEL__;
    border: none;
    border-bottom: 2px solid __LINE_STRONG__;
    padding: 8px 10px;
    color: __MUTED__;
    font-weight: 700;
    font-size: 12px;
}
#VideoScopeLibTree::item {
    min-height: 30px;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
    margin: 0 2px;
    font-size: 13px;
}
#VideoScopeLibTree::item:hover {
    background: __ACCENT_SOFT__;
}
#VideoScopeLibTree::item:selected {
    background: __TRACK__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#VideoScopeLibTree::item:selected:active {
    background: __ACCENT_SOFT__;
    border-bottom: 1px solid __LINE__;
}
#VideoScopeLibBody {
    background: transparent;
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
QToolTip {
    max-width: 360px;
    padding: 6px 8px;
}
"""


def build_style(colors):
    style = STYLE_TEMPLATE
    for key, value in colors.items():
        style = style.replace(f"__{key}__", value)
    return style


from ui.widgets.theme_tokens import load_merged_theme_colors

THEME_COLORS_DARK_BASE = {
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
    "WARN": "#f4c95d",
    "WARN_SOFT": "#43381a",
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
    "NOTICE_BG": "#21365f",
    "NOTICE_LINE": "#5d87d6",
    "NOTICE_TEXT": "#eef4ff",
    "INVERSE_TEXT": "#ffffff",
}

THEME_COLORS_LIGHT_BASE = {
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
    "WARN": "#9a6b00",
    "WARN_SOFT": "#fff1c9",
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
    "NOTICE_BG": "#e8f0ff",
    "NOTICE_LINE": "#7ca2f7",
    "NOTICE_TEXT": "#1a3f8a",
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

STYLE_TEMPLATE = """
QMainWindow {
    background: __WINDOW__;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: __FS_SM__;
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
    border-radius: __RADIUS_LG__;
    padding: __SPACE_1__;
}
QMenu::item {
    padding: __SPACE_2__ __SPACE_5__ __SPACE_2__ __SPACE_3__;
    background-color: __PANEL__;
    color: __HEADLINE__;
    border-radius: __RADIUS_MD__;
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
    margin: __SPACE_1__ __SPACE_3__;
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
    border-radius: __RADIUS_LG__;
}
#NoticeCard {
    background: __NOTICE_BG__;
    border: 1px solid __NOTICE_LINE__;
    border-radius: __RADIUS_LG__;
}
#NoticeUpdateHint {
    color: __ACCENT__;
    font-size: __FS_XS__;
    font-weight: 600;
    padding: 0;
}
/* Runtime / indexing strip: info tone uses accent-soft so it reads as a highlight strip; ``bannerTone=warn`` when resources missing */
#RuntimeBanner {
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_MD__;
}
#RuntimeBanner #RuntimeBannerText {
    color: __TEXT__;
    font-size: __FS_XS__;
    font-weight: 600;
}
#RuntimeBanner[bannerTone="warn"] {
    background: __WARN_SOFT__;
    border: 1px solid __WARN__;
    border-radius: __RADIUS_MD__;
}
#RuntimeBanner[bannerTone="warn"] #RuntimeBannerText {
    color: __WARN__;
    font-size: __FS_XS__;
    font-weight: 700;
}
/* Page title-row tip: no strip — yellow text only when warn */
#RuntimeInlineTip {
    background: transparent;
    border: none;
}
#RuntimeInlineTip #RuntimeInlineTipText {
    color: __TEXT__;
    font-size: __FS_MD__;
    font-weight: 600;
    padding: 0;
}
#RuntimeInlineTip[bannerTone="warn"] {
    background: transparent;
    border: none;
}
#RuntimeInlineTip[bannerTone="warn"] #RuntimeInlineTipText {
    color: __WARN__;
    font-size: __FS_MD__;
    font-weight: 700;
}
#RuntimeInlineTip #AccentGhostButton[chrome="textLink"] {
    background: transparent;
    border: none;
    border-bottom: 1px solid __ACCENT__;
    border-radius: 0;
    padding: 0 0 1px 0;
    min-height: 0;
    max-height: 28px;
    font-size: __FS_MD__;
    font-weight: 700;
    color: __ACCENT__;
}
#RuntimeInlineTip #AccentGhostButton[chrome="textLink"]:hover,
#RuntimeInlineTip #AccentGhostButton[chrome="textLink"]:pressed {
    background: transparent;
    border: none;
    border-bottom: 1px solid __ACCENT_HOVER__;
    padding: 0 0 1px 0;
    color: __ACCENT_HOVER__;
}
#RuntimeInlineTip[bannerTone="warn"] #AccentGhostButton[chrome="textLink"],
#RuntimeInlineTip[bannerTone="warn"] #AccentGhostButton[chrome="textLink"]:hover,
#RuntimeInlineTip[bannerTone="warn"] #AccentGhostButton[chrome="textLink"]:pressed {
    background: transparent;
    border: none;
    border-bottom: 1px solid __WARN__;
    padding: 0 0 1px 0;
    color: __WARN__;
}
#NoticeTitle {
    color: __NOTICE_TEXT__;
    font-size: __FS_SM__;
    font-weight: 800;
}
#NoticeBody {
    color: __NOTICE_TEXT__;
    font-size: __FS_SM__;
    font-weight: 600;
    line-height: 1.5em;
}
#SettingsSectionHeader {
    background: __FIELD__;
    border-bottom: 1px solid __LINE__;
    border-top-left-radius: __RADIUS_LG__;
    border-top-right-radius: __RADIUS_LG__;
}
#SettingsSectionHeader #CardTitle {
    font-size: __FS_MD__;
    font-weight: 700;
    color: __HEADLINE__;
}
#BrandTitle {
    color: __HEADLINE__;
    font-size: __FS_XL__;
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
    border-radius: __RADIUS_MD__;
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
    border-radius: __RADIUS_MD__;
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
    border-radius: __RADIUS_SM__;
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
    font-size: __FS_XS__;
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
    font-size: __FS_XS__;
    font-weight: 600;
    background: __ACCENT_SOFT__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
    line-height: 1.35em;
    min-height: 18px;
}
#HeroCard {
    background: __HERO__;
    border: 1px solid __HERO_LINE__;
    border-radius: __RADIUS_MD__;
}
#HeroTag {
    color: __ACCENT__;
    font-size: __FS_XS__;
    font-weight: 700;
}
#HeroTitle, #PageTitle, #CardTitle {
    color: __HEADLINE__;
    font-weight: 700;
}
#PageTitle {
    font-size: __FS_XL__;
}
#PageTitleBadge {
    color: __WARN__;
    background: __WARN_SOFT__;
    border: 1px solid __WARN__;
    border-radius: __RADIUS_PILL__;
    padding: __SPACE_1__ __SPACE_3__;
    font-size: __FS_XS__;
    font-weight: 700;
    min-height: 22px;
}
#CardTitle {
    font-size: __FS_MD__;
}
#UnderstandingChunkTimeLabel {
    color: __ACCENT__;
    font-size: __FS_SM__;
    font-weight: 700;
    padding: 0;
}
#UnderstandingConfigHeader {
    background: transparent;
    border: none;
    border-radius: __RADIUS_MD__;
}
#UnderstandingConfigHeader:hover {
    background: __BUTTON_SOFT__;
}
#UnderstandingCommandBar, #CloneCommandBar {
    background: transparent;
    border: none;
}
#UnderstandingCommandBar #PrimaryButton,
#UnderstandingCommandBar #GhostButton,
#UnderstandingCommandBar #AccentGhostButton,
#UnderstandingCommandBar #DangerGhostButton,
#UnderstandingCommandBar #SuccessGhostButton,
#UnderstandingCommandBar #NeutralToolButton {
    min-height: 32px;
    padding: __SPACE_1__ __SPACE_4__;
    border-radius: __RADIUS_MD__;
}
#CloneCommandBar #PrimaryButton,
#CloneCommandBar #GhostButton,
#CloneCommandBar #AccentGhostButton,
#CloneCommandBar #DangerGhostButton,
#CloneCommandBar #SuccessGhostButton,
#CloneCommandBar #NeutralToolButton {
    min-height: 24px;
    max-height: 26px;
    padding: __SPACE_1__ __SPACE_3__;
    border-radius: __RADIUS_SM__;
    font-size: __FS_XS__;
}
#CloneCommandBar #PrimaryButton:pressed,
#CloneCommandBar #GhostButton:pressed,
#CloneCommandBar #AccentGhostButton:pressed,
#CloneCommandBar #DangerGhostButton:pressed,
#CloneCommandBar #SuccessGhostButton:pressed,
#CloneCommandBar #NeutralToolButton:pressed {
    padding-top: 2px;
    padding-bottom: 0px;
}
#UnderstandingStepBar {
    background: transparent;
    border: none;
}
#UnderstandingStepBar #GhostButton {
    min-height: 24px;
    max-height: 26px;
    padding: __SPACE_1__ __SPACE_3__;
    border-radius: __RADIUS_SM__;
    font-size: __FS_XS__;
}
#UnderstandingStepBar #GhostButton:pressed {
    padding-top: 2px;
    padding-bottom: 0px;
}
#UnderstandingWizardBar {
    background: transparent;
    border: none;
}
#GhostButton[chrome="wizardStep"] {
    background: transparent;
    border: none;
    padding: 0;
    min-height: 28px;
    max-height: 32px;
    border-radius: 0;
}
#GhostButton[chrome="wizardStep"]:hover,
#GhostButton[chrome="wizardStep"]:pressed,
#GhostButton[chrome="wizardStep"]:checked,
#GhostButton[chrome="wizardStep"]:checked:hover {
    background: transparent;
    border: none;
    padding: 0;
    color: __HEADLINE__;
}
#UnderstandingStepIndex {
    background: transparent;
    color: __MUTED__;
    border: 1px solid __LINE_STRONG__;
    border-radius: 11px;
    font-size: __FS_XS__;
    font-weight: 700;
    padding: 0;
    margin: 0;
}
#UnderstandingStepIndex[stepState="done"] {
    color: __ACCENT__;
    border-color: __ACCENT__;
    background: transparent;
}
#UnderstandingStepIndex[stepState="current"] {
    color: __INVERSE_TEXT__;
    border-color: __ACCENT__;
    background: __ACCENT__;
}
#UnderstandingStepTitle {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: __FS_SM__;
    font-weight: 600;
    padding: 0;
}
#UnderstandingStepTitle[stepState="done"] {
    color: __TEXT__;
}
#UnderstandingStepTitle[stepState="current"] {
    color: __HEADLINE__;
    font-weight: 700;
}
#UnderstandingStepConnector {
    background: __LINE__;
    border: none;
    min-height: 2px;
    max-height: 2px;
}
#UnderstandingStepConnector[stepState="done"] {
    background: __ACCENT__;
}
#UnderstandingStepScroll, #UnderstandingStepScrollViewport {
    background: transparent;
    border: none;
}
#UnderstandingWizardNav,
#UnderstandingServicesActions {
    background: __WINDOW__;
    border: none;
}
#UnderstandingTimelineBlock {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#ChunkTimelineScroll {
    background: transparent;
    border: none;
}
#UnderstandingSection {
    background: transparent;
    border: none;
}
#VerticalStretchHandle {
    background: transparent;
    border: none;
    margin: 0 __SPACE_1__;
}
#VerticalStretchHandle:hover {
    background: __LINE__;
    border-radius: __RADIUS_SM__;
}
#UnderstandingSampleFrame {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    color: __MUTED__;
}
#UnderstandingDetailPanel {
    background: transparent;
    border: none;
}
#UnderstandingDetailPanel #CardTitle {
    font-size: __FS_SM__;
}
QPlainTextEdit#UnderstandingOutput {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
    color: __TEXT__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
QPlainTextEdit#UnderstandingOutput:focus {
    border: 1px solid __ACCENT__;
}
#UnderstandingChromeHint {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
    border: none;
    padding: 0;
}
QPushButton {
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE__;
    padding: __SPACE_2__ __SPACE_3__;
    background: __BUTTON_SOFT__;
    color: __HEADLINE__;
}
QPushButton:hover {
    background: __BUTTON_SOFT_HOVER__;
}
QPushButton:pressed {
    background: __BUTTON_SOFT_PRESSED__;
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
#AccentGhostButton[chrome="update"] {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __ACCENT__;
    font-weight: 700;
}
#AccentGhostButton[chrome="update"]:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#AccentGhostButton[chrome="update"]:pressed {
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
#GhostButton[chrome="mobileToggle"] {
    min-width: 52px;
    max-width: 52px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border-radius: __RADIUS_LG__;
    border: 1px solid __LINE_STRONG__;
    background: __TRACK__;
    color: __MUTED__;
    font-weight: 700;
    text-align: center;
}
#GhostButton[chrome="mobileToggle"][bridgeState="off"] {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    color: __MUTED__;
}
#GhostButton[chrome="mobileToggle"][bridgeState="on"] {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
}
#GhostButton[chrome="mobileToggle"]:hover {
    border-color: currentColor;
    background: __BUTTON_SOFT_HOVER__;
}
#GhostButton[chrome="mobileToggle"][bridgeState="on"]:hover {
    background: __SUCCESS_SOFT__;
}
#GhostButton[chrome="mobileToggle"][bridgeState="off"]:hover {
    background: __BUTTON_SOFT_HOVER__;
}
#SearchPrecisionToggle {
    min-width: 52px;
    max-width: 52px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border-radius: __RADIUS_LG__;
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
#AccentGhostButton[chrome="mobileQr"] {
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
#AccentGhostButton[chrome="mobileQr"][qrState="hidden"] {
    background: transparent;
    border: none;
    color: transparent;
    padding: 0;
}
#AccentGhostButton[chrome="mobileQr"][qrState="hidden"]:hover {
    background: transparent;
    border: none;
}
#AccentGhostButton[chrome="mobileQr"][placement="settings"] {
    min-width: 72px;
    max-width: 88px;
    min-height: 32px;
    max-height: 32px;
}
#AccentGhostButton[chrome="mobileQr"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __ACCENT__;
}
#AccentGhostButton[chrome="mobileQr"]:disabled {
    background: __FIELD__;
    border: 1px solid __LINE__;
    color: __MUTED__;
}
#AccentGhostButton[chrome="linkUtility"] {
    background: __ACCENT_SOFT__;
    border-color: __LINE_STRONG__;
    color: __HEADLINE__;
    font-weight: 600;
}
#AccentGhostButton[chrome="linkUtility"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __ACCENT__;
}
#GhostButton {
    background: __BUTTON_SOFT__;
    border-color: __LINE_STRONG__;
    color: __HEADLINE__;
    font-weight: 600;
}
#GhostButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton:pressed {
    background: __BUTTON_SOFT_PRESSED__;
    border-color: __ACCENT__;
}
#GhostButton:checked {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __ACCENT__;
}
#GhostButton[chrome="filterToggle"] {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE_STRONG__;
    color: __HEADLINE__;
    font-weight: 600;
    padding: __SPACE_1__ __SPACE_3__;
}
#GhostButton[chrome="filterToggle"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton[chrome="filterToggle"][active="true"] {
    color: __ACCENT__;
    border-color: __ACCENT__;
}
#GhostButton[chrome="filterToggle"]:checked {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __ACCENT__;
    padding: __SPACE_1__ __SPACE_3__;
}
#GhostButton[chrome="filterToggle"]:pressed {
    background: __BUTTON_SOFT_PRESSED__;
    padding: __SPACE_1__ __SPACE_3__;
}
#SearchScoreSlider {
    min-height: 22px;
}
#SearchScoreSlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background: __LINE_STRONG__;
}
#SearchScoreSlider::sub-page:horizontal {
    height: 4px;
    border-radius: 2px;
    background: __ACCENT__;
}
#SearchScoreSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: __ACCENT__;
    border: 2px solid __WINDOW__;
}
#SearchScoreSlider::handle:horizontal:hover {
    background: __ACCENT_HOVER__;
}
#SearchScoreValue {
    color: __HEADLINE__;
    font-size: __FS_XS__;
    font-weight: 600;
    background: transparent;
    border: none;
    padding: 0;
}
#SearchFilterSummary {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
    border: none;
    padding: 0 __SPACE_1__;
}
#PresetChipButton {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __HEADLINE__;
    font-weight: 600;
    font-size: __FS_XS__;
    padding: 0 __SPACE_3__;
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
    border-radius: __RADIUS_MD__;
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
    margin: 0 __SPACE_1__;
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
    border-radius: __RADIUS_SM__;
    min-width: 28px;
    margin: 0 __SPACE_1__;
}
#SearchPresetsScroll QScrollBar::add-line, #SearchPresetsScroll QScrollBar::sub-line {
    width: 0;
    height: 0;
    border: none;
}
#PresetChip {
    background: transparent;
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_PILL__;
}
#PresetChip:hover {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#PresetChipLabel {
    color: __HEADLINE__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
}
#PresetTrackEmpty {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
}
#GhostButton[chrome="presetManage"] {
    background: transparent;
    color: __ACCENT__;
    border: 1px solid __ACCENT__;
    font-weight: 600;
}
#GhostButton[chrome="presetManage"]:hover {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT_HOVER__;
    color: __ACCENT_HOVER__;
}
#GhostButton[chrome="presetManage"]:pressed {
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
}
#SearchResultsActions {
    background: transparent;
}
#SearchResultsPager {
    background: transparent;
}
#GhostButton[chrome="pager"] {
    background-color: transparent;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_MD__;
    color: __ACCENT__;
    font-weight: 600;
    font-size: __FS_XS__;
    padding: 0 __SPACE_2__;
    min-height: 22px;
    max-height: 24px;
}
#GhostButton[chrome="pager"]:hover:enabled {
    background-color: __ACCENT_SOFT__;
    border-color: __ACCENT_HOVER__;
    color: __ACCENT_HOVER__;
}
#GhostButton[chrome="pager"]:pressed:enabled {
    background-color: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    padding-top: 1px;
}
#GhostButton[chrome="pager"]:disabled {
    background-color: transparent;
    border-color: __ACCENT__;
    color: __MUTED__;
    font-weight: 600;
}
#SearchResultsPagerInfo {
    background-color: transparent;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_MD__;
    padding: 0 __SPACE_3__;
    min-height: 22px;
    max-height: 24px;
    color: __HEADLINE__;
    font-weight: 600;
    font-size: __FS_XS__;
}
#PresetImageThumb {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#PresetImageThumb[compact="true"] {
    border-radius: __RADIUS_MD__;
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
    background: __ACCENT_SOFT__;
    border-color: __ACCENT__;
    color: __ACCENT__;
    font-weight: 700;
}
#AccentGhostButton:hover {
    background: __ACCENT_SOFT_HOVER__;
    border-color: __ACCENT_HOVER__;
    color: __ACCENT_HOVER__;
}
#AccentGhostButton:pressed {
    background: __ACCENT_SOFT_HOVER__;
    border-color: __ACCENT__;
}
#AccentGhostButton:disabled {
    background: __FIELD__;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#SuccessGhostButton {
    background: __SUCCESS_SOFT__;
    border-color: __SUCCESS__;
    color: __SUCCESS__;
    font-weight: 700;
}
#SuccessGhostButton:hover {
    background: __SUCCESS_SOFT_HOVER__;
    border-color: __SUCCESS_HOVER__;
    color: __SUCCESS_HOVER__;
}
#SuccessGhostButton:pressed {
    background: __SUCCESS_SOFT_HOVER__;
    border-color: __SUCCESS__;
}
#SuccessGhostButton:disabled {
    background: __FIELD__;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#DangerGhostButton {
    background: __DANGER_SOFT__;
    border-color: __DANGER__;
    color: __DANGER__;
    font-weight: 700;
}
#DangerGhostButton:hover {
    background: __DANGER_SOFT_HOVER__;
    border-color: __DANGER__;
}
#DangerGhostButton:pressed {
    background: __DANGER_SOFT_HOVER__;
    border-color: __DANGER__;
}
#DangerGhostButton:disabled {
    background: __FIELD__;
    border-color: __LINE__;
    color: __MUTED__;
    font-weight: 600;
}
#ToolbarDivider {
    color: __LINE__;
    background: __LINE__;
    min-width: 1px;
    max-width: 1px;
    margin: __SPACE_2__ __SPACE_1__;
}
#GhostButton[chrome="nav"] {
    text-align: left;
    padding: __SPACE_2__ __SPACE_3__;
    font-weight: 600;
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE_STRONG__;
    background: __PANEL__;
    color: __HEADLINE__;
}
#GhostButton[chrome="nav"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border: 1px solid __LINE_STRONG__;
}
#GhostButton[chrome="nav"]:pressed {
    background: __BUTTON_SOFT_PRESSED__;
    border: 1px solid __LINE_STRONG__;
    padding-top: 9px;
    padding-bottom: 7px;
}
#GhostButton[chrome="nav"]:checked {
    background: __ACCENT_SOFT__;
    border: 1px solid __ACCENT__;
    border-left: 3px solid __ACCENT__;
    color: __HEADLINE__;
}
#GhostButton[chrome="nav"]:checked:hover {
    background: __ACCENT_SOFT_HOVER__;
    border: 1px solid __ACCENT_HOVER__;
    border-left: 3px solid __ACCENT_HOVER__;
}
/* Sidebar bottom row + link-page file/cache utilities: visible on light panels (avoid four identical AccentGhost). */
#GhostButton[chrome="sidebarFooter"], #NeutralToolButton {
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE_STRONG__;
    background: __PANEL__;
    color: __HEADLINE__;
    padding: __SPACE_2__ __SPACE_3__;
    font-weight: 600;
}
#GhostButton[chrome="sidebarFooter"]:hover, #NeutralToolButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton[chrome="sidebarFooter"]:pressed, #NeutralToolButton:pressed {
    background: __BUTTON_SOFT_PRESSED__;
    border-color: __LINE_STRONG__;
    padding-top: 8px;
    padding-bottom: 6px;
}
#GhostButton[chrome="sidebarFooter"]:disabled, #NeutralToolButton:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: __FIELD__;
    font-weight: 600;
}
#GhostButton[chrome="sidebarFooterGhost"] {
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE_STRONG__;
    background: __PANEL__;
    color: __HEADLINE__;
    padding: __SPACE_2__ __SPACE_3__;
    font-weight: 600;
}
#GhostButton[chrome="sidebarFooterGhost"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton[chrome="sidebarFooterGhost"]:pressed {
    background: __TRACK__;
    border-color: __LINE_STRONG__;
    padding-top: 8px;
    padding-bottom: 6px;
}
#GhostButton[chrome="sidebarFooterGhost"]:disabled {
    color: __MUTED__;
    border-color: __LINE__;
    background: __FIELD__;
    font-weight: 600;
}
#SidebarIconButton {
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE_STRONG__;
    background: __PANEL__;
    color: __HEADLINE__;
    font-weight: 700;
    padding: 0;
}
#SidebarIconButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#SidebarIconButton:pressed {
    background: __TRACK__;
    border-color: __LINE_STRONG__;
}
#SidebarDonateButton {
    border-radius: __RADIUS_MD__;
    border: 1px solid __LINE_STRONG__;
    background: __PANEL__;
    color: #e81123;
    font-weight: 700;
    padding: 0;
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
    padding: __SPACE_2__ 0;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
    color: __TEXT__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
/* Text editors: never pair pale ACCENT_SOFT with system white HighlightedText. */
QPlainTextEdit, QTextEdit {
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
QTextEdit#SearchInput, QPlainTextEdit#SearchInput {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_1__ __SPACE_3__;
    color: __TEXT__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
QTextEdit#SearchInput:focus, QPlainTextEdit#SearchInput:focus {
    border: 1px solid __ACCENT__;
}
#SearchModeSelect {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_1__ __SPACE_2__;
    min-height: 22px;
}
#SearchModeSelect::drop-down {
    width: 0px;
    border: none;
    background: transparent;
}
#SearchModeSelect::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
#SearchModeSelect QAbstractItemView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
    outline: 0;
}
#TagSuggestPopup {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#TagSearchForm {
    background: transparent;
}
#TagSearchField {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#TagSearchField[focused="true"] {
    border: 1px solid __ACCENT__;
}
#TagSearchBar {
    background: transparent;
    color: __HEADLINE__;
    border: none;
    padding: 0 __SPACE_1__;
    selection-background-color: __ACCENT_SOFT__;
}
#ComposeImagePopup {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#TagChipScroll {
    background: transparent;
    border: none;
}
#TagChipHost {
    background: transparent;
}
#TagChipButton {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
    padding: __SPACE_1__ __SPACE_3__;
    font-size: __FS_XS__;
    min-height: 22px;
}
#TagChipButton:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton[chrome="chipNav"] {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    color: __HEADLINE__;
    padding: 0;
    font-size: __FS_MD__;
    min-width: 22px;
    max-width: 22px;
    min-height: 32px;
    max-height: 32px;
}
#GhostButton[chrome="chipNav"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    border-color: __LINE_STRONG__;
}
#GhostButton[chrome="chipNav"]:disabled {
    color: __MUTED__;
    border-color: transparent;
}
#TagSuggestList {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    outline: 0;
    padding: 0;
}
#TagSuggestList::item {
    padding: __SPACE_1__ __SPACE_2__;
    min-height: 18px;
    max-height: 24px;
    border-bottom: 1px solid __LINE__;
}
#TagSuggestList::item:selected,
#TagSuggestList::item:hover {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
}
#SearchableIdCombo {
    background: transparent;
    border: none;
}
#SearchableIdComboFace {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    min-height: 28px;
}
#SearchableIdComboFace:hover {
    border-color: __LINE_STRONG__;
    background: __BUTTON_SOFT_HOVER__;
}
#SearchableIdComboText {
    background: transparent;
    border: none;
    color: __HEADLINE__;
    font-size: __FS_SM__;
    padding: 0;
}
#SearchableIdComboArrow {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 700;
    min-width: 14px;
    padding: 0 __SPACE_1__ 0 0;
}
#SearchableIdComboPopup {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
#SearchableIdComboFilter {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_2__;
}
#SearchableIdComboView {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    outline: 0;
}
#SearchableIdComboView::item {
    padding: __SPACE_2__ __SPACE_2__;
    min-height: 28px;
}
#SearchableIdComboView::item:selected {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid __FOCUS_RING__;
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
    color: __TEXT__;
    font-weight: 600;
    line-height: 1.35em;
}
#SubPanelCard QLabel[settingLabel="true"] {
    padding-top: __SPACE_1__;
    font-size: __FS_SM__;
}
QLabel[settingLabel="true"][detailActive="true"] {
    color: __ACCENT__;
    font-weight: 700;
}
#SettingHintButton {
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    max-height: 18px;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    color: __MUTED__;
    background: __FIELD__;
    font-weight: 700;
    font-size: __FS_XS__;
}
#SettingHintButton:hover {
    border-color: __ACCENT__;
    color: __ACCENT__;
    background: __ACCENT_SOFT__;
}
QSpinBox[settingField="true"], QDoubleSpinBox[settingField="true"], QComboBox[settingField="true"], QLineEdit[settingField="true"] {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
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
    border-radius: __RADIUS_MD__;
    padding: __SPACE_1__;
    outline: 0;
    selection-background-color: __ACCENT_SOFT__;
    selection-color: __HEADLINE__;
}
QComboBox[settingField="true"] QAbstractItemView::item {
    min-height: 28px;
    padding: __SPACE_1__ __SPACE_2__;
    border-radius: __RADIUS_SM__;
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
    font-size: __FS_XS__;
    font-weight: 600;
    padding: 0 __SPACE_1__ 0 0;
}
#SearchQueryTabs {
    background: transparent;
    border: none;
}
#SearchQueryTabs QTabBar {
    background: transparent;
    border: none;
    qproperty-drawBase: 0;
}
#SearchQueryTabs[barOnly="true"]::pane {
    border: none;
    background: transparent;
    max-height: 0px;
    margin: 0;
    padding: 0;
    top: 0px;
}
#SearchQueryTabs::pane, #RecapPromptTabs::pane {
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    background: __FIELD__;
    top: -1px;
}
#SearchQueryTabs QTabBar::tab {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    /* Open-bottom folder tabs make Qt stroke the top as a straight line that misses the corners. */
    padding: 3px __SPACE_2__;
    margin-top: 2px;
    margin-right: __SPACE_1__;
    min-height: 22px;
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
#RecapPromptTabs QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: __SPACE_2__ __SPACE_4__;
    margin-right: __SPACE_1__;
    color: __MUTED__;
    font-weight: 600;
}
#RecapPromptTabs QTabBar::tab:selected {
    background: transparent;
    color: __TEXT__;
    border-bottom: 2px solid __ACCENT__;
}
#RecapPromptTabs QTabBar::tab:hover {
    background: __BUTTON_SOFT__;
    color: __TEXT__;
}
#LibraryTabs::pane {
    border: none;
    background: transparent;
    top: 0;
    padding-top: __SPACE_2__;
}
#LibraryTabs QTabBar::tab {
    background: __BUTTON_SOFT__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    min-width: 112px;
    min-height: 34px;
    padding: __SPACE_2__ __SPACE_5__;
    margin-right: __SPACE_2__;
    color: __MUTED__;
    font-size: __FS_SM__;
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
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
    padding: 0;
}
/* Same family as 添加库 / 删除库; never set max-height (clips bottom borders). */
#LibrarySharedStrip #SuccessGhostButton,
#LibrarySharedStrip #DangerGhostButton {
    min-height: 28px;
    padding: __SPACE_1__ __SPACE_3__;
    border-radius: __RADIUS_MD__;
}
#LibraryChromeCaption {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    letter-spacing: 0.02em;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}
#LibraryChromeHint {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}
#LibraryStack {
    background: transparent;
    border: none;
}
#LibraryModeSegment,
#UnderstandingDialogueMode {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#GhostButton[chrome="modeSegment"] {
    background: transparent;
    border: 1px solid transparent;
    border-radius: __RADIUS_MD__;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 700;
    min-height: 26px;
    padding: __SPACE_1__ __SPACE_3__;
}
#GhostButton[chrome="modeSegment"]:hover:!checked {
    background: __BUTTON_SOFT_HOVER__;
    color: __TEXT__;
}
#GhostButton[chrome="modeSegment"]:checked {
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
    border-radius: __RADIUS_MD__;
}
#ListFindBar #ListFindStatus {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    background: transparent;
    min-width: 72px;
}
#ListFindBar #ListFindStatus[hasMatches="true"] {
    color: __ACCENT__;
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
#LibraryLibCard[focused="true"] {
    border-left: 3px solid __ACCENT__;
}
#LibraryLibCard[focused="true"] #LibraryLibHeader,
#LibraryLibCard[focused="true"][expanded="true"] #LibraryLibHeader {
    background: __ACCENT_SOFT__;
}
#LibraryLibCard[focused="true"] #LibraryLibTitle {
    color: __ACCENT__;
    font-weight: 700;
}
#LibraryLibCard[findHit="true"] {
    background: __ACCENT_SOFT__;
}
#LibraryLibCard[findHit="true"] #LibraryLibHeader,
#LibraryLibCard[findHit="true"][expanded="true"] #LibraryLibHeader {
    background: __ACCENT_SOFT__;
    border-bottom: 1px solid __ACCENT__;
}
#LibraryLibCard[findHit="true"] #LibraryLibTitle {
    color: __ACCENT__;
    font-weight: 700;
}
#LibraryLibCard[findHit="true"][findHitKind="library"] {
    border-left: 3px solid __ACCENT__;
}
#LibraryLibCard[findHit="true"][findHitKind="video"] #LibraryLibHeader {
    border-left: 2px solid __ACCENT__;
}
#LibraryLibTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 600;
}
#LibraryLibCount {
    color: __MUTED__;
    background: transparent;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
    padding: __SPACE_1__ __SPACE_2__;
    font-size: __FS_XS__;
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
    font-size: __FS_XS__;
    font-weight: 600;
    padding: __SPACE_1__ __SPACE_2__;
    min-height: 22px;
    border-radius: __RADIUS_SM__;
}
#LibraryLibAction:hover {
    background: __BUTTON_SOFT__;
    color: __TEXT__;
}
#LibraryLibSyncStatus {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    padding: __SPACE_1__ __SPACE_2__;
    min-height: 22px;
}
#LibraryLibSyncStatus[libSync="needs_fix"] {
    color: __WARN__;
}
#LibraryLibSyncStatus[libSync="offline"] {
    color: __MUTED__;
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
    font-size: __FS_XS__;
    font-weight: 600;
    padding: 0 __SPACE_1__;
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
    padding: __SPACE_1__ __SPACE_3__ __SPACE_1__ __SPACE_3__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
    font-size: __FS_SM__;
    color: __TEXT__;
}
QTableView#LibraryGroupedLibTree::item:hover {
    background: __ACCENT_SOFT__;
}
QTableView#LibraryGroupedLibTree::item:selected,
QTableView#LibraryGroupedLibTree::item:selected:active,
QTableView#LibraryGroupedLibTree::item:selected:!active {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
    font-weight: 600;
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
    border-radius: __RADIUS_LG__;
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
    border-radius: __RADIUS_MD__;
    padding: __SPACE_3__;
}
#ImageQueryInput {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#ImageQueryInput:hover {
    border-color: __ACCENT__;
}
#ImageQueryInput[filled="true"] {
    background: __FIELD__;
    border: 1px solid __LINE_STRONG__;
}
#ImageQueryInput[filled="true"]:hover {
    border-color: __ACCENT__;
}
#ImageQueryInputText {
    background: transparent;
    border: none;
    color: __MUTED__;
    font-size: __FS_SM__;
    font-weight: 500;
    padding: 0;
}
#ImageQueryInput[filled="true"] #ImageQueryInputText {
    color: __TEXT__;
    font-weight: 500;
}
#ImageQueryThumbPic {
    background: transparent;
    border: none;
    padding: 0;
}
#GhostButton[chrome="imageClear"] {
    background: transparent;
    border: none;
    border-radius: __RADIUS_SM__;
    color: __MUTED__;
    font-size: __FS_MD__;
    font-weight: 500;
    padding: 0;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}
#GhostButton[chrome="imageClear"]:hover {
    background: __BUTTON_SOFT_HOVER__;
    color: __DANGER__;
    padding: 0;
}
#GhostButton[chrome="imageClear"]:pressed {
    background: __BUTTON_SOFT_HOVER__;
    color: __DANGER__;
    padding: 0;
}
#ImageQueryPreview {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#ImageQueryPreview QLabel {
    background: transparent;
    border: none;
    padding: 0;
}
#ImageQueryPath {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 400;
    padding: 0;
}
#SearchPreviewStripThumb {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
    padding: 0;
}
#SearchPreviewStripThumb[selected="true"] {
    border: 2px solid __ACCENT__;
}
#SearchPreviewStripCaption {
    color: __MUTED__;
    font-size: __FS_XS__;
    padding: 0;
    background: transparent;
}
#PreviewPlaceholder {
    /* Fill the preview host; do not force a tall min (starves the results splitter). */
    min-height: 0px;
}
#ThumbPreview {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
}
#ThumbPreview:hover {
    border-color: __ACCENT__;
}
QSplitter#SearchCompareSplitter {
    background: transparent;
}
QSplitter#SearchCompareSplitter::handle {
    background: transparent;
    margin: 0 __SPACE_1__;
    border-radius: __RADIUS_SM__;
}
QSplitter#SearchCompareSplitter::handle:hover,
QSplitter#SearchCompareSplitter::handle:pressed {
    background: __LINE_STRONG__;
}
QSplitter#SearchWorkspaceSplitter {
    background: transparent;
}
QSplitter#SearchWorkspaceSplitter::handle {
    background: transparent;
    margin: __SPACE_1__ 0;
    border-radius: __RADIUS_SM__;
}
QSplitter#SearchWorkspaceSplitter::handle:hover,
QSplitter#SearchWorkspaceSplitter::handle:pressed {
    background: __LINE_STRONG__;
}
#VideoContainer {
    background: __VIDEO_BG__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#PreviewTimeLabel {
    color: __HEADLINE__;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: __FS_SM__;
    font-weight: 700;
    padding: __SPACE_1__ __SPACE_2__;
    background: __TRACK__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    min-width: 102px;
}
#PreviewDialog QPushButton {
    padding: __SPACE_1__ __SPACE_3__;
}
#PreviewSegmentQueueHint {
    color: #38bdf8;
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
    padding: 0 __SPACE_1__ __SPACE_1__ __SPACE_1__;
}
#PreviewCaption {
    color: transparent;
    font-size: __FS_MD__;
    font-weight: 700;
    background: transparent;
    border: none;
    padding: __SPACE_2__ __SPACE_1__;
}
#ResultTable, #DataTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    gridline-color: transparent;
    outline: none;
    selection-background-color: __SELECTION_BG__;
    selection-color: __HEADLINE__;
}
#ResultTable::item, #DataTable::item {
    border-left: none;
    border-right: none;
    border-top: none;
    border-bottom: 1px solid __LINE__;
    padding: __SPACE_2__ __SPACE_3__;
    color: __TEXT__;
}
#ResultTable::item:hover, #DataTable::item:hover {
    background: __BUTTON_SOFT_HOVER__;
    color: __TEXT__;
}
#ResultTable::item:selected, #DataTable::item:selected {
    background: __SELECTION_BG__;
    color: __HEADLINE__;
    border-bottom: 1px solid __LINE__;
}
#ResultTable::item:selected:active, #DataTable::item:selected:active {
    background: __SELECTION_BG__;
    color: __HEADLINE__;
}
#ResultTable::item:selected:!active, #DataTable::item:selected:!active {
    background: __SELECTION_BG__;
    color: __HEADLINE__;
}
/* Inline cell editors: global QLineEdit padding is too fat for table rows. */
#ResultTable QLineEdit, #DataTable QLineEdit {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_SM__;
    padding: __SPACE_1__ __SPACE_2__;
    margin: 0;
    min-height: 22px;
    font-size: __FS_SM__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
#ResultGrid {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#ResultGridHost {
    background: transparent;
}
#ResultGridCard {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
#ResultGridCard:hover {
    border-color: __ACCENT__;
    background: __BUTTON_SOFT__;
}
#ResultGridCard[selected="true"] {
    border-color: __ACCENT__;
    background: __ACCENT_SOFT__;
}
#ResultGridThumb {
    background: __TRACK__;
    border: none;
    border-radius: __RADIUS_MD__;
}
#ResultGridRank {
    background: __ACCENT_SOFT__;
    color: __ACCENT__;
    border-radius: __RADIUS_MD__;
    font-size: __FS_XS__;
    font-weight: 700;
}
#ResultGridTitle {
    color: __HEADLINE__;
    font-size: __FS_XS__;
    font-weight: 650;
    background: transparent;
    border: none;
    padding: 0;
}
#ResultGridMeta {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    background: transparent;
    border: none;
    padding: 0;
}
#ResultGridActions {
    background: transparent;
    border: none;
}
#DownloadListTable {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    gridline-color: transparent;
    outline: none;
}
#DownloadListTable::item {
    border: none;
    border-bottom: 1px solid __LINE__;
    padding: __SPACE_3__ __SPACE_2__;
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
    padding: __SPACE_2__ __SPACE_3__;
    color: __MUTED__;
    font-size: __FS_XS__;
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
    border-radius: __RADIUS_MD__;
    padding: 0 __SPACE_2__;
    min-height: 28px;
    max-height: 28px;
    font-size: __FS_XS__;
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
    border-radius: __RADIUS_MD__;
    color: __HEADLINE__;
    font-size: __FS_XS__;
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
    border-radius: __RADIUS_MD__;
    min-height: 22px;
    max-height: 22px;
    text-align: center;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    padding: __SPACE_1__;
}
#DownloadRowProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 __ACCENT__, stop:1 __ACCENT_HOVER__);
    border-radius: __RADIUS_MD__;
    margin: __SPACE_1__;
}
#ThumbPreview[gapFrameRow="true"] {
    background: __WARN_SOFT__;
    border: 2px solid __ACCENT__;
    border-radius: __RADIUS_MD__;
    color: __ACCENT__;
    font-weight: 700;
}
#ThumbPreview[gapChainRow="true"] {
    background: __WARN_SOFT__;
    border: 2px solid __WARN__;
    border-radius: __RADIUS_MD__;
    color: __WARN__;
    font-weight: 700;
}
QWidget[gapFrameRow="true"] {
    background: __WARN_SOFT__;
    border-radius: __RADIUS_MD__;
}
QWidget[gapChainRow="true"] {
    background: __WARN_SOFT__;
    border-radius: __RADIUS_MD__;
}
#ThumbPreview[strongCoherentRow="true"] {
    background: __SUCCESS_SOFT__;
    border: 2px solid __SUCCESS__;
    border-radius: __RADIUS_MD__;
    color: __SUCCESS__;
    font-weight: 700;
}
#ThumbPreview[strongJumpRow="true"] {
    background: __DANGER_SOFT__;
    border: 2px solid __DANGER__;
    border-radius: __RADIUS_MD__;
    color: __DANGER__;
    font-weight: 700;
}
QWidget[strongCoherentRow="true"] {
    background: __SUCCESS_SOFT__;
    border-radius: __RADIUS_MD__;
}
QWidget[strongJumpRow="true"] {
    background: __DANGER_SOFT__;
    border-radius: __RADIUS_MD__;
}
#ResultTable QHeaderView::section, #DataTable QHeaderView::section {
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-right: 1px solid __LINE__;
    padding: __SPACE_2__ __SPACE_3__;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
}
#RecapReviewPanel {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
#RecapReviewDetail {
    color: __TEXT__;
    font-size: __FS_XS__;
    font-weight: 500;
    line-height: 1.35em;
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
    min-height: 76px;
    max-height: 110px;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
#RecapReviewTree {
    background: __PANEL__;
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_MD__;
    outline: none;
    show-decoration-selected: 1;
    selection-background-color: transparent;
    selection-color: __HEADLINE__;
}
#RecapReviewTree::item {
    min-height: 32px;
    padding: 0;
    border: none;
    color: __TEXT__;
}
#RecapReviewTree::item:hover,
#RecapReviewTree::item:selected,
#RecapReviewTree::item:selected:active,
#RecapReviewTree::item:selected:!active {
    background: transparent;
    color: __HEADLINE__;
}
#RecapReviewTree::branch {
    background: transparent;
    border: none;
}
#RecapReviewTree QHeaderView::section {
    background: __FIELD__;
    border: none;
    border-bottom: 2px solid __LINE_STRONG__;
    border-right: 1px solid __LINE__;
    padding: __SPACE_2__ __SPACE_3__;
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
}
#RecapChunkPickScroll {
    background: transparent;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#RecapChunkSwatchOwned {
    background: __SUCCESS__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
}
#RecapChunkSwatchUsed {
    background: __WARN__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
}
#RecapChunkSwatchFree {
    background: __LINE_STRONG__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_SM__;
}
#RecapChunkSwatchPick {
    background: transparent;
    border: 2px solid __ACCENT__;
    border-radius: __RADIUS_SM__;
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
    font-size: __FS_XS__;
    font-weight: 700;
    letter-spacing: 0.02em;
}
#LibraryCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
}
#LibraryCard:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#LibraryCardIndex {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 700;
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}
#LibraryCardTitle {
    color: __HEADLINE__;
    font-size: __FS_MD__;
    font-weight: 700;
}
#LibraryCardSubpath {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
}
#LibraryEmptyHint {
    color: __MUTED__;
    font-size: __FS_SM__;
    font-weight: 600;
    padding: __SPACE_6__ __SPACE_4__;
}
/* --- Dialog & popup chrome (object names + theme tokens) --- */
QDialog#VSDialogShell,
QDialog#AppBusyDialog {
    background: __WINDOW__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
QDialog#AppBusyDialog #DialogBodyLabel {
    min-height: 36px;
}
QProgressBar#DialogBusyProgress {
    background: __TRACK__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    max-height: 10px;
    min-height: 8px;
    text-align: center;
}
QProgressBar#DialogBusyProgress::chunk {
    background: __ACCENT__;
    border-radius: __RADIUS_SM__;
}
QFrame#Card, #DialogCard {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
#DialogHeader {
    background: transparent;
    border: none;
}
#DialogContent {
    background: transparent;
    border: none;
}
#DialogFooter {
    background: transparent;
    border: none;
    border-top: 1px solid __LINE__;
}
#DialogFooter #PrimaryButton,
#DialogFooter #GhostButton,
#DialogFooter #DangerGhostButton,
#DialogFooter #SuccessGhostButton,
#DialogFooter #AccentGhostButton,
#DialogFooter #NeutralToolButton {
    min-height: 34px;
    padding: __SPACE_2__ __SPACE_4__;
    border-radius: __RADIUS_MD__;
}
#ToolbarCard, #DetailsCard, #StatusCard, #PreviewCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
}
#DialogToolbar {
    background: transparent;
    border: none;
}
#DialogTableHost {
    background: transparent;
    border: none;
}
#DialogMetaLine {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    background: transparent;
    padding: 0 __SPACE_1__;
}
#DialogStatusHint {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
    padding: __SPACE_1__ __SPACE_1__ 0 __SPACE_1__;
}
#AppBusyDialog #DialogFooter,
QDialog#VSDialogShell #DialogFooter {
    margin-top: __SPACE_1__;
}
#SummaryCard {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_3__;
}
#SummaryValue {
    color: __HEADLINE__;
    font-size: __FS_MD__;
    font-weight: 800;
    background: transparent;
}
#SummaryLabel {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
}
#DialogHeroTitle {
    font-size: __FS_LG__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogPageTitle {
    font-size: __FS_LG__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogHeadline {
    font-size: __FS_XL__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogSectionTitle {
    font-size: __FS_LG__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#DialogInlineTitle {
    font-size: __FS_SM__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#Hint {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
}
#DialogMetaLabel {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
}
#DialogBodyLabel {
    color: __MUTED__;
    font-size: __FS_SM__;
    font-weight: 400;
    background: transparent;
    line-height: 1.45em;
}
QFrame#ExportModeOptionCard {
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
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
    font-size: __FS_MD__;
    font-weight: 700;
    color: __HEADLINE__;
    background: transparent;
}
#ExportModeSubtitle {
    font-size: __FS_XS__;
    color: __MUTED__;
    background: transparent;
}
#SectionTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
}
#DialogBodyBrowser {
    background: __FIELD__;
    color: __MUTED__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_3__;
    font-size: __FS_SM__;
}
#DialogCodeBox {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    padding: __SPACE_3__ __SPACE_3__;
    color: __HEADLINE__;
    font-weight: 600;
}
#DialogDivider {
    color: __LINE__;
    background: __LINE__;
    border: none;
    max-height: 1px;
    min-height: 1px;
    margin: __SPACE_2__ 0;
}
#DialogPlainBody {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
    padding: __SPACE_3__;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: __FS_XS__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
#MessageBadge {
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: __RADIUS_MD__;
    color: __INVERSE_TEXT__;
    font-size: __FS_XS__;
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
#ModelImportGuide {
    border: 1px solid __LINE__;
    border-radius: __RADIUS_LG__;
    background: __TRACK__;
}
#ModelImportGuide #SectionLabel {
    color: __HEADLINE__;
    font-size: __FS_XS__;
    font-weight: 700;
}
#ModelImportGuideSubTitle {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 700;
    margin-top: __SPACE_2__;
    padding-top: __SPACE_1__;
    background: transparent;
}
#ModelImportGuideLine {
    color: __TEXT__;
    font-size: __FS_XS__;
    line-height: 1.35;
    background: transparent;
}
#ModelUploadArea {
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_LG__;
    background: __TRACK__;
    min-height: 88px;
}
#ModelUploadArea:hover {
    border-color: __ACCENT__;
    background: __ACCENT_SOFT__;
}
#ModelUploadIcon {
    background: __PANEL__;
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_MD__;
}
#ModelUploadTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
}
#ModelUploadMeta {
    color: __MUTED__;
    font-size: __FS_XS__;
    background: transparent;
}
#ModelUploadAction {
    color: __ACCENT__;
    font-size: __FS_XS__;
    font-weight: 600;
    background: transparent;
}
#ModelResourceStatusInline {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
}
#ModelResourceStatusBar {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    min-width: 148px;
}
#ModelResourceStatusChip {
    font-size: __FS_XS__;
    font-weight: 600;
}
QDialog#ModelImportDialog {
    background: __WINDOW__;
}
QDialog#ModelImportDialog QFrame#Card {
    background: __PANEL__;
    border: 1px solid __LINE_STRONG__;
}
QListWidget#ModelFileList {
    border: none;
    background: transparent;
    padding: 0;
    outline: 0;
}
QListWidget#ModelFileList::item {
    padding: 0;
    margin: 0 0 __SPACE_2__ 0;
    border: none;
    background: transparent;
}
QListWidget#ModelFileList::item:selected {
    background: transparent;
}
#ModelPendingPanel {
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_LG__;
    background: __TRACK__;
}
#ModelPendingPanel #SectionLabel {
    color: __HEADLINE__;
    font-size: __FS_XS__;
    font-weight: 700;
}
#ModelPendingCount {
    color: __ACCENT__;
    font-size: __FS_XS__;
    font-weight: 700;
}
#ModelPendingRow {
    border: 1px solid __LINE_STRONG__;
    border-radius: __RADIUS_MD__;
    background: __PANEL__;
}
#ModelPendingRow:hover {
    border-color: __ACCENT__;
}
#ModelPendingRow[selected="true"] {
    border: 2px solid __ACCENT__;
    background: __ACCENT_SOFT__;
}
#ModelPendingRowName {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 600;
}
#ModelPendingRowMeta {
    color: __MUTED__;
    font-size: __FS_XS__;
}
#ModelPendingKind {
    color: __ACCENT__;
    font-size: __FS_XS__;
    font-weight: 700;
    padding: __SPACE_1__ __SPACE_3__;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_SM__;
    background: __ACCENT_SOFT__;
}
QListWidget#ModelInstalledList {
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    background: __PANEL__;
    padding: __SPACE_1__;
    outline: 0;
}
QListWidget#ModelInstalledList::item {
    padding: __SPACE_2__ __SPACE_3__;
    border-radius: __RADIUS_MD__;
    color: __TEXT__;
    font-size: __FS_XS__;
}
#SectionLabel {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 700;
}
QListWidget#UnderstandingServiceNav {
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    background: __PANEL__;
    padding: __SPACE_2__;
    outline: 0;
}
QListWidget#UnderstandingServiceNav::item {
    padding: __SPACE_3__ __SPACE_3__;
    border-radius: __RADIUS_MD__;
    margin: __SPACE_1__ 0;
    border: 1px solid transparent;
    color: __TEXT__;
}
QListWidget#UnderstandingServiceNav::item:hover {
    background: __FIELD__;
    border-color: __LINE__;
}
QListWidget#UnderstandingServiceNav::item:selected {
    background: __FIELD__;
    color: __HEADLINE__;
    border-color: __ACCENT__;
}
QScrollArea#DialogScroll {
    background: transparent;
    border: none;
}
QListWidget#DialogueLibraryList {
    border: none;
    background: transparent;
    padding: __SPACE_1__ 0;
    outline: 0;
}
QListWidget#DialogueLibraryList::item {
    padding: 0;
    margin: 0 0 __SPACE_2__ 0;
    border: none;
    background: transparent;
}
QListWidget#DialogueLibraryList::item:selected {
    background: transparent;
}
#DialogueLibraryRow {
    background: __FIELD__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
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
    font-size: __FS_SM__;
    font-weight: 700;
}
#DialogueLibraryRowMeta {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
}
#DialogueLibraryRowBadge {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 700;
    padding: __SPACE_1__ __SPACE_3__;
    border-radius: __RADIUS_PILL__;
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
    border-radius: __RADIUS_MD__;
    padding: __SPACE_2__ __SPACE_4__;
}
#DialogRulesTable, #ResourceDialogTable {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_MD__;
    gridline-color: transparent;
    outline: none;
    padding: __SPACE_1__;
}
#DialogRulesTable::item, #ResourceDialogTable::item {
    background: transparent;
    padding: __SPACE_2__ __SPACE_3__;
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
#DialogRulesTable QLineEdit, #ResourceDialogTable QLineEdit {
    background: __FIELD__;
    color: __HEADLINE__;
    border: 1px solid __ACCENT__;
    border-radius: __RADIUS_SM__;
    padding: __SPACE_1__ __SPACE_2__;
    margin: 0;
    min-height: 22px;
    font-size: __FS_SM__;
    selection-background-color: __ACCENT__;
    selection-color: __INVERSE_TEXT__;
}
#DialogRulesTable QHeaderView::section, #ResourceDialogTable QHeaderView::section {
    color: __MUTED__;
    background: __PANEL__;
    border: none;
    border-bottom: 1px solid __LINE__;
    padding: __SPACE_3__ __SPACE_3__;
    font-weight: 700;
    font-size: __FS_XS__;
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
    padding: 0 __SPACE_1__;
    font-size: __FS_SM__;
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
    border-radius: __RADIUS_MD__;
}
#SettingDetailPopupTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
}
#SettingDetailPopupBody {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 600;
    line-height: 1.45em;
    background: transparent;
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
    border-radius: __RADIUS_MD__;
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
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
}
#SearchScopeLibPath {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
}
#SearchScopeLibBadge {
    background: transparent;
    border: none;
    padding: 0 __SPACE_1__;
    font-size: __FS_XS__;
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
    border-radius: __RADIUS_MD__;
}
#SearchPresetManageRow:hover {
    background: __BUTTON_SOFT__;
    border-color: __LINE__;
}
#SearchPresetManageAccent {
    background: __ACCENT__;
    border-radius: __RADIUS_SM__;
}
#SearchPresetManageTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
    font-weight: 700;
    background: transparent;
}
#SearchPresetManageDesc {
    color: __MUTED__;
    font-size: __FS_XS__;
    font-weight: 500;
    background: transparent;
}
#SearchPresetManageBadge {
    background: __PANEL__;
    border: 1px solid __LINE__;
    border-radius: __RADIUS_PILL__;
    padding: __SPACE_1__ __SPACE_3__;
    font-size: __FS_XS__;
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
    border-radius: __RADIUS_MD__;
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
#VideoScopeLibCard[focused="true"] {
    border-left: 3px solid __ACCENT__;
}
#VideoScopeLibCard[focused="true"] #VideoScopeLibHeader,
#VideoScopeLibCard[focused="true"][expanded="true"] #VideoScopeLibHeader {
    background: __ACCENT_SOFT__;
}
#VideoScopeLibCard[focused="true"] #VideoScopeLibTitle {
    color: __ACCENT__;
    font-weight: 700;
}
#VideoScopeLibCard[findHit="true"] {
    background: __ACCENT_SOFT__;
}
#VideoScopeLibCard[findHit="true"] #VideoScopeLibHeader,
#VideoScopeLibCard[findHit="true"][expanded="true"] #VideoScopeLibHeader {
    background: __ACCENT_SOFT__;
    border-bottom: 1px solid __ACCENT__;
}
#VideoScopeLibCard[findHit="true"] #VideoScopeLibTitle {
    color: __ACCENT__;
    font-weight: 700;
}
#VideoScopeLibCard[findHit="true"][findHitKind="library"] {
    border-left: 3px solid __ACCENT__;
}
#VideoScopeLibCard[findHit="true"][findHitKind="video"] #VideoScopeLibHeader {
    border-left: 2px solid __ACCENT__;
}
#VideoScopeLibTitle {
    color: __HEADLINE__;
    font-size: __FS_SM__;
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
    padding: __SPACE_1__ __SPACE_3__ __SPACE_1__ __SPACE_3__;
    border: none;
    border-bottom: 1px solid __LINE__;
    border-radius: 0;
    font-size: __FS_SM__;
    color: __TEXT__;
}
QTableView#VideoScopeLibTree::item:hover {
    background: __ACCENT_SOFT__;
}
QTableView#VideoScopeLibTree::item:selected,
QTableView#VideoScopeLibTree::item:selected:active,
QTableView#VideoScopeLibTree::item:selected:!active {
    background: __ACCENT_SOFT__;
    color: __HEADLINE__;
    font-weight: 600;
}
#VideoScopeLibBody {
    background: transparent;
    border: none;
}
QHeaderView::section {
    background: transparent;
    border: none;
    color: __MUTED__;
    padding: __SPACE_2__;
    font-weight: 700;
}
QTableCornerButton::section {
    background: transparent;
    border: none;
}
QProgressBar {
    background: __FIELD__;
    border: none;
    border-radius: __RADIUS_SM__;
    height: 8px;
}
QProgressBar::chunk {
    background: __ACCENT__;
    border-radius: __RADIUS_SM__;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: __SPACE_1__ __SPACE_1__ __SPACE_1__ __SPACE_1__;
}
QScrollBar::handle:vertical {
    background: __SCROLL__;
    border-radius: __RADIUS_SM__;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: __LINE_STRONG__;
}
QScrollBar:horizontal {
    /* Bottom bars need a real hit target — 8px was effectively unclickable. */
    background: __LINE__;
    height: 14px;
    margin: __SPACE_1__ __SPACE_1__ __SPACE_1__ __SPACE_1__;
    border-radius: __RADIUS_MD__;
}
QScrollBar::handle:horizontal {
    background: __SCROLL__;
    border-radius: __RADIUS_MD__;
    min-width: 40px;
    min-height: 10px;
    margin: __SPACE_1__ __SPACE_1__;
}
QScrollBar::handle:horizontal:hover {
    background: __LINE_STRONG__;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    width: 0;
    height: 0;
}
#ResourceDialogTable QScrollBar:horizontal,
#DialogRulesTable QScrollBar:horizontal,
#ResultTable QScrollBar:horizontal,
#DataTable QScrollBar:horizontal {
    height: 16px;
    margin: __SPACE_1__ __SPACE_2__ __SPACE_1__ __SPACE_2__;
}
QPushButton[class="TableBtn"], QPushButton[class="TableLocateBtn"], QPushButton[class="TableDeleteBtn"],
#GhostButton[class="TableBtn"],
#SuccessGhostButton[class="TableBtn"],
#SuccessGhostButton[class="TableLocateBtn"],
#DangerGhostButton[class="TableDeleteBtn"] {
    background: transparent;
    border: 1px solid transparent;
    padding: __SPACE_1__ __SPACE_2__;
    border-radius: __RADIUS_MD__;
    font-weight: 600;
    min-height: 0px;
}
#GhostButton[class="TableBtn"]:pressed,
#SuccessGhostButton[class="TableBtn"]:pressed,
#SuccessGhostButton[class="TableLocateBtn"]:pressed,
#DangerGhostButton[class="TableDeleteBtn"]:pressed {
    padding: __SPACE_1__ __SPACE_2__;
    border-color: transparent;
}
#GhostButton[class="TableBtn"]:disabled,
#SuccessGhostButton[class="TableBtn"]:disabled,
#SuccessGhostButton[class="TableLocateBtn"]:disabled,
#DangerGhostButton[class="TableDeleteBtn"]:disabled {
    background: transparent;
    border-color: transparent;
    color: __MUTED__;
}
QPushButton[class="TableBtn"],
#GhostButton[class="TableBtn"] {
    color: __ACCENT__;
}
QPushButton[class="TableBtn"]:hover,
#GhostButton[class="TableBtn"]:hover {
    background: __ACCENT_SOFT__;
}
QPushButton[class="TableLocateBtn"],
#SuccessGhostButton[class="TableLocateBtn"],
#SuccessGhostButton[class="TableBtn"] {
    color: __SUCCESS__;
}
QPushButton[class="TableLocateBtn"]:hover,
#SuccessGhostButton[class="TableLocateBtn"]:hover,
#SuccessGhostButton[class="TableBtn"]:hover {
    background: __SUCCESS_SOFT__;
}
QPushButton[class="TableDeleteBtn"],
#DangerGhostButton[class="TableDeleteBtn"] {
    color: __DANGER__;
}
QPushButton[class="TableDeleteBtn"]:hover,
#DangerGhostButton[class="TableDeleteBtn"]:hover {
    background: __DANGER_SOFT__;
}
QToolTip, QMessageBox, QDialog {
    background: __PANEL__;
    color: __HEADLINE__;
    border: 1px solid __LINE__;
}
QDialog {
    border-radius: __RADIUS_MD__;
}
QToolTip {
    /* Width/wrapping handled by ui.widgets.tooltip_utils (QSS max-width clips CJK). */
    padding: __SPACE_2__ __SPACE_2__;
    border-radius: __RADIUS_MD__;
}
"""


def _qss_url(path: str) -> str:
    """Qt stylesheet url() path: forward slashes, escaped for Windows."""
    import os

    text = os.path.normpath(str(path or "")).replace("\\", "/")
    return text.replace("'", "\\'")


_FONT_SCALE_STEPS = {"FS_XS": 12, "FS_SM": 14, "FS_MD": 16, "FS_LG": 18, "FS_XL": 22}
_RADIUS_TOKENS = {
    "RADIUS_SM": "4px",
    "RADIUS_MD": "8px",
    "RADIUS_LG": "12px",
    "RADIUS_PILL": "999px",
}
_SPACE_TOKENS = {
    "SPACE_1": "4px",
    "SPACE_2": "8px",
    "SPACE_3": "12px",
    "SPACE_4": "16px",
    "SPACE_5": "24px",
    "SPACE_6": "32px",
}


def font_scale_for_screen(screen=None) -> float:
    """Logical DPI relative to 96. Qt 6 already scales paint by devicePixelRatio."""
    if screen is None:
        try:
            from PySide6.QtGui import QGuiApplication
        except ImportError:
            return 1.0
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    dpi = float(screen.logicalDotsPerInch() or 96.0)
    return max(0.8, min(2.0, dpi / 96.0))


def _font_size_tokens(scale: float = 1.0) -> dict:
    scale = max(0.8, min(2.0, float(scale or 1.0)))
    return {
        name: f"{max(9, int(round(logical * scale)))}px"
        for name, logical in _FONT_SCALE_STEPS.items()
    }


def _replace_tokens(style: str, tokens: dict) -> str:
    for key, value in tokens.items():
        style = style.replace(f"__{key}__", value)
    return style


def build_style(colors, font_scale: float = 1.0):
    from src.infra.paths import get_resource_path

    style = _replace_tokens(STYLE_TEMPLATE, colors)
    style = _replace_tokens(style, _font_size_tokens(font_scale))
    style = _replace_tokens(style, _RADIUS_TOKENS)
    style = _replace_tokens(style, _SPACE_TOKENS)
    check_icon = _qss_url(get_resource_path("resources/icons/check.png"))
    partial_icon = _qss_url(get_resource_path("resources/icons/check_partial.png"))
    style = style.replace("__CHECK_ICON__", check_icon)
    style = style.replace("__CHECK_PARTIAL_ICON__", partial_icon)
    return style


from ui.widgets.theme_tokens import load_merged_theme_colors

THEME_COLORS_DARK_BASE = {
    # Win11-like neutral layers (less cold blue-black).
    "WINDOW": "#181818",
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
    "SIDEBAR": "#121212",
    "PANEL": "#2e2e2e",
    "FIELD": "#242424",
    "HERO": "#262626",
    "HERO_LINE": "#454545",
    "LINE": "#454545",
    "LINE_STRONG": "#525252",
    "TRACK": "#2f2f2f",
    "SCROLL": "#6b6b6b",
    "BUTTON_SOFT": "#3a3a3a",
    "BUTTON_SOFT_HOVER": "#4a4a4a",
    "BUTTON_SOFT_PRESSED": "#323232",
    "ACCENT_SOFT_HOVER": "#2a5080",
    "DANGER_SOFT_HOVER": "#6b2a2a",
    "SUCCESS_SOFT_HOVER": "#165c3e",
    "OVERLAY_HOVER": "rgba(255,255,255,0.06)",
    "OVERLAY_ACTIVE": "rgba(255,255,255,0.10)",
    "OVERLAY_PRESS": "rgba(0,0,0,0.18)",
    "SELECTION_BG": "rgba(96,165,250,0.18)",
    "FOCUS_RING": "rgba(96,165,250,0.45)",
    "SCRIM": "rgba(0,0,0,0.45)",
    "VIDEO_BG": "#141414",
    "NOTICE_BG": "#1e3a5f",
    "NOTICE_LINE": "#60a5fa",
    "NOTICE_TEXT": "#e8f1ff",
    "INVERSE_TEXT": "#ffffff",
}

THEME_COLORS_LIGHT_BASE = {
    # Win11-like gray shell; accent stays product blue.
    "WINDOW": "#e8e8e8",
    "TEXT": "#2b2b2b",
    "HEADLINE": "#1a1a1a",
    "MUTED": "#6b6b6b",
    "ACCENT": "#0078d4",
    "ACCENT_HOVER": "#1a86d9",
    "ACCENT_SOFT": "#e8f3fc",
    "SUCCESS": "#0f7b3a",
    "SUCCESS_HOVER": "#159345",
    "SUCCESS_SOFT": "#e6f5ec",
    "WARN": "#7a4f00",
    "WARN_SOFT": "#fff4ce",
    "DANGER": "#c42b1c",
    "DANGER_SOFT": "#fde7e9",
    "SIDEBAR": "#f2f2f2",
    "PANEL": "#ffffff",
    "FIELD": "#f6f6f6",
    "HERO": "#e8e8e8",
    "HERO_LINE": "#d4d4d4",
    "LINE": "#d4d4d4",
    "LINE_STRONG": "#bdbdbd",
    "TRACK": "#e4e4e4",
    "SCROLL": "#b0b0b0",
    "BUTTON_SOFT": "#f3f3f3",
    "BUTTON_SOFT_HOVER": "#e2e2e2",
    "BUTTON_SOFT_PRESSED": "#d8d8d8",
    "ACCENT_SOFT_HOVER": "#d0e7f8",
    "DANGER_SOFT_HOVER": "#f8d0d4",
    "SUCCESS_SOFT_HOVER": "#cfead9",
    "OVERLAY_HOVER": "rgba(0,0,0,0.04)",
    "OVERLAY_ACTIVE": "rgba(0,0,0,0.07)",
    "OVERLAY_PRESS": "rgba(0,0,0,0.12)",
    "SELECTION_BG": "rgba(0,120,212,0.14)",
    "FOCUS_RING": "rgba(0,120,212,0.40)",
    "SCRIM": "rgba(0,0,0,0.25)",
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

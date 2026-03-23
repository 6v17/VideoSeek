# src/styles.py

# ========== 公共样式 ==========
COMMON_STYLE = """
/* 全局字体与平滑渲染 */
QMainWindow {
    font-family: "Segoe UI", "Microsoft YaHei", "Helvetica Neue", sans-serif;
    font-size: 13px;
}
/* 全局字体与平滑渲染 */
QMainWindow {
    font-family: "Segoe UI", "Microsoft YaHei", "Helvetica Neue", sans-serif;
    font-size: 13px;
}

/* 表格单元格内边距 */
QTableWidget::item {
    padding: 8px 6px;
}

/* 让预览列图片和文字居中对齐更舒服 */
QTableWidget::item:selected {
    background-color: rgba(0, 120, 212, 0.2);
}

/* 进度条 — 细线风格 */
QProgressBar {
    border: none;
    background-color: rgba(128, 128, 128, 0.2);
    height: 5px;
    border-radius: 2px;
}
QProgressBar::chunk {
    background-color: #0078D4;
    border-radius: 2px;
}

/* 表格头部加一点内边距 */
QHeaderView::section {
    padding: 10px 4px;
    border: none;
    font-weight: 500;
    background-color: transparent;
}
QTableWidget {
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: rgba(0, 120, 212, 0.2);
}

/* 分割线 */
#Separator {
    background-color: rgba(128, 128, 128, 0.2);
    max-height: 1px;
    margin: 14px 0;
}

/* 滚动条 — 扁平现代风格 */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(128, 128, 128, 0.5);
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(128, 128, 128, 0.7);
}
QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
    border: none;
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 8px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: rgba(128, 128, 128, 0.5);
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(128, 128, 128, 0.7);
}
QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal {
    border: none;
    background: none;
    width: 0;
}

/* 通用按钮过渡 */
QPushButton {
    border-radius: 6px;
    padding: 8px 14px;
    transition: background 0.2s ease;
}
QPushButton:hover {
    transition: background 0.1s ease;
}
QPushButton:pressed {
    padding-top: 9px;
    padding-bottom: 7px;
}

/* 输入框 */
QLineEdit {
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #0078D4;
}
/* 进度条 — 细线风格 */
QProgressBar {
    border: none;
    background-color: rgba(128, 128, 128, 0.2);
    height: 4px;
    border-radius: 2px;
}
QProgressBar::chunk {
    background-color: #0078D4;
    border-radius: 2px;
}

/* 表格头部 */
QHeaderView::section {
    padding: 8px;
    border: none;
    font-weight: 500;
    background-color: transparent;
}
QTableWidget {
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: rgba(0, 120, 212, 0.2);
}

/* 分割线 */
#Separator {
    background-color: rgba(128, 128, 128, 0.2);
    max-height: 1px;
    margin: 12px 0;
}

/* 滚动条 — 扁平现代风格 */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(128, 128, 128, 0.5);
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(128, 128, 128, 0.7);
}
QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
    border: none;
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 8px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: rgba(128, 128, 128, 0.5);
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(128, 128, 128, 0.7);
}
QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal {
    border: none;
    background: none;
    width: 0;
}

/* 通用按钮过渡 */
QPushButton {
    border-radius: 6px;
    padding: 6px 12px;
    transition: background 0.2s ease;
}
QPushButton:hover {
    transition: background 0.1s ease;
}
QPushButton:pressed {
    padding-top: 7px;
    padding-bottom: 5px;
}

/* 输入框 */
QLineEdit {
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #0078D4;
}

/* 下拉框 */
QComboBox {
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid;
    margin-right: 8px;
}

/* 复选框、单选框 */
QCheckBox, QRadioButton {
    spacing: 8px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
}
QRadioButton::indicator {
    border-radius: 8px;
}

/* 菜单栏 */
QMenuBar {
    background-color: transparent;
    padding: 4px;
}
QMenuBar::item {
    padding: 4px 8px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background-color: rgba(128, 128, 128, 0.2);
}
QMenu {
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px 6px 20px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: rgba(0, 120, 212, 0.2);
}
QMenu::separator {
    height: 1px;
    margin: 4px 8px;
}

/* 工具提示 */
QToolTip {
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
"""

# ========== 暗色主题 ==========
DARK_STYLE = COMMON_STYLE + """
/* 主窗口背景 */
QMainWindow {
    background-color: #1E1E1E;
}
#SidePanel {
    background-color: #252526;
    border-right: 1px solid #3E3E42;
}

/* 标签 */
QLabel {
    color: #E0E0E0;
}
#SidePanel QLabel {
    color: #CCCCCC;
}

/* 图片拖放区 */
#ImageDropZone {
    background-color: #2D2D2D;
    border: 2px dashed #3E3E42;
    color: #8A8A8A;
    border-radius: 12px;
}
#ImageDropZone:hover {
    border-color: #0078D4;
    color: #B0B0B0;
}

/* 输入框 */
QLineEdit {
    background-color: #3C3C3C;
    border: 1px solid #3E3E42;
    color: #E0E0E0;
}
QLineEdit:focus {
    border-color: #0078D4;
}

/* 下拉框 */
QComboBox {
    background-color: #3C3C3C;
    border: 1px solid #3E3E42;
    color: #E0E0E0;
}
QComboBox:hover {
    border-color: #555;
}
QComboBox::down-arrow {
    border-top-color: #E0E0E0;
}

/* 普通按钮 */
QPushButton {
    background-color: #3C3C3C;
    border: 1px solid #3E3E42;
    color: #E0E0E0;
}
QPushButton:hover {
    background-color: #4C4C4C;
    border-color: #555;
}
QPushButton:pressed {
    background-color: #2C2C2C;
}
#PrimaryButton {
    background-color: #0078D4;
    border: 1px solid #0078D4;
    color: white;
    font-weight: 500;
}
#PrimaryButton:hover {
    background-color: #1E8AE0;
    border-color: #1E8AE0;
}
#SearchButton {
    background-color: #2DA44E;
    border: 1px solid #2DA44E;
    color: white;
    font-weight: 500;
}
#SearchButton:hover {
    background-color: #3CB95E;
    border-color: #3CB95E;
}

/* 表格 */
QTableWidget {
    background-color: #1E1E1E;
    color: #E0E0E0;
    alternate-background-color: #252526;
}
QHeaderView::section {
    background-color: #252526;
    color: #AAAAAA;
}
QTableWidget::item:selected {
    background-color: rgba(0, 120, 212, 0.3);
    color: #FFFFFF;
}

/* 状态栏标签 */
#StatusLabel {
    color: #8A8A8A;
    font-size: 11px;
}

/* 视频容器 */
#VideoContainer {
    background-color: #000000;
    border-radius: 12px;
}

/* 分割条 */
QSplitter::handle {
    background-color: #3E3E42;
}

/* 消息框 */
QMessageBox {
    background-color: #252526;
}
QMessageBox QLabel {
    color: #E0E0E0;
}

/* 菜单 */
QMenuBar {
    color: #E0E0E0;
}
QMenuBar::item:selected {
    background-color: #3E3E42;
}
QMenu {
    background-color: #2D2D2D;
    border: 1px solid #3E3E42;
    color: #E0E0E0;
}
QMenu::item:selected {
    background-color: #0078D4;
    color: white;
}
QMenu::separator {
    background-color: #3E3E42;
}
QToolTip {
    background-color: #2D2D2D;
    color: #E0E0E0;
    border: 1px solid #3E3E42;
}

/* 复选框、单选框 */
QCheckBox::indicator, QRadioButton::indicator {
    background-color: #3C3C3C;
    border: 1px solid #3E3E42;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #0078D4;
    border-color: #0078D4;
}
QCheckBox::indicator:checked {
    image: url(:/icons/check.svg);
}
"""

# ========== 亮色主题 ==========
LIGHT_STYLE = COMMON_STYLE + """
/* 主窗口背景 */
QMainWindow {
    background-color: #F5F5F5;
}
#SidePanel {
    background-color: #FFFFFF;
    border-right: 1px solid #E5E5E5;
}

/* 标签 */
QLabel {
    color: #333333;
}
#SidePanel QLabel {
    color: #2C2C2C;
}

/* 图片拖放区 */
#ImageDropZone {
    background-color: #FAFAFA;
    border: 2px dashed #DDDDDD;
    color: #999999;
    border-radius: 12px;
}
#ImageDropZone:hover {
    border-color: #0078D4;
    color: #0078D4;
}

/* 输入框 */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #DDDDDD;
    color: #333333;
}
QLineEdit:focus {
    border-color: #0078D4;
}

/* 下拉框 */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #DDDDDD;
    color: #333333;
}
QComboBox:hover {
    border-color: #BBBBBB;
}
QComboBox::down-arrow {
    border-top-color: #333333;
}

/* 普通按钮 */
QPushButton {
    background-color: #F0F0F0;
    border: 1px solid #DDDDDD;
    color: #333333;
}
QPushButton:hover {
    background-color: #E5E5E5;
    border-color: #CCCCCC;
}
QPushButton:pressed {
    background-color: #DADADA;
}
#PrimaryButton {
    background-color: #0078D4;
    border: 1px solid #0078D4;
    color: white;
    font-weight: 500;
}
#PrimaryButton:hover {
    background-color: #1E8AE0;
}
#SearchButton {
    background-color: #2DA44E;
    border: 1px solid #2DA44E;
    color: white;
    font-weight: 500;
}
#SearchButton:hover {
    background-color: #3CB95E;
}

/* 表格 */
QTableWidget {
    background-color: #FFFFFF;
    color: #333333;
    alternate-background-color: #F9F9F9;
}
QHeaderView::section {
    background-color: #F0F0F0;
    color: #666666;
}
QTableWidget::item:selected {
    background-color: #E6F3FF;
    color: #0078D4;
}

/* 状态栏标签 */
#StatusLabel {
    color: #999999;
    font-size: 11px;
}

/* 视频容器 */
#VideoContainer {
    background-color: #EAEAEA;
    border-radius: 12px;
}

/* 分割条 */
QSplitter::handle {
    background-color: #E0E0E0;
}

/* 消息框 */
QMessageBox {
    background-color: #FFFFFF;
}
QMessageBox QLabel {
    color: #333333;
}

/* 菜单 */
QMenuBar {
    color: #333333;
}
QMenuBar::item:selected {
    background-color: #E5E5E5;
}
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #DDDDDD;
    color: #333333;
}
QMenu::item:selected {
    background-color: #E6F3FF;
    color: #0078D4;
}
QMenu::separator {
    background-color: #DDDDDD;
}
QToolTip {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #DDDDDD;
}

/* 复选框、单选框 */
QCheckBox::indicator, QRadioButton::indicator {
    background-color: #FFFFFF;
    border: 1px solid #CCCCCC;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #0078D4;
    border-color: #0078D4;
}
QCheckBox::indicator:checked {
    image: url(:/icons/check_white.svg);
}
"""
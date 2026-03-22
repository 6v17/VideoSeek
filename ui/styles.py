# src/styles.py

# 通用基础样式
COMMON_STYLE = """
QMainWindow { font-family: "Microsoft YaHei UI", sans-serif; }
QProgressBar { border: none; background-color: #333; height: 6px; border-radius: 3px; }
QProgressBar::chunk { background-color: #0078D4; border-radius: 3px; }
"""

DARK_STYLE = COMMON_STYLE + """
QMainWindow { background-color: #1a1a1a; }
#SidePanel { background-color: #252525; border-right: 1px solid #333; min-width: 320px; }
#ImageDropZone { background-color: #1e1e1e; border: 2px dashed #444; color: #888; border-radius: 12px; font-size: 14px; }
QLineEdit { background-color: #333; border: 1px solid #444; color: #eee; border-radius: 6px; padding: 8px; }
QPushButton { background-color: #3d3d3d; color: white; border-radius: 6px; padding: 8px; border: none; }
QPushButton:hover { background-color: #4d4d4d; }
#PrimaryButton { background-color: #0078D4; font-weight: bold; }
#SearchButton { background-color: #2da44e; font-weight: bold; font-size: 15px; }
QTableWidget {
    background-color: #1a1a1a;
    color: #ccc;
    gridline-color: #252525;
    border: none;
    alternate-background-color: #222;
}
/* 禁用选中行变色：让选中行的背景与未选中时完全一致 */
QTableWidget::item:selected {
    background-color: #1a1a1a;   /* 与普通行背景相同 */
    color: #ccc;                 /* 保持文字颜色不变 */
}
QTableWidget::item:selected:alternate {
    background-color: #222;       /* 与交替行背景相同 */
    color: #ccc;
}
QTableWidget::item:hover {
    background-color: #2a2a2a;   /* 普通行悬停：比 #1a1a1a 深一点 */
}
QTableWidget::item:alternate:hover {
    background-color: #2f2f2f;   /* 交替行悬停：比 #222 深一点 */
}
QHeaderView::section { background-color: #252525; color: #888; border: none; font-weight: bold; padding: 8px; }
QLabel { color: #eee; }
#StatusLabel { color: #888; }
QMenuBar { background-color: #252525; color: #ccc; }
QMenuBar::item:selected { background-color: #3d3d3d; }
QMenu { background-color: #252525; color: #ccc; border: 1px solid #444; }
QSplitter::handle {
    background-color: #333;
}
QSplitter::handle:vertical {
    height: 4px;
}
"""

LIGHT_STYLE = COMMON_STYLE + """
QMainWindow { background-color: #f5f5f7; }
#SidePanel { background-color: #ffffff; border-right: 1px solid #ddd; min-width: 320px; }
#ImageDropZone { background-color: #fafafa; border: 2px dashed #ccc; color: #999; border-radius: 12px; font-size: 14px; }
QLineEdit { background-color: #ffffff; border: 1px solid #ccc; color: #333; border-radius: 6px; padding: 8px; }
QPushButton { background-color: #e0e0e0; color: #333; border-radius: 6px; padding: 8px; border: none; }
QPushButton:hover { background-color: #d0d0d0; }
#PrimaryButton { background-color: #0078D4; color: white; font-weight: bold; }
#SearchButton { background-color: #2da44e; color: white; font-weight: bold; font-size: 15px; }
QTableWidget {
    background-color: #ffffff;
    color: #333;
    gridline-color: #eee;
    border: none;
    alternate-background-color: #fafafa;
}
/* 禁用选中行变色 */
QTableWidget::item:selected {
    background-color: #ffffff;    /* 与普通行背景相同 */
    color: #333;
}
QTableWidget::item:selected:alternate {
    background-color: #fafafa;    /* 与交替行背景相同 */
    color: #333;
}
QTableWidget::item:hover {
    background-color: #e8e8e8;   /* 普通行悬停：比白色略暗 */
}
QTableWidget::item:alternate:hover {
    background-color: #f0f0f0;   /* 交替行悬停：比 #fafafa 略暗 */
}
QHeaderView::section { background-color: #f0f0f0; color: #666; border: none; font-weight: bold; padding: 8px; }
QLabel { color: #333; }
#StatusLabel { color: #666; }
QMenuBar { background-color: #ffffff; color: #333; }
QMenuBar::item:selected { background-color: #eee; }
QMenu { background-color: #ffffff; color: #333; border: 1px solid #ddd; }
QSplitter::handle {
    background-color: #ddd;
}
QSplitter::handle:vertical {
    height: 4px;
}
"""
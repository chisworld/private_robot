"""桌宠设置窗样式 — Apple Health / iOS 17 清爽健康风。"""

SETTINGS_DIALOG_QSS = """
* {
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif;
}

QDialog {
    background-color: #eef5fc;
}

/* ── 玻璃拟态侧边栏 ── */
QFrame#settingsSidebar {
    background-color: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(255, 255, 255, 0.92);
    border-radius: 20px;
    min-width: 172px;
    max-width: 172px;
}
QFrame#settingsNavRail {
    background: transparent;
    border: none;
}
QFrame#sidebarAccent {
    background-color: #5ac8fa;
    border-radius: 2px;
    margin: 0 6px 8px 6px;
}
QLabel#sidebarBrand {
    font-size: 17px;
    font-weight: 700;
    color: #1c1c1e;
    letter-spacing: -0.3px;
    padding: 6px 6px 0 6px;
}
QLabel#sidebarHint {
    font-size: 11px;
    color: #8e8e93;
    padding: 0 6px 10px 6px;
}
QPushButton#navBtn {
    text-align: left;
    padding: 9px 12px 9px 11px;
    border: 1px solid transparent;
    border-radius: 12px;
    background: transparent;
    color: #636366;
    font-size: 13px;
    font-weight: 500;
    icon-size: 17px 17px;
}
QPushButton#navBtn:hover {
    background-color: rgba(255, 255, 255, 0.55);
    color: #1c1c1e;
    border-color: rgba(0, 122, 255, 0.12);
}
QPushButton#navBtn:checked,
QPushButton#navBtn[active="true"] {
    background-color: rgba(0, 122, 255, 0.12);
    color: #007aff;
    border-color: rgba(0, 122, 255, 0.22);
    font-weight: 600;
}

/* ── 内容卡片 ── */
QFrame#contentPanel {
    background-color: #ffffff;
    border: 1px solid #e3eff9;
    border-radius: 20px;
}
QLabel#contentTitle {
    font-size: 22px;
    font-weight: 700;
    color: #1c1c1e;
    letter-spacing: -0.4px;
}
QLabel#contentSubtitle {
    font-size: 13px;
    color: #8e8e93;
    padding-bottom: 4px;
}
QLabel#dialogTitle {
    font-size: 20px;
    font-weight: 700;
    color: #1c1c1e;
}
QLabel#dialogSubtitle {
    font-size: 12px;
    color: #8e8e93;
}
QLabel#tabIntro {
    color: #48484a;
    font-size: 12px;
    background: #f0f7ff;
    border: 1px solid #d6e8f7;
    border-left: 3px solid #5ac8fa;
    border-radius: 14px;
    padding: 12px 14px;
}
QLabel#sectionHint {
    color: #8e8e93;
    font-size: 12px;
    line-height: 1.5;
}

/* ── 子页分段 Tab（iOS Segmented） ── */
QTabWidget#sectionTabs::pane {
    border: none;
    border-radius: 0;
    background: transparent;
    top: 0;
    padding: 12px 0 0 0;
}
QTabWidget#sectionTabs QTabBar::tab {
    background: #eef2f7;
    color: #636366;
    border: none;
    border-radius: 10px;
    padding: 7px 16px;
    margin-right: 6px;
    font-size: 12px;
    font-weight: 500;
    min-height: 18px;
}
QTabWidget#sectionTabs QTabBar::tab:selected {
    background: #ffffff;
    color: #007aff;
    font-weight: 600;
    border: 1px solid #d6e8f7;
}
QTabWidget#sectionTabs QTabBar::tab:hover:!selected {
    background: rgba(255, 255, 255, 0.7);
    color: #1c1c1e;
}
QTabWidget::tab-bar {
    alignment: left;
}

QTabWidget#mainTabs::pane {
    border: 1px solid #e3eff9;
    border-radius: 16px;
    background: #ffffff;
    top: -1px;
    padding: 12px;
}
QTabWidget#mainTabs QTabBar::tab {
    background: #eef2f7;
    color: #636366;
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    margin-right: 4px;
    font-size: 13px;
}
QTabWidget#mainTabs QTabBar::tab:selected {
    background: #ffffff;
    color: #007aff;
    font-weight: 600;
    border: 1px solid #d6e8f7;
}

/* ── 圆角模块卡片 ── */
QGroupBox {
    font-size: 13px;
    font-weight: 600;
    color: #1c1c1e;
    border: 1px solid #e8f0f8;
    border-radius: 16px;
    margin-top: 14px;
    padding: 18px 14px 14px 14px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: #007aff;
    font-weight: 600;
}
QGroupBox:hover {
    border-color: #d0e4f5;
}

QFormLayout QLabel {
    color: #48484a;
    font-size: 13px;
}

/* ── iOS 风格勾选 ── */
QCheckBox {
    color: #1c1c1e;
    font-size: 13px;
    spacing: 9px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 1.5px solid #c7c7cc;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #007aff;
    background: #f5faff;
}
QCheckBox::indicator:checked {
    background: #007aff;
    border-color: #007aff;
}
QCheckBox::indicator:checked:hover {
    background: #0066d6;
    border-color: #0066d6;
}

QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox, QTextEdit, QDateEdit, QDateTimeEdit {
    border: 1px solid #d1d1d6;
    border-radius: 10px;
    padding: 7px 11px;
    background: #fafcfe;
    color: #1c1c1e;
    min-height: 22px;
    selection-background-color: rgba(0, 122, 255, 0.25);
    selection-color: #1c1c1e;
}
QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover, QComboBox:hover, QTextEdit:hover,
QDateEdit:hover, QDateTimeEdit:hover {
    border-color: #5ac8fa;
    background: #ffffff;
}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
QDateEdit:focus, QDateTimeEdit:focus {
    border: 1.5px solid #007aff;
    background: #ffffff;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #e3eff9;
    border-radius: 10px;
    selection-background-color: rgba(0, 122, 255, 0.15);
    selection-color: #007aff;
    padding: 4px;
}

QTableWidget {
    background: #fafcfe;
    border: 1px solid #e8f0f8;
    border-radius: 14px;
    gridline-color: #eef2f7;
    selection-background-color: rgba(0, 122, 255, 0.12);
    selection-color: #007aff;
}
QHeaderView::section {
    background: #f5f9fd;
    color: #636366;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #e8f0f8;
}

QListWidget {
    background: #fafcfe;
    border: 1px solid #e8f0f8;
    border-radius: 14px;
    padding: 6px;
}
QListWidget::item {
    padding: 7px 8px;
    border-radius: 10px;
}
QListWidget::item:hover {
    background: rgba(0, 122, 255, 0.06);
}
QListWidget::item:selected {
    background: rgba(0, 122, 255, 0.14);
    color: #007aff;
}

QPushButton#primaryBtn {
    background-color: #007aff;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 600;
    min-height: 36px;
}
QPushButton#primaryBtn:hover {
    background-color: #0066d6;
}
QPushButton#primaryBtn:pressed {
    background-color: #0055b3;
}
QPushButton#primaryBtn:disabled {
    background-color: #aeaeb2;
}

QPushButton#secondaryBtn {
    background-color: rgba(255, 255, 255, 0.9);
    color: #007aff;
    border: 1px solid #d6e8f7;
    border-radius: 12px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}
QPushButton#secondaryBtn:hover {
    background-color: #f0f7ff;
    border-color: #5ac8fa;
}

QPushButton#ghostBtn {
    background-color: #f5f9fd;
    color: #007aff;
    border: 1px solid #e3eff9;
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#ghostBtn:hover {
    background-color: #eef5fc;
    border-color: #5ac8fa;
}

QWidget#memoryRow {
    background-color: #ffffff;
    border: 1px solid #e8f0f8;
    border-radius: 14px;
}
QWidget#memoryRow:hover {
    border-color: #5ac8fa;
    background-color: #f8fbff;
}
QPushButton#memoryDelBtn {
    background-color: #f5f9fd;
    color: #8e8e93;
    border: 1px solid #e3eff9;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    padding: 0;
    min-width: 28px;
    min-height: 28px;
}
QPushButton#memoryDelBtn:hover {
    color: #ff3b30;
    border-color: #ffd6d3;
    background-color: #fff5f5;
}

QLabel#memoryGroupHeader {
    margin-top: 4px;
}

QLabel#hexLabel {
    color: #636366;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 12px;
    background: #f0f7ff;
    border: 1px solid #d6e8f7;
    border-radius: 8px;
    padding: 4px 8px;
}

QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 6px 2px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 122, 255, 0.22);
    border-radius: 3px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 122, 255, 0.38);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 6px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 122, 255, 0.22);
    border-radius: 3px;
}
"""

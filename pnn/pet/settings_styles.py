"""桌宠设置窗样式 — Premium Dark Glass 主题。
深色玻璃拟态 + 渐变光晕 + 微动效，灵感来自现代 macOS / Vision OS / 高端设计系统。
"""

SETTINGS_DIALOG_QSS = """
/* ═══════════════════════════════════════════════════════════════════════════
   GLOBAL
   ═══════════════════════════════════════════════════════════════════════ */

* {
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei UI", "SF Pro Display", system-ui, sans-serif;
}

QDialog {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #080b14, stop:0.35 #0d1020, stop:0.7 #0f1428, stop:1 #0a0d1a);
}

/* ── 全局透明 + 浅色文字（覆盖所有未指定 objectName 的容器） ── */
QWidget {
    background: transparent;
    color: #cbd5e1;
}

QScrollArea QWidget {
    background: transparent;
}

QLabel {
    background: transparent;
    color: #cbd5e1;
}

/* ═══════════════════════════════════════════════════════════════════════════
   SIDEBAR — frosted glass rail
   ═══════════════════════════════════════════════════════════════════════════ */

QFrame#settingsSidebar {
    background: rgba(15, 20, 38, 0.78);
    border: 1px solid rgba(99, 102, 241, 0.12);
    border-radius: 22px;
    min-width: 180px;
    max-width: 180px;
}

QFrame#settingsNavRail {
    background: transparent;
    border: none;
}

QFrame#sidebarAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6366f1, stop:0.35 #8b5cf6, stop:0.7 #a78bfa, stop:1 #06b6d4);
    border-radius: 2px;
    min-height: 3px;
    max-height: 3px;
    margin: 0 4px 10px 4px;
}

QLabel#sidebarBrand {
    font-size: 18px;
    font-weight: 700;
    color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e0e7ff, stop:0.5 #c4b5fd, stop:1 #a5f3fc);
    letter-spacing: -0.2px;
    padding: 4px 6px 0 6px;
    background: transparent;
}

QLabel#sidebarHint {
    font-size: 10.5px;
    color: #6366f1;
    opacity: 0.7;
    padding: 0 6px 14px 6px;
    font-weight: 500;
    letter-spacing: 0.8px;
    background: transparent;
}

QLabel#sidebarFooter {
    font-size: 9px;
    color: #475569;
    padding: 8px 6px 2px 6px;
    background: transparent;
}

/* ── Nav buttons ── */
QPushButton#navBtn {
    text-align: left;
    padding: 10px 12px 10px 12px;
    border: 1px solid transparent;
    border-radius: 13px;
    background: transparent;
    color: #94a3b8;
    font-size: 13px;
    font-weight: 500;
    icon-size: 18px 18px;
    margin-bottom: 1px;
}

QPushButton#navBtn:hover {
    background: rgba(99, 102, 241, 0.08);
    color: #c7d2fe;
    border-color: rgba(99, 102, 241, 0.15);
}

QPushButton#navBtn:checked,
QPushButton#navBtn[active="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(99, 102, 241, 0.18), stop:0.5 rgba(139, 92, 246, 0.15), stop:1 rgba(99, 102, 241, 0.12));
    color: #e0e7ff;
    border: 1px solid rgba(99, 102, 241, 0.28);
    font-weight: 600;
}

/* ═══════════════════════════════════════════════════════════════════════════
   CONTENT PANEL — elevated glass card
   ═══════════════════════════════════════════════════════════════════════════ */

QFrame#contentPanel {
    background: rgba(17, 22, 42, 0.72);
    border: 1px solid rgba(99, 102, 241, 0.10);
    border-radius: 22px;
}

QLabel#contentTitle {
    font-size: 24px;
    font-weight: 700;
    color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e0e7ff, stop:0.4 #c4b5fd, stop:0.8 #a5f3fc, stop:1 #67e8f9);
    letter-spacing: -0.5px;
    background: transparent;
}

QLabel#contentSubtitle {
    font-size: 12.5px;
    color: #64748b;
    padding-bottom: 2px;
    letter-spacing: 0.1px;
    background: transparent;
}

QLabel#dialogTitle {
    font-size: 21px;
    font-weight: 700;
    color: #e0e7ff;
    background: transparent;
}

QLabel#dialogSubtitle {
    font-size: 12px;
    color: #64748b;
    background: transparent;
}

/* ── Tab intro / info banner ── */
QLabel#tabIntro {
    color: #a5b4fc;
    font-size: 12px;
    line-height: 1.55;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(99, 102, 241, 0.10), stop:1 rgba(6, 182, 212, 0.06));
    border: 1px solid rgba(99, 102, 241, 0.13);
    border-left: 3px solid #818cf8;
    border-radius: 15px;
    padding: 14px 16px;
}

QLabel#sectionHint {
    color: #64748b;
    font-size: 12px;
    line-height: 1.55;
}

QLabel#downloadLinks {
    color: #cbd5e1;
    font-size: 12px;
    line-height: 1.6;
    padding: 10px 12px;
    background: rgba(99, 102, 241, 0.05);
    border: 1px solid rgba(99, 102, 241, 0.10);
    border-radius: 12px;
}
QLabel#downloadLinks a {
    color: #818cf8;
    text-decoration: none;
}
QLabel#downloadLinks a:hover {
    color: #a78bfa;
    text-decoration: underline;
}

/* ═══════════════════════════════════════════════════════════════════════════
   TAB WIDGETS — segmented control style
   ═══════════════════════════════════════════════════════════════════════════ */

QTabWidget#sectionTabs::pane {
    border: none;
    border-radius: 0;
    background: transparent;
    top: 0;
    padding: 14px 0 0 0;
}
QTabWidget#sectionTabs QTabBar::tab {
    background: rgba(30, 41, 59, 0.55);
    color: #64748b;
    border: 1px solid transparent;
    border-radius: 11px;
    padding: 8px 18px;
    margin-right: 6px;
    font-size: 12px;
    font-weight: 500;
    min-height: 20px;
}
QTabWidget#sectionTabs QTabBar::tab:selected {
    background: rgba(99, 102, 241, 0.15);
    color: #a5b4fc;
    font-weight: 600;
    border: 1px solid rgba(99, 102, 241, 0.22);
}
QTabWidget#sectionTabs QTabBar::tab:hover:!selected {
    background: rgba(99, 102, 241, 0.07);
    color: #94a3b8;
}
QTabWidget::tab-bar {
    alignment: left;
}

QTabWidget#mainTabs::pane {
    border: 1px solid rgba(99, 102, 241, 0.10);
    border-radius: 16px;
    background: rgba(15, 20, 35, 0.45);
    top: -1px;
    padding: 14px;
}
QTabWidget#mainTabs QTabBar::tab {
    background: rgba(30, 41, 59, 0.5);
    color: #64748b;
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    margin-right: 4px;
    font-size: 13px;
}
QTabWidget#mainTabs QTabBar::tab:selected {
    background: rgba(99, 102, 241, 0.16);
    color: #c7d2fe;
    font-weight: 600;
    border: 1px solid rgba(99, 102, 241, 0.22);
}

/* ═══════════════════════════════════════════════════════════════════════════
   GROUPS / CARDS — elegant bordered cards
   ═══════════════════════════════════════════════════════════════════════════ */

QGroupBox {
    font-size: 13.5px;
    font-weight: 600;
    color: #c7d2fe;
    border: 1px solid rgba(99, 102, 241, 0.12);
    border-radius: 18px;
    margin-top: 16px;
    padding: 20px 16px 16px 16px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(25, 32, 56, 0.6), stop:1 rgba(15, 20, 38, 0.5));
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 18px;
    padding: 0 10px;
    color: #a78bfa;
    font-weight: 600;
    font-size: 13px;
}
QGroupBox:hover {
    border-color: rgba(99, 102, 241, 0.22);
}

QFormLayout QLabel {
    color: #cbd5e1;
    font-size: 13px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   INPUTS — elevated dark glass controls
   ═══════════════════════════════════════════════════════════════════════════ */

QSpinBox, QDoubleSpinBox,
QLineEdit, QComboBox, QTextEdit,
QDateEdit, QDateTimeEdit {
    border: 1px solid rgba(71, 85, 105, 0.35);
    border-radius: 11px;
    padding: 9px 13px;
    background: rgba(15, 23, 42, 0.65);
    color: #e2e8f0;
    min-height: 24px;
    font-size: 13px;
    selection-background-color: rgba(99, 102, 241, 0.45);
    selection-color: #ffffff;
}

QSpinBox:hover, QDoubleSpinBox:hover,
QLineEdit:hover, QComboBox:hover, QTextEdit:hover,
QDateEdit:hover, QDateTimeEdit:hover {
    border-color: rgba(99, 102, 241, 0.5);
    background: rgba(20, 30, 52, 0.75);
}

QSpinBox:focus, QDoubleSpinBox:focus,
QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
QDateEdit:focus, QDateTimeEdit:focus {
    border: 1.5px solid #818cf8;
    background: rgba(25, 35, 60, 0.85);
}

QComboBox::drop-down {
    border: none;
    width: 24px;
    subcontrol-position: right center;
    subcontrol-origin: padding;
    padding-right: 6px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #64748b;
    margin-right: 2px;
}
QComboBox::down-arrow:hover {
    border-top-color: #818cf8;
}

QComboBox QAbstractItemView {
    background: rgba(15, 23, 42, 0.98);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 12px;
    selection-background-color: rgba(99, 102, 241, 0.25);
    selection-color: #e0e7ff;
    padding: 5px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 7px 12px;
    border-radius: 8px;
    min-height: 22px;
}
QComboBox QAbstractItemView::item:hover {
    background: rgba(99, 102, 241, 0.10);
}

/* ── Checkboxes — luminous gem toggle ── */
QCheckBox {
    color: #cbd5e1;
    font-size: 13px;
    spacing: 11px;
}
QCheckBox::indicator {
    width: 22px;
    height: 22px;
    border-radius: 8px;
    border: 1.5px solid #334155;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(30, 41, 59, 0.8), stop:1 rgba(15, 23, 42, 0.9));
}
QCheckBox::indicator:hover {
    border-color: #6366f1;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(49, 46, 129, 0.5), stop:1 rgba(30, 41, 59, 0.8));
}
QCheckBox::indicator:checked {
    border: 1.5px solid #6366f1;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #818cf8, stop:0.45 #6366f1, stop:1 #4f46e5);
}
QCheckBox::indicator:checked:hover {
    border-color: #a78bfa;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a78bfa, stop:0.4 #818cf8, stop:1 #6366f1);
}

/* ═══════════════════════════════════════════════════════════════════════════
   TABLES — refined dark data grid
   ═══════════════════════════════════════════════════════════════════════════ */

QTableWidget {
    background: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(99, 102, 241, 0.10);
    border-radius: 15px;
    gridline-color: rgba(71, 85, 105, 0.15);
    selection-background-color: rgba(99, 102, 241, 0.2);
    selection-color: #e0e7ff;
    color: #cbd5e1;
    font-size: 12.5px;
}

QHeaderView::section {
    background: rgba(25, 35, 58, 0.7);
    color: #94a3b8;
    font-weight: 600;
    font-size: 11.5px;
    letter-spacing: 0.3px;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid rgba(99, 102, 241, 0.12);
}

QTableWidget::item {
    padding: 6px 10px;
}
QTableWidget::item:hover {
    background: rgba(99, 102, 241, 0.06);
}
QTableWidget::item:selected {
    background: rgba(99, 102, 241, 0.18);
    color: #e0e7ff;
}

/* ═══════════════════════════════════════════════════════════════════════════
   LIST WIDGET — elegant item list
   ═══════════════════════════════════════════════════════════════════════════ */

QListWidget {
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(99, 102, 241, 0.10);
    border-radius: 15px;
    padding: 6px;
    color: #cbd5e1;
    font-size: 13px;
    outline: none;
}
QListWidget::item {
    padding: 9px 10px;
    border-radius: 10px;
    border: 1px solid transparent;
}
QListWidget::item:hover {
    background: rgba(99, 102, 241, 0.07);
    border-color: rgba(99, 102, 241, 0.10);
}
QListWidget::item:selected {
    background: rgba(99, 102, 241, 0.16);
    color: #e0e7ff;
    border-color: rgba(99, 102, 241, 0.18);
}

/* ═══════════════════════════════════════════════════════════════════════════
   BUTTONS — gradient primary, ghost secondary
   ═══════════════════════════════════════════════════════════════════════════ */

QPushButton#primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6366f1, stop:0.4 #7c3aed, stop:0.7 #8b5cf6, stop:1 #6366f1);
    color: #ffffff;
    border: none;
    border-radius: 13px;
    padding: 11px 26px;
    font-size: 13px;
    font-weight: 600;
    min-height: 38px;
    letter-spacing: 0.2px;
}
QPushButton#primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #818cf8, stop:0.4 #8b5cf6, stop:0.7 #a78bfa, stop:1 #818cf8);
}
QPushButton#primaryBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #4f46e5, stop:0.5 #6d28d9, stop:1 #4f46e5);
}
QPushButton#primaryBtn:disabled {
    background: #334155;
    color: #64748b;
}

QPushButton#secondaryBtn {
    background: rgba(30, 41, 59, 0.6);
    color: #a5b4fc;
    border: 1px solid rgba(99, 102, 241, 0.18);
    border-radius: 13px;
    padding: 11px 24px;
    font-size: 13px;
    font-weight: 500;
    min-height: 38px;
    letter-spacing: 0.1px;
}
QPushButton#secondaryBtn:hover {
    background: rgba(99, 102, 241, 0.12);
    border-color: rgba(99, 102, 241, 0.35);
    color: #c7d2fe;
}

QPushButton#ghostBtn {
    background: rgba(30, 41, 59, 0.4);
    color: #94a3b8;
    border: 1px solid rgba(71, 85, 105, 0.25);
    border-radius: 11px;
    padding: 7px 15px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#ghostBtn:hover {
    background: rgba(99, 102, 241, 0.10);
    border-color: rgba(99, 102, 241, 0.30);
    color: #a5b4fc;
}

/* ═══════════════════════════════════════════════════════════════════════════
   MEMORY ROWS — interactive card items
   ═══════════════════════════════════════════════════════════════════════════ */

QWidget#memoryRow {
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(99, 102, 241, 0.08);
    border-radius: 15px;
}
QWidget#memoryRow:hover {
    border-color: rgba(99, 102, 241, 0.25);
    background: rgba(99, 102, 241, 0.06);
}

QPushButton#memoryDelBtn {
    background: rgba(30, 41, 59, 0.5);
    color: #64748b;
    border: 1px solid rgba(71, 85, 105, 0.2);
    border-radius: 11px;
    font-size: 15px;
    font-weight: 600;
    padding: 0;
    min-width: 30px;
    min-height: 30px;
}
QPushButton#memoryDelBtn:hover {
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.35);
    background: rgba(239, 68, 68, 0.10);
}

QLabel#memoryGroupHeader {
    margin-top: 6px;
    color: #818cf8;
    font-weight: 600;
    font-size: 11.5px;
    letter-spacing: 0.4px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   SPECIAL LABELS
   ═══════════════════════════════════════════════════════════════════════════ */

QLabel#hexLabel {
    color: #94a3b8;
    font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(99, 102, 241, 0.12);
    border-radius: 9px;
    padding: 5px 10px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   SCROLLBARS — slim cyan glow
   ═══════════════════════════════════════════════════════════════════════════ */

QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollArea QWidget#qt_scrollarea_viewport {
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 7px;
    margin: 8px 3px;
}
QScrollBar::handle:vertical {
    background: rgba(99, 102, 241, 0.25);
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(99, 102, 241, 0.45);
}
QScrollBar::handle:vertical:pressed {
    background: rgba(139, 92, 246, 0.55);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 7px;
    margin: 3px 8px;
}
QScrollBar::handle:horizontal {
    background: rgba(99, 102, 241, 0.25);
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(99, 102, 241, 0.45);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ═══════════════════════════════════════════════════════════════════════════
   RADIO BUTTONS — jewel dot selector
   ═══════════════════════════════════════════════════════════════════════════ */

QRadioButton {
    color: #cbd5e1;
    font-size: 13px;
    spacing: 10px;
}
QRadioButton::indicator {
    width: 20px;
    height: 20px;
    border-radius: 12px;
    border: 1.5px solid #334155;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(30, 41, 59, 0.7), stop:1 rgba(15, 23, 42, 0.85));
}
QRadioButton::indicator:hover {
    border-color: #6366f1;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(49, 46, 129, 0.4), stop:1 rgba(30, 41, 59, 0.7));
}
QRadioButton::indicator:checked {
    border: 2px solid #818cf8;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.6,
        fx:0.45, fy:0.4,
        stop:0 #e0e7ff, stop:0.15 #c4b5fd, stop:0.5 #818cf8, stop:0.85 #6366f1, stop:1 #4f46e5);
}
QRadioButton::indicator:checked:hover {
    border-color: #a78bfa;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.6,
        fx:0.45, fy:0.4,
        stop:0 #ffffff, stop:0.15 #ddd6fe, stop:0.5 #a78bfa, stop:0.85 #7c3aed, stop:1 #5b21b6);
}

/* ═══════════════════════════════════════════════════════════════════════════
   SLIDERS (QSlider)
   ═══════════════════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    background: rgba(30, 41, 59, 0.7);
    border: 1px solid rgba(71, 85, 105, 0.25);
    border-radius: 5px;
    height: 8px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a78bfa, stop:1 #6366f1);
    border: 2px solid #818cf8;
    border-radius: 8px;
    width: 16px;
    height: 16px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #c4b5fd, stop:1 #818cf8);
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6366f1, stop:1 #8b5cf6);
    border-radius: 5px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   TOOLTIPS
   ═══════════════════════════════════════════════════════════════════════════ */

QToolTip {
    background: rgba(15, 23, 42, 0.96);
    color: #e2e8f0;
    border: 1px solid rgba(99, 102, 241, 0.25);
    border-radius: 10px;
    padding: 7px 12px;
    font-size: 11.5px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PROGRESS BAR
   ═══════════════════════════════════════════════════════════════════════════ */

QProgressBar {
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(71, 85, 105, 0.2);
    border-radius: 8px;
    height: 8px;
    text-align: center;
    font-size: 0;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6366f1, stop:0.5 #8b5cf6, stop:1 #a78bfa);
    border-radius: 7px;
}

/* ═══════════════════════════════════════════════════════════════════════════
   MESSAGE BOX / DIALOG — frosted glass alerts
   ═══════════════════════════════════════════════════════════════════════════ */

QMessageBox {
    background: rgba(15, 23, 42, 0.95);
}
QMessageBox QLabel {
    color: #e2e8f0;
    font-size: 13px;
}
QMessageBox QPushButton {
    background: rgba(99, 102, 241, 0.15);
    color: #a5b4fc;
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 10px;
    padding: 8px 20px;
    font-size: 12.5px;
    font-weight: 500;
    min-width: 70px;
}
QMessageBox QPushButton:hover {
    background: rgba(99, 102, 241, 0.25);
    color: #c7d2fe;
}
"""

# ── Animated glow keyframes (inject into widget via dynamic property + timer) ──
# Not natively supported by QSS; implemented via QGraphicsDropShadowEffect in settings_effects.py

# ── Accent palette reference (used in effects, not QSS) ──
ACCENT_GRADIENT_STOPS = [
    (0.0, "#6366f1"),
    (0.35, "#8b5cf6"),
    (0.7, "#a78bfa"),
    (1.0, "#06b6d4"),
]

PRIMARY_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6366f1, stop:0.4 #7c3aed, stop:0.7 #8b5cf6, stop:1 #6366f1)"
PRIMARY_HOVER_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #818cf8, stop:0.4 #8b5cf6, stop:0.7 #a78bfa, stop:1 #818cf8)"

SURFACE_DARK = "rgba(15, 23, 42, 0.65)"
SURFACE_MEDIUM = "rgba(20, 30, 52, 0.70)"
SURFACE_LIGHT = "rgba(25, 35, 60, 0.75)"
BORDER_SUBTLE = "rgba(99, 102, 241, 0.10)"
BORDER_ACTIVE = "rgba(99, 102, 241, 0.25)"
BORDER_FOCUS = "#818cf8"

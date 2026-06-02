"""桌宠设置窗样式。"""

SETTINGS_DIALOG_QSS = """
QDialog {
    background-color: #f1f5f9;
}
QLabel#dialogTitle {
    font-size: 18px;
    font-weight: 700;
    color: #0f172a;
    padding: 4px 0 8px 0;
}
QLabel#sectionHint {
    color: #64748b;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    background: #ffffff;
    top: -1px;
    padding: 12px;
}
QTabWidget::tab-bar {
    alignment: left;
}
QTabBar::tab {
    background: #e2e8f0;
    color: #475569;
    border: 1px solid #cbd5e1;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 18px;
    margin-right: 4px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1d4ed8;
    font-weight: 600;
    border-bottom: 2px solid #ffffff;
}
QTabBar::tab:hover:!selected {
    background: #f8fafc;
    color: #334155;
}
QGroupBox {
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    background: #f8fafc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #1e40af;
}
QFormLayout QLabel {
    color: #475569;
    font-size: 13px;
}
QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 10px;
    background: #ffffff;
    color: #0f172a;
    min-height: 20px;
}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QPushButton#primaryBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
}
QPushButton#primaryBtn:pressed {
    background-color: #1e3a8a;
}
QPushButton#secondaryBtn {
    background-color: #ffffff;
    color: #475569;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
}
QPushButton#secondaryBtn:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}
QPushButton#ghostBtn {
    background-color: #f1f5f9;
    color: #475569;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton#ghostBtn:hover {
    background-color: #e2e8f0;
}
QLabel#hexLabel {
    color: #64748b;
    font-family: Consolas, monospace;
    font-size: 12px;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 4px 6px;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""

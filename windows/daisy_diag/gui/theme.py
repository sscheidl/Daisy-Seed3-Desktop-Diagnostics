"""Dark theme: palette, colours and widget stylesheet."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = QColor("#121418")
PANEL = QColor("#1a1d23")
TEXT = QColor("#e6e8eb")
MUTED = QColor("#8b929c")
SILK = QColor("#e9eaec")
ACCENT = QColor("#29c7e8")
RANGE = QColor("#b98cff")
OK = QColor("#3ddc84")
WARN = QColor("#ffb347")
ERROR = QColor("#ff5c5c")
LED_ON = QColor("#ffd257")
NI_BADGE = QColor("#3a3f48")
NI_TEXT = QColor("#c3c8cf")
SIM = QColor("#ff9f1a")

STYLESHEET = """
QWidget { color: #e6e8eb; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #121418; }
QGroupBox {
    background: #1a1d23; border: 1px solid #2a2f37; border-radius: 8px;
    margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #29c7e8; }
QPushButton {
    background: #262b33; border: 1px solid #353b45; border-radius: 6px; padding: 5px 10px;
}
QPushButton:hover { background: #2f3540; }
QPushButton:pressed { background: #1f242b; }
QPushButton:checked { background: #136b80; border-color: #29c7e8; color: #ffffff; }
QPushButton:disabled { color: #5d636c; background: #1d2026; border-color: #262a31; }
QComboBox, QSpinBox {
    background: #262b33; border: 1px solid #353b45; border-radius: 6px; padding: 3px 6px;
}
QComboBox QAbstractItemView { background: #1f232a; selection-background-color: #136b80; }
QPlainTextEdit, QTableWidget {
    background: #0f1115; border: 1px solid #2a2f37; border-radius: 6px;
    font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 9pt;
}
QHeaderView::section { background: #1f232a; color: #8b929c; border: none; padding: 3px; }
QTableWidget { gridline-color: #232831; }
QSlider::groove:horizontal { height: 6px; background: #2a2f37; border-radius: 3px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #29c7e8; }
QCheckBox::indicator { width: 15px; height: 15px; }
QLabel#statusPill { border-radius: 10px; padding: 4px 10px; font-weight: 700; }
QLabel#simBanner {
    background: #ff9f1a; color: #1a1205; font-weight: 800; padding: 6px; font-size: 11pt;
}
QLabel#niBadge {
    background: #3a3f48; color: #c3c8cf; border-radius: 8px; padding: 1px 8px;
    font-size: 8pt; font-weight: 700;
}
QLabel#hint { color: #8b929c; font-size: 9pt; }
QToolTip { background: #1f232a; color: #e6e8eb; border: 1px solid #29c7e8; padding: 4px; }
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, BG)
    pal.setColor(QPalette.WindowText, TEXT)
    pal.setColor(QPalette.Base, QColor("#0f1115"))
    pal.setColor(QPalette.AlternateBase, PANEL)
    pal.setColor(QPalette.Text, TEXT)
    pal.setColor(QPalette.Button, QColor("#262b33"))
    pal.setColor(QPalette.ButtonText, TEXT)
    pal.setColor(QPalette.Highlight, QColor("#136b80"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, PANEL)
    pal.setColor(QPalette.ToolTipText, TEXT)
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)

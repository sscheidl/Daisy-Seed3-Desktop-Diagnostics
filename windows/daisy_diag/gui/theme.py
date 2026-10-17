"""Instrument-style dark theme: neutral anthracite, grey panels, sparse status colours.

Colour rules: green = connection/success, red = errors and the physical LEDs,
amber = simulation and warnings. No cyan/violet accents, no decorative glow.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# Application surfaces
BG = QColor("#1c1d1f")
HEADER = QColor("#141516")
PANEL = QColor("#25272a")
PANEL_EDGE = QColor("#36393d")
TEXT = QColor("#e3e4e6")
MUTED = QColor("#989ca2")
FAINT = QColor("#5f636a")

# Status colours
OK = QColor("#3fae49")
ERROR = QColor("#e0443a")
WARN = QColor("#d9a227")
SIM = QColor("#d9a227")

# Board (matte dark-grey PCB with white silkscreen, as on the Seed3 Desktop Dev Kit)
PCB = QColor("#2f3133")
PCB_EDGE = QColor("#46494d")
SILK = QColor("#e8e8e6")
SILK_MUTED = QColor("#a9aba9")
METAL = QColor("#b9bcbf")
METAL_DARK = QColor("#7d8085")
PLASTIC = QColor("#121314")
LED_ON = QColor("#ff2f24")
LED_OFF = QColor("#4a1e1b")
SWITCH_BODY = QColor("#b3302b")
BUTTON_CAP = QColor("#c39a6b")
NI_BADGE = QColor("#45484d")
NI_TEXT = QColor("#c9ccd0")

# Kept for code that refers to a generic highlight: neutral, not coloured.
ACCENT = TEXT
RANGE = MUTED

UI_FONT = "Segoe UI"
TECH_FONT = "Bahnschrift"
MONO_FONT = "Cascadia Mono"

STYLESHEET = """
QWidget { color: #e3e4e6; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #1c1d1f; }
QWidget#header { background: #141516; border-bottom: 1px solid #2c2e31; }
QLabel#appTitle { font-family: 'Bahnschrift'; font-size: 14pt; font-weight: 600; }
QLabel#appVersion { color: #7d8187; font-family: 'Bahnschrift'; font-size: 10pt; }
QLabel#statusText { font-family: 'Bahnschrift'; font-size: 11pt; }
QGroupBox {
    background: #25272a; border: 1px solid #36393d; border-top: 2px solid #4a4e53;
    border-radius: 0px; margin-top: 24px; padding: 6px 10px 8px 10px;
    font-family: 'Bahnschrift'; font-size: 11.5pt; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left; left: 1px;
    padding: 0 0 3px 0; color: #e3e4e6;
}
QPushButton {
    background: #303235; border: 1px solid #46494e; border-radius: 2px;
    padding: 5px 12px; font-family: 'Bahnschrift';
}
QPushButton:hover { background: #393c40; border-color: #5a5e64; }
QPushButton:pressed { background: #26282b; }
QPushButton:checked { background: #44484d; border: 1px solid #d6d8db; color: #ffffff; }
QPushButton:disabled { color: #62666c; background: #26282a; border-color: #303236; }
QPushButton#segment { border-radius: 0px; padding: 6px 16px; }
QPushButton#segment:checked { background: #3b3e42; border: 1px solid #8d9197; }
QComboBox {
    background: #2b2d30; border: 1px solid #46494e; border-radius: 2px; padding: 3px 6px;
}
QComboBox QAbstractItemView { background: #26282b; selection-background-color: #44484d; }
QPlainTextEdit, QTableWidget {
    background: #161718; border: 1px solid #33363a; border-radius: 0px;
    font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 9pt;
}
QHeaderView::section {
    background: #26282b; color: #989ca2; border: none; border-bottom: 1px solid #36393d;
    padding: 3px; font-family: 'Bahnschrift';
}
QTableWidget { gridline-color: #2a2c2f; }
QSlider::groove:horizontal { height: 4px; background: #3a3d41; border-radius: 0px; }
QSlider::sub-page:horizontal { background: #8e9298; }
QSlider::handle:horizontal {
    width: 12px; margin: -6px 0; border-radius: 2px; background: #d9dbde;
    border: 1px solid #6d7177;
}
QCheckBox::indicator { width: 13px; height: 13px; }
QCheckBox#ledCheck::indicator {
    width: 12px; height: 12px; border-radius: 6px; border: 1px solid #6a2622;
    background: #3e1a18;
}
QCheckBox#ledCheck::indicator:checked { background: #ff2f24; border-color: #ff8a80; }
QCheckBox#ledCheck::indicator:disabled { background: #2c2423; border-color: #3a302f; }
QLabel#simBanner {
    background: #d9a227; color: #1b1505; font-weight: 700; padding: 4px;
    font-family: 'Bahnschrift'; font-size: 10.5pt;
}
QLabel#niBadge {
    background: #45484d; color: #c9ccd0; border-radius: 1px; padding: 1px 8px;
    font-family: 'Bahnschrift'; font-size: 8.5pt;
}
QLabel#hint { color: #989ca2; font-size: 9pt; }
QLabel#sectionLabel { color: #989ca2; font-family: 'Bahnschrift'; font-size: 9pt; }
QLabel#valueLabel { font-family: 'Cascadia Mono', 'Consolas'; font-size: 9pt; }
QScrollBar:vertical { background: #1c1d1f; width: 10px; }
QScrollBar::handle:vertical { background: #3a3d41; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #1c1d1f; }
QToolTip {
    background: #26282b; color: #e3e4e6; border: 1px solid #5a5e64; padding: 4px;
}
"""


def font(family: str, point_size: float, bold: bool = False) -> QFont:
    f = QFont(family)
    f.setPointSizeF(point_size)
    f.setBold(bold)
    # The board is painted through a scaling transform; hinted glyph advances would
    # produce uneven letter spacing there.
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, BG)
    pal.setColor(QPalette.WindowText, TEXT)
    pal.setColor(QPalette.Base, QColor("#161718"))
    pal.setColor(QPalette.AlternateBase, PANEL)
    pal.setColor(QPalette.Text, TEXT)
    pal.setColor(QPalette.Button, QColor("#303235"))
    pal.setColor(QPalette.ButtonText, TEXT)
    pal.setColor(QPalette.Highlight, QColor("#44484d"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, PANEL)
    pal.setColor(QPalette.ToolTipText, TEXT)
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)

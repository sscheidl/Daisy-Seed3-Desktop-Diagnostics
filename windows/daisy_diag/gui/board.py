"""Scaled drawing of the Seed3 Desktop Dev Kit with live control states.

Geometry follows the official Electro-Smith board photo / pinout graphic
(board-local units, origin at the top-left PCB corner, 1160 x 655 units).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QMouseEvent, QPainter,
                           QPainterPath, QPen, QRadialGradient, QWheelEvent)
from PySide6.QtWidgets import QToolTip, QWidget

from .. import protocol as p
from . import theme

BOARD_W, BOARD_H = 1160.0, 655.0
SCENE = QRectF(-30, -40, 1240, 740)

POT_Y = 325.0
POT_X = [345.0 + 90.0 * i for i in range(p.NUM_POTS)]
COL_X = [405.0 + 72.86 * i for i in range(8)]
LED_Y = (453.0, 547.0)
BTN_Y = (493.0, 585.0)
SW18_POS = QPointF(185, 560)
SW17_POS = QPointF(265, 560)
SD_RECT = QRectF(5, 495, 95, 95)
J7_RECT = QRectF(-6, 205, 46, 60)
SEED_RECT = QRectF(5, 375, 315, 100)
AUDIO_JACKS = {  # id: (center x, label, implemented detection)
    "out_r": (205.0, "AUDIO OUT RIGHT"),
    "out_l": (365.0, "AUDIO OUT LEFT"),
    "in_r": (830.0, "AUDIO IN RIGHT"),
    "in_l": (955.0, "AUDIO IN LEFT"),
}
CV_JACKS = {
    "cv_out_1": (QPointF(480, 85), "CV OUT 1"),
    "cv_out_2": (QPointF(480, 175), "CV OUT 2"),
    "cv_in_1": (QPointF(660, 85), "CV IN 1"),
    "cv_in_2": (QPointF(660, 175), "CV IN 2"),
    "gate_in_1": (QPointF(718, 85), "GATE 1"),
    "gate_in_2": (QPointF(718, 175), "GATE 2"),
}
MIDI_JACKS = {"midi_out": (115.0, "OUT"), "midi_thru": (255.0, "THRU"), "midi_in": (395.0, "INPUT")}
PHONES_RECT = QRectF(1000, 545, 45, 125)
RV1_CENTER = QPointF(1130, 530)

NOT_IMPLEMENTED_TIPS = {
    "out_r": 'Right audio output (J4)\nAudio output: not implemented (silent)',
    "out_l": 'Left audio output (J3)\nAudio output: not implemented (silent)',
    "cv": 'CV inputs/outputs and gate inputs\nNot implemented',
    "midi": 'MIDI DIN (OUT/THRU/INPUT)\nNot implemented',
    "phones": 'Headphone output J5\nAudio output: not implemented',
    "rv1": 'RV1: analog headphone volume control\nCannot be read by software',
    "seed_usb": 'USB-C on the Seed3 module\nUsed only to install the bootloader; not used by this diagnostic application',
}


@dataclass
class SdDisplay:
    text: str
    color: QColor


def button_rect(i: int) -> QRectF:
    x = COL_X[i % 8]
    y = BTN_Y[i // 8]
    return QRectF(x - 17, y - 17, 34, 34)


def led_rect(i: int) -> QRectF:
    x = COL_X[i % 8]
    y = LED_Y[i // 8]
    return QRectF(x - 11, y - 6, 22, 12)


def pot_center(i: int) -> QPointF:
    return QPointF(POT_X[i], POT_Y)


def switch_rect(center: QPointF) -> QRectF:
    return QRectF(center.x() - 20, center.y() - 34, 40, 68)


def audio_jack_rect(x: float) -> QRectF:
    return QRectF(x - 55, -12, 110, 125)


def pot_angle(value: float) -> float:
    """Knob pointer angle in degrees, clockwise from 12 o'clock (-135 .. +135)."""
    return -135.0 + 270.0 * min(1.0, max(0.0, value))


class BoardWidget(QWidget):
    """Shows a BoardState. In simulation mode the controls can be operated by mouse."""

    buttonChanged = Signal(int, bool)
    potChanged = Signal(int, float)
    sw17Changed = Signal(str)
    sw18Changed = Signal(str)
    sdToggled = Signal()
    jackToggled = Signal(str)  # "left" / "right"
    ledClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 380)
        self.setMouseTracking(True)
        self.state: p.BoardState | None = None
        self.interactive = False  # simulation: inputs can be operated with the mouse
        self.led_selectable = False  # LED mode MASK: LEDs can be toggled
        self.simulated = False
        self.connected = False
        self.sd_display = SdDisplay('No data', theme.MUTED)
        self.pot_min: list[float | None] = [None] * p.NUM_POTS
        self.pot_max: list[float | None] = [None] * p.NUM_POTS
        self._drag_pot: int | None = None
        self._held_button: int | None = None
        self._transform_scale = 1.0
        self._offset = QPointF()

    # ---- coordinate mapping -----------------------------------------------------------
    def _update_transform(self) -> None:
        scale = min(self.width() / SCENE.width(), self.height() / SCENE.height())
        self._transform_scale = scale
        self._offset = QPointF((self.width() - SCENE.width() * scale) / 2 - SCENE.left() * scale,
                               (self.height() - SCENE.height() * scale) / 2 - SCENE.top() * scale)

    def to_board(self, pos: QPointF) -> QPointF:
        self._update_transform()
        return QPointF((pos.x() - self._offset.x()) / self._transform_scale,
                       (pos.y() - self._offset.y()) / self._transform_scale)

    def to_widget(self, pt: QPointF) -> QPointF:
        self._update_transform()
        return QPointF(pt.x() * self._transform_scale + self._offset.x(),
                       pt.y() * self._transform_scale + self._offset.y())

    def hit_test(self, pt: QPointF) -> tuple[str, int] | None:
        for i in range(p.NUM_BUTTONS):
            if button_rect(i).adjusted(-4, -4, 4, 4).contains(pt):
                return ("button", i)
            if led_rect(i).adjusted(-6, -6, 6, 6).contains(pt):
                return ("led", i)
        for i in range(p.NUM_POTS):
            c = pot_center(i)
            if math.hypot(pt.x() - c.x(), pt.y() - c.y()) <= 38:
                return ("pot", i)
        if switch_rect(SW17_POS).contains(pt):
            return ("sw17", 0)
        if switch_rect(SW18_POS).contains(pt):
            return ("sw18", 0)
        if SD_RECT.contains(pt):
            return ("sd", 0)
        if J7_RECT.contains(pt):
            return ("j7", 0)
        if SEED_RECT.contains(pt):
            return ("seed", 0)
        for key, (x, _label) in AUDIO_JACKS.items():
            if audio_jack_rect(x).contains(pt):
                return (key, 0)
        if QRectF(430, 30, 325, 190).contains(pt):
            return ("cv", 0)
        if QRectF(1050, 50, 130, 420).contains(pt):
            return ("midi", 0)
        if PHONES_RECT.contains(pt):
            return ("phones", 0)
        if math.hypot(pt.x() - RV1_CENTER.x(), pt.y() - RV1_CENTER.y()) <= 44:
            return ("rv1", 0)
        return None

    # ---- events ------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        pt = self.to_board(event.position())
        hit = self.hit_test(pt)
        if hit is None or event.button() != Qt.LeftButton:
            return
        kind, index = hit
        if kind == "led" and self.led_selectable:
            self.ledClicked.emit(index)
            return
        if not self.interactive:
            return
        if kind == "button":
            self._held_button = index
            self.buttonChanged.emit(index, True)
        elif kind == "pot":
            self._drag_pot = index
            self._drag_to(pt)
        elif kind == "sw17":
            self.sw17Changed.emit("U" if pt.y() < SW17_POS.y() else "D")
        elif kind == "sw18":
            dy = pt.y() - SW18_POS.y()
            self.sw18Changed.emit("U" if dy < -11 else "D" if dy > 11 else "C")
        elif kind == "sd":
            self.sdToggled.emit()
        elif kind == "in_l":
            self.jackToggled.emit("left")
        elif kind == "in_r":
            self.jackToggled.emit("right")

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pot is not None:
            self._drag_to(self.to_board(event.position()))
            return
        hit = self.hit_test(self.to_board(event.position()))
        clickable = hit is not None and (
            (self.interactive and hit[0] in ("button", "pot", "sw17", "sw18", "sd", "in_l", "in_r"))
            or (self.led_selectable and hit[0] == "led"))
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._held_button is not None:
            self.buttonChanged.emit(self._held_button, False)
            self._held_button = None
        self._drag_pot = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.interactive or self.state is None:
            return
        hit = self.hit_test(self.to_board(event.position()))
        if hit and hit[0] == "pot":
            step = 0.02 if event.angleDelta().y() > 0 else -0.02
            self.potChanged.emit(hit[1], min(1.0, max(0.0, self.state.pots[hit[1]] + step)))
            event.accept()

    def _drag_to(self, pt: QPointF) -> None:
        c = pot_center(self._drag_pot)
        angle = math.degrees(math.atan2(pt.x() - c.x(), -(pt.y() - c.y())))  # 0 = up, cw
        angle = max(-135.0, min(135.0, angle))
        self.potChanged.emit(self._drag_pot, (angle + 135.0) / 270.0)

    def event(self, ev) -> bool:
        if ev.type() == ev.Type.ToolTip:
            hit = self.hit_test(self.to_board(QPointF(ev.pos())))
            text = self.tooltip_for(hit)
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    def tooltip_for(self, hit: tuple[str, int] | None) -> str:
        if hit is None:
            return ""
        kind, i = hit
        st = self.state
        suffix = '\n(simulated data)' if self.simulated else ""
        if kind == "button":
            if st is None:
                return f"Button S{i + 1}"
            return (f"Button S{i + 1}: {'pressed' if st.buttons[i] else 'released'}\n"
                    f"Press count: {st.press_counts[i]} (modulo 256){suffix}")
        if kind == "led":
            state = 'no data' if st is None else ('ON' if st.leds[i] else 'OFF')
            hint = '\nClick to toggle this LED (Individual mode)' if self.led_selectable else ""
            return (f"LED D{i + 1}: commanded state {state}\n"
                    f"No electrical feedback – inspect the physical board.{hint}{suffix}")
        if kind == "pot":
            if st is None:
                return f"Potentiometer VR{i + 1}"
            return (f"VR{i + 1}: {st.pots[i] * 100:.1f} % (raw ADC {st.pots_raw[i]})"
                    f"{suffix}")
        if kind == "sw17":
            return 'SW17 (2 positions, ON-ON)\nU/D from libDaisy tog_sw17.Pressed();\nverify the physical direction on your board' + suffix
        if kind == "sw18":
            return 'SW18 (3 positions, ON-OFF-ON)\nU/C/D from libDaisy Switch3;\nverify the physical direction on your board' + suffix
        if kind == "sd":
            return f"microSD slot: {self.sd_display.text}{suffix}"
        if kind == "j7":
            return 'J7 USB-C (Desktop carrier)\nPower + USB CDC (DDP diagnostic protocol)'
        if kind == "seed":
            return NOT_IMPLEMENTED_TIPS["seed_usb"]
        if kind in ("in_l", "in_r"):
            side = 'left' if kind == "in_l" else 'right'
            plugged = None if st is None else (st.jack_left if kind == "in_l" else st.jack_right)
            plug_txt = 'no data' if plugged is None else ('plugged in' if plugged else 'unplugged')
            return (f"Audio input {side}: plug detection = {plug_txt}\n"
                    f"Audio input processing: not implemented{suffix}")
        return NOT_IMPLEMENTED_TIPS.get(kind, "")

    # ---- painting ----------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        self._update_transform()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self._offset)
        painter.scale(self._transform_scale, self._transform_scale)
        st = self.state
        self._paint_board(painter)
        self._paint_audio_jacks(painter, st)
        self._paint_cv_section(painter)
        self._paint_midi(painter)
        self._paint_usb_and_seed(painter)
        self._paint_sd(painter)
        self._paint_switches(painter, st)
        for i in range(p.NUM_POTS):
            self._paint_pot(painter, i, st)
        self._paint_button_area(painter, st)
        self._paint_phones(painter)
        if st is None:
            self._paint_overlay(painter)
        painter.end()

    # -- helpers --
    def _font(self, size: float, bold: bool = False, family: str = theme.TECH_FONT) -> QFont:
        return theme.font(family, size, bold)

    def _text(self, painter: QPainter, rect: QRectF, text: str, size: float = 9,
              color: QColor = theme.SILK, align=Qt.AlignCenter, bold: bool = False,
              family: str = theme.TECH_FONT) -> None:
        painter.setFont(self._font(size, bold, family))
        painter.setPen(color)
        painter.drawText(rect, int(align), text)

    def _ni_badge(self, painter: QPainter, center: QPointF) -> None:
        rect = QRectF(center.x() - 20, center.y() - 8, 40, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.NI_BADGE)
        painter.drawRoundedRect(rect, 1.5, 1.5)
        self._text(painter, rect, 'N/I', 7.5, theme.NI_TEXT)

    @staticmethod
    def _metal(rect: QRectF, light: str = "#d3d6d9", dark: str = "#8b8f94") -> QLinearGradient:
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor(light))
        grad.setColorAt(1, QColor(dark))
        return grad

    def _screw(self, painter: QPainter, c: QPointF, r: float) -> None:
        painter.setPen(QPen(QColor("#55585c"), 1))
        painter.setBrush(self._metal(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                                     "#c5c8cb", "#6f7378"))
        painter.drawEllipse(c, r, r)
        painter.setPen(QPen(QColor("#4a4d51"), 2))
        painter.drawLine(QPointF(c.x() - r * 0.6, c.y() - r * 0.6),
                         QPointF(c.x() + r * 0.6, c.y() + r * 0.6))

    # -- board --
    def _paint_board(self, painter: QPainter) -> None:
        board = QRectF(0, 0, BOARD_W, BOARD_H)
        shadow = QRectF(4, 6, BOARD_W, BOARD_H)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(shadow, 14, 14)
        grad = QLinearGradient(0, 0, 0, BOARD_H)
        grad.setColorAt(0, theme.PCB.lighter(108))
        grad.setColorAt(1, theme.PCB.darker(108))
        painter.setPen(QPen(theme.PCB_EDGE, 1.5))
        painter.setBrush(grad)
        painter.drawRoundedRect(board, 14, 14)
        for x, y in ((28, 22), (1130, 22), (28, 615), (1130, 615)):
            self._screw(painter, QPointF(x, y), 11)
        # open hardware mark and QR code, as printed on the board
        painter.setPen(QPen(theme.SILK, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(95, 55), 18, 18)
        painter.drawEllipse(QPointF(95, 55), 7, 7)
        self._text(painter, QRectF(50, 76, 90, 14), "open hardware", 7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.SILK)
        for r in range(9):
            for c in range(9):
                if ((r * 7 + c * 3 + r * c) % 5 < 2 or (r < 3 and c < 3) or (r < 3 and c > 5)
                        or (r > 5 and c < 3)):
                    painter.drawRect(QRectF(68 + c * 5.5, 100 + r * 5.5, 5, 5))
        self._text(painter, QRectF(40, 152, 120, 14), "Get Started Here!", 7)
        self._text(painter, QRectF(430, 2, 330, 26), "Seed3  Desktop  Dev  Kit", 14,
                   theme.SILK, bold=True)

    # -- jacks --
    def _paint_audio_jacks(self, painter: QPainter, st: p.BoardState | None) -> None:
        for key, (x, label) in AUDIO_JACKS.items():
            rect = audio_jack_rect(x)
            grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
            grad.setColorAt(0, QColor("#0d0e0f"))
            grad.setColorAt(0.45, QColor("#2a2c2f"))
            grad.setColorAt(1, QColor("#0d0e0f"))
            painter.setPen(QPen(QColor("#050505"), 1.5))
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QPen(QColor("#3c3f43"), 1.5))
            for k in range(3):
                y = rect.top() + 24 + k * 24
                painter.drawLine(QPointF(rect.left() + 6, y), QPointF(rect.right() - 6, y))
            detected = None
            if st is not None and key == "in_l":
                detected = st.jack_left
            elif st is not None and key == "in_r":
                detected = st.jack_right
            painter.setPen(QPen(theme.OK if detected else QColor("#000000"),
                                3 if detected else 1.5))
            painter.setBrush(QColor("#000000"))
            painter.drawEllipse(QPointF(x, rect.top() + 7), 17, 8)
            self._text(painter, QRectF(x - 70, 118, 140, 14), label, 8)
            if key.startswith("in"):
                txt = "–" if detected is None else ('Plug detected' if detected else 'no plug')
                self._text(painter, QRectF(x - 70, 133, 140, 14), txt, 8,
                           theme.OK if detected else theme.SILK_MUTED)
                self._ni_badge(painter, QPointF(x, 160))
            else:
                self._ni_badge(painter, QPointF(x, 145))

    def _mini_jack(self, painter: QPainter, center: QPointF, label: str) -> None:
        painter.setPen(QPen(QColor("#050505"), 1))
        painter.setBrush(theme.PLASTIC)
        painter.drawRect(QRectF(center.x() - 21, center.y() - 21, 42, 42))
        painter.setPen(QPen(QColor("#4c4f53"), 1))
        painter.setBrush(self._metal(QRectF(center.x() - 13, center.y() - 13, 26, 26)))
        painter.drawEllipse(center, 13, 13)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(center, 6, 6)
        self._text(painter, QRectF(center.x() - 40, center.y() - 40, 80, 14), label, 7.5)

    def _paint_cv_section(self, painter: QPainter) -> None:
        painter.setPen(QPen(theme.SILK, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(430, 30, 325, 190))
        for center, label in CV_JACKS.values():
            self._mini_jack(painter, center, label)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.SILK)
        c = QPointF(570, 85)
        for k in range(8):
            a = math.radians(k * 45)
            painter.drawEllipse(QPointF(c.x() + 15 * math.sin(a), c.y() - 15 * math.cos(a)), 7, 7)
        painter.setBrush(theme.PCB)
        painter.drawEllipse(c, 6, 6)
        self._text(painter, QRectF(500, 140, 140, 16), "CV / Gate", 8.5, theme.SILK_MUTED)
        self._ni_badge(painter, QPointF(570, 170))

    def _paint_midi(self, painter: QPainter) -> None:
        for y, label in MIDI_JACKS.values():
            body = QRectF(1052, y - 60, 122, 120)
            painter.setPen(QPen(QColor("#050505"), 1.5))
            painter.setBrush(QColor("#151617"))
            painter.drawRoundedRect(body, 3, 3)
            painter.setPen(QPen(QColor("#2e3033"), 1.5))
            painter.drawLine(QPointF(1060, y - 40), QPointF(1166, y - 40))
            painter.drawLine(QPointF(1060, y + 40), QPointF(1166, y + 40))
            painter.save()
            painter.translate(1038, y)
            painter.rotate(-90)
            self._text(painter, QRectF(-50, -8, 100, 16), label, 9, bold=True)
            painter.restore()
        self._text(painter, QRectF(1050, 465, 125, 14), "MIDI DIN", 8, theme.SILK_MUTED)
        self._ni_badge(painter, QPointF(1113, 255))

    def _paint_usb_and_seed(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#4c4f53"), 1))
        painter.setBrush(self._metal(J7_RECT))
        painter.drawRoundedRect(J7_RECT, 5, 5)
        painter.setBrush(QColor("#161718"))
        painter.drawRoundedRect(QRectF(J7_RECT.left() + 7, J7_RECT.top() + 14, 11, 32), 5, 5)
        self._text(painter, QRectF(44, 211, 140, 14), "J7 USB-C", 8.5, theme.SILK,
                   Qt.AlignLeft, bold=True)
        self._text(painter, QRectF(44, 227, 160, 14),
                   'DDP connected' if self.connected else 'DDP disconnected', 8,
                   theme.OK if self.connected else theme.SILK_MUTED, Qt.AlignLeft)
        # Seed3 module
        painter.setPen(QPen(QColor("#050505"), 1))
        painter.setBrush(QColor("#111213"))
        painter.drawRoundedRect(SEED_RECT, 3, 3)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#b8964a"))
        for k in range(20):
            x = SEED_RECT.left() + 14 + k * 15
            painter.drawEllipse(QPointF(x, SEED_RECT.top() + 9), 3.2, 3.2)
            painter.drawEllipse(QPointF(x, SEED_RECT.bottom() - 9), 3.2, 3.2)
        painter.setBrush(self._metal(QRectF(10, 405, 34, 42)))
        painter.drawRoundedRect(QRectF(10, 405, 34, 42), 4, 4)
        painter.setBrush(QColor("#1d1e20"))
        painter.drawRect(QRectF(130, 395, 60, 60))
        self._text(painter, QRectF(200, 405, 110, 40), "Seed3", 12, theme.SILK, bold=True)

    def _paint_sd(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#4c4f53"), 1))
        painter.setBrush(self._metal(SD_RECT, "#c9ccd0", "#8e9297"))
        painter.drawRoundedRect(SD_RECT, 2, 2)
        slot = QRectF(SD_RECT.left() + 12, SD_RECT.top() + 10, SD_RECT.width() - 24, 52)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1d1e20"))
        painter.drawRect(slot)
        if self.state is not None and self.state.sd_card:
            r = slot.adjusted(7, -12, -7, -6)
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + 8)
            path.lineTo(r.left() + 8, r.top())
            path.lineTo(r.right(), r.top())
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            painter.setPen(QPen(QColor("#5c6066"), 1))
            painter.setBrush(QColor("#2b2d30"))
            painter.drawPath(path)
            self._text(painter, r.adjusted(0, 10, 0, 0), "SD", 8, theme.SILK, bold=True)
        self._text(painter, QRectF(SD_RECT.left(), SD_RECT.bottom() - 30, SD_RECT.width(), 14),
                   "microSD", 8.5, QColor("#1b1c1e"), bold=True)
        short = self.sd_display.text.split(" (")[0]  # details are in the side panel
        self._text(painter, QRectF(SD_RECT.left() - 2, SD_RECT.bottom() + 3, 132, 34), short, 8,
                   self.sd_display.color, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   bold=True)

    # -- toggle switches --
    def _paint_toggle(self, painter: QPainter, center: QPointF, pos: str | None, label: str,
                      sub: str, positions: str) -> None:
        rect = switch_rect(center)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        grad.setColorAt(0, theme.SWITCH_BODY.darker(125))
        grad.setColorAt(0.5, theme.SWITCH_BODY)
        grad.setColorAt(1, theme.SWITCH_BODY.darker(125))
        painter.setPen(QPen(QColor("#5c1714"), 1))
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, 2, 2)
        # bushing nut
        painter.setPen(QPen(QColor("#55585c"), 1))
        painter.setBrush(self._metal(QRectF(center.x() - 12, center.y() - 12, 24, 24)))
        painter.drawEllipse(center, 12, 12)
        painter.setBrush(QColor("#3a3c3f"))
        painter.drawEllipse(center, 5, 5)
        if pos is not None:
            dy = {"U": -24.0, "C": 0.0, "D": 24.0}[pos]
            tip = QPointF(center.x(), center.y() + dy)
            painter.setPen(QPen(QColor("#9da1a6"), 7, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(center, tip)
            painter.setPen(QPen(QColor("#e7e9eb"), 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(center, tip)
            painter.setPen(QPen(QColor("#5c6066"), 1))
            painter.setBrush(self._metal(QRectF(tip.x() - 7, tip.y() - 7, 14, 14),
                                         "#ffffff", "#9a9ea3"))
            painter.drawEllipse(tip, 7, 7)
        for ch in positions:
            y = {"U": -26, "C": 0, "D": 26}[ch]
            active = ch == pos
            self._text(painter, QRectF(center.x() + 20, center.y() + y - 8, 16, 16), ch, 8,
                       theme.SILK if active else theme.SILK_MUTED, bold=active)
        self._text(painter, QRectF(center.x() - 45, center.y() + 36, 90, 14), label, 9, bold=True)
        self._text(painter, QRectF(center.x() - 45, center.y() + 50, 90, 14), sub, 7.5,
                   theme.SILK_MUTED)

    def _paint_switches(self, painter: QPainter, st: p.BoardState | None) -> None:
        self._paint_toggle(painter, SW18_POS, st.sw18 if st else None, "SW18", "ON-OFF-ON", "UCD")
        self._paint_toggle(painter, SW17_POS, st.sw17 if st else None, "SW17", "ON-ON", "UD")

    # -- potentiometers --
    def _paint_pot(self, painter: QPainter, i: int, st: p.BoardState | None) -> None:
        c = pot_center(i)
        # mounting tabs
        painter.setPen(QPen(QColor("#4c4f53"), 1))
        painter.setBrush(self._metal(QRectF(c.x() - 42, c.y() - 8, 84, 16)))
        painter.drawRect(QRectF(c.x() - 42, c.y() - 6, 7, 12))
        painter.drawRect(QRectF(c.x() + 35, c.y() - 6, 7, 12))
        # printed scale: 270 degrees, 11 major and 10 minor ticks
        for k in range(21):
            a = math.radians(pot_angle(k / 20))
            major = k % 2 == 0
            r1, r2 = (31.0, 37.5) if major else (31.0, 34.5)
            painter.setPen(QPen(theme.SILK if major else theme.SILK_MUTED, 1.4 if major else 1))
            painter.drawLine(QPointF(c.x() + r1 * math.sin(a), c.y() - r1 * math.cos(a)),
                             QPointF(c.x() + r2 * math.sin(a), c.y() - r2 * math.cos(a)))
        # min/max markers seen since connecting
        lo, hi = self.pot_min[i], self.pot_max[i]
        if lo is not None and hi is not None:
            for v in (lo, hi):
                a = math.radians(pot_angle(v))
                tip = QPointF(c.x() + 39 * math.sin(a), c.y() - 39 * math.cos(a))
                left = QPointF(c.x() + 45 * math.sin(a - 0.09), c.y() - 45 * math.cos(a - 0.09))
                right = QPointF(c.x() + 45 * math.sin(a + 0.09), c.y() - 45 * math.cos(a + 0.09))
                path = QPainterPath(tip)
                path.lineTo(left)
                path.lineTo(right)
                path.closeSubpath()
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.SILK_MUTED)
                painter.drawPath(path)
        # knob: black, knurled skirt, white pointer
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QColor("#0b0b0c"))
        painter.drawEllipse(c, 27, 27)
        painter.setPen(QPen(QColor("#2a2b2d"), 1))
        for k in range(36):
            a = math.radians(k * 10)
            painter.drawLine(QPointF(c.x() + 23.5 * math.sin(a), c.y() - 23.5 * math.cos(a)),
                             QPointF(c.x() + 26.5 * math.sin(a), c.y() - 26.5 * math.cos(a)))
        top = QRadialGradient(c.x() - 7, c.y() - 9, 26)
        top.setColorAt(0, QColor("#38393c"))
        top.setColorAt(1, QColor("#0e0e0f"))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(top)
        painter.drawEllipse(c, 22, 22)
        if st is not None:
            a = math.radians(pot_angle(st.pots[i]))
            painter.setPen(QPen(QColor("#f4f4f2"), 3.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(c.x() + 6 * math.sin(a), c.y() - 6 * math.cos(a)),
                             QPointF(c.x() + 20 * math.sin(a), c.y() - 20 * math.cos(a)))
        self._text(painter, QRectF(c.x() - 45, c.y() - 62, 90, 16), f"VR{i + 1}", 9.5, bold=True)
        box = QRectF(c.x() - 30, c.y() + 41, 60, 18)
        painter.setPen(QPen(QColor("#45484c"), 1))
        painter.setBrush(QColor("#0c0d0e"))
        painter.drawRect(box)
        val = "–" if st is None else f"{st.pots[i] * 100:.1f} %"
        self._text(painter, box, val, 8.5, theme.TEXT if st else theme.FAINT,
                   family=theme.MONO_FONT)
        if lo is not None and hi is not None:
            self._text(painter, QRectF(c.x() - 45, c.y() + 60, 90, 13),
                       f"{lo * 100:.0f}–{hi * 100:.0f} %", 7, theme.SILK_MUTED)

    # -- buttons and LEDs --
    def _paint_button_area(self, painter: QPainter, st: p.BoardState | None) -> None:
        painter.setPen(QPen(theme.SILK, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(365, 425, 580, 200))
        for i in range(p.NUM_BUTTONS):
            self._paint_led(painter, i, st)
            self._paint_button(painter, i, st)

    def _paint_led(self, painter: QPainter, i: int, st: p.BoardState | None) -> None:
        rect = led_rect(i)
        on = st is not None and st.leds[i]
        level = (st.led_brightness / 100.0) if st else 0.0
        if on and level > 0:
            halo = QRadialGradient(rect.center(), 26)
            col = QColor(theme.LED_ON)
            col.setAlphaF(0.55 * level)
            halo.setColorAt(0, col)
            halo.setColorAt(1, QColor(255, 47, 36, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(rect.center(), 26, 19)
        if on:
            lens = QRadialGradient(rect.center(), rect.width() / 2)
            lens.setColorAt(0, QColor("#ffe0da") if level > 0.5 else theme.LED_ON)
            lens.setColorAt(0.5, theme.LED_ON)
            lens.setColorAt(1, QColor(theme.LED_ON).darker(int(140 - 40 * level)))
            painter.setPen(QPen(QColor("#ff8a80"), 1))
            painter.setBrush(lens)
        else:
            painter.setPen(QPen(QColor("#1d0b0a"), 1))
            painter.setBrush(theme.LED_OFF)
        painter.drawRoundedRect(rect, 3, 3)
        self._text(painter, QRectF(rect.left() - 32, rect.top() - 2, 30, 16), f"D{i + 1}", 7.5,
                   theme.SILK_MUTED, Qt.AlignRight | Qt.AlignVCenter)

    def _paint_button(self, painter: QPainter, i: int, st: p.BoardState | None) -> None:
        rect = button_rect(i)
        pressed = st is not None and st.buttons[i]
        c = rect.center()
        # metal switch body
        painter.setPen(QPen(QColor("#f2f2f0") if pressed else QColor("#1a1b1c"),
                            2.2 if pressed else 1))
        painter.setBrush(self._metal(rect, "#cfd2d5", "#8a8e93"))
        painter.drawRoundedRect(rect, 1.5, 1.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#6c7075"))
        for dx in (-13, 13):
            for dy in (-13, 13):
                painter.drawEllipse(QPointF(c.x() + dx, c.y() + dy), 2.2, 2.2)
        # round actuator: raised when released, pushed in (smaller, darker, shaded) when pressed
        if pressed:
            painter.setBrush(QColor("#3b3d40"))
            painter.drawEllipse(c, 12, 12)
            cap = QRadialGradient(c.x() + 2, c.y() + 2, 11)
            cap.setColorAt(0, theme.BUTTON_CAP.darker(150))
            cap.setColorAt(1, theme.BUTTON_CAP.darker(210))
            painter.setBrush(cap)
            painter.setPen(QPen(QColor("#2a1d10"), 1))
            painter.drawEllipse(c, 9, 9)
        else:
            painter.setBrush(QColor(0, 0, 0, 70))
            painter.drawEllipse(QPointF(c.x() + 1.5, c.y() + 2), 11.5, 11.5)
            cap = QRadialGradient(c.x() - 3, c.y() - 4, 13)
            cap.setColorAt(0, theme.BUTTON_CAP.lighter(125))
            cap.setColorAt(1, theme.BUTTON_CAP.darker(125))
            painter.setBrush(cap)
            painter.setPen(QPen(QColor("#5e4227"), 1))
            painter.drawEllipse(c, 11, 11)
        self._text(painter, QRectF(rect.left() - 34, rect.top() + 9, 32, 16), f"S{i + 1}", 8.5,
                   theme.SILK if pressed else theme.SILK_MUTED, Qt.AlignRight | Qt.AlignVCenter,
                   bold=pressed)

    # -- headphones, RV1 --
    def _paint_phones(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#050505"), 1.5))
        painter.setBrush(QColor("#141516"))
        painter.drawRoundedRect(PHONES_RECT, 3, 3)
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(QPointF(PHONES_RECT.center().x(), PHONES_RECT.bottom() - 6), 10, 6)
        self._text(painter, QRectF(935, 520, 90, 14), "PHONES J5", 7.5)
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QColor("#0b0b0c"))
        painter.drawEllipse(RV1_CENTER, 42, 42)
        painter.setPen(QPen(QColor("#26272a"), 1))
        for k in range(48):
            a = math.radians(k * 7.5)
            painter.drawLine(QPointF(RV1_CENTER.x() + 37 * math.sin(a), RV1_CENTER.y() - 37 * math.cos(a)),
                             QPointF(RV1_CENTER.x() + 41 * math.sin(a), RV1_CENTER.y() - 41 * math.cos(a)))
        top = QRadialGradient(RV1_CENTER.x() - 10, RV1_CENTER.y() - 12, 40)
        top.setColorAt(0, QColor("#333437"))
        top.setColorAt(1, QColor("#0d0d0e"))
        painter.setBrush(top)
        painter.drawEllipse(RV1_CENTER, 34, 34)
        self._text(painter, QRectF(1080, 576, 100, 14), "RV1 (analog)", 8, theme.SILK_MUTED)

    def _paint_overlay(self, painter: QPainter) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(12, 13, 14, 165))
        painter.drawRoundedRect(QRectF(0, 0, BOARD_W, BOARD_H), 14, 14)
        self._text(painter, QRectF(0, 258, BOARD_W, 40), 'No device data', 22, theme.TEXT,
                   bold=True)
        self._text(painter, QRectF(0, 300, BOARD_W, 30),
                   'Connect a Daisy Seed3 via J7 or select Simulation', 12, theme.MUTED)

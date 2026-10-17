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
    "out_r": "Audioausgang rechts (J4)\nAudio-Ausgabe: nicht implementiert (stumm)",
    "out_l": "Audioausgang links (J3)\nAudio-Ausgabe: nicht implementiert (stumm)",
    "cv": "CV-Ein-/Ausgänge und Gate-Eingänge\nNicht implementiert",
    "midi": "MIDI DIN (OUT/THRU/INPUT)\nNicht implementiert",
    "phones": "Kopfhörerausgang J5\nAudio-Ausgabe: nicht implementiert",
    "rv1": "RV1: analoger Kopfhörer-Lautstärkeregler\nNicht per Software lesbar",
    "seed_usb": "USB-C am Seed3-Modul\nNur für die Bootloader-Installation; von dieser Diagnose nicht verwendet",
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
        self.sd_display = SdDisplay("Keine Daten", theme.MUTED)
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
        suffix = "\n(simulierte Daten)" if self.simulated else ""
        if kind == "button":
            if st is None:
                return f"Taster S{i + 1}"
            return (f"Taster S{i + 1}: {'gedrückt' if st.buttons[i] else 'losgelassen'}\n"
                    f"Druckzähler: {st.press_counts[i]} (modulo 256){suffix}")
        if kind == "led":
            state = "keine Daten" if st is None else ("EIN" if st.leds[i] else "AUS")
            hint = "\nKlicken schaltet diese LED (Modus „Einzeln“)" if self.led_selectable else ""
            return (f"LED D{i + 1}: Sollzustand {state}\n"
                    f"Keine elektrische Rückmeldung – bitte am Board ansehen.{hint}{suffix}")
        if kind == "pot":
            if st is None:
                return f"Potentiometer VR{i + 1}"
            return (f"VR{i + 1}: {st.pots[i] * 100:.1f} % (ADC roh {st.pots_raw[i]})"
                    f"{suffix}")
        if kind == "sw17":
            return "SW17 (2 Positionen, ON-ON)\nU/D nach libDaisy tog_sw17.Pressed();\n" \
                   "physische Richtung beim ersten Hardwaretest bestätigen" + suffix
        if kind == "sw18":
            return "SW18 (3 Positionen, ON-OFF-ON)\nU/C/D nach libDaisy Switch3;\n" \
                   "physische Richtung beim ersten Hardwaretest bestätigen" + suffix
        if kind == "sd":
            return f"microSD-Steckplatz: {self.sd_display.text}{suffix}"
        if kind == "j7":
            return "J7 USB-C (Desktop-Träger)\nStromversorgung + USB CDC (Diagnoseprotokoll DDP)"
        if kind == "seed":
            return NOT_IMPLEMENTED_TIPS["seed_usb"]
        if kind in ("in_l", "in_r"):
            side = "links" if kind == "in_l" else "rechts"
            plugged = None if st is None else (st.jack_left if kind == "in_l" else st.jack_right)
            plug_txt = "keine Daten" if plugged is None else ("gesteckt" if plugged else "frei")
            return (f"Audioeingang {side}: Steckererkennung = {plug_txt}\n"
                    f"Audio-Eingang selbst: nicht implementiert{suffix}")
        return NOT_IMPLEMENTED_TIPS.get(kind, "")

    # ---- painting ----------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        self._update_transform()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self._offset)
        painter.scale(self._transform_scale, self._transform_scale)
        self._paint_board(painter)
        st = self.state
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

    def _font(self, size: float, bold: bool = False) -> QFont:
        font = QFont("Segoe UI")
        font.setPointSizeF(size)
        font.setBold(bold)
        return font

    def _text(self, painter: QPainter, rect: QRectF, text: str, size: float = 9,
              color: QColor = theme.SILK, align=Qt.AlignCenter, bold: bool = False) -> None:
        painter.setFont(self._font(size, bold))
        painter.setPen(color)
        painter.drawText(rect, int(align), text)

    def _ni_badge(self, painter: QPainter, center: QPointF) -> None:
        rect = QRectF(center.x() - 22, center.y() - 8, 44, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.NI_BADGE)
        painter.drawRoundedRect(rect, 8, 8)
        self._text(painter, rect, "n. i.", 7.5, theme.NI_TEXT, bold=True)

    def _paint_board(self, painter: QPainter) -> None:
        grad = QLinearGradient(0, 0, 0, BOARD_H)
        grad.setColorAt(0, QColor("#24272d"))
        grad.setColorAt(1, QColor("#191b20"))
        painter.setPen(QPen(QColor("#3a3e46"), 2))
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(0, 0, BOARD_W, BOARD_H), 18, 18)
        painter.setPen(QPen(QColor("#5b616b"), 1.5))
        painter.setBrush(QColor("#9aa0a8"))
        for x, y in ((28, 22), (1130, 22), (28, 615), (1130, 615)):
            painter.drawEllipse(QPointF(x, y), 11, 11)
            painter.drawLine(QPointF(x - 6, y - 6), QPointF(x + 6, y + 6))
        # open hardware logo and QR code (decoration, as on the silkscreen)
        painter.setPen(QPen(theme.SILK, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(95, 55), 20, 20)
        painter.drawEllipse(QPointF(95, 55), 8, 8)
        self._text(painter, QRectF(55, 78, 80, 14), "open hardware", 7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.SILK)
        for r in range(9):
            for c in range(9):
                if (r * 7 + c * 3 + r * c) % 5 < 2 or (r < 3 and c < 3) or (r < 3 and c > 5) or (r > 5 and c < 3):
                    painter.drawRect(QRectF(62 + c * 6, 100 + r * 6, 5.5, 5.5))
        self._text(painter, QRectF(40, 158, 120, 14), "Get Started Here!", 7)
        self._text(painter, QRectF(450, 4, 260, 22), "Seed3  Desktop  Dev  Kit", 13)

    def _paint_audio_jacks(self, painter: QPainter, st: p.BoardState | None) -> None:
        for key, (x, label) in AUDIO_JACKS.items():
            rect = audio_jack_rect(x)
            grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
            grad.setColorAt(0, QColor("#2b2d31"))
            grad.setColorAt(0.5, QColor("#4a4d53"))
            grad.setColorAt(1, QColor("#2b2d31"))
            painter.setPen(QPen(QColor("#0e0f11"), 2))
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QPen(QColor("#6d7178"), 2))
            for k in range(3):
                y = rect.top() + 22 + k * 22
                painter.drawLine(QPointF(rect.left() + 8, y), QPointF(rect.right() - 8, y))
            detected = None
            if st is not None and key == "in_l":
                detected = st.jack_left
            elif st is not None and key == "in_r":
                detected = st.jack_right
            ring = theme.OK if detected else QColor("#15161a")
            painter.setPen(QPen(ring, 4 if detected else 2))
            painter.setBrush(QColor("#0b0c0e"))
            painter.drawEllipse(QPointF(x, rect.top() + 6), 16, 9)
            self._text(painter, QRectF(x - 70, 118, 140, 14), label, 7.5)
            if key.startswith("in"):
                txt = "–" if detected is None else ("Stecker erkannt" if detected else "kein Stecker")
                col = theme.OK if detected else theme.MUTED
                self._text(painter, QRectF(x - 70, 133, 140, 14), txt, 8, col, bold=bool(detected))
                self._ni_badge(painter, QPointF(x, 160))
            else:
                self._ni_badge(painter, QPointF(x, 145))

    def _mini_jack(self, painter: QPainter, center: QPointF, label: str) -> None:
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#34373c"))
        painter.drawRoundedRect(QRectF(center.x() - 22, center.y() - 22, 44, 44), 5, 5)
        painter.setBrush(QColor("#8a8f96"))
        painter.drawEllipse(center, 13, 13)
        painter.setBrush(QColor("#0b0c0e"))
        painter.drawEllipse(center, 6, 6)
        self._text(painter, QRectF(center.x() - 40, center.y() - 40, 80, 14), label, 7)

    def _paint_cv_section(self, painter: QPainter) -> None:
        painter.setPen(QPen(theme.SILK, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(430, 30, 325, 190))
        for center, label in CV_JACKS.values():
            self._mini_jack(painter, center, label)
        # Daisy logo
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#f2f2f2"))
        c = QPointF(570, 85)
        for k in range(8):
            a = math.radians(k * 45)
            painter.drawEllipse(QPointF(c.x() + 17 * math.sin(a), c.y() - 17 * math.cos(a)), 8, 8)
        painter.setBrush(QColor("#c9c9c9"))
        painter.drawEllipse(c, 8, 8)
        self._text(painter, QRectF(500, 140, 140, 16), "CV / Gate", 8.5, theme.MUTED)
        self._ni_badge(painter, QPointF(570, 170))

    def _paint_midi(self, painter: QPainter) -> None:
        for y, label in MIDI_JACKS.values():
            body = QRectF(1050, y - 60, 125, 120)
            painter.setPen(QPen(QColor("#0e0f11"), 2))
            painter.setBrush(QColor("#1d1f23"))
            painter.drawRoundedRect(body, 10, 10)
            painter.setPen(QPen(QColor("#3c3f45"), 1.5))
            painter.drawLine(QPointF(1060, y - 40), QPointF(1165, y - 40))
            painter.drawLine(QPointF(1060, y + 40), QPointF(1165, y + 40))
            painter.save()
            painter.translate(1038, y)
            painter.rotate(-90)
            self._text(painter, QRectF(-50, -8, 100, 16), label, 9, bold=True)
            painter.restore()
        self._text(painter, QRectF(1050, 465, 125, 14), "MIDI DIN", 8, theme.MUTED)
        self._ni_badge(painter, QPointF(1112, 255))

    def _paint_usb_and_seed(self, painter: QPainter) -> None:
        # J7: carrier USB-C (power + DDP)
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#b8bcc2"))
        painter.drawRoundedRect(J7_RECT, 6, 6)
        painter.setBrush(QColor("#2a2c30"))
        painter.drawRoundedRect(QRectF(J7_RECT.left() + 6, J7_RECT.top() + 14, 12, 32), 5, 5)
        col = theme.OK if self.connected else theme.MUTED
        self._text(painter, QRectF(42, 210, 120, 14), "J7 USB-C", 8, theme.SILK, Qt.AlignLeft)
        self._text(painter, QRectF(42, 225, 160, 14),
                   "DDP verbunden" if self.connected else "DDP getrennt", 8, col, Qt.AlignLeft,
                   bold=self.connected)
        # Seed3 module
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#121316"))
        painter.drawRoundedRect(SEED_RECT, 6, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#c8a74d"))
        for k in range(20):
            x = SEED_RECT.left() + 14 + k * 15
            painter.drawEllipse(QPointF(x, SEED_RECT.top() + 9), 3.5, 3.5)
            painter.drawEllipse(QPointF(x, SEED_RECT.bottom() - 9), 3.5, 3.5)
        painter.setBrush(QColor("#b8bcc2"))
        painter.drawRoundedRect(QRectF(10, 405, 34, 42), 5, 5)
        painter.setBrush(QColor("#26282c"))
        painter.drawRect(QRectF(130, 395, 60, 60))
        self._text(painter, QRectF(200, 405, 110, 40), "Seed3", 11, theme.SILK, bold=True)

    def _paint_sd(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#9da2a9"))
        painter.drawRoundedRect(SD_RECT, 4, 4)
        card = self.state is not None and self.state.sd_card
        slot = QRectF(SD_RECT.left() + 12, SD_RECT.top() + 10, SD_RECT.width() - 24, 52)
        painter.setBrush(QColor("#2b2d31"))
        painter.drawRect(slot)
        if card:
            painter.setBrush(self.sd_display.color)
            path = QPainterPath()
            r = slot.adjusted(6, -14, -6, -4)
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + 8)
            path.lineTo(r.left() + 8, r.top())
            path.lineTo(r.right(), r.top())
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        self._text(painter, QRectF(SD_RECT.left(), SD_RECT.bottom() - 30, SD_RECT.width(), 14),
                   "microSD", 8, QColor("#1b1d21"), bold=True)
        short = self.sd_display.text.split(" (")[0]  # details are in the side panel
        self._text(painter, QRectF(SD_RECT.left() - 2, SD_RECT.bottom() + 2, 132, 34), short, 8,
                   self.sd_display.color, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   bold=True)

    def _paint_toggle(self, painter: QPainter, center: QPointF, pos: str | None, label: str,
                      sub: str, positions: str) -> None:
        rect = switch_rect(center)
        painter.setPen(QPen(QColor("#7a2a2a"), 2))
        painter.setBrush(QColor("#c94a4a"))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setBrush(QColor("#d6d8dc"))
        painter.setPen(QPen(QColor("#555"), 1))
        painter.drawEllipse(center, 12, 12)
        if pos is not None:
            dy = {"U": -22.0, "C": 0.0, "D": 22.0}[pos]
            tip = QPointF(center.x(), center.y() + dy)
            painter.setPen(QPen(QColor("#e6e8ea"), 7, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(center, tip)
            painter.setPen(QPen(theme.ACCENT, 2))
            painter.setBrush(QColor("#f5f6f7"))
            painter.drawEllipse(tip, 7, 7)
        for k, ch in enumerate(positions):
            y = {"U": -26, "C": 0, "D": 26}[ch]
            active = ch == pos
            self._text(painter, QRectF(center.x() + 20, center.y() + y - 8, 16, 16), ch, 8,
                       theme.ACCENT if active else theme.MUTED, bold=active)
        self._text(painter, QRectF(center.x() - 45, center.y() + 36, 90, 14), label, 8.5, bold=True)
        self._text(painter, QRectF(center.x() - 45, center.y() + 50, 90, 14), sub, 7, theme.MUTED)

    def _paint_switches(self, painter: QPainter, st: p.BoardState | None) -> None:
        self._paint_toggle(painter, SW18_POS, st.sw18 if st else None, "SW18", "ON-OFF-ON", "UCD")
        self._paint_toggle(painter, SW17_POS, st.sw17 if st else None, "SW17", "ON-ON", "UD")

    def _paint_pot(self, painter: QPainter, i: int, st: p.BoardState | None) -> None:
        c = pot_center(i)
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#d9dbde"))
        painter.drawRoundedRect(QRectF(c.x() - 36, c.y() - 30, 72, 60), 6, 6)
        painter.setBrush(QColor("#9da2a9"))
        painter.drawRect(QRectF(c.x() - 41, c.y() - 8, 6, 16))
        painter.drawRect(QRectF(c.x() + 35, c.y() - 8, 6, 16))
        # value arc and min/max range
        arc_rect = QRectF(c.x() - 33, c.y() - 33, 66, 66)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#4a4e55"), 4, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(arc_rect, int(225 * 16), int(-270 * 16))
        lo, hi = self.pot_min[i], self.pot_max[i]
        if lo is not None and hi is not None and hi > lo:
            painter.setPen(QPen(theme.RANGE, 4, Qt.SolidLine, Qt.FlatCap))
            painter.drawArc(arc_rect, int((225 - 270 * lo) * 16), int(-270 * (hi - lo) * 16))
        if st is not None:
            painter.setPen(QPen(theme.ACCENT, 4, Qt.SolidLine, Qt.FlatCap))
            painter.drawArc(arc_rect, int(225 * 16), int(-270 * st.pots[i] * 16))
        knob = QRadialGradient(c.x() - 6, c.y() - 6, 30)
        knob.setColorAt(0, QColor("#3b3e44"))
        knob.setColorAt(1, QColor("#0f1012"))
        painter.setPen(QPen(QColor("#000"), 1))
        painter.setBrush(knob)
        painter.drawEllipse(c, 24, 24)
        if st is not None:
            a = math.radians(pot_angle(st.pots[i]))
            tip = QPointF(c.x() + 19 * math.sin(a), c.y() - 19 * math.cos(a))
            painter.setPen(QPen(QColor("#f5f6f7"), 4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(c.x() + 5 * math.sin(a), c.y() - 5 * math.cos(a)), tip)
        self._text(painter, QRectF(c.x() - 45, c.y() - 58, 90, 16), f"VR{i + 1}", 9, bold=True)
        val = "–" if st is None else f"{st.pots[i] * 100:5.1f} %"
        self._text(painter, QRectF(c.x() - 45, c.y() + 34, 90, 16), val, 10,
                   theme.ACCENT if st else theme.MUTED, bold=True)
        if lo is not None and hi is not None:
            self._text(painter, QRectF(c.x() - 45, c.y() + 50, 90, 14),
                       f"{lo * 100:.0f}–{hi * 100:.0f} %", 7.5, theme.RANGE)

    def _paint_button_area(self, painter: QPainter, st: p.BoardState | None) -> None:
        painter.setPen(QPen(theme.SILK, 2))
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
            glow = QRadialGradient(rect.center(), 26)
            col = QColor(theme.LED_ON)
            col.setAlphaF(0.55 * level)
            glow.setColorAt(0, col)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(rect.center(), 26, 22)
        painter.setPen(QPen(theme.ACCENT if self.led_selectable else QColor("#55595f"),
                            1.5 if self.led_selectable else 1))
        if on:
            fill = QColor(theme.LED_ON)
            fill.setAlphaF(0.35 + 0.65 * level)
            painter.setBrush(fill)
        else:
            painter.setBrush(QColor("#4a4d52"))
        painter.drawRoundedRect(rect, 2, 2)
        self._text(painter, QRectF(rect.left() - 32, rect.top() - 3, 30, 16), f"D{i + 1}", 7.5,
                   theme.MUTED, Qt.AlignRight | Qt.AlignVCenter)

    def _paint_button(self, painter: QPainter, i: int, st: p.BoardState | None) -> None:
        rect = button_rect(i)
        pressed = st is not None and st.buttons[i]
        if pressed:
            painter.setPen(Qt.NoPen)
            glow = QRadialGradient(rect.center(), 34)
            col = QColor(theme.ACCENT)
            col.setAlphaF(0.6)
            glow.setColorAt(0, col)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.drawEllipse(rect.center(), 34, 34)
        painter.setPen(QPen(QColor("#0e0f11"), 1.5))
        painter.setBrush(QColor("#c9ccd0"))
        painter.drawRoundedRect(rect, 3, 3)
        for dx in (-13, 13):
            for dy in (-13, 13):
                painter.setBrush(QColor("#7d8187"))
                painter.drawEllipse(QPointF(rect.center().x() + dx, rect.center().y() + dy), 2.5, 2.5)
        cap = QRadialGradient(rect.center().x() - 3, rect.center().y() - 3, 14)
        if pressed:
            cap.setColorAt(0, QColor("#7ff3ff"))
            cap.setColorAt(1, QColor("#1aa6c4"))
        else:
            cap.setColorAt(0, QColor("#e3b48a"))
            cap.setColorAt(1, QColor("#a8754c"))
        painter.setBrush(cap)
        painter.setPen(QPen(QColor("#5a3a20") if not pressed else theme.ACCENT, 1.5))
        painter.drawEllipse(rect.center(), 11 if not pressed else 10, 11 if not pressed else 10)
        self._text(painter, QRectF(rect.left() - 34, rect.top() + 9, 32, 16), f"S{i + 1}", 8.5,
                   theme.ACCENT if pressed else theme.SILK, Qt.AlignRight | Qt.AlignVCenter,
                   bold=pressed)

    def _paint_phones(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#0e0f11"), 2))
        painter.setBrush(QColor("#1b1c20"))
        painter.drawRoundedRect(PHONES_RECT, 6, 6)
        painter.setBrush(QColor("#0b0c0e"))
        painter.drawEllipse(QPointF(PHONES_RECT.center().x(), PHONES_RECT.bottom() - 6), 10, 6)
        self._text(painter, QRectF(940, 520, 80, 14), "PHONES J5", 7.5)
        knob = QRadialGradient(RV1_CENTER.x() - 10, RV1_CENTER.y() - 10, 50)
        knob.setColorAt(0, QColor("#2f3237"))
        knob.setColorAt(1, QColor("#050506"))
        painter.setPen(QPen(QColor("#000"), 1))
        painter.setBrush(knob)
        painter.drawEllipse(RV1_CENTER, 42, 42)
        self._text(painter, QRectF(1085, 575, 90, 14), "RV1 (analog)", 7.5, theme.MUTED)

    def _paint_overlay(self, painter: QPainter) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(10, 11, 13, 150))
        painter.drawRoundedRect(QRectF(0, 0, BOARD_W, BOARD_H), 18, 18)
        self._text(painter, QRectF(0, 260, BOARD_W, 40), "Keine Gerätedaten", 22, theme.TEXT,
                   bold=True)
        self._text(painter, QRectF(0, 300, BOARD_W, 30),
                   "Daisy Seed3 über J7 anschließen oder Simulation wählen", 12, theme.MUTED)

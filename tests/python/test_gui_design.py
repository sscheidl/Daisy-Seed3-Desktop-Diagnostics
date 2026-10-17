"""Checks of the visual design rules (instrument look, red LEDs, no cyan/violet accents)."""
import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import FakeClock  # noqa: E402
from daisy_diag import protocol as p  # noqa: E402
from daisy_diag.gui import board as board_mod  # noqa: E402
from daisy_diag.gui import main_window as mw  # noqa: E402
from daisy_diag.gui import theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


def is_cyan_or_violet(color: QColor) -> bool:
    hue = color.hslHue()
    return color.hslSaturationF() > 0.35 and 160 <= hue <= 300


def test_no_cyan_or_violet_in_theme():
    constants = [v for v in vars(theme).values() if isinstance(v, QColor)]
    css_colors = [QColor(h) for h in re.findall(r"#[0-9a-fA-F]{6}", theme.STYLESHEET)]
    offenders = [c.name() for c in constants + css_colors if is_cyan_or_violet(c)]
    assert offenders == []


def test_status_colours():
    assert theme.OK.hslHue() in range(90, 150)  # green
    for red in (theme.ERROR, theme.LED_ON):
        assert red.hslHue() < 15 or red.hslHue() > 345


def render(board: board_mod.BoardWidget) -> QImage:
    board.resize(QSize(1240, 740))  # 1:1 with the scene
    return board.grab().toImage()


def pixel(board, image, point: QPointF) -> QColor:
    pt = board.to_widget(point)
    return image.pixelColor(round(pt.x()), round(pt.y()))


def test_leds_are_red_when_on_and_dark_when_off(app):
    board = board_mod.BoardWidget()
    board.state = p.BoardState(leds=[i % 2 == 0 for i in range(16)])
    image = render(board)
    for i in range(p.NUM_LEDS):
        c = pixel(board, image, board_mod.led_rect(i).center() + QPointF(5, 0))
        if i % 2 == 0:
            assert c.red() > 200 and c.green() < 120 and c.blue() < 120, (i, c.name())
        else:
            assert c.red() < 110 and c.lightness() < 70, (i, c.name())
            assert not is_cyan_or_violet(c)


def test_pressed_button_is_visibly_different(app):
    board = board_mod.BoardWidget()
    board.state = p.BoardState()
    released = render(board)
    board.state = p.BoardState(buttons=[i == 4 for i in range(16)])
    pressed = render(board)
    centre = board_mod.button_rect(4).center()
    a, b = pixel(board, released, centre), pixel(board, pressed, centre)
    assert abs(a.lightness() - b.lightness()) > 60
    other = board_mod.button_rect(5).center()
    assert pixel(board, released, other) == pixel(board, pressed, other)


def test_status_dot_colour_follows_connection(app):
    clock = FakeClock()
    window = mw.MainWindow(simulation=True, clock=clock)
    for timer in (window.poll_timer, window.panel_timer, window.port_timer):
        timer.stop()
    for _ in range(60):
        clock.advance(0.005)
        window._tick()
    window._refresh_panels()
    assert theme.OK.name() in window.status_dot.styleSheet()
    window.sim_freeze.setChecked(True)
    for _ in range(400):
        clock.advance(0.005)
        window._tick()
    window._refresh_panels()
    assert window.status_pill.text() == "Verbindungsfehler"
    assert theme.ERROR.name() in window.status_dot.styleSheet()
    window.close()

"""Headless GUI tests in simulation mode (QT_QPA_PLATFORM=offscreen)."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from conftest import FakeClock  # noqa: E402
from daisy_diag import protocol as p  # noqa: E402
from daisy_diag.gui import board as board_mod  # noqa: E402
from daisy_diag.gui import main_window as mw  # noqa: E402
from daisy_diag.gui import theme  # noqa: E402
from daisy_diag.session import ConnState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


@pytest.fixture
def sim(app):
    clock = FakeClock()
    window = mw.MainWindow(simulation=True, clock=clock)
    for timer in (window.poll_timer, window.panel_timer, window.port_timer):
        timer.stop()
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    def step(seconds=0.1):
        for _ in range(int(seconds / 0.005)):
            clock.advance(0.005)
            window._tick()
        window._refresh_panels()
        app.processEvents()

    step(0.3)
    yield window, step
    window.close()


def widget_point(window, board_point):
    pt = window.board.to_widget(board_point)
    return QPoint(round(pt.x()), round(pt.y()))


def test_starts_in_simulation_and_is_marked(sim):
    window, _ = sim
    assert window.session.state == ConnState.CONNECTED
    assert window.sim_banner.isVisible() and "SIMULATION" in window.sim_banner.text()
    assert "SIMULATION" in window.windowTitle()
    assert window.status_pill.text() == "Connected (Simulation)"
    assert window.info["fw"].text() == "DaisyDiagnostic 0.1.0-sim"
    assert window.info["proto"].text().startswith("DDP v1")
    assert window.board.simulated and window.board.interactive


@pytest.mark.parametrize("index", range(p.NUM_BUTTONS))
def test_clicking_each_button_on_board(sim, index):
    window, step = sim
    pos = widget_point(window, board_mod.button_rect(index).center())
    QTest.mousePress(window.board, Qt.LeftButton, Qt.NoModifier, pos)
    step(0.05)
    assert window.board.state.buttons[index]
    assert window.board.state.leds[index]  # FOLLOW mode
    assert window.counter_labels[index].text() == f"S{index + 1}: 1"
    QTest.mouseRelease(window.board, Qt.LeftButton, Qt.NoModifier, pos)
    step(0.05)
    assert not any(window.board.state.buttons)


@pytest.mark.parametrize("index", range(p.NUM_POTS))
def test_dragging_each_pot(sim, index):
    window, step = sim
    c = board_mod.pot_center(index)
    # Pointer straight up = 50 %, then to the right (3 o'clock) = 83.3 %
    QTest.mousePress(window.board, Qt.LeftButton, Qt.NoModifier,
                     widget_point(window, c + board_mod.QPointF(0, -30)))
    step(0.05)
    assert window.board.state.pots[index] == pytest.approx(0.5, abs=0.02)
    QTest.mouseMove(window.board, widget_point(window, c + board_mod.QPointF(30, 0)))
    QTest.mouseRelease(window.board, Qt.LeftButton, Qt.NoModifier,
                       widget_point(window, c + board_mod.QPointF(30, 0)))
    step(0.05)
    assert window.board.state.pots[index] == pytest.approx(225 / 270, abs=0.02)
    assert window.pot_table.item(index, 1).text().endswith("%")
    assert window.board.pot_min[index] == pytest.approx(0.0, abs=1e-6)
    assert window.board.pot_max[index] == pytest.approx(225 / 270, abs=0.02)


def test_toggle_switches_by_click(sim):
    window, step = sim
    for center, attr, positions in ((board_mod.SW18_POS, "sw18", {"U": -25, "C": 0, "D": 25}),
                                    (board_mod.SW17_POS, "sw17", {"U": -25, "D": 25})):
        for pos, dy in positions.items():
            QTest.mouseClick(window.board, Qt.LeftButton, Qt.NoModifier,
                             widget_point(window, center + board_mod.QPointF(0, dy)))
            step(0.05)
            assert getattr(window.board.state, attr) == pos
    assert window.in_labels["sw17"].text().startswith("D")


def test_led_mode_buttons_and_board_led_click(sim):
    window, step = sim
    window.led_buttons["ON"].click()
    step(0.05)
    assert window.board.state.led_mode == "ON" and all(window.board.state.leds)
    window.led_buttons["OFF"].click()
    step(0.05)
    assert not any(window.board.state.leds)
    QTest.mouseClick(window.board, Qt.LeftButton, Qt.NoModifier,
                     widget_point(window, board_mod.led_rect(6).center()))
    step(0.05)
    assert window.board.state.led_mode == "MASK"
    assert [i for i, on in enumerate(window.board.state.leds) if on] == [6]
    assert window.led_checks[6].isChecked()
    window.led_buttons["CHASE"].click()
    step(0.05)
    assert window.board.state.led_mode == "CHASE" and sum(window.board.state.leds) == 1
    assert window.led_buttons["CHASE"].isChecked()


def test_sd_states(sim):
    window, step = sim
    assert window.sd_status.text() == 'No card'
    assert not window.sd_button.isEnabled()
    QTest.mouseClick(window.board, Qt.LeftButton, Qt.NoModifier,
                     widget_point(window, board_mod.SD_RECT.center()))
    step(0.05)
    assert window.sd_status.text() == 'Card detected'
    assert window.sd_button.isEnabled()
    window.sd_button.click()
    step(0.05)
    assert window.sd_status.text().startswith('Filesystem readable (FAT32')
    window.sim_sd_fs.setChecked(False)
    window.sd_button.click()
    step(0.05)
    assert window.sd_status.text().startswith('Error: FR_NO_FILESYSTEM')
    window.sim_sd_card.setChecked(False)
    step(0.05)
    assert window.sd_status.text() == 'No card'


def test_jack_detection_click(sim):
    window, step = sim
    x, _ = board_mod.AUDIO_JACKS["in_l"]
    QTest.mouseClick(window.board, Qt.LeftButton, Qt.NoModifier,
                     widget_point(window, board_mod.QPointF(x, 40)))
    step(0.05)
    assert window.board.state.jack_left and not window.board.state.jack_right
    assert window.in_labels["jl"].text() == 'Plug detected'


def test_usb_unplug_and_reconnect(sim):
    window, step = sim
    window.sim_plug.click()
    step(0.1)
    assert window.status_pill.text() == 'Disconnected'
    assert window.board.state is None
    assert not window.led_buttons["ON"].isEnabled()
    window.sim_plug.click()
    step(1.5)
    assert window.status_pill.text() == "Connected (Simulation)"
    assert window.info["reconnects"].text() == "1"


def test_frozen_firmware_shows_connection_error(sim):
    window, step = sim
    window.sim_freeze.setChecked(True)
    step(1.7)
    assert window.status_pill.text() == 'Connection error'
    window.sim_freeze.setChecked(False)
    step(2.5)
    assert window.session.connected


def test_not_implemented_sections_are_labelled(sim):
    window, _ = sim
    badges = [w for w in window.findChildren(QLabel) if w.objectName() == "niBadge"]
    assert len(badges) == len(mw.EXTENSIONS) == 7
    assert all(b.text() == 'Not implemented' for b in badges)
    names = {name for name, _ in mw.EXTENSIONS}
    assert names == {"Audio Input/Output", "Audio-Engine / DSP", "MIDI DIN", "USB-MIDI",
                     "USB-Host", "CV Input/Output", "Gate Input"}
    tip = window.board.tooltip_for(("midi", 0))
    assert 'Not implemented' in tip


def test_led_tooltip_states_no_optical_feedback(sim):
    window, _ = sim
    assert 'No electrical feedback' in window.board.tooltip_for(("led", 0))


def test_hardware_mode_without_device(app, monkeypatch):
    monkeypatch.setattr(mw, "list_serial_ports", lambda: [])
    clock = FakeClock()
    window = mw.MainWindow(simulation=False, clock=clock)
    for timer in (window.poll_timer, window.panel_timer, window.port_timer):
        timer.stop()
    for _ in range(50):
        clock.advance(0.05)
        window._tick()
    window._refresh_panels()
    assert window.sim_banner.isHidden()
    assert window.session.state == ConnState.SEARCHING
    assert window.status_pill.text() == 'Disconnected'
    assert "No Daisy" in window.status_detail.text()
    assert window.board.state is None
    window.close()

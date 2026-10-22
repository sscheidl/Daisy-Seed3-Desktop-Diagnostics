"""Main window: board view, status/control panel, simulation controls and event log."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea,
                               QSlider, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QMessageBox)

from .. import __version__
from .. import protocol as p
from ..session import ConnState, DeviceSession, SerialLink, list_serial_ports
from ..simulator import SimulatedCable, demo_pattern
from . import theme
from .board import BoardWidget, SdDisplay

LED_MODE_BUTTONS = (
    ("OFF", 'All off'),
    ("ON", 'All on'),
    ("MASK", 'Individual'),
    ("CHASE", 'Chase'),
    ("FOLLOW", 'Buttons → LEDs'),
)

EXTENSIONS = (
    ("Audio Input/Output", 'Audio inputs J1/J2, outputs J3/J4, headphones J5. The firmware outputs silence; only input jack detection is implemented.'),
    ("Audio-Engine / DSP", 'No signal processing in this diagnostic firmware.'),
    ("MIDI DIN", 'OUT/THRU/INPUT (USART1, D13/D14). Not implemented.'),
    ("USB-MIDI", 'Not implemented. J7 carries the diagnostic protocol over USB CDC.'),
    ("USB-Host", 'Not implemented. USB host capability and electrical requirements (VBUS supply and port role) have not been verified on hardware.'),
    ("CV Input/Output", 'CV IN 1/2 (D20/D21), CV OUT 1/2 (DAC). Not implemented.'),
    ("Gate Input", 'GATE IN 1/2 (D0/D18). Not implemented.'),
)

STATE_COLORS = {
    ConnState.CONNECTED: theme.OK,
    ConnState.HANDSHAKE: theme.TEXT,
    ConnState.SEARCHING: theme.FAINT,
    ConnState.ERROR: theme.ERROR,
    ConnState.INCOMPATIBLE: theme.WARN,
}
STATE_TEXT = {
    ConnState.CONNECTED: 'Connected',
    ConnState.HANDSHAKE: 'Connecting …',
    ConnState.SEARCHING: 'Disconnected',
    ConnState.ERROR: 'Connection error',
    ConnState.INCOMPATIBLE: 'Incompatible protocol',
}


def _value_label(text: str = "–") -> QLabel:
    label = QLabel(text)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class MainWindow(QMainWindow):
    def __init__(self, simulation: bool = False, port: str | None = None, clock=time.monotonic):
        super().__init__()
        self._clock = clock
        self.cable: SimulatedCable | None = None
        self.session: DeviceSession | None = None
        self.paused = False
        self.led_mask = 0
        self.sd_result: p.SdInfo | None = None
        self._last_sd_card: bool | None = None
        self._demo_start = 0.0
        self._port_override = port
        self.resize(1560, 940)

        self._build_ui()
        self._start_session(simulation)

        self.poll_timer = QTimer(self)
        self.poll_timer.setTimerType(Qt.PreciseTimer)
        self.poll_timer.timeout.connect(self._tick)
        self.poll_timer.start(10)
        self.panel_timer = QTimer(self)
        self.panel_timer.timeout.connect(self._refresh_panels)
        self.panel_timer.start(100)
        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self._refresh_ports)
        self.port_timer.start(2000)

    # ---- UI construction ---------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        self.sim_banner = QLabel('SIMULATION – all displayed values are simulated; no Daisy Seed3 is connected')
        self.sim_banner.setObjectName("simBanner")
        self.sim_banner.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.sim_banner)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 6, 12)
        left_layout.setSpacing(6)
        self.board = BoardWidget()
        left_layout.addWidget(self.board, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setFixedHeight(130)
        log_label = QLabel('Event log')
        log_label.setObjectName("sectionLabel")
        left_layout.addWidget(log_label)
        left_layout.addWidget(self.log)
        split.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(470)
        panel = QWidget()
        self.panel_layout = QVBoxLayout(panel)
        self.panel_layout.setContentsMargins(6, 0, 12, 12)
        self.panel_layout.setSpacing(4)
        self.panel_layout.addWidget(self._build_connection_group())
        self.sim_group = self._build_sim_group()
        self.panel_layout.addWidget(self.sim_group)
        self.panel_layout.addWidget(self._build_led_group())
        self.panel_layout.addWidget(self._build_sd_group())
        self.panel_layout.addWidget(self._build_inputs_group())
        self.panel_layout.addWidget(self._build_pot_group())
        self.panel_layout.addWidget(self._build_counter_group())
        self.panel_layout.addWidget(self._build_extensions_group())
        self.panel_layout.addStretch(1)
        scroll.setWidget(panel)
        split.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setSizes([1070, 490])
        outer.addWidget(split, 1)
        self.setCentralWidget(central)

        self.board.buttonChanged.connect(self._sim_button)
        self.board.potChanged.connect(self._sim_pot)
        self.board.sw17Changed.connect(lambda pos: self._sim_device() and self._sim_device().set_sw17(pos))
        self.board.sw18Changed.connect(lambda pos: self._sim_device() and self._sim_device().set_sw18(pos))
        self.board.sdToggled.connect(self._sim_toggle_sd)
        self.board.jackToggled.connect(self._sim_toggle_jack)
        self.board.ledClicked.connect(self._toggle_led)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 8, 16, 8)
        title = QLabel("Daisy Seed3 – Hardware Diagnostic Suite")
        title.setObjectName("appTitle")
        version = QLabel(f"v{__version__}")
        version.setObjectName("appVersion")
        row.addWidget(title)
        row.addSpacing(10)
        row.addWidget(version)
        row.addStretch(1)
        self.mode_hw = QPushButton("Hardware (USB)")
        self.mode_sim = QPushButton("Simulation")
        for b in (self.mode_hw, self.mode_sim):
            b.setCheckable(True)
            b.setObjectName("segment")
            row.addWidget(b)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_hw)
        self.mode_group.addButton(self.mode_sim)
        self.mode_hw.clicked.connect(lambda: self._start_session(False))
        self.mode_sim.clicked.connect(lambda: self._start_session(True))
        row.addStretch(1)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        row.addWidget(self.status_dot)
        row.addSpacing(6)
        self.status_pill = QLabel('Disconnected')
        self.status_pill.setObjectName("statusText")
        row.addWidget(self.status_pill)
        row.addSpacing(14)
        self.connect_button = QPushButton('Disconnect')
        self.connect_button.clicked.connect(self._toggle_pause)
        row.addWidget(self.connect_button)
        return header

    def _build_connection_group(self) -> QGroupBox:
        box = QGroupBox('USB diagnostics')
        layout = QVBoxLayout(box)
        self.status_detail = QLabel("")
        self.status_detail.setObjectName("hint")
        self.status_detail.setWordWrap(True)
        layout.addWidget(self.status_detail)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.addItem('Automatic (VID 0483 / PID 5740)', None)
        self.port_combo.currentIndexChanged.connect(self._port_selected)
        port_row.addWidget(self.port_combo, 1)
        layout.addLayout(port_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.info = {}
        for key, label in (("port", "Port"), ("fw", "Firmware"), ("proto", 'Protocol'),
                           ("boot", 'Application / bootloader'), ("rate", 'State rate'),
                           ("frames", 'Frames OK / errors'), ("lost", 'Lost frames'),
                           ("rtt", 'Round-trip time (PING)'), ("cb", 'Control update rate'),
                           ("uptime", 'Firmware uptime'), ("fwstats", "Firmware TX / RX"),
                           ("reconnects", 'Reconnections')):
            self.info[key] = _value_label()
            form.addRow(label + ":", self.info[key])
        layout.addLayout(form)
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel('Stream rate:'))
        self.rate_combo = QComboBox()
        for hz in (20, 50, 100):
            self.rate_combo.addItem(f"{hz} Hz", hz)
        self.rate_combo.setCurrentIndex(1)
        self.rate_combo.activated.connect(
            lambda _i: self.session and self.session.send(p.cmd_rate(self.rate_combo.currentData())))
        rate_row.addWidget(self.rate_combo)
        rate_row.addStretch(1)
        layout.addLayout(rate_row)
        return box

    def _build_sim_group(self) -> QGroupBox:
        box = QGroupBox("Simulation")
        layout = QVBoxLayout(box)
        hint = QLabel('Click the board to press buttons, drag knobs or turn them with the mouse wheel, select toggle positions, and toggle the microSD card or audio input plugs.')
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        self.sim_plug = QPushButton('Unplug USB cable')
        self.sim_plug.clicked.connect(self._sim_toggle_cable)
        self.sim_freeze = QPushButton('Freeze firmware')
        self.sim_freeze.setCheckable(True)
        self.sim_freeze.toggled.connect(self._sim_set_freeze)
        self.sim_noise = QPushButton('Send corrupt frame')
        self.sim_noise.clicked.connect(self._sim_corrupt)
        self.sim_demo = QPushButton('Demo animation')
        self.sim_demo.setCheckable(True)
        self.sim_demo.toggled.connect(self._sim_demo_toggled)
        grid.addWidget(self.sim_plug, 0, 0)
        grid.addWidget(self.sim_freeze, 0, 1)
        grid.addWidget(self.sim_noise, 1, 0)
        grid.addWidget(self.sim_demo, 1, 1)
        layout.addLayout(grid)
        self.sim_sd_card = QCheckBox('microSD card inserted')
        self.sim_sd_card.toggled.connect(self._sim_set_sd)
        self.sim_sd_fs = QCheckBox('Card has a readable FAT32 filesystem')
        self.sim_sd_fs.setChecked(True)
        self.sim_sd_fs.toggled.connect(
            lambda on: self._sim_device() and setattr(self._sim_device(), "sd_filesystem",
                                                      "FAT32" if on else None))
        self.sim_jl = QCheckBox('Left audio input plugged in')
        self.sim_jl.toggled.connect(lambda on: self._sim_set_jack("left", on))
        self.sim_jr = QCheckBox('Right audio input plugged in')
        self.sim_jr.toggled.connect(lambda on: self._sim_set_jack("right", on))
        for w in (self.sim_sd_card, self.sim_sd_fs, self.sim_jl, self.sim_jr):
            layout.addWidget(w)
        self.sim_reader_eject = QPushButton("Simulate Windows eject")
        self.sim_reader_eject.clicked.connect(
            lambda: self._sim_device() and self._sim_device().reader_eject())
        layout.addWidget(self.sim_reader_eject)
        self.sim_reader_reset = QPushButton("Simulate USB bus reset")
        self.sim_reader_reset.clicked.connect(
            lambda: self._sim_device() and self._sim_device().reader_bus_reset())
        layout.addWidget(self.sim_reader_reset)
        return box

    def _build_led_group(self) -> QGroupBox:
        box = QGroupBox('LED diagnostics')
        layout = QVBoxLayout(box)
        row = QGridLayout()
        self.led_buttons: dict[str, QPushButton] = {}
        self.led_group = QButtonGroup(self)
        for k, (mode, text) in enumerate(LED_MODE_BUTTONS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, m=mode: self._send_led(m))
            self.led_group.addButton(b)
            self.led_buttons[mode] = b
            row.addWidget(b, k // 3, k % 3)
        layout.addLayout(row)
        grid = QGridLayout()
        self.led_checks: list[QCheckBox] = []
        for i in range(p.NUM_LEDS):
            cb = QCheckBox(f"D{i + 1}")
            cb.setObjectName("ledCheck")
            cb.clicked.connect(lambda checked, idx=i: self._set_led_bit(idx, checked))
            grid.addWidget(cb, i // 8, i % 8)
            self.led_checks.append(cb)
        layout.addLayout(grid)
        sliders = QFormLayout()
        self.br_slider = QSlider(Qt.Horizontal)
        self.br_slider.setRange(0, 100)
        self.br_slider.setValue(100)
        self.br_slider.sliderReleased.connect(lambda: self._send_led(self._current_led_mode()))
        self.br_label = QLabel("100 %")
        self.br_slider.valueChanged.connect(lambda v: self.br_label.setText(f"{v} %"))
        br_row = QHBoxLayout()
        br_row.addWidget(self.br_slider, 1)
        br_row.addWidget(self.br_label)
        sliders.addRow('Brightness:', br_row)
        self.chase_slider = QSlider(Qt.Horizontal)
        self.chase_slider.setRange(20, 1000)
        self.chase_slider.setValue(120)
        self.chase_label = QLabel("120 ms")
        self.chase_slider.valueChanged.connect(lambda v: self.chase_label.setText(f"{v} ms"))
        self.chase_slider.sliderReleased.connect(lambda: self._send_led(self._current_led_mode()))
        ch_row = QHBoxLayout()
        ch_row.addWidget(self.chase_slider, 1)
        ch_row.addWidget(self.chase_label)
        sliders.addRow('Chase step:', ch_row)
        layout.addLayout(sliders)
        note = QLabel('The display shows the <b>commanded state</b> set by the firmware. LEDs have no electrical feedback; inspect the physical board to confirm that they light up. Click an LED on the board to toggle it.')
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def _build_sd_group(self) -> QGroupBox:
        box = QGroupBox("microSD")
        layout = QVBoxLayout(box)
        self.sd_status = QLabel('No data')
        self.sd_status.setStyleSheet("font-size: 12pt; font-weight: 700;")
        layout.addWidget(self.sd_status)
        self.sd_detail = QLabel("")
        self.sd_detail.setObjectName("hint")
        self.sd_detail.setWordWrap(True)
        layout.addWidget(self.sd_detail)
        self.sd_button = QPushButton('Start read test (read-only)')
        self.sd_button.clicked.connect(self._sd_test)
        layout.addWidget(self.sd_button)
        note = QLabel('The test mounts the filesystem and reads the root directory without writing or formatting. Streaming pauses during the test. Reads have a 5 s budget plus initialization; the host allows up to 20 s.')
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.reader_status = QLabel("Card reader: checking firmware capability …")
        self.reader_status.setWordWrap(True)
        layout.addWidget(self.reader_status)
        self.reader_share = QPushButton("Share SD card with Windows")
        self.reader_share.clicked.connect(self._share_reader)
        layout.addWidget(self.reader_share)
        self.reader_return = QPushButton("Return card to diagnostics")
        self.reader_return.clicked.connect(self._return_reader)
        layout.addWidget(self.reader_return)
        return box

    def _build_inputs_group(self) -> QGroupBox:
        box = QGroupBox('Toggle switches and plug detection')
        form = QFormLayout(box)
        self.in_labels = {}
        for key, label in (("sw17", 'SW17 (2 positions)'), ("sw18", 'SW18 (3 positions)'),
                           ("jl", 'Left audio input'), ("jr", 'Right audio input'),
                           ("sd", 'microSD detection')):
            self.in_labels[key] = _value_label()
            form.addRow(label + ":", self.in_labels[key])
        return box

    def _build_pot_group(self) -> QGroupBox:
        box = QGroupBox('Potentiometers VR1–VR8')
        layout = QVBoxLayout(box)
        self.pot_table = QTableWidget(p.NUM_POTS, 5)
        self.pot_table.setHorizontalHeaderLabels(["", 'Value', 'Raw ADC', "Min", "Max"])
        self.pot_table.verticalHeader().setVisible(False)
        self.pot_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pot_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.pot_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i in range(p.NUM_POTS):
            self.pot_table.setItem(i, 0, QTableWidgetItem(f"VR{i + 1}"))
            for c in range(1, 5):
                item = QTableWidgetItem("–")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.pot_table.setItem(i, c, item)
            self.pot_table.setRowHeight(i, 22)
        self.pot_table.setFixedHeight(22 * p.NUM_POTS + 30)
        layout.addWidget(self.pot_table)
        reset = QPushButton('Reset min/max')
        reset.clicked.connect(self._reset_minmax)
        layout.addWidget(reset)
        return box

    def _build_counter_group(self) -> QGroupBox:
        box = QGroupBox('Buttons S1–S16 (press counts)')
        grid = QGridLayout(box)
        self.counter_labels: list[QLabel] = []
        for i in range(p.NUM_BUTTONS):
            label = QLabel(f"S{i + 1}: –")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(42)
            grid.addWidget(label, i // 8, i % 8)
            self.counter_labels.append(label)
        return box

    def _build_extensions_group(self) -> QGroupBox:
        box = QGroupBox('Planned features')
        grid = QGridLayout(box)
        for row, (name, tip) in enumerate(EXTENSIONS):
            label = QLabel(name)
            label.setToolTip(tip)
            badge = QLabel('Not implemented')
            badge.setObjectName("niBadge")
            badge.setToolTip(tip)
            grid.addWidget(label, row, 0)
            grid.addWidget(badge, row, 1, Qt.AlignRight)
        return box

    # ---- session handling ----------------------------------------------------------------
    def _start_session(self, simulation: bool) -> None:
        if self.session is not None:
            self.session.disconnect('Mode changed')
        self.paused = False
        self.connect_button.setText('Disconnect')
        self.sd_result = None
        self._reset_minmax()
        if simulation:
            self.cable = SimulatedCable()
            cable = self.cable
            self.session = DeviceSession(cable.ports, lambda port: cable.open(port, self._clock),
                                         self._clock, simulated=True)
            self._sync_sim_controls()
        else:
            self.cable = None
            self.sim_demo.setChecked(False)
            self.session = DeviceSession(list_serial_ports, SerialLink, self._clock,
                                         port_override=self._port_override)
        self.mode_sim.setChecked(simulation)
        self.mode_hw.setChecked(not simulation)
        self.sim_banner.setVisible(simulation)
        self.sim_group.setVisible(simulation)
        self.port_combo.setEnabled(not simulation)
        self.board.interactive = simulation
        self.board.simulated = simulation
        self.setWindowTitle(f"Daisy Seed3 Hardware Diagnostics {__version__}"
                            + (" – SIMULATION" if simulation else ""))
        self._log('Mode: ' + ('Simulation (no hardware)' if simulation
                               else 'Hardware over USB CDC'))
        self._refresh_ports()
        self._update_status()

    def _toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.paused:
            self.paused = False
            self.connect_button.setText('Disconnect')
            self._log('Automatic connection resumed')
        else:
            self.session.disconnect()
            self.paused = True
            self.connect_button.setText('Connect')
        self._update_status()

    def _refresh_ports(self) -> None:
        if self.cable is not None or self.port_combo.view().isVisible():
            return
        try:
            ports = list_serial_ports()
        except Exception:
            return
        current = self.port_combo.currentData()
        wanted = [None] + [port.device for port in ports]
        existing = [self.port_combo.itemData(i) for i in range(self.port_combo.count())]
        if wanted == existing:
            return
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItem('Automatic (VID 0483 / PID 5740)', None)
        for port in ports:
            mark = " ★" if port.is_daisy_candidate else ""
            self.port_combo.addItem(f"{port.device} – {port.description}{mark}", port.device)
        index = self.port_combo.findData(current)
        self.port_combo.setCurrentIndex(max(0, index))
        self.port_combo.blockSignals(False)

    def _port_selected(self, _index: int) -> None:
        self._port_override = self.port_combo.currentData()
        if self.cable is None:
            self._start_session(False)

    def _tick(self) -> None:
        if self.session is None:
            return
        if self.cable is not None and self.sim_demo.isChecked():
            demo_pattern(self.cable.device, self._clock() - self._demo_start)
        if not self.paused:
            self.session.poll()
        board_changed = False
        for kind, payload in self.session.drain_events():
            if kind == "board":
                board_changed = True
            elif kind == "state":
                self._update_status()
            elif kind == "connected":
                info: p.DeviceInfo = payload
                self.sd_result = None
                self._reset_minmax()
                self._log(f"Connected to {self.session.port}: {info.app} {info.firmware}, "
                          f"Protocol {info.protocol}, Bootloader {info.bootloader}"
                          + (" (SIMULATION)" if info.simulated else ""))
            elif kind == "disconnected":
                board_changed = True
                self.sd_result = None
            elif kind == "sd":
                self.sd_result = payload
                self._log(f"microSD test: {self._sd_text()[0]}")
            elif kind == "reader":
                self.sd_result = None
                if payload is not None:
                    self._log(f"Card reader: {payload.state}")
            elif kind == "log":
                self._log(str(payload))
        if board_changed:
            self._apply_board()

    def _apply_board(self) -> None:
        st = self.session.board if self.session else None
        if st is not None:
            for i, v in enumerate(st.pots):
                lo, hi = self.board.pot_min[i], self.board.pot_max[i]
                self.board.pot_min[i] = v if lo is None else min(lo, v)
                self.board.pot_max[i] = v if hi is None else max(hi, v)
            if self._last_sd_card and not st.sd_card:
                self.sd_result = None  # card removed: an old test result is no longer valid
            self._last_sd_card = st.sd_card
        self.board.state = st
        self.board.connected = self.session is not None and self.session.connected
        self.board.led_selectable = self.board.connected
        text, color = self._sd_text()
        self.board.sd_display = SdDisplay(text, color)
        self.board.update()

    def _sd_text(self) -> tuple[str, QColor]:
        st = self.session.board if self.session else None
        if st is None:
            return 'No data', theme.MUTED
        if not st.sd_card:
            return 'No card', theme.MUTED
        reader = self.session.reader if self.session.reader_supported else None
        if reader and reader.state != "LOCAL":
            return {
                "STARTING": ("Preparing card reader …", theme.TEXT),
                "SHARED": ("Shared with Windows", theme.WARN),
                "EJECTED": ("Ejected by Windows", theme.OK),
                "INTERRUPTED": ("Card access interrupted", theme.ERROR),
                "ERROR": ("Card I/O error", theme.ERROR),
            }[reader.state]
        if self.session.sd_test_pending:
            return 'Read test in progress …', theme.TEXT
        r = self.sd_result
        if r is None:
            return 'Card detected', theme.TEXT
        if r.status == "MOUNTED":
            size = f"{r.size_mb / 1024:.1f} GB" if r.size_mb >= 1024 else f"{r.size_mb} MB"
            return f"Filesystem readable ({r.fs_type}, {size}, {r.entries} entries)", theme.OK
        if r.status == "NONE":
            return 'No card (test)', theme.MUTED
        return f"Error: {p.FRESULT_TEXT.get(r.fresult, f'FRESULT {r.fresult}')}", theme.ERROR

    # ---- periodic panel refresh ----------------------------------------------------------
    def _update_status(self) -> None:
        s = self.session
        if s is None:
            return
        state = s.state
        text = 'Paused' if self.paused else STATE_TEXT[state]
        if s.simulated and state == ConnState.CONNECTED:
            text += " (Simulation)"
        color = theme.FAINT if self.paused else STATE_COLORS[state]
        self.status_pill.setText(text)
        self.status_dot.setStyleSheet(f"background: {color.name()}; border-radius: 5px;")
        self.status_detail.setText('Disconnected manually' if self.paused
                                   else s.status_detail)

    def _refresh_panels(self) -> None:
        s = self.session
        if s is None:
            return
        self._update_status()
        dev = s.device if s.connected else None
        self.info["port"].setText(s.port if s.connected and s.port else "–")
        self.info["fw"].setText(f"{dev.app} {dev.firmware}" if dev else "–")
        self.info["proto"].setText(f"DDP v{dev.protocol} (Host: v{p.PROTOCOL_VERSION})" if dev else
                                   f"– (Host: v{p.PROTOCOL_VERSION})")
        self.info["boot"].setText(f"{dev.boot} / {dev.bootloader}" if dev else "–")
        self.info["rate"].setText(f"{s.state_rate_hz:.0f} Hz" if s.connected else "–")
        self.info["frames"].setText(f"{s.frames_ok} / {s.frame_errors + s.content_errors}")
        self.info["lost"].setText(str(s.lost_frames))
        self.info["rtt"].setText(f"{s.rtt_ms:.0f} ms" if s.rtt_ms is not None and s.connected else "–")
        sysinfo = s.sys if s.connected else None
        self.info["cb"].setText(f"{sysinfo.control_rate_hz} Hz (target 1000)" if sysinfo else "–")
        self.info["uptime"].setText(f"{sysinfo.uptime_s} s" if sysinfo else "–")
        self.info["fwstats"].setText(
            f"TX {sysinfo.tx_ok} (busy {sysinfo.tx_busy}, dropped {sysinfo.tx_drop}) / "
            f"RX {sysinfo.rx_ok} (errors {sysinfo.rx_bad})" if sysinfo else "–")
        self.info["reconnects"].setText(str(s.reconnects))

        st = s.board if s.connected else None
        enabled = st is not None
        for b in self.led_buttons.values():
            b.setEnabled(enabled)
        for cb in self.led_checks:
            cb.setEnabled(enabled)
        self.br_slider.setEnabled(enabled)
        self.chase_slider.setEnabled(enabled)
        reader = s.reader if s.reader_supported else None
        local = not s.reader_supported or (reader is not None and reader.state == "LOCAL")
        self.sd_button.setEnabled(enabled and st.sd_card and not s.sd_test_pending
                                  and not s.reader_pending and local)
        self.reader_share.setEnabled(bool(enabled and st.sd_card and reader and
                                          reader.state == "LOCAL" and not reader.busy
                                          and not s.sd_test_pending and not s.reader_pending))
        self.reader_return.setEnabled(bool(enabled and reader and not reader.busy and
                                           reader.state in ("EJECTED", "INTERRUPTED", "ERROR")
                                           and not s.reader_pending))
        self.reader_return.setText("Acknowledge interrupted access" if reader and
                                  reader.state in ("INTERRUPTED", "ERROR") else
                                  "Return card to diagnostics")
        if not s.connected:
            reader_text = "Card reader: disconnected; card ownership is unknown."
        elif not s.reader_supported:
            reader_text = "Card reader unavailable: install the CardReader firmware variant."
        elif s.reader_pending:
            reader_text = "Card reader: waiting for firmware …"
        elif reader is None:
            reader_text = "Card reader: state unknown; waiting for firmware status."
        else:
            reader_text = {
                "LOCAL": "Card available for diagnostics. Sharing enables Windows read/write access.",
                "STARTING": "Preparing the card for Windows …",
                "SHARED": "Windows owns the card. Eject it in Windows before returning it here.",
                "EJECTED": "Windows eject received and card writes completed. You can return the card.",
                "INTERRUPTED": "Access was interrupted. Windows may have lost pending changes. Close card files before acknowledging.",
                "ERROR": "Card I/O failed. Windows may have lost pending changes. Close card files before acknowledging.",
            }[reader.state]
        if s.simulated:
            reader_text += " Simulation only: no Windows drive is created."
        self.reader_status.setText(reader_text)
        self.rate_combo.setEnabled(enabled)
        if st is not None:
            btn = self.led_buttons.get(st.led_mode)
            if btn is not None and not btn.isChecked():
                btn.setChecked(True)
            if not self.br_slider.isSliderDown():
                self.br_slider.setValue(st.led_brightness)
        else:
            self.led_group.setExclusive(False)
            for b in self.led_buttons.values():
                b.setChecked(False)
            self.led_group.setExclusive(True)
        for i, cb in enumerate(self.led_checks):
            cb.setChecked(bool(self.led_mask >> i & 1))

        text, color = self._sd_text()
        self.sd_status.setText(text)
        self.sd_status.setStyleSheet(f"font-size: 12pt; font-weight: 700; color: {color.name()};")
        self.sd_detail.setText(
            "" if st is None else
            ('SD read test is unavailable until the card is returned.' if st.sd_card and not local else
             'Card detected on D7 (SDMMC_DETECT). Read test available.' if st.sd_card and
             self.sd_result is None else
             'The slot reports no card.' if not st.sd_card else ""))

        def show(key: str, value: str, active: bool = False, ok: bool = False) -> None:
            self.in_labels[key].setText(value)
            color = theme.OK if ok else theme.TEXT
            self.in_labels[key].setStyleSheet(f"color: {color.name()}; font-weight: 700;"
                                              if active else f"color: {theme.MUTED.name()};")

        if st is None:
            for key in self.in_labels:
                show(key, "–")
        else:
            show("sw17", {"U": 'U (up according to libDaisy)', "D": 'D (down according to libDaisy)'}[st.sw17],
                 st.sw17 == "U")
            show("sw18", {"U": 'U (up)', "C": 'C (center / OFF)', "D": 'D (down)'}[st.sw18],
                 st.sw18 != "C")
            show("jl", 'Plug detected' if st.jack_left else 'unplugged', st.jack_left, ok=True)
            show("jr", 'Plug detected' if st.jack_right else 'unplugged', st.jack_right, ok=True)
            show("sd", 'Card detected' if st.sd_card else 'no card', st.sd_card, ok=True)

        for i in range(p.NUM_POTS):
            lo, hi = self.board.pot_min[i], self.board.pot_max[i]
            cells = ("–", "–", "–", "–") if st is None else (
                f"{st.pots[i] * 100:.1f} %", str(st.pots_raw[i]),
                "–" if lo is None else f"{lo * 100:.1f} %",
                "–" if hi is None else f"{hi * 100:.1f} %")
            for c, txt in enumerate(cells, start=1):
                self.pot_table.item(i, c).setText(txt)
        for i, label in enumerate(self.counter_labels):
            if st is None:
                label.setText(f"S{i + 1}: –")
                label.setStyleSheet("")
            else:
                label.setText(f"S{i + 1}: {st.press_counts[i]}")
                label.setStyleSheet(f"color: {theme.TEXT.name()}; font-weight: 700;"
                                    f"background: #3a3d41;" if st.buttons[i] else "")

        if self.cable is not None:
            self.sim_plug.setText('Plug in USB cable' if not self.cable.plugged
                                  else 'Unplug USB cable')
            self._sync_sim_controls()
        if not s.connected and self.board.state is not None:
            self._apply_board()

    # ---- LED commands -------------------------------------------------------------------
    def _current_led_mode(self) -> str:
        st = self.session.board if self.session else None
        return st.led_mode if st else "FOLLOW"

    def _send_led(self, mode: str) -> None:
        if self.session is None:
            return
        ok = self.session.set_led(mode, mask=self.led_mask, brightness=self.br_slider.value(),
                                  step_ms=self.chase_slider.value())
        if ok:
            self._log(f"LED mode requested: {mode}")

    def _set_led_bit(self, index: int, on: bool) -> None:
        if on:
            self.led_mask |= 1 << index
        else:
            self.led_mask &= ~(1 << index)
        self._send_led("MASK")

    def _toggle_led(self, index: int) -> None:
        self._set_led_bit(index, not bool(self.led_mask >> index & 1))

    def _sd_test(self) -> None:
        if self.session and self.session.request_sd_test():
            self._log('microSD read test requested')

    def _share_reader(self) -> None:
        if self.session and self.session.request_reader("SHARE"):
            self.sd_result = None
            self._log("SD card sharing requested; eject in Windows before returning the card")

    def _return_reader(self) -> None:
        s = self.session
        if s is None or s.reader is None:
            return
        if s.reader.state in ("INTERRUPTED", "ERROR"):
            answer = QMessageBox.warning(self, "Interrupted SD access",
                "Windows may have lost pending changes. Close all files and applications "
                "using this card. Acknowledging does not recover unsaved data or confirm "
                "a clean eject. Return the card to diagnostics?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if s.request_reader("RETURN"):
            self.sd_result = None
            self._log("SD card return requested")

    def _reset_minmax(self) -> None:
        self.board.pot_min = [None] * p.NUM_POTS
        self.board.pot_max = [None] * p.NUM_POTS
        self.board.update()

    # ---- simulation controls -------------------------------------------------------------
    def _sim_device(self):
        return self.cable.device if self.cable is not None else None

    def _sim_button(self, index: int, pressed: bool) -> None:
        if self._sim_device():
            self._sim_device().set_button(index, pressed)

    def _sim_pot(self, index: int, value: float) -> None:
        if self._sim_device():
            self._sim_device().set_pot(index, value)

    def _sim_toggle_sd(self) -> None:
        dev = self._sim_device()
        if dev:
            dev.inputs.sd_card = not dev.inputs.sd_card

    def _sim_set_sd(self, on: bool) -> None:
        dev = self._sim_device()
        if dev:
            dev.inputs.sd_card = on

    def _sim_toggle_jack(self, side: str) -> None:
        dev = self._sim_device()
        if dev:
            attr = "jack_left" if side == "left" else "jack_right"
            setattr(dev.inputs, attr, not getattr(dev.inputs, attr))

    def _sim_set_jack(self, side: str, on: bool) -> None:
        dev = self._sim_device()
        if dev:
            setattr(dev.inputs, "jack_left" if side == "left" else "jack_right", on)

    def _sim_toggle_cable(self) -> None:
        if self.cable is None:
            return
        if self.cable.plugged:
            self.cable.unplug()
            self._log('Simulation: USB cable unplugged (board powered off)')
        else:
            self.cable.plug()
            self.cable.device.responsive = not self.sim_freeze.isChecked()
            self._log('Simulation: USB cable plugged in (firmware restarting)')

    def _sim_set_freeze(self, frozen: bool) -> None:
        if self.cable is not None:
            self.cable.device.responsive = not frozen
            self._log("Simulation: Firmware " + ('unresponsive' if frozen else 'responsive again'))

    def _sim_corrupt(self) -> None:
        if self.cable is not None:
            self.cable.device.corrupt_next_frame = True
            self._log('Simulation: the next frame will have an invalid CRC')

    def _sim_demo_toggled(self, on: bool) -> None:
        self._demo_start = self._clock()
        if not on and self.cable is not None:
            for i in range(p.NUM_BUTTONS):
                self.cable.device.set_button(i, False)

    def _sync_sim_controls(self) -> None:
        dev = self._sim_device()
        if dev is None:
            return
        for widget, value in ((self.sim_sd_card, dev.inputs.sd_card),
                              (self.sim_jl, dev.inputs.jack_left),
                              (self.sim_jr, dev.inputs.jack_right)):
            if widget.isChecked() != value:
                widget.blockSignals(True)
                widget.setChecked(value)
                widget.blockSignals(False)

    # ---- misc ----------------------------------------------------------------------------
    def _log(self, text: str) -> None:
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def closeEvent(self, event) -> None:
        if self.session is not None:
            self.session.disconnect('Application closed')
        super().closeEvent(event)

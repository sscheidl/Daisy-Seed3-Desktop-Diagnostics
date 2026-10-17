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
                               QWidget)

from .. import __version__
from .. import protocol as p
from ..session import ConnState, DeviceSession, SerialLink, list_serial_ports
from ..simulator import SimulatedCable, demo_pattern
from . import theme
from .board import BoardWidget, SdDisplay

LED_MODE_BUTTONS = (
    ("OFF", "Alle aus"),
    ("ON", "Alle ein"),
    ("MASK", "Einzeln"),
    ("CHASE", "Lauflicht"),
    ("FOLLOW", "Taster → LED"),
)

EXTENSIONS = (
    ("Audio Input/Output", "Audioeingänge J1/J2, Ausgänge J3/J4, Kopfhörer J5. "
     "Die Firmware gibt Stille aus; nur die Steckererkennung der Eingänge ist implementiert."),
    ("Audio-Engine / DSP", "Keine Signalverarbeitung in dieser Diagnosefirmware."),
    ("MIDI DIN", "OUT/THRU/INPUT (USART1, D13/D14). Nicht implementiert."),
    ("USB-MIDI", "Nicht implementiert. J7 wird für das Diagnoseprotokoll (USB CDC) genutzt."),
    ("USB-Host", "Nicht implementiert. Host-Fähigkeit und elektrische Voraussetzungen "
     "(VBUS-Versorgung, Port-Rolle) sind noch nicht anhand der Hardware geprüft."),
    ("CV Input/Output", "CV IN 1/2 (D20/D21), CV OUT 1/2 (DAC). Nicht implementiert."),
    ("Gate Input", "GATE IN 1/2 (D0/D18). Nicht implementiert."),
)

STATE_COLORS = {
    ConnState.CONNECTED: theme.OK,
    ConnState.HANDSHAKE: theme.TEXT,
    ConnState.SEARCHING: theme.FAINT,
    ConnState.ERROR: theme.ERROR,
    ConnState.INCOMPATIBLE: theme.WARN,
}
STATE_TEXT = {
    ConnState.CONNECTED: "Verbunden",
    ConnState.HANDSHAKE: "Verbinde …",
    ConnState.SEARCHING: "Getrennt",
    ConnState.ERROR: "Verbindungsfehler",
    ConnState.INCOMPATIBLE: "Protokoll inkompatibel",
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
        self.sim_banner = QLabel("SIMULATION – alle angezeigten Werte sind simulierte Daten, "
                                 "es ist kein Daisy Seed3 angeschlossen")
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
        log_label = QLabel("Ereignisprotokoll")
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
        self.status_pill = QLabel("Getrennt")
        self.status_pill.setObjectName("statusText")
        row.addWidget(self.status_pill)
        row.addSpacing(14)
        self.connect_button = QPushButton("Trennen")
        self.connect_button.clicked.connect(self._toggle_pause)
        row.addWidget(self.connect_button)
        return header

    def _build_connection_group(self) -> QGroupBox:
        box = QGroupBox("USB-Diagnose")
        layout = QVBoxLayout(box)
        self.status_detail = QLabel("")
        self.status_detail.setObjectName("hint")
        self.status_detail.setWordWrap(True)
        layout.addWidget(self.status_detail)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.addItem("Automatisch (VID 0483 / PID 5740)", None)
        self.port_combo.currentIndexChanged.connect(self._port_selected)
        port_row.addWidget(self.port_combo, 1)
        layout.addLayout(port_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.info = {}
        for key, label in (("port", "Port"), ("fw", "Firmware"), ("proto", "Protokoll"),
                           ("boot", "Anwendung / Bootloader"), ("rate", "Zustandsrate"),
                           ("frames", "Rahmen ok / Fehler"), ("lost", "Verlorene Rahmen"),
                           ("rtt", "Antwortzeit (PING)"), ("cb", "Steuer-Update-Rate"),
                           ("uptime", "Firmware-Laufzeit"), ("fwstats", "Firmware TX / RX"),
                           ("reconnects", "Wiederverbindungen")):
            self.info[key] = _value_label()
            form.addRow(label + ":", self.info[key])
        layout.addLayout(form)
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Datenrate:"))
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
        hint = QLabel("Im Board klicken: Taster drücken, Potis ziehen oder mit dem Mausrad "
                      "drehen, Kippschalter oben/mitte/unten anklicken, microSD und "
                      "Audioeingänge anklicken.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        self.sim_plug = QPushButton("USB-Kabel ziehen")
        self.sim_plug.clicked.connect(self._sim_toggle_cable)
        self.sim_freeze = QPushButton("Firmware hängt")
        self.sim_freeze.setCheckable(True)
        self.sim_freeze.toggled.connect(self._sim_set_freeze)
        self.sim_noise = QPushButton("Fehlerhaften Rahmen senden")
        self.sim_noise.clicked.connect(self._sim_corrupt)
        self.sim_demo = QPushButton("Demo-Animation")
        self.sim_demo.setCheckable(True)
        self.sim_demo.toggled.connect(self._sim_demo_toggled)
        grid.addWidget(self.sim_plug, 0, 0)
        grid.addWidget(self.sim_freeze, 0, 1)
        grid.addWidget(self.sim_noise, 1, 0)
        grid.addWidget(self.sim_demo, 1, 1)
        layout.addLayout(grid)
        self.sim_sd_card = QCheckBox("microSD-Karte gesteckt")
        self.sim_sd_card.toggled.connect(self._sim_set_sd)
        self.sim_sd_fs = QCheckBox("Karte hat lesbares FAT32-Dateisystem")
        self.sim_sd_fs.setChecked(True)
        self.sim_sd_fs.toggled.connect(
            lambda on: self._sim_device() and setattr(self._sim_device(), "sd_filesystem",
                                                      "FAT32" if on else None))
        self.sim_jl = QCheckBox("Audioeingang links gesteckt")
        self.sim_jl.toggled.connect(lambda on: self._sim_set_jack("left", on))
        self.sim_jr = QCheckBox("Audioeingang rechts gesteckt")
        self.sim_jr.toggled.connect(lambda on: self._sim_set_jack("right", on))
        for w in (self.sim_sd_card, self.sim_sd_fs, self.sim_jl, self.sim_jr):
            layout.addWidget(w)
        return box

    def _build_led_group(self) -> QGroupBox:
        box = QGroupBox("LED-Diagnose")
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
        sliders.addRow("Helligkeit:", br_row)
        self.chase_slider = QSlider(Qt.Horizontal)
        self.chase_slider.setRange(20, 1000)
        self.chase_slider.setValue(120)
        self.chase_label = QLabel("120 ms")
        self.chase_slider.valueChanged.connect(lambda v: self.chase_label.setText(f"{v} ms"))
        self.chase_slider.sliderReleased.connect(lambda: self._send_led(self._current_led_mode()))
        ch_row = QHBoxLayout()
        ch_row.addWidget(self.chase_slider, 1)
        ch_row.addWidget(self.chase_label)
        sliders.addRow("Lauflicht-Schritt:", ch_row)
        layout.addLayout(sliders)
        note = QLabel("Angezeigt wird der von der Firmware gesetzte <b>Sollzustand</b>. "
                      "Die LEDs haben keine elektrische Rückmeldung – ob eine LED wirklich "
                      "leuchtet, muss am Board angesehen werden. LEDs im Board anklicken "
                      "schaltet einzelne LEDs.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def _build_sd_group(self) -> QGroupBox:
        box = QGroupBox("microSD")
        layout = QVBoxLayout(box)
        self.sd_status = QLabel("Keine Daten")
        self.sd_status.setStyleSheet("font-size: 12pt; font-weight: 700;")
        layout.addWidget(self.sd_status)
        self.sd_detail = QLabel("")
        self.sd_detail.setObjectName("hint")
        self.sd_detail.setWordWrap(True)
        layout.addWidget(self.sd_detail)
        self.sd_button = QPushButton("Lesetest starten (nur lesen)")
        self.sd_button.clicked.connect(self._sd_test)
        layout.addWidget(self.sd_button)
        note = QLabel("Der Test hängt das Dateisystem nur ein und liest das Wurzelverzeichnis. "
                      "Keine Formatierung, keine Schreibzugriffe. Während des Tests pausiert "
                      "der Datenstrom (bei einer nicht antwortenden Karte bis zu 30 s).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def _build_inputs_group(self) -> QGroupBox:
        box = QGroupBox("Kippschalter und Steckererkennung")
        form = QFormLayout(box)
        self.in_labels = {}
        for key, label in (("sw17", "SW17 (2 Pos.)"), ("sw18", "SW18 (3 Pos.)"),
                           ("jl", "Audioeingang links"), ("jr", "Audioeingang rechts"),
                           ("sd", "microSD-Erkennung")):
            self.in_labels[key] = _value_label()
            form.addRow(label + ":", self.in_labels[key])
        return box

    def _build_pot_group(self) -> QGroupBox:
        box = QGroupBox("Potentiometer VR1–VR8")
        layout = QVBoxLayout(box)
        self.pot_table = QTableWidget(p.NUM_POTS, 5)
        self.pot_table.setHorizontalHeaderLabels(["", "Wert", "ADC roh", "Min", "Max"])
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
        reset = QPushButton("Min/Max zurücksetzen")
        reset.clicked.connect(self._reset_minmax)
        layout.addWidget(reset)
        return box

    def _build_counter_group(self) -> QGroupBox:
        box = QGroupBox("Taster S1–S16 (Druckzähler)")
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
        box = QGroupBox("Vorbereitete Erweiterungen")
        grid = QGridLayout(box)
        for row, (name, tip) in enumerate(EXTENSIONS):
            label = QLabel(name)
            label.setToolTip(tip)
            badge = QLabel("Nicht implementiert")
            badge.setObjectName("niBadge")
            badge.setToolTip(tip)
            grid.addWidget(label, row, 0)
            grid.addWidget(badge, row, 1, Qt.AlignRight)
        return box

    # ---- session handling ----------------------------------------------------------------
    def _start_session(self, simulation: bool) -> None:
        if self.session is not None:
            self.session.disconnect("Modus gewechselt")
        self.paused = False
        self.connect_button.setText("Trennen")
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
        self.setWindowTitle(f"Daisy Seed3 Hardware-Diagnose {__version__}"
                            + (" – SIMULATION" if simulation else ""))
        self._log("Modus: " + ("Simulation (keine echte Hardware)" if simulation
                               else "Hardware über USB CDC"))
        self._refresh_ports()
        self._update_status()

    def _toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.paused:
            self.paused = False
            self.connect_button.setText("Trennen")
            self._log("Automatische Verbindung wieder aktiv")
        else:
            self.session.disconnect()
            self.paused = True
            self.connect_button.setText("Verbinden")
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
        self.port_combo.addItem("Automatisch (VID 0483 / PID 5740)", None)
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
                self._log(f"Verbunden mit {self.session.port}: {info.app} {info.firmware}, "
                          f"Protokoll {info.protocol}, Bootloader {info.bootloader}"
                          + (" (SIMULATION)" if info.simulated else ""))
            elif kind == "disconnected":
                board_changed = True
                self.sd_result = None
            elif kind == "sd":
                self.sd_result = payload
                self._log(f"microSD-Test: {self._sd_text()[0]}")
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
            return "Keine Daten", theme.MUTED
        if not st.sd_card:
            return "Keine Karte", theme.MUTED
        if self.session.sd_test_pending:
            return "Lesetest läuft …", theme.TEXT
        r = self.sd_result
        if r is None:
            return "Karte erkannt", theme.TEXT
        if r.status == "MOUNTED":
            size = f"{r.size_mb / 1024:.1f} GB" if r.size_mb >= 1024 else f"{r.size_mb} MB"
            return f"Dateisystem lesbar ({r.fs_type}, {size}, {r.entries} Einträge)", theme.OK
        if r.status == "NONE":
            return "Keine Karte (Test)", theme.MUTED
        return f"Fehler: {p.FRESULT_TEXT.get(r.fresult, f'FRESULT {r.fresult}')}", theme.ERROR

    # ---- periodic panel refresh ----------------------------------------------------------
    def _update_status(self) -> None:
        s = self.session
        if s is None:
            return
        state = s.state
        text = "Pausiert" if self.paused else STATE_TEXT[state]
        if s.simulated and state == ConnState.CONNECTED:
            text += " (Simulation)"
        color = theme.FAINT if self.paused else STATE_COLORS[state]
        self.status_pill.setText(text)
        self.status_dot.setStyleSheet(f"background: {color.name()}; border-radius: 5px;")
        self.status_detail.setText("Verbindung manuell getrennt" if self.paused
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
        self.info["cb"].setText(f"{sysinfo.control_rate_hz} Hz (Soll 1000)" if sysinfo else "–")
        self.info["uptime"].setText(f"{sysinfo.uptime_s} s" if sysinfo else "–")
        self.info["fwstats"].setText(
            f"TX {sysinfo.tx_ok} (belegt {sysinfo.tx_busy}, verworfen {sysinfo.tx_drop}) / "
            f"RX {sysinfo.rx_ok} (Fehler {sysinfo.rx_bad})" if sysinfo else "–")
        self.info["reconnects"].setText(str(s.reconnects))

        st = s.board if s.connected else None
        enabled = st is not None
        for b in self.led_buttons.values():
            b.setEnabled(enabled)
        for cb in self.led_checks:
            cb.setEnabled(enabled)
        self.br_slider.setEnabled(enabled)
        self.chase_slider.setEnabled(enabled)
        self.sd_button.setEnabled(enabled and st.sd_card and not s.sd_test_pending)
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
            ("Karte über D7 (SDMMC_DETECT) erkannt. Lesetest möglich." if st.sd_card and
             self.sd_result is None else
             "Steckplatz meldet keine Karte." if not st.sd_card else ""))

        def show(key: str, value: str, active: bool = False, ok: bool = False) -> None:
            self.in_labels[key].setText(value)
            color = theme.OK if ok else theme.TEXT
            self.in_labels[key].setStyleSheet(f"color: {color.name()}; font-weight: 700;"
                                              if active else f"color: {theme.MUTED.name()};")

        if st is None:
            for key in self.in_labels:
                show(key, "–")
        else:
            show("sw17", {"U": "U (oben laut libDaisy)", "D": "D (unten laut libDaisy)"}[st.sw17],
                 st.sw17 == "U")
            show("sw18", {"U": "U (oben)", "C": "C (Mitte / OFF)", "D": "D (unten)"}[st.sw18],
                 st.sw18 != "C")
            show("jl", "Stecker erkannt" if st.jack_left else "frei", st.jack_left, ok=True)
            show("jr", "Stecker erkannt" if st.jack_right else "frei", st.jack_right, ok=True)
            show("sd", "Karte erkannt" if st.sd_card else "keine Karte", st.sd_card, ok=True)

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
            self.sim_plug.setText("USB-Kabel einstecken" if not self.cable.plugged
                                  else "USB-Kabel ziehen")
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
            self._log(f"LED-Modus angefordert: {mode}")

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
            self._log("microSD-Lesetest angefordert")

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
            self._log("Simulation: USB-Kabel gezogen (Board ohne Strom)")
        else:
            self.cable.plug()
            self.cable.device.responsive = not self.sim_freeze.isChecked()
            self._log("Simulation: USB-Kabel eingesteckt (Firmware startet neu)")

    def _sim_set_freeze(self, frozen: bool) -> None:
        if self.cable is not None:
            self.cable.device.responsive = not frozen
            self._log("Simulation: Firmware " + ("reagiert nicht mehr" if frozen else "läuft wieder"))

    def _sim_corrupt(self) -> None:
        if self.cable is not None:
            self.cable.device.corrupt_next_frame = True
            self._log("Simulation: nächster Rahmen wird mit falscher CRC gesendet")

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
            self.session.disconnect("Anwendung beendet")
        super().closeEvent(event)

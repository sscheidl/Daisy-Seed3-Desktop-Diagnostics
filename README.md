# Daisy Seed3 Hardware Diagnostic Suite

Diagnose aller mechanischen Bedienelemente des **Electro-Smith Seed3 Desktop
Development Kit** – bestehend aus einer flashbaren C++-Firmware und einer
Windows-Anwendung (Python/PySide6), die über USB (CDC, Buchse **J7**) bidirektional
kommunizieren.

> **Prüfstatus:** Firmware ARM-cross-kompiliert, alle Software- und Simulationstests
> bestanden. **Hardwaretest am Seed3 Desktop Dev Kit (17.10.2026): H1–H10 bestanden**,
> teils protokolliert, teils als Bedienertest. Offen ist nur H11 (EXE auf einem zweiten
> PC). Siehe [Testbericht](docs/TEST_REPORT.md) und Vorabversion
> [v0.1.0](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/releases/tag/v0.1.0).

![Oberfläche im Simulationsmodus](docs/images/gui-simulation.png)

## Funktionen

| Bereich | Firmware | Windows-GUI |
| --- | --- | --- |
| 16 Taster S1–S16 | libDaisy-Entprellung, gehaltener Zustand, Druckzähler | zwei Reihen à 8, Hervorhebung, Zähler |
| 16 LEDs D1–D16 | Aus / Ein / Einzeln / Lauflicht / Taster → LED, Helligkeit | Sollzustand oberhalb der Taster, Steuerung |
| 8 Potis VR1–VR8 | normiert 0…1 und ADC-Rohwert | Drehregler, Prozent, Min/Max |
| SW17 (2 Pos.), SW18 (3 Pos.) | libDaisy `Switch` / `Switch3` (+ Entprellung) | Hebelstellung |
| microSD | Kartenerkennung, optional **nur lesender** Dateisystemtest | keine Karte / erkannt / lesbar / Fehler |
| Audioeingänge L/R | Steckererkennung | Anzeige an den Buchsen |
| USB | DDP v1: Handshake, 10–100 Hz Zustand, Befehle, CRC, Keepalive | Autoerkennung, Zeitüberwachung, Wiederverbindung |
| Simulation | – | Gerätesimulator mit demselben Protokoll |

Audio, DSP, MIDI DIN, USB-MIDI, USB-Host, CV und Gate sind in der GUI als
**„Nicht implementiert“** vorgesehen und gekennzeichnet.

## Verzeichnisse

```

├── firmware/   C++-Firmware (libDaisy, BOOT_SRAM) – Makefile, src/
├── windows/    PySide6-Anwendung (daisy_diag/), EXE-Build, requirements.txt
├── protocol/   Protokollspezifikation, C++-Implementierung, gemeinsame Prüfvektoren
├── tests/      firmware/ (C++-Host-Tests), python/ (Protokoll, Sitzung, GUI)
├── scripts/    Toolchain-Installation (Windows), Firmware-Build, MSVC-Tests
└── docs/       Installation/Bedienung, Firmware, Testbericht, Übergabebericht
```

## Binaerdateien herunterladen

Der [Workflow Hardware diagnostics](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/actions/workflows/diagnostics.yml)
baut Firmware (`DaisyDiagnostic.bin`, `.elf`) und Windows-Anwendung (`DaisyDiagnostic.exe`).
Im letzten erfolgreichen Lauf stehen beide ZIP-Dateien unter **Artifacts**, jeweils
mit `SHA256SUMS`. Das private Repository erfordert eine GitHub-Anmeldung mit Zugriff.
Actions-Artefakte haben eine begrenzte Aufbewahrungsdauer. Releases werden nicht
automatisch angelegt.

## Schnellstart

```bash
git clone https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics.git
cd Daisy-Seed3-Desktop-Diagnostics

# Firmware (Git Bash unter Windows)
bash scripts/install-toolchain-windows.sh
git submodule update --init libDaisy && git -C libDaisy submodule update --init --recursive
bash scripts/build-firmware.sh      # -> firmware/build/DaisyDiagnostic.bin

# Windows-Anwendung
cd windows
python -m pip install -r requirements.txt
python -m daisy_diag --sim                      # ohne Hardware
build_exe.cmd                                   # -> dist/DaisyDiagnostic.exe
cd ../                                          # back to repository root

# Tests
python -m pytest tests/python
scripts/run-host-tests-msvc.cmd     # oder: make -C firmware test
```

Flashen und Bedienung: [Installation und Bedienung](docs/INSTALLATION_UND_BEDIENUNG.md).

## Dokumentation

* [Protokoll DDP v1](protocol/PROTOCOL.md)
* [Installation und Bedienung](docs/INSTALLATION_UND_BEDIENUNG.md)
* [Firmware: Konfiguration, Abhängigkeiten, Aufbau](docs/FIRMWARE.md)
* [Testbericht](docs/TEST_REPORT.md)
* [Technischer Übergabebericht (für die unabhängige Prüfung)](docs/HANDOVER.md)

Das [Toy Piano](https://github.com/sscheidl/Daisy-Seed) wird separat entwickelt. Dieses Repository braucht weder dessen Quellcode noch DaisySP. Siehe [Migration](docs/MIGRATION.md).

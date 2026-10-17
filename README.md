# Daisy Seed3 Hardware Diagnostic Suite

Diagnose aller mechanischen Bedienelemente des **Electro-Smith Seed3 Desktop
Development Kit** – bestehend aus einer flashbaren C++-Firmware und einer
Windows-Anwendung (Python/PySide6), die über USB (CDC, Buchse **J7**) bidirektional
kommunizieren.

> **Prüfstatus:** Firmware ARM-cross-kompiliert, alle Software- und Simulationstests
> bestanden. **An echter Hardware wurde noch nichts getestet** – es war kein Gerät
> angeschlossen. Siehe [Testbericht](docs/TEST_REPORT.md).

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
| USB | DDP v1: Handshake, 20–100 Hz Zustand, Befehle, CRC, Keepalive | Autoerkennung, Zeitüberwachung, Wiederverbindung |
| Simulation | – | vollständiger Gerätesimulator mit demselben Protokoll |

Audio, DSP, MIDI DIN, USB-MIDI, USB-Host, CV und Gate sind in der GUI als
**„Nicht implementiert“** vorgesehen und gekennzeichnet.

## Verzeichnisse

```
diagnostics/
├── firmware/   C++-Firmware (libDaisy, BOOT_SRAM) – Makefile, src/
├── windows/    PySide6-Anwendung (daisy_diag/), EXE-Build, requirements.txt
├── protocol/   Protokollspezifikation, C++-Implementierung, gemeinsame Prüfvektoren
├── tests/      firmware/ (C++-Host-Tests), python/ (Protokoll, Sitzung, GUI)
├── scripts/    Toolchain-Installation (Windows), Firmware-Build, MSVC-Tests
└── docs/       Installation/Bedienung, Firmware, Testbericht, Übergabebericht
```

## Schnellstart

```bash
# Firmware (Git Bash unter Windows)
bash diagnostics/scripts/install-toolchain-windows.sh
git submodule update --init libDaisy && git -C libDaisy submodule update --init --recursive
bash diagnostics/scripts/build-firmware.sh      # -> diagnostics/firmware/build/DaisyDiagnostic.bin

# Windows-Anwendung
cd diagnostics/windows
python -m pip install -r requirements.txt
python -m daisy_diag --sim                      # ohne Hardware
build_exe.cmd                                   # -> dist/DaisyDiagnostic.exe

# Tests
python -m pytest diagnostics/tests/python
diagnostics/scripts/run-host-tests-msvc.cmd     # oder: make -C diagnostics/firmware test
```

Flashen und Bedienung: [Installation und Bedienung](docs/INSTALLATION_UND_BEDIENUNG.md).

## Dokumentation

* [Protokoll DDP v1](protocol/PROTOCOL.md)
* [Installation und Bedienung](docs/INSTALLATION_UND_BEDIENUNG.md)
* [Firmware: Konfiguration, Abhängigkeiten, Aufbau](docs/FIRMWARE.md)
* [Testbericht](docs/TEST_REPORT.md)
* [Technischer Übergabebericht (für die unabhängige Prüfung)](docs/HANDOVER.md)

Die Toy-Piano-Firmware im Repository-Wurzelverzeichnis ist unverändert.

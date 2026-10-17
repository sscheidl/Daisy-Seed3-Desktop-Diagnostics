# Testbericht

> Historischer Bericht aus dem Ursprungsrepository; Herkunft und aktuelle Buildstruktur: [MIGRATION.md](MIGRATION.md).

Stand: 17.10.2026, Branch `fix/codex-review-findings` (Korrekturen zum Codex-Review,
siehe [HANDOVER.md, Abschnitt 9](HANDOVER.md#9-codex-review-von-6f709ec-befunde-und-korrekturen)),
lokal unter Windows 11 Pro
(10.0.26300). **Es war kein Daisy Seed3 angeschlossen.** Die einzige angeschlossene
serielle USB-Schnittstelle (COM3, VID `17CC`) gehört zu einem anderen Gerät und
wurde von der Anwendung korrekt ignoriert.

## A. Bestandene Softwaretests

| # | Prüfung | Befehl | Ergebnis |
| --- | --- | --- | --- |
| 1 | ARM-Cross-Compile (sauberer Neubau) | `bash scripts/build-firmware.sh` | **bestanden**, keine Warnungen aus eigenem Code (`-Wall`) |
| 2 | BOOT_SRAM-Vektortabelle | `make -C firmware check` | **bestanden**: 122 152 B, Stack `0x20020000`, Reset `0x240003f1` |
| 3 | Kein SD-Schreib-/Lösch-/Sperrpfad gelinkt (SDMMC, HAL, BSP, FatFs) | `make … check` (nm) | **bestanden**; Gegenprobe mit eingeschleustem `f_open(…, FA_WRITE)` wird erkannt |
| 4 | Reproduzierbarkeit | zweimal sauber gebaut | **bestanden**: identische SHA-256 |
| 5 | C++-Host-Tests Kern, Protokoll und Hauptschleife (MSVC 19.51, `/W4 /WX`) | `diagnostics\scripts\run-host-tests-msvc.cmd` | **bestanden**: 339 + 635 Prüfungen, 0 Fehler |
| 6 | Python-Tests gesamt (Python 3.12.10, PySide6 6.8.3, pytest 9.0.3) | `python -m pytest tests/python` | **bestanden**: 162 Tests |
| 7 | GUI-Start im Simulationsmodus (Quellcode) | `python -m daisy_diag --sim --selftest 3` | **bestanden** (Exitcode 0) |
| 8 | EXE-Build (PyInstaller 6.19.0, onefile, windowed) | `diagnostics\windows\build_exe.cmd` | **bestanden**: 46,9 MB |
| 9 | EXE-Start Simulation | `DaisyDiagnostic.exe --sim --selftest 5` | **bestanden** (Exitcode 0) |
| 10 | EXE-Start Hardwaremodus ohne Gerät | `DaisyDiagnostic.exe --selftest 4` | **bestanden**: startet, sucht, kein Absturz, Exitcode 1 = „keine Gerätedaten“ (erwartet) |

GUI- und EXE-Tests liefen mit `QT_QPA_PLATFORM=offscreen` (ohne sichtbares Fenster).

### Abdeckung der geforderten Prüfungen (Software / Simulation)

| Anforderung | Tests | Ebene |
| --- | --- | --- |
| Protokolltests | CRC-Prüfvektoren (unabhängig mit `binascii.crc_hqx` erzeugt) in C++ **und** Python; Rahmen-Roundtrip; Resynchronisation bei Störbytes, abgeschnittenen Rahmen, falscher CRC, ungültigen Zeichen, Überlänge, CRLF, Kleinbuchstaben; Feldparser; Firmware- und Host-Formatierung von `ST` byte-identisch | C++, Python |
| Alle 16 Taster | Bitposition je Taster (C++), Drücken/Loslassen je Taster über die komplette Host-Kette, Mausklick je Taster in der GUI, Druckzähler inkl. Überlauf, kurzer Druck zwischen zwei Rahmen, Kontaktaussetzer ohne Doppelzählung | C++, Python, GUI |
| Alle 8 Potis | Feldposition je Poti, Werte 0/25/100 % je Poti über die Host-Kette, Ziehen je Poti in der GUI inkl. Min/Max, Rundung NaN/<0/>1 | C++, Python, GUI |
| Beide Kippschalter | U/D bzw. U/C/D über Protokoll und GUI-Klick, SW18-Entprellung (Störimpuls < 8 ms verworfen) | C++, Python, GUI |
| LED-Steuerung | alle fünf Modi, jede einzelne LED im Modus „Einzeln“, Lauflicht über alle 16 Positionen, Helligkeit, ungültige Argumente (Einstellungen bleiben unverändert), LED-Klick in der Board-Ansicht | C++, Python, GUI |
| microSD-Statusmeldungen | keine Karte, Karte erkannt, Dateisystem lesbar, Fehler `FR_NO_FILESYSTEM`, Karte entfernt; langsame Karte (6 s blockiert) ohne Verbindungsabbruch | C++, Python, GUI |
| USB-Abbruch und Wiederverbindung | Kabel ziehen/stecken (Firmware-Neustart), hängende Firmware → Zeitüberschreitung → automatische Wiederverbindung, verlorenes erstes HELLO, fremdes Gerät mit gleicher VID/PID wird übersprungen, Nicht-Daisy-Ports werden nicht geöffnet, Port lässt sich nicht öffnen, inkompatible Protokollversion, Benutzer-Trennung mit `BYE`, Firmware stoppt den Datenstrom ohne Host | Python, GUI |

### Was diese Tests nicht beweisen

* Die Python-Simulation ist ein **Modell** der Firmware, nicht die Firmware selbst.
  Die Hauptschleife der Firmware (`diag_app`) läuft dagegen als echter C++-Code mit
  Fake-Board und Fake-USB. Nur die hardwarenahe Datei `firmware/src/main.cpp`
  (Audiocallback, CDC-Sender, SD-Treiber, LED-Ansteuerung) ist nur kompiliert.
* ASan/UBSan-Läufe (`make test-sanitize`) benötigen g++ und laufen im GitHub-Workflow.
* Kein Test auf echter USB-Hardware, kein Test des echten Windows-CDC-Treibers mit
  diesem Gerät, kein Test von Timing, ADC-Rauschen oder Entprellung am Board.

## B. Ausstehende Hardwaretests (nicht durchgeführt)

| # | Test | Status |
| --- | --- | --- |
| H1 | Flashen über J7 mit Bootloader v6.x External, Firmwarestart, USR-LED blinkt langsam | **ausstehend** |
| H2 | Windows erkennt COM-Port (VID 0483/PID 5740), automatische Verbindung, `HELLO`-Daten, Bootloaderanzeige | **ausstehend** |
| H3 | Steuer-Update-Rate ≈ 1000 Hz, Zustandsrate ≈ 50 Hz, keine Rahmenfehler über 10 min | **ausstehend** |
| H4 | S1–S16 einzeln, Zuordnung S-Nummer ↔ Position, kein Prellen/Doppelzählen | **ausstehend** |
| H5 | VR1–VR8 Zuordnung, Endwerte (0 %/100 % erreichbar?), Rauschen | **ausstehend** |
| H6 | SW17/SW18: Zuordnung U/C/D zur tatsächlichen Hebelrichtung | **ausstehend** |
| H7 | D1–D16 in allen LED-Modi **optisch** prüfen, Helligkeit | **ausstehend** |
| H8 | microSD: Kartenerkennung (Polarität), Lesetest FAT32/exFAT, Karte ohne Dateisystem, Karte während Test | **ausstehend** |
| H9 | Steckererkennung Audioeingang links/rechts (Polarität, Zuordnung L/R) | **ausstehend** |
| H10 | USB-Kabel ziehen/stecken, Anwendung schließen/öffnen, Wiederverbindung | **ausstehend** |
| H11 | EXE auf einem zweiten Windows-11-PC ohne Python | **ausstehend** |

Ablauf: [HANDOVER.md, Abschnitt 8](HANDOVER.md#8-anleitung-für-den-ersten-hardwaretest).

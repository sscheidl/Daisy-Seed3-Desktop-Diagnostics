# Testbericht

> Historischer Bericht aus dem Ursprungsrepository; Herkunft und aktuelle Buildstruktur: [MIGRATION.md](MIGRATION.md).
> **Ergänzt am 17.10.2026:** Hardwaretest H1–H10 bestanden, H11 offen – siehe Abschnitt B.

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

## B. Hardwaretest am Seed3 Desktop Dev Kit (17.10.2026)

Geflasht wurde `DaisyDiagnostic.bin` mit SHA-256
`5246380984e199368a30c545b45d1263493903ad02a864bde2f04f17c0d15dc0`. Diese Datei ist
bit-identisch mit dem CI-Build von `8c0522d` und mit Release
[v0.1.0](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/releases/tag/v0.1.0).
Getestet wurde über J7 an einem Windows-11-PC mit Bootloader „Daisy Bootloader“
(`0483:DF11`, von libDaisy als `v6_1` = v6.1 oder neuer gemeldet).

„Protokolliert“ heißt: Messwerte wurden über das Diagnoseprotokoll mitgeschrieben.
„Bedienertest“ heißt: am Board und in der Windows-Anwendung durchgeführt und als
erfolgreich gemeldet, ohne Einzelwerte.

| # | Test | Ergebnis | Nachweis |
| --- | --- | --- | --- |
| H1 | Flashen über J7, Firmwarestart, USR-LED | **bestanden** | protokolliert: Bootloader `0483:DF11`, danach Firmware als `0483:5740` (COM14), kein Neustart-Kreislauf |
| H2 | COM-Port, automatische Verbindung, `HELLO`, Bootloaderanzeige | **bestanden** | protokolliert: fw 0.1.0, Protokoll 1, BOOT_SRAM, `bl=v6_1`, libDaisy f715e48 |
| H3 | Steuer-Update-Rate, Zustandsrate, Rahmenfehler | **bestanden, verkürzt** | protokolliert über ca. 3 min statt 10 min: 1000 Hz, 50 Hz, 0 Rahmen-/Inhaltsfehler, 0 verlorene Rahmen, 0 Empfangsfehler |
| H4 | S1–S16 Zuordnung, Prellen, Druckzähler | **bestanden** | Bedienertest |
| H5 | VR1–VR8 Zuordnung und Endwerte | **bestanden** | VR1 protokolliert: 0,0–100,0 % (roh 1–65534) in beide Richtungen, nur Kanal VR1 reagiert; VR2–VR8 Bedienertest |
| H6 | SW17/SW18 Anzeige gegenüber realer Hebelstellung | **bestanden** | Bedienertest |
| H7 | D1–D16 in allen LED-Modi optisch, Helligkeit | **bestanden** | Bedienertest |
| H8 | microSD: Erkennung, Lesetest | **bestanden** | Bedienertest |
| H9 | Klinkenerkennung Audioeingang links/rechts | **bestanden** | Bedienertest |
| H10 | USB-Kabel ziehen/stecken, Anwendung schließen/öffnen | **bestanden** | Bedienertest; Port schließen/öffnen zusätzlich protokolliert (sofortige Wiederverbindung) |
| H11 | EXE auf einem zweiten Windows-11-PC ohne Python | **offen** | – |

Beobachtung: Nach Schließen des Ports ohne `BYE` meldete die Firmware 117 verworfene
Rahmen (`txdrop`). Das ist das dokumentierte Verhalten (bis zu 3 s Weitersenden,
siehe HANDOVER.md, Risiko 7), kein Fehler.

Noch nicht gemessen: Poti-Rauschen in Ruhe, Langzeitstabilität über 10 min,
exFAT und Karte ohne Dateisystem sowie Karte während eines laufenden Tests
(H8-Teilfälle, soweit nicht im Bedienertest enthalten).

Ablauf: [HANDOVER.md, Abschnitt 8](HANDOVER.md#8-anleitung-für-den-ersten-hardwaretest).

# Technischer Übergabebericht – Daisy Seed3 Hardware Diagnostic Suite

> Historischer Bericht aus dem Ursprungsrepository; Herkunft und aktuelle Buildstruktur: [MIGRATION.md](MIGRATION.md).

Für die unabhängige Prüfung (z. B. durch OpenAI Codex). Stand 17.10.2026,
zuletzt aktualisiert mit den Korrekturen zum Codex-Review von `6f709ec`
(Abschnitt 9), Branch `fix/codex-review-findings`, Version Firmware 0.1.0 / Anwendung 0.1.0 /
Protokoll DDP v1.

**Kurzfassung:** Firmware und Windows-Anwendung sind implementiert, die Firmware ist
ARM-cross-kompiliert, alle automatisierten Software- und Simulationstests bestehen.
**Es wurde keine echte Hardware getestet.** Alle Aussagen zum Verhalten am Board sind
aus Quellcode, libDaisy und offizieller Dokumentation abgeleitet.

## 1. Implementierte Funktionen

### Firmware (`firmware`, C++17, libDaisy `f715e48`, BOOT_SRAM)

* Liest alle Bedienelemente über die offizielle Klasse `daisy::desktop_devkit::Hardware`
  (keine eigene Pinzuordnung): 16 Taster (Schieberegister, `DigitalControl`-Entprellung,
  gehaltener Zustand, Druckzähler), 8 Potis (normiert 0…1 und 16-Bit-Rohwert),
  SW17, SW18 (zusätzlich entprellt), microSD-Erkennung, Steckererkennung Audioeingänge.
* 1-kHz-Steuertakt im Audiocallback (48 kHz/48), Audioausgänge stumm.
* 16 LEDs über PCA9685-DMA-Treiber: Aus, Ein, Einzeln (Bitmaske), Lauflicht,
  Taster → LED (Standard), Helligkeit 0–100 %.
* Optionaler microSD-Test: nur `f_mount`/`f_opendir`/`f_readdir`/`f_closedir` über einen
  eigenen schreibgeschützten, zeitbegrenzten Disk-Treiber; der Build prüft, dass kein
  SD-Schreib-, Lösch- oder Sperrbefehl gelinkt ist (SDMMC, HAL, Treiber, FatFs).
* USB CDC über J7 mit `UsbHandle` (nicht blockierend, ISR → Ringpuffer → Hauptschleife).
* Protokoll DDP v1: CRC-16-Rahmen, Handshake mit Protokollversion, vollständige
  Zustandsrahmen 20–100 Hz (Standard 50 Hz) plus sofortige Rahmen bei Eingangsänderung
  (≥ 10 ms Abstand), 1-Hz-Systemstatistik, Befehle `HELLO PING GET RATE LED SDTEST BYE`,
  Host-Überwachung (Datenstrom stoppt 3 s nach dem letzten Host-Rahmen).
* USR-LED des Seed3: langsam = wartet auf Host, schnell = verbunden.

### Windows-Anwendung (`windows`, Python 3.12, PySide6 6.8.3, pyserial 3.5)

* Grafische Board-Ansicht nach Foto/Pinout: Taster, LEDs, Potis (Prozent, Min/Max),
  Kippschalter, microSD, Audioeingänge, J7, nicht implementierte Bereiche markiert.
* Automatische Geräteerkennung (VID/PID + Handshake), HELLO-Wiederholung,
  PING-Keepalive, Zeitüberwachung (1,5 s), Wiederverbindung, Fehlerzähler,
  verlorene Rahmen, Antwortzeit, Firmware-/Protokoll-/Bootloaderanzeige.
* LED-Diagnose, microSD-Lesetest, Poti-Tabelle, Druckzähler, Ereignisprotokoll.
* Simulationsmodus mit vollständigem Gerätemodell (gleiches Protokoll), deutlich
  als Simulation gekennzeichnet; Fehlerinjektion (Kabel ziehen, hängende Firmware,
  fehlerhafter Rahmen, langsame SD-Karte in Tests).
* Dunkle Messgeräte-Optik (Anthrazit, graue Bedienfelder, rote LEDs; Grün/Rot nur als Statusfarben), keine Menüs, EXE per PyInstaller.

## 2. Nicht implementiert (bewusst)

Audio Input/Output (nur Steckererkennung), Audio-Engine/DSP, MIDI DIN, USB-MIDI,
USB-Host, CV Input/Output, Gate Input. In der GUI als „Nicht implementiert“ bzw.
„n. i.“ gekennzeichnet. USB-Host-Fähigkeit und elektrische Voraussetzungen wurden
nicht vorausgesetzt und nicht geprüft. Keine Schreib- oder Formatierfunktionen für SD.
Keine automatische Bootloader-Installation.

## 3. Testergebnisse

Details: [TEST_REPORT.md](TEST_REPORT.md).

| Prüfung | Ergebnis |
| --- | --- |
| ARM-Cross-Compile (xPack GCC 13.2.1-1.1, Windows) | bestanden, reproduzierbar |
| Binärprüfung BOOT_SRAM + nur lesende FatFs-Symbole | bestanden |
| C++-Host-Tests Kern + Protokoll (MSVC `/W4 /WX`) | 339/339 Prüfungen bestanden |
| C++-Host-Tests Hauptschleife `diag_app` (MSVC `/W4 /WX`) | 635/635 Prüfungen bestanden |
| Python-Tests (Protokoll, Sitzung, Simulator, GUI offscreen) | 162/162 bestanden |
| Gegenprobe SD-Symbolprüfung (eingeschleuster `f_open(…, FA_WRITE)`) | wird erkannt |
| GUI- und EXE-Start im Simulationsmodus | bestanden |
| GitHub Actions (g++, ASan/UBSan, Linux-Cross-Compile, Windows-Tests, EXE) | Workflow `diagnostics.yml` angelegt; Ergebnis siehe Pull Request |
| **Alle Hardwaretests H1–H11** | **ausstehend** |

## 4. Bekannte Probleme und Risiken

1. **Keine Hardwarevalidierung.** Insbesondere ungeprüft: Polarität der SD- und
   Klinkenerkennung (aus libDaisy übernommen), Zuordnung U/C/D zur realen Hebelrichtung
   von SW17/SW18, Poti-Endwerte, tatsächliche USB-Enumeration an J7 mit dieser Firmware.
2. **libDaisy `CDC_Transmit_HS()` ohne NULL-Prüfung.** Umgangen durch Prüfung von
   `hUsbDeviceHS.dev_state`/`pClassData` und Start des Transfers bei per `BASEPRI`
   maskiertem USB-Interrupt (globales Symbol aus libDaisy `usb.cpp`). Nur per Review
   geprüft; bei einem libDaisy-Update erneut prüfen.
3. **SD-Test blockiert die Hauptschleife.** Lesezugriffe sind auf 1 s je Vorgang und
   5 s je Test begrenzt; `HAL_SD_Init` nur durch HAL-Zeitgrenzen. Der Host toleriert
   20 s, die blockierte Zeit zählt nicht gegen die Host-Überwachung der Firmware.
   Der eigene Lesetreiber ist nicht an Hardware erprobt.
4. **Geteilte USB-Kennung 0483:5740.** Fremde STM32-VCP-Geräte erhalten beim Suchen
   einen `$HELLO proto=1*…`-Textrahmen und werden nach 1 s ohne passende Antwort
   für 5 s übersprungen. Mit `--port` lässt sich die Suche auf einen Port beschränken.
5. **Bootloaderversion:** libDaisy meldet nur `v6_1` (= v6.1 oder neuer); v6.4 ist
   nicht eindeutig nachweisbar.
6. **LED-Treiber** (libDaisy): möglicher dauerhafter Wartezustand nach fehlgeschlagenem
   DMA-Start, muss weiterhin am Board geprüft werden.
7. **Host schließt ohne `BYE`:** Firmware sendet noch bis zu 3 s in einen nicht
   abgeholten Endpunkt; verworfene Rahmen werden in `SYS txdrop` gezählt. Ein neues
   `HELLO` verwirft wartende Altdaten; bereits übergebene Pakete liest der Host beim
   nächsten Öffnen noch, sein Parser verwirft sie.
8. **Hauptschleife ohne Pause** (Polling); unkritisch für Funktion, nicht energieoptimiert.
9. **EXE unsigniert** → SmartScreen-Warnung möglich. 46,9 MB (Qt-Laufzeit).
10. FatFs ist in libDaisy nicht als `_FS_READONLY` konfiguriert (eine Umstellung würde
    das `FATFS`-Layout gegenüber dem vorkompilierten libDaisy ändern). „Nur lesen“ ist
    dreifach abgesichert: Aufrufpfad, schreibgeschützter Treiber (`STA_PROTECT`,
    `RES_WRPRT`) und Build-Prüfung, dass kein Schreib-/Löschbefehl gelinkt ist.
11. **Firmwaretests ohne Hardware:** `main.cpp` (Audiocallback, CDC-Sender, SD-Treiber,
    LED-Ansteuerung) wird nur kompiliert. Alles andere der Hauptschleife läuft in
    `diag_app` und ist mit Fake-Board/-USB getestet.

## 5. Firmware- und Bootloader-Kompatibilität

| Punkt | Wert |
| --- | --- |
| Anwendungstyp | `BOOT_SRAM` (Linker `STM32H750IB_sram.lds`, Image in QSPI `0x90040000`, Ausführung ab `0x24000000`) |
| Erforderlicher Bootloader | Daisy Bootloader **v6.x External** (`dsy_bootloader_v6_4-extdfu-2000ms.bin` aus libDaisy `core/`), separat vom Benutzer installiert |
| Flashweg | J7 → RESET, dann BOOT innerhalb 2 s → Daisy Web Programmer „Custom“ oder `dfu-util -a 0 -s 0x90040000:leave -D DaisyDiagnostic.bin -d ,0483:df11` |
| Nicht kompatibel | ohne Bootloader (ROM-DFU an `0x08000000`) und Bootloader < v6.0 |
| Bootloader v6.x „internal DFU“ | Anwendung sollte ebenfalls laufen; Flashen dann über den USB-C am Seed3-Modul (nicht geprüft) |
| Laufzeit-USB | CDC an J7 (OTG HS/FS-PHY, D29/D30), VID 0483 PID 5740, Produkt „Daisy Seed External“ |
| Toy Piano | unverändert; wechselseitig austauschbar über denselben Bootloader |

## 6. Kompilierte Artefakte

Lokal unter `release/` (nicht in Git), in CI als Workflow-Artefakte:

| Datei | Größe | SHA-256 |
| --- | --- | --- |
| `DaisyDiagnostic.bin` | 122 152 B | `5246380984e199368a30c545b45d1263493903ad02a864bde2f04f17c0d15dc0` |
| `DaisyDiagnostic.elf` | 2 170 824 B | `ba9f67c0373b6382204877ed53c293c7668c5d1db6972362a943e53f9fbd5ace` |
| `DaisyDiagnostic.exe` | – | wird vom Workflow „Hardware diagnostics“ gebaut (Artefakt) |

Die CI baut die `.bin` unter Linux mit derselben GCC-Version; die Prüfsumme kann wegen
abweichender Pfade in Debug-Informationen bei der `.elf` abweichen. PyInstaller-EXEs
sind nicht bit-reproduzierbar.

## 7. Hinweise für die Prüfung

Empfohlene Reihenfolge und Schwerpunkte:

1. `protocol/PROTOCOL.md` gegen `ddp.cpp` und `windows/daisy_diag/protocol.py`.
2. `firmware/src/main.cpp`: Nebenläufigkeit (Audiocallback ↔ Hauptschleife),
   `BASEPRI`-geschützter CDC-Sender, schreibgeschützter SD-Treiber (DMA, Cache-Pflege,
   Zeitgrenzen, Neuinitialisierung), SDRAM-Platzierung, NVIC-Prioritäten.
   `firmware/src/diag_app.cpp`, `ring_buffer.h`: Hauptschleife, Sendepuffer, Empfangsring.
3. `firmware/src/diag_core.cpp`: Befehlsvalidierung, Host-Timeout mit Überlauf von `GetNow()`.
4. `windows/daisy_diag/session.py`: Zustandsautomat, Zeitüberwachung, SD-Toleranz,
   Port-Backoff.
5. `windows/daisy_diag/simulator.py` gegen das Firmwareverhalten (Modelltreue).
6. Prüfbefehle:
   ```bash
   bash scripts/build-firmware.sh
   make -C firmware test test-sanitize      # Linux/g++
   python -m pytest tests/python -v
   ```

## 8. Anleitung für den ersten Hardwaretest

Vorbereitung: Bootloader v6.x External vorhanden (sonst
[FLASHING.md](FLASHING.md)), Audioeingänge frei, keine SD-Karte.

1. **Flashen (H1):** J7 an den PC, RESET, BOOT innerhalb 2 s, `DaisyDiagnostic.bin`
   im Web Programmer programmieren. Erwartung: USR-LED blinkt danach langsam (1 Hz).
   Ohne PC-Anwendung: Drücken von S1 lässt D1 leuchten.
2. **Verbindung (H2):** `DaisyDiagnostic.exe` starten, Modus „Hardware (USB)“.
   Erwartung binnen ~2 s: grün „Verbunden“, Firmware `DaisyDiagnostic 0.1.0`,
   Protokoll DDP v1, `BOOT_SRAM / v6_1`; USR-LED blinkt schnell.
   Gerätemanager: „Serielles USB-Gerät (COMx)“, VID_0483&PID_5740.
   Falls nicht: Port im Auswahlfeld manuell wählen und Ereignisprotokoll notieren.
3. **Stabilität (H3):** 10 min laufen lassen. Erwartung: Zustandsrate 49–50 Hz,
   Steuer-Update-Rate 1000 Hz (±1), Rahmenfehler 0, verlorene Rahmen 0,
   `TX verworfen` 0.
4. **Taster (H4):** S1 bis S16 nacheinander einzeln drücken. Erwartung: jeweils genau
   der gleiche Taster in der Grafik hervorgehoben, Zähler +1 je Druck, die LED
   darüber leuchtet am Board. Schnelles Antippen: Zähler zählt jeden Druck einmal.
5. **Potis (H5):** VR1…VR8 einzeln von Anschlag zu Anschlag drehen. Erwartung: nur der
   gleichnamige Regler ändert sich, links ≈ 0 %, rechts ≈ 100 % (Min/Max-Spalte
   notieren), Rauschen in Ruhe < 0,5 %.
6. **Kippschalter (H6):** SW17 und SW18 durch alle Stellungen schalten. Notieren,
   welche physische Hebelrichtung als U/C/D angezeigt wird. Abweichungen von der
   erwarteten Richtung sind ein Dokumentationspunkt, kein Funktionsfehler.
7. **LEDs (H7):** „Alle ein“, „Alle aus“, „Einzeln“ (jede LED D1–D16 einmal anklicken),
   „Lauflicht“, Helligkeit 10/50/100 %. **Visuell am Board** prüfen und Ergebnis
   pro LED notieren – die Software kann das nicht feststellen.
8. **microSD (H8):** FAT32-Karte einstecken → „Karte erkannt“; „Lesetest“ →
   „Dateisystem lesbar“ mit plausibler Größe/Eintragszahl. Danach Karte ziehen →
   „Keine Karte“. Optional exFAT-Karte und Karte ohne Dateisystem. Vorher sichern
   ist nicht nötig (nur lesend), wird aber für fremde Karten empfohlen.
9. **Audioeingänge (H9):** Klinkenstecker in IN LEFT, dann IN RIGHT. Erwartung:
   grüner Ring an der richtigen Buchse. Seite und Polarität notieren.
10. **USB (H10):** Anwendung schließen und neu öffnen → verbindet wieder. USB-Kabel an
    J7 ziehen → „Getrennt“; wieder einstecken → nach ~2 s „Verbunden“,
    „Wiederverbindungen“ +1.
11. Ergebnisse in [TEST_REPORT.md](TEST_REPORT.md) Abschnitt B eintragen
    (bestanden/fehlgeschlagen, Beobachtungen, Firmware-SHA-256).

## 9. Codex-Review von `6f709ec`: Befunde und Korrekturen

| # | Befund | Korrektur | Nachweis |
| --- | --- | --- | --- |
| P1 | USB-Reset zwischen Zustandsprüfung und `TransmitExternal()` | Prüfung und Transferstart bei per `BASEPRI` maskiertem USB-Interrupt (`CdcSink`, `main.cpp`) | Review (hardwarenah, nicht host-testbar) |
| P2 | SD nach Kartenwechsel/Fehlversuch nicht neu initialisiert | eigener Treiber wird vor jedem Test neu verknüpft (setzt FatFs-Merker zurück), vorher `HAL_SD_DeInit` | Review; Quellcode von `disk_initialize`/`FATFS_LinkDriverEx` geprüft |
| P2 | Symbolprüfung unvollständig (`f_open`) | Prüfung auf allen Ebenen (SDMMC-Befehle, HAL, BSP, FatFs inkl. `f_open`) + Pflichtsymbole; schreibgeschützter Treiber | Gegenprobe: eingeschleuster `f_open(…, FA_WRITE)` → `make check` scheitert |
| P3 | Kein Backoff bei Handshake-I/O-Fehlern | jeder Abbruch im Handshake sperrt den Port 5 s; nach Schreibfehler sofort nächster Port | `test_handshake_io_error_backs_off_and_tries_next_port[write/read]` |
| P2 | 35-s-SD-Toleranz falsch begründet | Lesezugriffe in der Firmware begrenzt (1 s/Vorgang, 5 s/Test); Host 20 s; Doku korrigiert | `test_slow_sd_card_does_not_drop_connection` |
| P2 | Simulator verarbeitet Befehle während SD-Blockade | Simulator puffert wie der 1-KiB-Ring, inkl. Überlauf | `test_commands_wait_while_firmware_is_blocked`, `test_rx_ring_overflow_while_blocked_is_counted` |
| P2 | `ACK c=BYE` wurde verworfen | kein Verwerfen beim Stream-Ende; erst neues `HELLO` verwirft Altdaten | C++ `TestByeIsAcknowledged`, `TestNewSessionDropsStaleOutput` |
| P2 | Lücken ≥ 1000 nicht gezählt | alle Lücken gezählt, 32-Bit-Überlauf erkannt, Rücksprünge protokolliert | `test_large_sequence_gap_is_counted`, `test_sequence_gap_rules` |
| P3 | PING belebt Stream nach Timeout | Timeout beendet den Stream endgültig (Firmware und Simulator) | C++ `TestSession`, `TestTimeoutNeedsNewHello`; Python `test_ping_after_timeout_does_not_restart_stream` |
| P3 | Überlange optionale LED-Felder als fehlend behandelt | `LookupField()` unterscheidet `Missing`/`TooLong`; Befehl wird abgewiesen | C++ `TestSession`, `TestFields`, `TestLeds` |
| P3 | Python-Parser zu tolerant | strikte Ziffern-/Hex-Prüfung, Bereiche für `n`, `t`, `br`, `pc`, `b`, `l`, `p`, `r`, SD, SYS | 12 neue Fälle in `test_invalid_state_content_is_rejected` |
| P3 | Simulator-Start bei Zeit 0 | `_boot_time is None` statt Wahrheitswert | `test_simulator_clock_starting_at_zero` |

Zusätzlich gefunden beim Beheben: Mit P9 hätte ein langer SD-Test den Datenstrom
beendet, weil die während der Blockade gepufferten PINGs erst danach verarbeitet
werden. Die Dauer eines angeforderten SD-Tests zählt deshalb nicht als Funkstille
(C++ `TestBlockingSdTestKeepsStream`, Python `test_slow_sd_card_does_not_drop_connection`).

Neue Regressionstests der Hauptschleife (`tests/firmware/test_diag_app.cpp`):
Handshake, Rate und Sequenz, Änderungsrahmen, BYE, Timeout, USB nicht bereit,
belegter Endpunkt mit Pufferüberlauf und Prüfung, dass ein übergebener Puffer nicht
verändert wird, veraltete Daten bei neuer Sitzung, Empfangsring-Überlauf mit
Resynchronisation, Ring-Indexüberlauf und Vollzustand, LED-Ratenbegrenzung, SD-Anfragen.
`make test-sanitize` (ASan/UBSan) benötigt g++ und läuft im GitHub-Workflow.

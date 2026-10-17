# Technischer Übergabebericht – Daisy Seed3 Hardware Diagnostic Suite

Für die unabhängige Prüfung (z. B. durch OpenAI Codex). Stand 17.10.2026,
Branch `feat/hardware-diagnostics`, Version Firmware 0.1.0 / Anwendung 0.1.0 /
Protokoll DDP v1.

**Kurzfassung:** Firmware und Windows-Anwendung sind implementiert, die Firmware ist
ARM-cross-kompiliert, alle automatisierten Software- und Simulationstests bestehen.
**Es wurde keine echte Hardware getestet.** Alle Aussagen zum Verhalten am Board sind
aus Quellcode, libDaisy und offizieller Dokumentation abgeleitet.

## 1. Implementierte Funktionen

### Firmware (`diagnostics/firmware`, C++17, libDaisy `f715e48`, BOOT_SRAM)

* Liest alle Bedienelemente über die offizielle Klasse `daisy::desktop_devkit::Hardware`
  (keine eigene Pinzuordnung): 16 Taster (Schieberegister, `DigitalControl`-Entprellung,
  gehaltener Zustand, Druckzähler), 8 Potis (normiert 0…1 und 16-Bit-Rohwert),
  SW17, SW18 (zusätzlich entprellt), microSD-Erkennung, Steckererkennung Audioeingänge.
* 1-kHz-Steuertakt im Audiocallback (48 kHz/48), Audioausgänge stumm.
* 16 LEDs über PCA9685-DMA-Treiber: Aus, Ein, Einzeln (Bitmaske), Lauflicht,
  Taster → LED (Standard), Helligkeit 0–100 %.
* Optionaler microSD-Test: nur `f_mount`/`f_opendir`/`f_readdir`/`f_closedir`;
  Build prüft, dass keine schreibenden FatFs-Funktionen gelinkt sind.
* USB CDC über J7 mit `UsbHandle` (nicht blockierend, ISR → Ringpuffer → Hauptschleife).
* Protokoll DDP v1: CRC-16-Rahmen, Handshake mit Protokollversion, vollständige
  Zustandsrahmen 20–100 Hz (Standard 50 Hz) plus sofortige Rahmen bei Eingangsänderung
  (≥ 10 ms Abstand), 1-Hz-Systemstatistik, Befehle `HELLO PING GET RATE LED SDTEST BYE`,
  Host-Überwachung (Datenstrom stoppt 3 s nach dem letzten Host-Rahmen).
* USR-LED des Seed3: langsam = wartet auf Host, schnell = verbunden.

### Windows-Anwendung (`diagnostics/windows`, Python 3.12, PySide6 6.8.3, pyserial 3.5)

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
| C++-Host-Tests (MSVC `/W4 /WX`) | 325/325 bestanden |
| Python-Tests (Protokoll, Sitzung, GUI offscreen) | 142/142 bestanden |
| GUI- und EXE-Start im Simulationsmodus | bestanden |
| GitHub Actions (g++, ASan/UBSan, Linux-Cross-Compile, Windows-Tests, EXE) | Workflow `diagnostics.yml` angelegt; Ergebnis siehe Pull Request |
| **Alle Hardwaretests H1–H11** | **ausstehend** |

## 4. Bekannte Probleme und Risiken

1. **Keine Hardwarevalidierung.** Insbesondere ungeprüft: Polarität der SD- und
   Klinkenerkennung (aus libDaisy übernommen), Zuordnung U/C/D zur realen Hebelrichtung
   von SW17/SW18, Poti-Endwerte, tatsächliche USB-Enumeration an J7 mit dieser Firmware.
2. **libDaisy `CDC_Transmit_HS()` ohne NULL-Prüfung.** Umgangen durch Prüfung von
   `hUsbDeviceHS.dev_state` (globales Symbol aus libDaisy `usb.cpp`). Bei einem
   libDaisy-Update erneut prüfen.
3. **SD-Treiber blockiert bis 30 s** (`SD_TIMEOUT` in libDaisy `sd_diskio.c`).
   Der Host toleriert das während eines angeforderten SD-Tests; andernfalls
   Verbindungsfehler + automatische Wiederverbindung.
4. **Geteilte USB-Kennung 0483:5740.** Fremde STM32-VCP-Geräte erhalten beim Suchen
   einen `$HELLO proto=1*…`-Textrahmen und werden nach 1 s ohne passende Antwort
   für 5 s übersprungen. Mit `--port` lässt sich die Suche auf einen Port beschränken.
5. **Bootloaderversion:** libDaisy meldet nur `v6_1` (= v6.1 oder neuer); v6.4 ist
   nicht eindeutig nachweisbar.
6. **LED-Treiber** (libDaisy): möglicher dauerhafter Wartezustand nach fehlgeschlagenem
   DMA-Start, wie in `docs/HARDWARE.md` für das Toy Piano beschrieben.
7. **Host schließt ohne `BYE`:** Firmware sendet noch bis zu 3 s in einen nicht
   abgeholten Endpunkt; verworfene Rahmen werden in `SYS txdrop` gezählt. Beim
   nächsten Öffnen gelesene Altdaten werden vom Parser verworfen.
8. **Hauptschleife ohne Pause** (Polling); unkritisch für Funktion, nicht energieoptimiert.
9. **EXE unsigniert** → SmartScreen-Warnung möglich. 46,9 MB (Qt-Laufzeit).
10. FatFs ist in libDaisy nicht als `_FS_READONLY` konfiguriert; „nur lesen“ ist durch
    den Code und die Symbolprüfung im Build abgesichert, nicht durch die FatFs-Konfiguration.

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

Lokal unter `diagnostics/release/` (nicht in Git), in CI als Workflow-Artefakte:

| Datei | Größe | SHA-256 |
| --- | --- | --- |
| `DaisyDiagnostic.bin` | 126 760 B | `bf5eda87144ac74eaf9a496189eb75da475f68a67ccbe2c9555c49822f576344` |
| `DaisyDiagnostic.elf` | 2 338 756 B | `0a070271fa759ca728fda78eeed54e014f8b07c47c70a84b22b0b789f053d4c5` |
| `DaisyDiagnostic.exe` | 46 861 814 B | `68bf0e6b77902249fe65f36b828a20077e3fe33cf04bb364141b3f7a20856dd6` |

Die CI baut die `.bin` unter Linux mit derselben GCC-Version; die Prüfsumme kann wegen
abweichender Pfade in Debug-Informationen bei der `.elf` abweichen. PyInstaller-EXEs
sind nicht bit-reproduzierbar.

## 7. Hinweise für die Prüfung

Empfohlene Reihenfolge und Schwerpunkte:

1. `diagnostics/protocol/PROTOCOL.md` gegen `ddp.cpp` und `windows/daisy_diag/protocol.py`.
2. `firmware/src/main.cpp`: Nebenläufigkeit (Audiocallback ↔ Hauptschleife,
   USB-ISR ↔ Ringpuffer), Zwei-Puffer-Senden, `dev_state`-Prüfung, SDRAM-Platzierung
   der FatFs-Objekte, NVIC-Prioritäten.
3. `firmware/src/diag_core.cpp`: Befehlsvalidierung, Host-Timeout mit Überlauf von `GetNow()`.
4. `windows/daisy_diag/session.py`: Zustandsautomat, Zeitüberwachung, SD-Toleranz,
   Port-Backoff.
5. `windows/daisy_diag/simulator.py` gegen das Firmwareverhalten (Modelltreue).
6. Prüfbefehle:
   ```bash
   bash diagnostics/scripts/build-firmware.sh
   make -C diagnostics/firmware test test-sanitize      # Linux/g++
   python -m pytest diagnostics/tests/python -v
   ```

## 8. Anleitung für den ersten Hardwaretest

Vorbereitung: Bootloader v6.x External vorhanden (sonst
[docs/FLASHING.md](../../docs/FLASHING.md)), Audioeingänge frei, keine SD-Karte.

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

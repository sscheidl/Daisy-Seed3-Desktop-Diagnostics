# Diagnosefirmware – Konfiguration, Abhängigkeiten, Aufbau

## Zielkonfiguration

| Punkt | Wert |
| --- | --- |
| Hardware | Electro-Smith **Seed3 Desktop Development Kit** (`daisy::desktop_devkit::Hardware`) |
| Anwendungstyp | `APP_TYPE = BOOT_SRAM` (Code und Daten im AXI-SRAM ab `0x24000000`, Image im QSPI ab `0x90040000`) |
| Bootloader | Daisy Bootloader **v6.x External**, vorgesehen `dsy_bootloader_v6_4-extdfu-2000ms.bin` (DFU über J7, 2 s Wartezeit). Wird von der Firmware **nicht** installiert. |
| USB | `UsbHandle::FS_EXTERNAL` = OTG-HS-Peripherie im FS-Modus an D29/D30, Buchse **J7** am Träger; CDC-ACM, VID `0483`, PID `5740` |
| Steuertakt | Audiocallback 48 kHz / 48 Samples = **1 kHz** `UpdateAllControls()`; Audioausgänge stumm |
| Compiler | xPack GNU Arm Embedded GCC **13.2.1-1.1** (`13.2.1 20231009`), GNU++17, `-O2`, Cortex-M7, FPv5-D16, Hard Float |
| Speicher (Build vom 17.10.2026) | SRAM 122 152 B von 480 KB (24,9 %), DTCM 71 808 B von 128 KB, SDRAM 632 B |

## Festgelegte Abhängigkeiten

| Bestandteil | Version | Quelle |
| --- | --- | --- |
| libDaisy | `f715e4875b2d28445d0c11a0a17f064a248f69d0` (v9.0.0-5) | bestehendes Git-Submodul, **unverändert** |
| ├ STM32H7xx HAL | `404a70d4c19c124636c78801ff7c0dbc87bc4256` | libDaisy-Submodul |
| └ STM32 USB Device Library | `7b5e6886d2f11ad15d2b46364e8a96984358f639` | libDaisy-Submodul |
| FatFs | in libDaisy enthalten (`Middlewares/Third_Party/FatFs`) | `USE_FATFS = 1`; eigener, schreibgeschützter Disk-Treiber statt `SD_Driver` |
| DaisySP | nicht benötigt | – |
| Windows-Toolchain | xPack ARM GCC 13.2.1-1.1 `win32-x64` (SHA-256 `56b18ccb…29e4f`), xPack Windows Build Tools 4.4.1-3 (GNU Make 4.4.1, SHA-256 `113d4dfd…1d218`) | [`scripts/install-toolchain-windows.sh`](../scripts/install-toolchain-windows.sh) |
| Linux-Toolchain (CI) | xPack ARM GCC 13.2.1-1.1 `linux-x64` | bestehendes `scripts/install-toolchain.sh` |

Die Submodule wurden nur mit `git submodule update --init` auf ihre festgelegten
Commits gesetzt, nicht aktualisiert. Kein `--remote`.

## Bauen

```bash
# Windows (Git Bash), einmalig:
bash scripts/install-toolchain-windows.sh
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4

# Firmware bauen und prüfen:
bash scripts/build-firmware.sh
# -> firmware/build/DaisyDiagnostic.bin
```

`make check` (vom Skript aufgerufen) prüft mit dem bestehenden
`scripts/check-firmware.py` die BOOT_SRAM-Vektortabelle und stellt per
`arm-none-eabi-nm` sicher, dass **kein SD-Schreib-, Lösch- oder Sperrpfad** gelinkt ist –
auf allen Ebenen: SDMMC-Befehle (`SDMMC_CmdWriteSingleBlock`/`MultiBlock`, Erase,
`LockUnlock`), HAL (`HAL_SD_WriteBlocks*`, `HAL_SD_Erase`), libDaisy-BSP/Treiber
(`BSP_SD_WriteBlocks*`, `SD_write`, `SD_Driver`) und FatFs-API (`f_open`, `f_write`,
`f_mkfs`, …). Damit ist kein Befehl im Image, der eine Karte verändern könnte.
Eine Pflichtliste (`RoRead`, `f_mount`, `SDMMC_CmdReadSingleBlock`, …) verhindert, dass
die Prüfung bei fehlerhafter Symbolliste leer durchläuft. Gegenprobe: ein erreichbarer
`f_open(…, FA_WRITE)` lässt `make check` mit „SD write/erase path f_open is linked“
scheitern.

Host-Tests der hardwareunabhängigen Logik:

```bash
make -C firmware test            # g++ (Linux/CI)
make -C firmware test-sanitize   # mit ASan/UBSan
diagnostics\scripts\run-host-tests-msvc.cmd  # Windows, MSVC /W4 /WX
```

## Aufbau

```
firmware/src/main.cpp       nur Hardware: Audiocallback, CDC-Sender, SD-Treiber,
                                        Board-Anbindung
firmware/src/diag_app.*     hardwareunabhängige Hauptschleife: Empfang, Befehle,
                                        Zustandsrahmen, Sendepuffer, LED-/SD-Anforderungen
firmware/src/diag_core.*    Tasterzähler, SW18-Entprellung, LED-Modi, Session,
                                        Nachrichtenformat
firmware/src/ring_buffer.h  lockfreier Empfangsring (USB-ISR -> Hauptschleife)
protocol/ddp.*              Rahmen, CRC, Parser, Feldzugriff (Firmware + Tests)
```

### Ablauf

* **Audiocallback (1 kHz, höchste Priorität):** `hw.UpdateAllControls()`,
  Flankenauswertung der 16 Taster (`DigitalControl`), Entprellung SW18, Schnappschuss
  aller digitalen Eingänge. Keine USB-, LED- oder SD-Zugriffe. Ausgänge = 0.
* **USB-Empfang (OTG-HS-Interrupt, Priorität 1):** kopiert Bytes in einen lockfreien
  1-KB-Ringpuffer. Kein Parsen, kein Senden im Interrupt.
* **Hauptschleife (`diag::App::Step`, auf dem Host getestet):** Rahmen parsen und beantworten, Eingänge mit kurz gesperrten
  Interrupts kopieren, Potis lesen (`pot[i].Value()` und `adc.GetMux(0, i)`),
  LEDs höchstens alle 10 ms und nur bei Änderung schreiben (`UpdateLeds()` kann auf
  den vorherigen DMA-Transfer warten), Zustandsrahmen erzeugen, nicht blockierend senden.
  USR-LED des Seed3: langsames Blinken = wartet auf Host, schnelles Blinken = Host verbunden.

### Entscheidungen

* **UsbHandle statt Logger:** Der libDaisy-Logger kann nicht empfangen und wartet
  beim Senden blockierend. Details in [PROTOCOL.md](../protocol/PROTOCOL.md).
* **Geschütztes Senden:** `CDC_Transmit_HS()` in libDaisy dereferenziert
  `pClassData` ohne Prüfung, und ein USB-Busreset im OTG-HS-Interrupt gibt diese Daten
  frei. Prüfung (`dev_state == USBD_STATE_CONFIGURED`, `pClassData != NULL`) und
  Start des Transfers laufen deshalb in einem Abschnitt, in dem `BASEPRI` den
  USB-Interrupt (Priorität 1) maskiert; der Audio-Interrupt (Priorität 0) läuft weiter.
  Dieser Teil ist hardwarenah und nur per Review geprüft.
* **Zwei Sendepuffer:** Die CDC-Klasse liest den übergebenen Puffer, bis der IN-Transfer
  abgeschlossen ist. Neue Rahmen werden im jeweils anderen Puffer gesammelt.
  Antworten (auch `ACK c=BYE`) bleiben nach Ende des Datenstroms erhalten; erst ein
  neues `HELLO` verwirft noch nicht gesendete Rahmen einer früheren Sitzung.
* **Host-Überwachung:** 3 s ohne Host-Rahmen beendet den Datenstrom endgültig; nur ein
  neues `HELLO` startet ihn wieder. Die Dauer eines vom Host angeforderten SD-Tests
  zählt nicht als Funkstille (während der Blockade gepufferte PINGs kommen danach).
* **Interruptprioritäten:** libDaisy setzt USB und Audio-DMA auf Priorität 0. Die
  Firmware senkt OTG_HS auf 1, damit der Audiocallback (Steuertakt) Vorrang hat
  (wie im Referenzprojekt Daisy-on-Tulip).
* **Tasterzustand:** gehalten zwischen `RisingEdge()` und `FallingEdge()` wie in der
  Toy-Piano-Firmware; eine zweite Anstiegsflanke nach kurzem Kontaktaussetzer zählt
  nicht als neuer Druck. Druckzähler (mod 256) machen auch sehr kurze Drücke sichtbar.
* **SW18:** `Switch3::Read()` ist ungefiltert; Übernahme nach 8 gleichen Lesungen (8 ms).
* **microSD – eigener schreibgeschützter Treiber:** statt `FatFSInterface`/`SD_Driver`
  verknüpft die Firmware einen eigenen FatFs-Disk-Treiber: Status immer mit
  `STA_PROTECT` (FatFs verweigert jeden Schreibzugriff mit `FR_WRITE_PROTECTED`),
  Schreibeintrag liefert nur `RES_WRPRT`, kein Schreibbefehl ist gelinkt.
  Lesezugriffe per DMA mit eigener Wartezeit: höchstens **1 s pro Vorgang** und
  **5 s pro Test** (libDaisys `SD_read()` wartet dagegen zweimal bis zu 30 s).
  Vor jedem Test: `HAL_SD_DeInit` und neues Verknüpfen des Treibers. Das setzt FatFs'
  „initialisiert“-Merker zurück (der Originaltreiber setzt ihn schon vor dem Ergebnis),
  sodass Kartenwechsel und fehlgeschlagene Erstversuche sauber neu initialisiert werden.
* **SD-Speicher:** Bei BOOT_SRAM liegt `.bss` im DTCM, das der SDMMC1-IDMA nicht erreicht.
  `FATFS` (inkl. Sektorpuffer) und `DIR` liegen daher in `.sdram_bss` (SDRAM, wird von
  `seed.Init()` initialisiert; kein statischer Konstruktor schreibt vorher dorthin).
  Cache-Pflege (Clean vor, Invalidate nach dem DMA) im eigenen Lesetreiber.
  SDMMC wird erst beim ersten `SDTEST` konfiguriert (`Speed::STANDARD`).
* **Potis:** `AnalogControl::Value()` (0…1) unverändert aus libDaisy, ohne eigene
  Kalibrierung; zusätzlich der 16-Bit-Rohwert des Mux-Kanals.

## Bekannte Grenzen der Firmware

* Während eines SD-Tests ist die Hauptschleife blockiert und der Datenstrom pausiert.
  Lesezugriffe sind auf 5 s (+1 s laufender Vorgang) begrenzt; die Karteninitialisierung
  (`HAL_SD_Init`) ist nur durch die HAL-eigenen Zeitgrenzen beschränkt. Der Host
  toleriert während eines angeforderten Tests 20 s, sonst gilt die 1,5-s-Grenze.
  Der eigene Lesetreiber ist nicht an Hardware erprobt.
* `System::GetBootloaderVersion()` unterscheidet nur `v6_0` und „`v6_1` oder neuer“.
  Ob tatsächlich v6.4 installiert ist, lässt sich so nicht nachweisen.
* Der von libDaisy übernommene LED-DMA-Treiber kann nach einem fehlgeschlagenen
  `TransmitDma()`-Start hängen.
* `Hardware::Init()` initialisiert auch MIDI-UART, DAC, Gate-Eingänge und CV-ADC.
  Die Firmware nutzt sie nicht.

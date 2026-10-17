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
| Speicher (Build vom 17.10.2026) | SRAM 126 760 B von 480 KB (25,8 %), DTCM 71 304 B von 128 KB, SDRAM 1 216 B |

## Festgelegte Abhängigkeiten

| Bestandteil | Version | Quelle |
| --- | --- | --- |
| libDaisy | `f715e4875b2d28445d0c11a0a17f064a248f69d0` (v9.0.0-5) | bestehendes Git-Submodul, **unverändert** |
| ├ STM32H7xx HAL | `404a70d4c19c124636c78801ff7c0dbc87bc4256` | libDaisy-Submodul |
| └ STM32 USB Device Library | `7b5e6886d2f11ad15d2b46364e8a96984358f639` | libDaisy-Submodul |
| FatFs | in libDaisy enthalten (`Middlewares/Third_Party/FatFs`) | `USE_FATFS = 1` |
| DaisySP | nicht benötigt | – |
| Windows-Toolchain | xPack ARM GCC 13.2.1-1.1 `win32-x64` (SHA-256 `56b18ccb…29e4f`), xPack Windows Build Tools 4.4.1-3 (GNU Make 4.4.1, SHA-256 `113d4dfd…1d218`) | [`scripts/install-toolchain-windows.sh`](../scripts/install-toolchain-windows.sh) |
| Linux-Toolchain (CI) | xPack ARM GCC 13.2.1-1.1 `linux-x64` | bestehendes `scripts/install-toolchain.sh` |

Die Submodule wurden nur mit `git submodule update --init` auf ihre festgelegten
Commits gesetzt, nicht aktualisiert. Kein `--remote`.

## Bauen

```bash
# Windows (Git Bash), einmalig:
bash diagnostics/scripts/install-toolchain-windows.sh
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4

# Firmware bauen und prüfen:
bash diagnostics/scripts/build-firmware.sh
# -> diagnostics/firmware/build/DaisyDiagnostic.bin
```

`make check` (vom Skript aufgerufen) prüft mit dem bestehenden
`scripts/check-firmware.py` die BOOT_SRAM-Vektortabelle und stellt per
`arm-none-eabi-nm` sicher, dass **keine schreibenden FatFs-Funktionen** gelinkt sind
(`f_write`, `f_mkfs`, `f_unlink`, `f_rename`, `f_mkdir`, `f_truncate`, `f_sync`, …).
Gelinkt sind ausschließlich `f_mount`, `f_opendir`, `f_readdir`, `f_closedir`.

Host-Tests der hardwareunabhängigen Logik:

```bash
make -C diagnostics/firmware test            # g++ (Linux/CI)
make -C diagnostics/firmware test-sanitize   # mit ASan/UBSan
diagnostics\scripts\run-host-tests-msvc.cmd  # Windows, MSVC /W4 /WX
```

## Aufbau

```
diagnostics/firmware/src/main.cpp       Hardwarezugriff, Audiocallback, Hauptschleife, USB, SD
diagnostics/firmware/src/diag_core.*    hardwareunabhängig: Tasterzähler, SW18-Entprellung,
                                        LED-Modi, Befehlsverarbeitung, Nachrichtenformat
diagnostics/protocol/ddp.*              Rahmen, CRC, Parser, Feldzugriff (Firmware + Tests)
```

### Ablauf

* **Audiocallback (1 kHz, höchste Priorität):** `hw.UpdateAllControls()`,
  Flankenauswertung der 16 Taster (`DigitalControl`), Entprellung SW18, Schnappschuss
  aller digitalen Eingänge. Keine USB-, LED- oder SD-Zugriffe. Ausgänge = 0.
* **USB-Empfang (OTG-HS-Interrupt, Priorität 1):** kopiert Bytes in einen lockfreien
  1-KB-Ringpuffer. Kein Parsen, kein Senden im Interrupt.
* **Hauptschleife:** Rahmen parsen und beantworten, Eingänge mit kurz gesperrten
  Interrupts kopieren, Potis lesen (`pot[i].Value()` und `adc.GetMux(0, i)`),
  LEDs höchstens alle 10 ms und nur bei Änderung schreiben (`UpdateLeds()` kann auf
  den vorherigen DMA-Transfer warten), Zustandsrahmen erzeugen, nicht blockierend senden.
  USR-LED des Seed3: langsames Blinken = wartet auf Host, schnelles Blinken = Host verbunden.

### Entscheidungen

* **UsbHandle statt Logger:** Der libDaisy-Logger kann nicht empfangen und wartet
  beim Senden blockierend. Details in [PROTOCOL.md](../protocol/PROTOCOL.md).
* **NULL-Schutz beim Senden:** `CDC_Transmit_HS()` in libDaisy dereferenziert
  `pClassData` ohne Prüfung. Vor der USB-Konfiguration durch den Host (nur
  Netzteil an J7, Enumeration läuft noch) sendet die Firmware deshalb nicht,
  sondern prüft `hUsbDeviceHS.dev_state == USBD_STATE_CONFIGURED`.
* **Zwei Sendepuffer:** Die CDC-Klasse liest den übergebenen Puffer, bis der IN-Transfer
  abgeschlossen ist. Neue Rahmen werden im jeweils anderen Puffer gesammelt.
* **Interruptprioritäten:** libDaisy setzt USB und Audio-DMA auf Priorität 0. Die
  Firmware senkt OTG_HS auf 1, damit der Audiocallback (Steuertakt) Vorrang hat
  (wie im Referenzprojekt Daisy-on-Tulip).
* **Tasterzustand:** gehalten zwischen `RisingEdge()` und `FallingEdge()` wie in der
  Toy-Piano-Firmware; eine zweite Anstiegsflanke nach kurzem Kontaktaussetzer zählt
  nicht als neuer Druck. Druckzähler (mod 256) machen auch sehr kurze Drücke sichtbar.
* **SW18:** `Switch3::Read()` ist ungefiltert; Übernahme nach 8 gleichen Lesungen (8 ms).
* **microSD:** Bei BOOT_SRAM liegt `.bss` im DTCM, das der SDMMC1-IDMA nicht erreicht.
  `FatFSInterface` (inkl. Sektorpuffer) und `DIR` liegen daher in `.sdram_bss`
  (SDRAM, wird von `seed.Init()` initialisiert; kein statischer Konstruktor schreibt
  vorher dorthin – am Objektcode geprüft). libDaisys `sd_diskio` übernimmt die
  Cache-Pflege. SDMMC wird erst beim ersten `SDTEST` initialisiert (`Speed::STANDARD`).
* **Potis:** `AnalogControl::Value()` (0…1) unverändert aus libDaisy, ohne eigene
  Kalibrierung; zusätzlich der 16-Bit-Rohwert des Mux-Kanals.

## Bekannte Grenzen der Firmware

* `SD_read()` in libDaisy wartet bei Problemen bis zu 30 s aktiv in der Hauptschleife.
  Der Datenstrom pausiert dann; der Host toleriert das nur während eines angeforderten
  SD-Tests (35 s), sonst meldet er nach 1,5 s „Verbindungsfehler“ und verbindet neu.
* `System::GetBootloaderVersion()` unterscheidet nur `v6_0` und „`v6_1` oder neuer“.
  Ob tatsächlich v6.4 installiert ist, lässt sich so nicht nachweisen.
* Der von libDaisy übernommene LED-DMA-Treiber kann nach einem fehlgeschlagenen
  `TransmitDma()`-Start hängen (siehe [docs/HARDWARE.md](../../docs/HARDWARE.md)).
* `Hardware::Init()` initialisiert auch MIDI-UART, DAC, Gate-Eingänge und CV-ADC.
  Die Firmware nutzt sie nicht.

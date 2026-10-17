# Flashen über USB

Hardwaretests H1-H11 bleiben ausstehend. Diese Anleitung beschreibt ausschliesslich manuelle Schritte am Kit.

## Zwei USB-C-Anschlüsse

* **Seed3-Modul:** eigener USB-Port für den STM32-ROM-DFU-Modus und die einmalige
  Installation des Daisy-Bootloaders.
* **Desktop-Träger, J7 (oberhalb des Seed3):** Stromversorgung, regulärer Betrieb
  und spätere Programmierung über den **externen** Daisy-Bootloader.

Ein USB-Datenkabel verwenden. Der Anschluss am Träger und der am Seed3 sind
unterschiedliche USB-Verbindungen. Zum jeweiligen Schritt das Kabel an den
angegebenen Anschluss umstecken.

## Einmalig: externen Bootloader installieren

**Überspringen, wenn bereits ein passender externer v6.x-Bootloader installiert ist.**
Die Diagnosefirmware ist eine BOOT_SRAM-Anwendung und ersetzt diesen nicht.
Eine direkte Installation der Anwendung über den ROM-DFU-Modus ist nicht der
hier verwendete Ablauf.

1. Computer mit dem USB-C-Port **am Seed3-Modul** verbinden.
2. **BOOT halten**, RESET drücken und loslassen, dann BOOT loslassen.
   Dies startet den eingebauten STM32-ROM-Bootloader.
3. In Chrome/Edge den [Daisy Web Programmer](https://flash.daisy.audio/) öffnen.
   Bootloader **v6.x (external)** auswählen und installieren.
   Alternativ, mit lokal installiertem `dfu-util`, im Projektverzeichnis:

   ```bash
   make -C firmware program-boot
   ```

   Das Makefile wählt wie das offizielle Desktop-Template gezielt
   `libDaisy/core/dsy_bootloader_v6_4-extdfu-2000ms.bin`.
   Dieser separate Befehl schreibt den Bootloader; er wird von `make` nicht ausgeführt.
4. USB-Kabel zum **Desktop-Träger J7** umstecken.

Die Bootloader-Installation ist nur bei fehlender oder unpassender Variante nötig.
Bei späteren Firmwareupdates nicht erneut `program-boot` ausführen.

## Diagnosefirmware flashen

1. Kit über **J7 am Desktop-Träger** mit dem Computer verbinden und versorgen.
2. **RESET drücken und loslassen, anschließend BOOT** innerhalb der ungefähr
   zweisekündigen Wartezeit drücken. Die USR-LED blinkt zuerst schnell und pulsiert
   danach langsam: der Daisy-Bootloader wartet auf die Anwendung.
   Dieser Ablauf unterscheidet sich vom oben beschriebenen ROM-DFU-Modus.
3. Im [Daisy Web Programmer](https://flash.daisy.audio/) verbinden,
   unter „Custom“ **`firmware/build/DaisyDiagnostic.bin`** auswählen und programmieren.
   Alternativ lokal im Projektverzeichnis:

   ```bash
   make -C firmware program-dfu
   ```

   Das offizielle Makefile schreibt die Anwendung nach QSPI `0x90040000`.
   Der Daisy-Bootloader lädt sie zum Ausführen ins SRAM (`0x24000000`).
4. Nach erfolgreichem Flashen startet die Firmware; gegebenenfalls RESET drücken.
   Der Bootloader bleibt für weitere Versionen installiert.

## Wenn das Gerät nicht erscheint

Zuerst Datenkabel, Anschluss und den zum Schritt gehörenden BOOT/RESET-Ablauf
prüfen. Bei Firmwareupdates muss der externe Bootloader über J7 erreichbar sein.
WebUSB benötigt einen unterstützten Browser sowie USB-Zugriffsrechte; unter Linux
können passende udev-Regeln, unter Windows die offiziellen Daisy/Zadig-Treiber nötig sein.
Siehe [offizielle Hilfe](https://docs.daisy.audio/tutorials/daisy-web-programmer/)
und [Anleitung des Desktop-Kits](https://github.com/daisyaudio/Seed3-DevKit-Desktop#4-install-the-daisy-bootloader-one-time).

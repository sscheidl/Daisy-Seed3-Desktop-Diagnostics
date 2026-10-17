# Installation und Bedienung

![Oberfläche im Simulationsmodus](images/gui-simulation.png)

*Abbildung: Simulationsmodus – alle Werte simuliert, kein Gerät angeschlossen.*

## 1. Voraussetzungen

* Seed3 Desktop Development Kit, USB-C-**Datenkabel**
* Windows 11 (Windows 10 sollte ebenfalls funktionieren, nicht geprüft)
* Daisy Bootloader **v6.x External** auf dem Seed3 (siehe Schritt 2)
* `DaisyDiagnostic.bin` und `DaisyDiagnostic.exe`
  (lokal gebaut oder als Artefakte des GitHub-Workflows „Hardware diagnostics“)

Ein zusätzlicher Treiber ist nicht nötig: Windows bindet USB-CDC-Geräte automatisch
an `usbser.sys` („Serielles USB-Gerät (COMx)“).

## 2. Bootloader (separat, nur falls nicht vorhanden)

Die Diagnosefirmware installiert **keinen** Bootloader. Ist bereits ein externer
v6.x-Bootloader vorhanden (z. B. für das Toy Piano), diesen Schritt überspringen.
Sonst wie in [FLASHING.md](FLASHING.md), Abschnitt „Einmalig“:
USB-C am **Seed3-Modul**, BOOT halten + RESET, im
[Daisy Web Programmer](https://flash.daisy.audio/) „v6.x (external)“ installieren.

## 3. Firmware flashen (über J7)

1. Kit über **J7 am Desktop-Träger** (USB-C oberhalb des Seed3) mit dem PC verbinden.
2. **RESET** drücken und loslassen, dann innerhalb von ca. 2 s **BOOT** drücken.
   Die USR-LED blinkt schnell und pulsiert dann langsam: Bootloader wartet.
3. [Daisy Web Programmer](https://flash.daisy.audio/) (Chrome/Edge) → Verbinden →
   „Custom“ → `DaisyDiagnostic.bin` → Programmieren.
   Alternativ mit `dfu-util`:
   ```bash
   dfu-util -a 0 -s 0x90040000:leave -D DaisyDiagnostic.bin -d ,0483:df11
   ```
4. Nach dem Start blinkt die USR-LED des Seed3 **langsam (1 Hz)**: Firmware läuft und
   wartet auf die Windows-Anwendung. Taster schalten bereits ohne PC ihre LED
   (Standardmodus „Taster → LED“).

Zurück zum Toy Piano: dessen `.bin` auf dieselbe Weise flashen.

## 4. Windows-Anwendung starten

**EXE:** `DaisyDiagnostic.exe` doppelklicken. Die Datei ist nicht signiert; Windows
SmartScreen kann beim ersten Start warnen („Weitere Informationen“ → „Trotzdem ausführen“).

**Aus dem Quellcode** (Python 3.12):

```bash
cd windows
python -m pip install -r requirements.txt
python -m daisy_diag            # Hardware
python -m daisy_diag --sim      # Simulation ohne Gerät
python -m daisy_diag --port COM5
```

Optionen: `--sim`, `--port COMx`, `--selftest SEKUNDEN` (beendet sich nach N Sekunden,
Exitcode 0 nur bei empfangenen Gerätedaten), `--screenshot DATEI`.

## 5. Bedienung

### Verbindung

* **Hardware (USB)** sucht automatisch jede Sekunde nach COM-Ports mit VID `0483` /
  PID `5740` und prüft sie mit einem `HELLO`-Handshake. Andere STM32-Geräte mit
  derselben Kennung werden nach 1 s ohne passende Antwort übersprungen.
* Ein fester Port kann im Auswahlfeld gewählt werden (★ = mögliche Daisy-Kennung).
* Kopfzeile: Umschalter **Hardware (USB)** / **Simulation**, Statuspunkt mit Text und
  **Trennen**/**Verbinden**.
* Status: **Verbunden** (grüner Punkt), **Verbinde …**, **Getrennt** (grau),
  **Verbindungsfehler** (rot, z. B. 1,5 s keine Daten), **Protokoll inkompatibel** (gelb).
* Angezeigt werden Firmware- und Protokollversion, Bootloader laut libDaisy,
  Zustandsrate, Rahmenfehler, verlorene Rahmen, PING-Antwortzeit, die gemessene
  Steuer-Update-Rate der Firmware (Soll 1000 Hz) und die Anzahl Wiederverbindungen.
* **Trennen** beendet die Verbindung und pausiert die automatische Suche;
  **Verbinden** setzt sie fort. Nach USB-Abbruch verbindet die Anwendung selbst neu.

### Board-Ansicht

Die Grafik entspricht der Anordnung auf dem Desktop Dev Kit:

* **S1–S16:** zwei Reihen à acht Taster. Gedrückt: Kappe eingedrückt und dunkel,
  weißer Rahmen, Beschriftung hell.
* **D1–D16:** rote LEDs je oberhalb des Tasters; leuchtend rot = **Sollzustand EIN**,
  dunkelrot = AUS.
* **VR1–VR8:** schwarzer Drehknopf mit weißer Marke auf gedruckter Skala, Wert in Prozent
  im Feld darunter; graue Dreiecke an der Skala = seit Verbindungsbeginn gesehener
  Minimal-/Maximalwert.
* **SW17** (2 Positionen) und **SW18** (3 Positionen): Hebel und Buchstabe U/C/D.
* **microSD:** grau „Keine Karte“, weiß „Karte erkannt“, grün „Dateisystem lesbar“,
  rot „Fehler“.
* **Audioeingänge:** grüner Ring und „Stecker erkannt“, wenn ein Stecker steckt.
* Grau markierte „n. i.“-Bereiche sind nicht implementiert. Tooltips erklären jedes Element.

### LED-Diagnose

Modi: **Alle aus**, **Alle ein**, **Einzeln** (Kästchen D1–D16 oder LED in der
Board-Ansicht anklicken), **Lauflicht** (Schrittweite einstellbar) und
**Taster → LED**. Helligkeit 0–100 %.

> Die LEDs haben keine elektrische Rückmeldung. Die Anwendung zeigt den von der
> Firmware gesetzten Sollzustand. Ob eine LED leuchtet, muss am Board angesehen werden.

### microSD

„Lesetest starten (nur lesen)“ hängt das Dateisystem ein, zählt die Einträge im
Wurzelverzeichnis und hängt es wieder aus. Keine Schreibzugriffe, keine Formatierung.
Ergebnis: Dateisystemtyp, Größe, Anzahl Einträge oder FatFs-Fehlercode.

### Weitere Panels

Kippschalter und Steckererkennung als Text, Poti-Tabelle (Prozent, ADC-Rohwert,
Min/Max, zurücksetzbar), Druckzähler S1–S16, Liste der vorbereiteten, **nicht
implementierten** Erweiterungen und das Ereignisprotokoll.

### Simulation

Umschalter **Simulation** oder Start mit `--sim`. Ein oranger Balken kennzeichnet
alle Werte als simuliert. In der Board-Ansicht lassen sich Taster drücken, Potis
ziehen oder mit dem Mausrad drehen, Kippschalter (oben/Mitte/unten anklicken),
microSD und Audioeingänge umschalten. Zusätzlich: USB-Kabel ziehen/einstecken,
hängende Firmware, fehlerhafter Rahmen, Demo-Animation, Karte mit/ohne Dateisystem.
Die Simulation spricht dasselbe Protokoll wie die Firmware.

## 6. Fehlerbehebung

| Symptom | Ursache / Abhilfe |
| --- | --- |
| „Kein Daisy (VID 0483 / PID 5740) gefunden“ | Kabel an J7 (nicht am Seed3), Datenkabel verwenden, Firmware geflasht? Gerätemanager → „Anschlüsse (COM & LPT)“ prüfen. |
| Port erscheint, aber „keine DDP-Antwort auf HELLO“ | Andere Firmware läuft (z. B. Toy Piano oder Bootloader). Diagnosefirmware flashen, RESET drücken. |
| „Port lässt sich nicht öffnen“ | Port ist von einem anderen Programm (Terminal, Web Programmer) belegt. |
| „Protokoll inkompatibel“ | Firmware- und Anwendungsversion passen nicht zusammen. |
| Verbindungsfehler nach 1,5 s | Firmware hängt oder USB gestört; die Anwendung verbindet automatisch neu. |
| Steuer-Update-Rate deutlich ≠ 1000 Hz | Audio/Codec läuft nicht wie erwartet; bitte melden. |

# Daisy Diagnostic Protocol (DDP) – Version 1

Bidirektionales Textprotokoll zwischen der Diagnosefirmware auf dem Seed3 und der
Windows-Anwendung. Transport: **USB CDC (virtueller COM-Port)** über den externen
USB-C-Anschluss **J7** des Desktop Dev Kits (OTG-HS-Peripherie im FS-Modus,
D29/D30). Baudrate und Handshake-Leitungen sind bei USB CDC bedeutungslos.

Die Referenzimplementierungen sind
[`ddp.h`](ddp.h)/[`ddp.cpp`](ddp.cpp) (Firmware, C++17, ohne libDaisy) und
[`windows/daisy_diag/protocol.py`](../windows/daisy_diag/protocol.py) (Host).
[`vectors.txt`](vectors.txt) enthält gemeinsame Prüfvektoren für beide Seiten.

## Warum nicht der libDaisy-Logger?

`daisy::Logger<LOGGER_EXTERNAL>` (libDaisy `f715e48`) kann nur **senden**
(`Print`, `PrintLine`). Er besitzt keine Empfangs-API, und `TransmitSync()` wartet
nach den ersten Paketen blockierend auf den Host. Die Firmware verwendet deshalb
direkt `daisy::UsbHandle` mit `Init(FS_EXTERNAL)`, `SetReceiveCallback(…, FS_EXTERNAL)`
und dem nicht blockierenden `TransmitExternal()`. Das ist dieselbe CDC-Klasse,
die auch der Logger verwendet; eine eigene CDC-Implementierung ist nicht nötig.

USB-Kennung (libDaisy-Standard): VID `0x0483`, PID `0x5740`, Produkt
„Daisy Seed External“. Diese Kennung teilen viele STM32-Geräte. Die Windows-
Anwendung betrachtet einen Port deshalb erst nach erfolgreichem `HELLO`-Handshake
als Diagnosegerät.

## Rahmenformat

```
$<body>*<CRC>\n
```

* `body`: druckbares ASCII `0x20..0x7E` ohne `$` und `*`, höchstens **400 Byte**.
* `CRC`: CRC-16/CCITT-FALSE über die Bytes von `body`
  (Polynom `0x1021`, Startwert `0xFFFF`, keine Spiegelung, kein XOR am Ende),
  vier hexadezimale Großbuchstaben. Prüfwert: `CRC("123456789") = 29B1`.
* Ein `\r` vor `\n` wird toleriert. Empfänger akzeptieren auch Kleinbuchstaben im CRC.

Empfängerregeln (Resynchronisation bei unvollständigen Daten):

1. Bytes außerhalb eines Rahmens werden verworfen, bis ein `$` erscheint.
2. Ein `$` innerhalb eines Rahmens verwirft den angefangenen Rahmen und beginnt neu.
3. Ungültige Zeichen, fehlendes `*`, ungültige oder falsche CRC, oder ein `body`
   über 400 Byte verwerfen den Rahmen. Die Fehler werden gezählt.

Damit sind abgeschnittene Rahmen nach einem USB-Abbruch, gepufferte Altdaten beim
erneuten Öffnen des Ports und Störbytes unkritisch.

## Nachrichtenaufbau

```
TYPE key=value key=value …
```

`TYPE` besteht aus Großbuchstaben. Schlüssel sind klein geschrieben, Werte enthalten
weder Leerzeichen noch `=`. Listen werden mit Komma getrennt. **Unbekannte Schlüssel
werden ignoriert**, unbekannte Nachrichtentypen vom Host ebenfalls. Die Firmware
beantwortet unbekannte Befehle mit `ERR`. Neue optionale Felder erfordern deshalb
keine neue Protokollversion; inkompatible Änderungen erhöhen `proto`.

## Verbindungsablauf

```
Host                                    Seed3
 | -- $HELLO proto=1*…  -------------->  |   Streaming einschalten, Host-Timer starten
 | <- $HELLO proto=1 fw=… ------------   |
 | <- $ST … (20–100 Hz) --------------   |
 | <- $SYS … (1 Hz) ------------------   |
 | -- $PING n=17*… (2 Hz) ------------>  |   Host-Timer neu starten
 | <- $PONG n=17*… -------------------   |
 | -- $LED m=CHASE*… ----------------->  |
 | <- $ACK c=LED m=CHASE …------------   |
```

* Die Firmware sendet Zustandsdaten nur, solange ein Host aktiv ist: nach `HELLO`
  und solange innerhalb von **3 s** ein gültiger Rahmen eintrifft. Danach (oder nach
  `BYE`) schweigt sie bis zum nächsten `HELLO`. Ein zufällig geöffnetes
  Terminal erhält so keinen ungefragten Datenstrom.
* Der Host sendet zweimal pro Sekunde `PING` und gilt als getrennt, wenn **1,5 s**
  lang kein gültiger Rahmen eintrifft oder der COM-Port verschwindet. Danach sucht
  er jede Sekunde erneut nach dem Gerät und wiederholt den Handshake.
* Das Desktop Dev Kit wird über J7 versorgt. Ein Ziehen des USB-Kabels ist daher
  zugleich ein Neustart der Firmware; die Wiederverbindung beginnt mit `HELLO`.
* Alle USB-Sendungen der Firmware sind nicht blockierend. Ist der CDC-Sendepuffer
  belegt, wartet der nächste Rahmen in einem zweiten Puffer; läuft auch dieser voll,
  wird der neue Rahmen verworfen und in `SYS txdrop` gezählt.

## Host → Firmware

| Befehl | Felder | Antwort |
| --- | --- | --- |
| `HELLO` | `proto=1` | `HELLO …`, danach Streaming |
| `PING` | `n=<u32>` | `PONG n=<u32>` |
| `GET` | – | sofort `ST` und `SYS` |
| `RATE` | `hz=10..100` | `ACK c=RATE hz=<n>` |
| `LED` | `m=OFF\|ON\|MASK\|CHASE\|FOLLOW`, optional `mask=<hex4>`, `br=0..100`, `ms=20..2000` | `ACK c=LED m=… mask=… br=… ms=…` |
| `SDTEST` | – | `SD …` (nur lesender Test) |
| `BYE` | – | `ACK c=BYE`, Streaming aus |

Fehler: `ERR c=<Befehl> e=<Code>` mit `UNKNOWN` (unbekannter Befehl),
`ARG` (fehlendes/ungültiges Feld) oder `PROTO` (nicht unterstützte Protokollversion).
`ERR` wird nur für vollständige Rahmen mit gültiger CRC erzeugt.

LED-Modi:

| Modus | Bedeutung |
| --- | --- |
| `OFF` | alle 16 LEDs aus |
| `ON` | alle 16 LEDs ein |
| `MASK` | einzelne LEDs: Bit 0 = D1 … Bit 15 = D16 (`mask=8001` → D1 und D16) |
| `CHASE` | Lauflicht D1 → D16, Schrittweite `ms` (Standard 120 ms) |
| `FOLLOW` | LED leuchtet, solange der zugehörige Taster gedrückt ist (Standard nach dem Start) |

`br` setzt die PWM-Helligkeit in Prozent (Standard 100). Die LEDs besitzen
**keine elektrische Rückmeldung**: `l` in `ST` ist nur der von der Firmware
gesetzte Sollzustand, kein Nachweis, dass eine LED tatsächlich leuchtet.

## Firmware → Host

### `HELLO`

```
HELLO proto=1 fw=0.1.0 app=DaisyDiagnostic dev=seed3-desktop boot=BOOT_SRAM bl=v6_1 libdaisy=f715e48 caps=btn,pot,potraw,sw17,sw18,sd,sdread,jack,led
```

`bl` ist die von libDaisy erkannte Bootloaderversion (`v6_1` steht für „v6.1 oder neuer“,
`v6_0`, `LT_v6_0`, `NONE`).

### `ST` – vollständiger Zustand

```
ST n=1234 t=56789 b=0001 pc=01000000000000000000000000000000 p=0,10000,5000,0,0,0,0,0 r=0,65535,32768,0,0,0,0,0 s17=U s18=C sd=0 jl=0 jr=1 lm=FOLLOW l=0001 br=100
```

| Feld | Bedeutung |
| --- | --- |
| `n` | Laufende Nummer (u32); Lücken zeigen verlorene Rahmen |
| `t` | Firmware-Laufzeit in ms |
| `b` | entprellte Taster als Bitmaske, Bit 0 = S1 … Bit 15 = S16 |
| `pc` | 16 Druckzähler (je 2 Hex-Ziffern, modulo 256, S1 zuerst) – auch sehr kurze Drücke zwischen zwei Rahmen bleiben sichtbar |
| `p` | VR1…VR8 normiert, `0..10000` entspricht `0.0000..1.0000` |
| `r` | VR1…VR8 ADC-Rohwerte `0..65535` (Mux-Kanal 0…7) |
| `s17` | SW17: `U` oder `D` (libDaisy `tog_sw17.Pressed()` = `U`) |
| `s18` | SW18: `U`, `C` oder `D` (libDaisy `Switch3`: `POS_UP`, `POS_CENTER`, `POS_DOWN`) |
| `sd` | microSD-Kartenerkennung, `1` = Karte erkannt |
| `jl`, `jr` | Audioeingang links/rechts gesteckt, `1` = Stecker erkannt |
| `lm` | aktiver LED-Modus |
| `l` | gesetzter LED-Sollzustand als Bitmaske (Bit 0 = D1) |
| `br` | LED-Helligkeit in Prozent |

Rate: periodisch mit `RATE` (Standard **50 Hz**), zusätzlich sofort bei einer
Änderung eines digitalen Eingangs, jedoch höchstens alle 10 ms.

### `SYS` – Diagnose der Firmware (1 Hz)

```
SYS up=123 cbhz=1000 txok=6150 txbusy=3 txdrop=0 rxok=250 rxbad=0 host=1 rate=50
```

`cbhz` ist die gemessene Anzahl Steuer-Updates pro Sekunde (Soll 1000; Audiocallback
48 kHz / 48 Samples). `rxbad` zählt verworfene Empfangsrahmen.

### `SD` – Ergebnis von `SDTEST`

```
SD st=MOUNTED res=0 fs=FAT32 mb=30436 ent=12
SD st=NONE res=-1
SD st=ERROR res=13
```

| `st` | Bedeutung |
| --- | --- |
| `NONE` | keine Karte erkannt, kein Zugriff versucht |
| `MOUNTED` | Dateisystem eingebunden und Wurzelverzeichnis gelesen (`ent` Einträge, max. 1000) |
| `ERROR` | Zugriff fehlgeschlagen; `res` ist der FatFs-`FRESULT` (z. B. `3` = `FR_NOT_READY`, `13` = `FR_NO_FILESYSTEM`) |

Der Test ruft ausschließlich `f_mount`, `f_opendir`, `f_readdir`, `f_closedir` und
das Aushängen auf. Er schreibt, formatiert oder verändert nichts. Der Build prüft,
dass keine schreibenden FatFs-Funktionen (`f_write`, `f_mkfs`, `f_unlink`, …) in die
Firmware gelinkt werden. Während des Tests (typisch < 0,5 s) pausiert der Datenstrom;
Tastendrücke gehen dank `pc` nicht verloren.

### `ACK`, `ERR`, `PONG`

Siehe Tabelle „Host → Firmware“.

## Versionierung

`proto=1` ist diese Spezifikation. Ein Host, der eine andere Hauptversion empfängt,
zeigt „Protokoll inkompatibel“ und sendet keine Steuerbefehle.

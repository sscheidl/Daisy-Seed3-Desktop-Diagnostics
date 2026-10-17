# Herkunft des eigenstaendigen Repositories

Die Diagnose-Suite wurde am 17.10.2026 aus dem privaten Repository
[sscheidl/Daisy-Seed](https://github.com/sscheidl/Daisy-Seed), Commit
`e2480bc33a5cb01f78c5ff5990c780698a516480`, ausgegliedert.
Die auf `diagnostics/` beschraenkte Git-Historie ist erhalten; die Commit-IDs
aendern sich durch das Verschieben dieses Ordners an die Repository-Wurzel.
Sie enthaelt Erstimplementierung, Review-Korrekturen und GUI-Redesign.
Historische PR-Nummern in den Berichten beziehen sich auf das Ursprungsrepo.

Mit uebernommen wurden `scripts/install-toolchain.sh` und
`scripts/check-firmware.py` sowie das festgelegte libDaisy-Submodul.
DaisySP und der Toy-Piano-Code werden nicht benoetigt.
Buildpfade, CI und Dokumentationslinks sind auf die neue Wurzel angepasst.
Quellcode und Funktion von Firmware, Hostprotokoll und GUI bleiben erhalten.

Die uebernommenen Testberichte dokumentieren Pruefungen vor der Ausgliederung.
Der eigenstaendige Stand wird zusaetzlich durch seinen eigenen GitHub-Workflow
gebaut und getestet. Nachtrag 17.10.2026: Der CI-Build von `8c0522d` wurde geflasht,
Hardwaretest H1–H10 bestanden (H11 offen), Vorabversion
[v0.1.0](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/releases/tag/v0.1.0) angelegt.

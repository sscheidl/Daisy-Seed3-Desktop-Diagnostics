# Eigenstaendig bauen und testen

Alle Befehle gelten vom Repository-Wurzelverzeichnis aus. Benutzung und
Firmwarekonfiguration: [FIRMWARE.md](FIRMWARE.md). Es besteht keine Abhaengigkeit
zum Toy-Piano-Repository. Einziges direktes Submodul ist libDaisy
`f715e4875b2d28445d0c11a0a17f064a248f69d0`.

```bash
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4
# Windows / Git Bash:
bash scripts/install-toolchain-windows.sh
# Linux x86_64 stattdessen:
# bash scripts/install-toolchain.sh
bash scripts/build-firmware.sh
```

Ergebnis: `firmware/build/DaisyDiagnostic.bin` und `.elf`; der Build prueft
BOOT_SRAM-Vektoren und die Abwesenheit schreibender SD-Pfade.

```bash
python -m pip install -r windows/requirements.txt
python -m pytest tests/python -v
make -C firmware test test-sanitize
# Windows mit MSVC alternativ:
# scripts\run-host-tests-msvc.cmd
```

Windows-EXE: `windows\build_exe.cmd`, Ergebnis `windows/dist/DaisyDiagnostic.exe`.
Start ohne Hardware: `DaisyDiagnostic.exe --sim --selftest 5`.
GitHub CI fuehrt diese Softwaretests aus und stellt BIN/ELF und EXE mit
Pruefsummen als getrennte Actions-Artefakte bereit. Keine dieser Pruefungen ersetzt
Hardwaretests. Flashen bleibt ein manueller Schritt: [FLASHING.md](FLASHING.md).

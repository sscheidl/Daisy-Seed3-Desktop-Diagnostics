@echo off
rem Builds dist\DaisyDiagnostic.exe (single file, no console) with PyInstaller.
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DaisyDiagnostic ^
    --workpath build\pyinstaller --distpath dist --specpath build ^
    --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtMultimedia --exclude-module PySide6.Qt3DCore ^
    DaisyDiagnostic.py || exit /b 1
echo Fertig: %CD%\dist\DaisyDiagnostic.exe

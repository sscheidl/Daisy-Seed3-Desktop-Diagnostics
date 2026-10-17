@echo off
rem Starts the diagnostic GUI from source. Add --sim for the simulation mode.
cd /d "%~dp0"
python -m daisy_diag %*

@echo off
rem Builds and runs the firmware logic host tests with MSVC (Visual Studio Build Tools).
setlocal
set "DIAG=%~dp0.."
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if not defined VS (echo Visual Studio C++ Build Tools nicht gefunden & exit /b 2)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 2
if not exist "%DIAG%\firmware\build\host-msvc" mkdir "%DIAG%\firmware\build\host-msvc"
pushd "%DIAG%\firmware\build\host-msvc"
cl /nologo /std:c++17 /W4 /WX /EHsc /I"%DIAG%\protocol" /I"%DIAG%\firmware\src" "%DIAG%\tests\firmware\test_diag_core.cpp" "%DIAG%\firmware\src\diag_core.cpp" "%DIAG%\protocol\ddp.cpp" /Fe:test_diag_core.exe || (popd & exit /b 1)
"%CD%\test_diag_core.exe" "%DIAG%\protocol\vectors.txt"
set RC=%ERRORLEVEL%
popd
exit /b %RC%

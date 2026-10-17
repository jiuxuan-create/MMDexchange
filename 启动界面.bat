@echo off
rem  ASCII only on purpose: cmd.exe mis-parses multi-byte (Chinese) text in .bat files.
rem  Chinese guidance lives in README.md and in the Python-side messages.
chcp 65001 >nul
cd /d "%~dp0"
title VRM to PMX
setlocal

set "PY="
call :try "python3.exe"
if not defined PY call :try "python.exe"
if not defined PY call :try "py.exe"
if not defined PY call :try "python3"
if not defined PY call :try "python"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :try "C:\Python313\python.exe"
if not defined PY call :try "C:\Python312\python.exe"

if not defined PY (
    echo.
    echo   [x] No Python with a working Tk was found.
    echo.
    echo   The conversion core needs only the standard library ^(any Python 3.8+^),
    echo   but the GUI needs a Python that ships a complete Tcl/Tk runtime.
    echo.
    echo   How to fix ^(pick one^):
    echo     1. Install a standard Python from https://www.python.org/downloads/
    echo        and keep "tcl/tk and IDLE" checked during setup.
    echo     2. Skip the GUI and use the command line:
    echo        python -m vrm2pmx "model.vrm" -o "output_dir"
    echo.
    echo   See README.md for details ^(Chinese^).
    echo.
    pause
    exit /b 1
)

echo   Interpreter: %PY%
start "" "%PY%" "vrm2pmx-gui.py" %*
exit /b 0

:try
if defined PY exit /b 0
"%~1" "vrm2pmx\probe_tk.py" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0

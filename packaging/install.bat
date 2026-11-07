@echo off
rem Jarvis one-click installer. Double-click this file.
setlocal
cd /d "%~dp0.."
echo === Jarvis installer ===
echo Folder: %CD%
echo.

rem 1. Find Python 3.11 or newer
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo ERROR: Python 3.11 or newer was not found.
    echo Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH". Then run this file again.
    goto :fail
)
echo [1/4] Using Python:
%PY% --version

rem 2. Make a private Python environment in .venv
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating .venv ...
    %PY% -m venv .venv || goto :fail
) else (
    echo [2/4] .venv already exists.
)
set "VPY=.venv\Scripts\python.exe"

rem 3. Install packages
echo [3/4] Installing packages (takes a few minutes the first time) ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" packaging\install_packages.py || goto :fail

rem 4. Download the speech model (~40 MB, one time)
echo [4/4] Getting the speech model ...
"%VPY%" -c "from jarvis import stt; stt.get_model(); print('Speech model ready.')" || goto :fail

echo.
choice /c YN /m "Start Jarvis automatically when you log in"
if errorlevel 2 (
    "%VPY%" packaging\autostart.py uninstall
) else (
    "%VPY%" packaging\autostart.py install || goto :fail
)

echo.
echo Done! Test by typing:   .venv\Scripts\python main.py --text
echo.
choice /c YN /m "Start Jarvis (voice) now"
if errorlevel 2 goto :end
start "" ".venv\Scripts\pythonw.exe" "packaging\start_jarvis.pyw"
echo Jarvis is running in the background. Say "Jarvis".
goto :end

:fail
echo.
echo Install FAILED. Read the message above.
pause
exit /b 1

:end
pause
exit /b 0

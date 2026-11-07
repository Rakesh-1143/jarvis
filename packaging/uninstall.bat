@echo off
rem Turns off Jarvis auto-start and stops a running Jarvis. Your files stay.
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" packaging\autostart.py uninstall
) else (
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Jarvis /f >nul 2>nul
    echo Auto-start is OFF.
)
rem Stop Jarvis if it is running in the background
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*start_jarvis.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Jarvis stopped. To remove it fully, delete this folder.
pause

@echo off
rem Hub: start without console window
rem Python version used by Hub. Some packages (e.g. faster-whisper) are not available for 3.15 yet.
rem Change this one line to switch. If this version is not installed, the newest Python is used.
set HUB_PY=3.14
cd /d "%~dp0"
py -%HUB_PY% -c "" >nul 2>nul && (start "" pyw -%HUB_PY% hub.py & exit /b)
where pyw >nul 2>nul && (start "" pyw -3 hub.py) || (start "" pythonw hub.py)

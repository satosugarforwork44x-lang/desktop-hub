@echo off
rem Hub: start without console window
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 hub.py) || (start "" pythonw hub.py)

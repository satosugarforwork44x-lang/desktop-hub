@echo off
rem Hub: start with console (shows errors)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 hub.py) || (python hub.py)
pause

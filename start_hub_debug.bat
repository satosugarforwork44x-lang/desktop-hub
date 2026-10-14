@echo off
rem Hub: start with console (shows errors)
rem Keep HUB_PY the same as in start_hub.bat
set HUB_PY=3.14
cd /d "%~dp0"
py -%HUB_PY% -c "" >nul 2>nul && (py -%HUB_PY% hub.py & pause & exit /b)
echo Python %HUB_PY% was not found. Using the default Python instead.
where py >nul 2>nul && (py -3 hub.py) || (python hub.py)
pause

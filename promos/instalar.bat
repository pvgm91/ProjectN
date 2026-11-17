@echo off
rem Instala o Playwright (uma vez so). O robo usa o Edge ja instalado no Windows.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m pip install --upgrade playwright cryptography telethon) else (python -m pip install --upgrade playwright cryptography telethon)
pause

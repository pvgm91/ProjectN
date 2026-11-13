@echo off
rem Uso: rodar.bat coletar | vigiar | ofertas | adicionar | status | demo
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m robo %*) else (python -m robo %*)

@echo off
rem Coleta agendada: grava o resultado em dados\log.txt
cd /d "%~dp0"
echo. >> dados\log.txt
echo ==== %date% %time% ==== >> dados\log.txt
call rodar.bat coletar >> dados\log.txt 2>&1

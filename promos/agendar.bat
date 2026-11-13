@echo off
rem Agenda a coleta para rodar de hora em hora no Agendador de Tarefas do Windows.
schtasks /Create /F /SC HOURLY /MO 1 /TN "ProjectN Promos" /TR "\"%~dp0coletar_agendado.bat\""
if %errorlevel%==0 (echo Agendado: a coleta roda de hora em hora enquanto voce estiver logado no Windows. O resultado fica em dados\log.txt) else (echo Nao foi possivel agendar.)
pause

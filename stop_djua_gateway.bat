@echo off
setlocal
cd /d "%~dp0"

if not exist "data" mkdir "data"
type nul > "data\gateway.stop"

echo Demande d'arret envoyee a DJUA_SMS.
echo La gateway terminera proprement sa boucle en cours.
timeout /t 2 /nobreak >nul
exit /b 0

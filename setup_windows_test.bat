@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==========================================
echo       DJUA_SMS - INSTALLATION TEST
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creation de l'environnement Python...
    where py >nul 2>nul
    if %ERRORLEVEL%==0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto :fail
) else (
    echo [1/5] Environnement Python deja present.
)

echo [2/5] Installation/verifications des dependances...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist "config" mkdir "config"
if not exist "data" mkdir "data"
if not exist "logs" mkdir "logs"

if not exist "config\gateway.env" (
    echo [3/5] Creation de la configuration locale...
    copy /Y "config\gateway.env.example" "config\gateway.env" >nul
    echo.
    echo Le fichier de configuration va s'ouvrir.
    echo COM16 et le mode D2 development sont deja proposes.
    echo Renseignez surtout MQTT_HOST et les identifiants MQTT si necessaires.
    echo Enregistrez puis FERMEZ le Bloc-notes pour continuer.
    echo.
    start /wait notepad.exe "config\gateway.env"
) else (
    echo [3/5] Configuration locale deja presente.
)

echo [4/5] Verification de la configuration...
set "PYTHONPATH=%~dp0src;%~dp0"
".venv\Scripts\python.exe" "scripts\run_gateway.py" --config "config\gateway.env" --check-config
if errorlevel 1 (
    echo.
    echo Configuration incomplete ou invalide.
    echo Le fichier va etre rouvert pour correction.
    start /wait notepad.exe "config\gateway.env"
    ".venv\Scripts\python.exe" "scripts\run_gateway.py" --config "config\gateway.env" --check-config
    if errorlevel 1 goto :config_fail
)

echo [5/5] Installation de la tache Windows...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\install_windows_test_task.ps1" -Root "%~dp0"
if errorlevel 1 goto :fail

echo.
echo DJUA_SMS est configure pour demarrer automatiquement a l'ouverture de session.
echo La gateway est egalement lancee maintenant en arriere-plan.
echo Logs : %~dp0logs\gateway.log
echo.
pause
exit /b 0

:config_fail
echo.
echo ECHEC: la configuration reste invalide.
echo Aucune tache Windows n'a ete installee.
pause
exit /b 2

:fail
echo.
echo ECHEC de l'installation automatique.
echo Consultez le message ci-dessus.
pause
exit /b 1

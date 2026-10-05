@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "CONFIG=%~dp0config\gateway.env"

if not exist "%PYTHON%" (
    echo DJUA_SMS: .venv introuvable. Lancez setup_windows_test.bat une fois.
    exit /b 10
)

if not exist "%CONFIG%" (
    echo DJUA_SMS: config\gateway.env introuvable. Lancez setup_windows_test.bat une fois.
    exit /b 11
)

set "PYTHONPATH=%~dp0src;%~dp0"

:restart
"%PYTHON%" "%~dp0scripts\run_gateway.py" --config "%CONFIG%"
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" exit /b 0

timeout /t 10 /nobreak >nul
goto restart

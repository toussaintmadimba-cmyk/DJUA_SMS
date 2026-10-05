@echo off
setlocal
cd /d "%~dp0"

call "stop_djua_gateway.bat"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$name='DJUA SMS Gateway Test'; if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host 'TASK_REMOVED' } else { Write-Host 'TASK_NOT_FOUND' }"

echo.
echo Le demarrage automatique DJUA_SMS est desactive.
pause

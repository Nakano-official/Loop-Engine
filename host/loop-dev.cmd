@echo off
setlocal
REM ---------------------------------------------------------------
REM  loop-dev launcher
REM    1. start the WSL2 distro (stopped when idle - by design)
REM    2. wait until sshd is reachable on 127.0.0.1:2222
REM    3. open VS Code via Remote-SSH
REM  Usage:  loop-dev [remote-path]      default: /home/maint
REM ---------------------------------------------------------------

set "DISTRO=Ubuntu-24.04"
set "SSHHOST=loop-dev"
set "PORT=2222"
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=/home/maint"

echo [1/3] Starting WSL distro %DISTRO% ...
wsl.exe -d %DISTRO% -u root --exec /usr/bin/true
if errorlevel 1 goto fail_start

echo [2/3] Waiting for sshd on 127.0.0.1:%PORT% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 40;$i++){ if(Test-NetConnection -ComputerName 127.0.0.1 -Port %PORT% -InformationLevel Quiet -WarningAction SilentlyContinue){exit 0}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 goto fail_sshd

echo [3/3] Launching VS Code -^> %SSHHOST%:%TARGET%
call code --remote ssh-remote+%SSHHOST% "%TARGET%"
if errorlevel 1 goto fail_code

echo.
echo OK. Keep the VS Code window open - the VM stops shortly after you disconnect.
exit /b 0

:fail_start
echo        ERROR: failed to start distro %DISTRO%
goto fail

:fail_sshd
echo        ERROR: sshd did not come up within 20 seconds.
echo        Try:  wsl -d %DISTRO% -u root --exec systemctl status ssh
goto fail

:fail_code
echo        ERROR: could not launch 'code'. Is VS Code on PATH?
goto fail

:fail
echo.
echo FAILED.
pause
exit /b 1
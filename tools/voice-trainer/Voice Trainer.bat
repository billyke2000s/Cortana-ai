@echo off
setlocal
title Voice Trainer
cd /d "%~dp0"

echo ==================================================
echo   Voice Trainer - double-click launcher for Windows
echo ==================================================
echo.

rem --- Keep setup.sh and voice_trainer.py in the same folder as this file ---
if not exist "%~dp0setup.sh" goto :missing
if not exist "%~dp0voice_trainer.py" goto :missing

rem --- 1. Make sure the hidden Linux engine (WSL Ubuntu) exists ---
where wsl >nul 2>nul
if errorlevel 1 goto :nowsl
wsl -e bash -c "true" >nul 2>nul
if errorlevel 1 goto :installwsl

rem --- 2. Copy the trainer into Ubuntu (training is much faster on its own disk) ---
for /f "delims=" %%i in ('wsl -e wslpath -a "%~dp0."') do set "SRC=%%i"
wsl -e bash -c "mkdir -p ~/voice-trainer && cp '%SRC%/setup.sh' '%SRC%/voice_trainer.py' ~/voice-trainer/ && sed -i 's/\r$//' ~/voice-trainer/setup.sh ~/voice-trainer/voice_trainer.py"
if errorlevel 1 goto :copyfail

rem --- 3. First run only: install everything ---
wsl -e bash -c "test -x ~/voice-trainer/piper1-gpl/.venv/bin/python && test -f ~/voice-trainer/run.sh"
if errorlevel 1 goto :setup
goto :run

:setup
echo First-time setup. This downloads a few GB and takes about 10-30 minutes.
echo It will ask once for the Ubuntu password you created.
echo.
wsl -e bash -c "bash ~/voice-trainer/setup.sh"
if errorlevel 1 goto :setupfail

:run
echo.
echo Starting the trainer. Your browser will open in a few seconds.
echo KEEP THIS WINDOW OPEN while you use the trainer - closing it stops training.
echo.
start "" cmd /c "timeout /t 15 >nul & start http://localhost:7860"
wsl -e bash -c "bash ~/voice-trainer/run.sh"
echo.
echo The trainer has stopped.
pause
exit /b 0

:installwsl
echo The Linux engine Piper needs is not installed yet - installing it now.
echo Windows will ask for administrator permission.
echo.
powershell -NoProfile -Command "Start-Process wsl -ArgumentList '--install','-d','Ubuntu' -Verb RunAs -Wait"
echo.
echo Next steps:
echo   1. Restart your PC if Windows asks you to.
echo   2. Open "Ubuntu" from the Start menu once and pick a username and password.
echo   3. Double-click this file again.
pause
exit /b 0

:nowsl
echo This version of Windows does not have WSL.
echo You need Windows 10 version 2004 or newer, or Windows 11.
pause
exit /b 1

:missing
echo Put setup.sh and voice_trainer.py in the same folder as this file, then try again.
pause
exit /b 1

:copyfail
echo Could not copy the trainer files into Ubuntu. Make sure Ubuntu finished its first-time setup
echo by opening "Ubuntu" from the Start menu once, then try again.
pause
exit /b 1

:setupfail
echo Setup failed - scroll up to see the error, and send me the last few lines.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
title Local AI - Private Memory
set "LOCAL_AI_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%LOCAL_AI_PYTHON%" goto dependencies

echo Setting up Local AI for this computer...
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto try_python
py -3 -m venv "%~dp0.venv"
if errorlevel 1 goto failed
goto dependencies

:try_python
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv "%~dp0.venv"
if errorlevel 1 goto failed

:dependencies
"%LOCAL_AI_PYTHON%" -c "import sys; import prompt_toolkit, cryptography, keyring; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto launch
echo Installing terminal UI and encryption dependencies. Internet is needed for this first setup.
"%LOCAL_AI_PYTHON%" -m pip install -e ".[ui,crypto]"
if errorlevel 1 goto failed

:launch
if /i "%~1"=="--check" goto check
if not "%~1"=="" goto arguments
"%LOCAL_AI_PYTHON%" "%~dp0scripts\local-ai.py" shell
if errorlevel 1 goto failed
exit /b 0

:arguments
"%LOCAL_AI_PYTHON%" "%~dp0scripts\local-ai.py" %*
if errorlevel 1 goto failed
exit /b 0

:check
"%LOCAL_AI_PYTHON%" "%~dp0scripts\local-ai.py" --version
if errorlevel 1 goto failed
echo Ready. Double-click START.bat to open your memory workspace.
exit /b 0

:missing_python
echo Python 3.11 or newer is required. Install it from python.org with Add Python to PATH enabled.
echo Then double-click START.bat again.
pause
exit /b 1

:failed
echo.
echo Local AI could not finish. Read the message above before closing this window.
echo If setup failed, check your Python installation and internet connection, then retry.
pause
exit /b 1

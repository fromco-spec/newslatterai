@echo off
setlocal
rem Use UTF-8 code page for safer output (optional)
chcp 65001 >nul

echo ====================================
echo  Newsletter AI - starting...
echo ====================================

cd /d "%~dp0"

if not exist "venv" (
    echo Creating Python virtual environment...
    py -3.13 -m venv venv 2>nul
    if errorlevel 1 (
        rem Fallback to default python if py launcher unavailable
        python -m venv venv
    )
) else (
    rem venv already exists
)

set "VENV_PY=%~dp0venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo.
    echo [ERROR] venv python not found: %VENV_PY%
    echo Please install Python and try again.
    pause
    exit /b 1
)

echo Installing dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo Please check the error message above.
    pause
    exit /b 1
)

echo.
echo Open: http://localhost:8000
echo Login: admin / admin1234
echo Quit:  Press Ctrl+C
echo ====================================
echo.

start "" "http://localhost:8000"
"%VENV_PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start server.
    echo Please check the error message above.
    pause
    exit /b 1
)

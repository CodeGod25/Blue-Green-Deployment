@echo off
setlocal
title Blue-Green Deployment Platform - Startup
color 0A

REM Change to script directory
cd /d "%~dp0"

echo.
echo  =========================================
echo   Blue-Green Deployment Platform
echo  =========================================
echo.
echo  [0/3] Checking Docker Desktop...
tasklist /FI "IMAGENAME eq Docker.exe" 2>NUL | find /I /N "Docker.exe">NUL
if "%ERRORLEVEL%"=="1" (
    echo  Docker Desktop is NOT running. Launching it now...
    start "" "C:\ProgramData\Microsoft\Windows\Start Menu\Docker Desktop.lnk"
    echo  Waiting 30 seconds for initialization...
    timeout /t 30 /nobreak >nul
) else (
    echo  Docker Desktop is already running.
    echo  Waiting 10 seconds for docker daemon...
    timeout /t 10 /nobreak >nul
)

echo.
echo  [1/3] Stopping any old containers...
docker-compose down 2>nul

echo.
echo  [2/3] Starting all services...
docker-compose up -d
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ERROR: Docker failed to start services.
    echo  Please ensure Docker Desktop is running.
    echo.
    pause
    exit /b 1
)

echo.
echo  [3/3] Waiting for services to be healthy...
timeout /t 8 /nobreak >nul

echo.
echo  =========================================
echo   Platform is UP!
echo.
echo   Open your browser: http://localhost
echo  =========================================
echo.
timeout /t 3 /nobreak >nul
start "" "http://localhost"

echo.
echo  Press any key to stop the platform.
pause >nul

docker-compose down
echo  Goodbye!
endlocal

@echo off
setlocal enabledelayedexpansion
title Project Titanium - Blue-Green Deployment Platform
color 0A

REM Change to script directory
cd /d "%~dp0"

echo.
echo  ========================================
echo   Project Titanium - Blue-Green Platform
echo  ========================================
echo.

REM [0.5/3] Prepare configuration
if not exist ".env" (
    echo  Creating .env from template...
    copy .env.example .env >nul
)

REM Default values if not in .env
set PORT=80

REM Quick parser for .env (specifically for opening the browser later)
if exist ".env" (
    for /f "tokens=1,2 delims==" %%a in (.env) do (
        if "%%a"=="HTTP_PORT" set PORT=%%b
    )
)

echo  [0/3] Checking Docker...
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    color 0E
    echo.
    echo  ERROR: Docker is NOT running.
    echo  Please start Docker Desktop manually and wait for it to be ready.
    echo.
    echo  Once Docker is running, press any key to continue...
    pause >nul
    
    docker info >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        color 0C
        echo  Still cannot reach Docker. Exiting...
        pause
        exit /b 1
    )
)
echo  Docker is running.

echo.
echo  [1/3] Stopping any old containers...
docker compose down 2>nul

echo.
echo  [2/3] Building images and starting all services...
echo         (First run will take ~2 min to build the frontend - grab a coffee)
docker compose up -d --build
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ERROR: Docker failed to start services.
    echo  Common issue: Port !PORT! might be in use. 
    echo  Edit .env and change HTTP_PORT if needed.
    echo.
    pause
    exit /b 1
)

echo.
echo  [3/3] Waiting for services to be healthy...
timeout /t 10 /nobreak >nul

echo.
echo  ========================================
echo   Platform is UP!
echo.
echo   Open your browser: http://localhost:!PORT!
echo  ========================================
echo.
timeout /t 3 /nobreak >nul
if "!PORT!"=="80" (
    start "" "http://localhost"
) else (
    start "" "http://localhost:!PORT!"
)

echo.
echo  Press any key to stop the platform.
pause >nul

docker compose down
echo  Goodbye!
endlocal

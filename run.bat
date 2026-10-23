@echo off
REM ============================================================
REM  Hawkeyes Optical System - Windows development launcher
REM  Double-click to start. Everything is resolved from this folder.
REM
REM  Optional overrides (set before running):
REM    set PORT=8001    run on another port
REM    set RELOAD=1     auto-reload when Python files change
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Hawkeyes Dev Server

set "APP_PORT=8000"
if not "%PORT%"=="" set "APP_PORT=%PORT%"
set "APP_HOST=0.0.0.0"
set "VENV_PY=venv\Scripts\python.exe"
set "APP_URL=http://localhost:%APP_PORT%"

echo ================================================
echo    Hawkeyes Optical System - Starting...
echo ================================================
echo.

REM ---------- 1. Python / virtual environment ----------
if not exist "%VENV_PY%" (
    echo [*] Creating virtual environment...
    set "PYBOOT="
    where python >nul 2>&1
    if not errorlevel 1 set "PYBOOT=python"
    if not defined PYBOOT (
        where py >nul 2>&1
        if not errorlevel 1 set "PYBOOT=py -3"
    )
    if not defined PYBOOT (
        echo [X] Python was not found on PATH.
        echo     Install Python 3.10+ and select "Add python.exe to PATH".
        goto :fail
    )
    !PYBOOT! -m venv venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment at "%~dp0venv".
        goto :fail
    )
    echo [+] Virtual environment created.
)

REM ---------- 2. Dependencies ----------
if not exist "venv\.installed" (
    echo [*] Installing dependencies...
    "%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo [X] Dependency installation failed. Re-run:
        echo     "%VENV_PY%" -m pip install -r requirements.txt
        goto :fail
    )
    >"venv\.installed" echo installed
    echo [+] Dependencies installed.
) else (
    echo [+] Dependencies ready.
)

REM ---------- 3. Configuration ----------
if not exist ".env" (
    if not exist ".env.example" (
        echo [X] .env is missing and .env.example was not found.
        goto :fail
    )
    copy /y ".env.example" ".env" >nul
    echo [!] Created .env from .env.example - check the DB credentials in it.
)

REM ---------- 4. Port availability ----------
call :port_owner %APP_PORT% OWNER_PID OWNER_IMAGE
if defined OWNER_PID (
    set "OWNER_IS_OURS="
    if /i "!OWNER_IMAGE:~0,6!"=="python" set "OWNER_IS_OURS=1"
    if /i "!OWNER_IMAGE!"=="uvicorn.exe" set "OWNER_IS_OURS=1"

    if not defined OWNER_IS_OURS goto :port_conflict

    echo [*] Port %APP_PORT% is used by an earlier Hawkeyes server ^(PID !OWNER_PID!^).
    echo [*] Stopping it...
    taskkill /F /PID !OWNER_PID! >nul 2>&1
    call :wait_port_free %APP_PORT% 15
    call :port_owner %APP_PORT% OWNER_PID OWNER_IMAGE
    if defined OWNER_PID (
        echo [X] Port %APP_PORT% is still in use by PID !OWNER_PID! ^(!OWNER_IMAGE!^).
        goto :port_conflict
    )
    echo [+] Port %APP_PORT% is free.
)

REM ---------- 5. Database ----------
echo [*] Checking database connection...
"%VENV_PY%" scripts\init_db.py --seed
if errorlevel 1 (
    echo.
    echo [X] Database setup failed.
    echo     Make sure MySQL is running and DB_HOST / DB_PORT / DB_USER / DB_PASSWORD
    echo     in .env are correct.
    goto :fail
)

REM ---------- 6. Start the server ----------
set "RELOAD_FLAG="
if /i "%RELOAD%"=="1" set "RELOAD_FLAG=--reload"

echo.
echo ================================================
echo    Server: %APP_URL%
echo ================================================
if defined RELOAD_FLAG echo    Auto-reload: enabled
echo    Press Ctrl+C to stop the server.
echo.

"%VENV_PY%" -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% !RELOAD_FLAG!
if errorlevel 1 (
    echo.
    echo [X] The server stopped with exit code !errorlevel!.
    echo     If the log mentions 10048, port %APP_PORT% was taken by another program.
    if not "%HK_NO_PAUSE%"=="1" pause
)
goto :end


:port_conflict
echo.
echo [X] Port %APP_PORT% is already in use by PID !OWNER_PID! ^(!OWNER_IMAGE!^).
if defined OWNER_IS_OURS (
    echo     Hawkeyes tried to stop it, but the port is still held.
) else (
    echo     Hawkeyes did not stop it because it is not a Hawkeyes/uvicorn process.
)
echo     Stop it manually ^(taskkill /F /PID !OWNER_PID!^), or use another port:
echo         set PORT=8001
echo         run.bat
goto :fail


:port_owner
REM %1 = port, %2 = variable to receive the PID, %3 = variable to receive the image name
set "%~2="
set "%~3="
for /f "tokens=2,4,5" %%A in ('netstat -ano ^| findstr /C:":%1 "') do (
    if /i "%%B"=="LISTENING" if not defined %~2 set "%~2=%%C"
)
if defined %~2 (
    for /f "tokens=1 delims=," %%I in ('tasklist /FI "PID eq !%~2!" /NH /FO CSV 2^>nul') do (
        if not defined %~3 set "%~3=%%~I"
    )
    if not defined %~3 set "%~3=unknown"
)
exit /b 0


:wait_port_free
REM %1 = port, %2 = maximum seconds to wait
set /a _wf_tries=0
:wait_port_free_loop
call :port_owner %1 _wf_pid _wf_image
if not defined _wf_pid exit /b 0
set /a _wf_tries+=1
if !_wf_tries! GEQ %2 exit /b 1
ping -n 2 127.0.0.1 >nul
goto :wait_port_free_loop


:fail
echo.
echo Startup aborted.
if not "%HK_NO_PAUSE%"=="1" pause
endlocal
exit /b 1


:end
endlocal
exit /b 0

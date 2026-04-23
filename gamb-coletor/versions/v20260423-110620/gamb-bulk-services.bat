@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ACTION=%~1"
set "TARGET_HOST=%~2"
set "SERVICE_LIST=%~3"
set "LOG_FILE=%~4"
set "SCRIPT_NAME=%~nx0"

if "%ACTION%"=="" goto :USAGE
if "%TARGET_HOST%"=="" set "TARGET_HOST=localhost"
if "%SERVICE_LIST%"=="" goto :USAGE
if not exist "%SERVICE_LIST%" (
    echo GAMB_BULK_FATAL^|Arquivo de lista nao encontrado: %SERVICE_LIST%
    exit /b 2
)

if /I not "%ACTION%"=="start" if /I not "%ACTION%"=="stop" (
    echo GAMB_BULK_FATAL^|Acao invalida: %ACTION%
    exit /b 2
)

set "SC_TARGET="
set "TASKKILL_TARGET="
if /I not "%TARGET_HOST%"=="localhost" if not "%TARGET_HOST%"=="127.0.0.1" if not "%TARGET_HOST%"=="." (
    set "SC_TARGET=\\%TARGET_HOST%"
    set "TASKKILL_TARGET=/S %TARGET_HOST%"
)

call :LOG "Inicio lote %ACTION% em %TARGET_HOST% usando %SERVICE_LIST%"
set /a FAILURES=0
set /a TOTAL=0

for /f "usebackq delims=" %%S in ("%SERVICE_LIST%") do (
    set "SERVICE_NAME=%%~S"
    if not "!SERVICE_NAME!"=="" (
        set /a TOTAL+=1
        call :PROCESS_SERVICE "!SERVICE_NAME!"
        if errorlevel 1 set /a FAILURES+=1
    )
)

call :LOG "Fim lote %ACTION% em %TARGET_HOST%. Total=%TOTAL% Falhas=%FAILURES%"
if %FAILURES% GTR 0 exit /b 1
exit /b 0

:USAGE
echo Uso: %SCRIPT_NAME% start^|stop HOST SERVICE_LIST_FILE [LOG_FILE]
exit /b 2

:PROCESS_SERVICE
set "SERVICE_NAME=%~1"
call :GET_STATE "%SERVICE_NAME%"

if /I "%ACTION%"=="start" (
    if /I "!SERVICE_STATE!"=="RUNNING" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|SKIPPED_ALREADY_RUNNING^|RUNNING^|Servico ja estava em execucao
        call :LOG "%SERVICE_NAME% ja estava RUNNING"
        exit /b 0
    )
    sc.exe %SC_TARGET% start "%SERVICE_NAME%" >nul 2>&1
    call :WAIT_STATE "%SERVICE_NAME%" "RUNNING" 45
    if /I "!SERVICE_STATE!"=="RUNNING" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|SUCCESS^|RUNNING^|Servico iniciado
        call :LOG "%SERVICE_NAME% iniciado"
        exit /b 0
    )
    echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|ERROR^|!SERVICE_STATE!^|Start executado mas status final nao confirmou RUNNING
    call :LOG "%SERVICE_NAME% falhou ao iniciar. Status=!SERVICE_STATE!"
    exit /b 1
)

if /I "%ACTION%"=="stop" (
    if /I "!SERVICE_STATE!"=="STOPPED" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|SKIPPED_ALREADY_STOPPED^|STOPPED^|Servico ja estava parado
        call :LOG "%SERVICE_NAME% ja estava STOPPED"
        exit /b 0
    )
    call :GET_PID "%SERVICE_NAME%"
    set "KILLED_PID=!SERVICE_PID!"
    if "!SERVICE_PID!"=="" set "SERVICE_PID=0"
    if "!SERVICE_PID!"=="0" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|ERROR^|!SERVICE_STATE!^|Servico sem PID para taskkill
        call :LOG "%SERVICE_NAME% sem PID para taskkill. Status=!SERVICE_STATE!"
        exit /b 1
    )
    taskkill.exe %TASKKILL_TARGET% /PID !SERVICE_PID! /T /F >nul 2>&1
    call :WAIT_STATE "%SERVICE_NAME%" "STOPPED" 45
    if /I "!SERVICE_STATE!"=="STOPPED" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|SUCCESS^|STOPPED^|Servico parado via taskkill
        call :LOG "%SERVICE_NAME% parado via taskkill PID !KILLED_PID!"
        exit /b 0
    )
    call :GET_PID "%SERVICE_NAME%"
    if not "!SERVICE_PID!"=="!KILLED_PID!" if not "!SERVICE_PID!"=="0" (
        echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|SUCCESS^|RESTARTED^|PID original finalizado mas Windows reportou novo PID
        call :LOG "%SERVICE_NAME% trocou de PID apos taskkill. PID antigo=!KILLED_PID! novo=!SERVICE_PID!"
        exit /b 0
    )
    echo GAMB_BULK_RESULT^|%SERVICE_NAME%^|%ACTION%^|ERROR^|!SERVICE_STATE!^|Taskkill executado mas Windows nao confirmou STOPPED
    call :LOG "%SERVICE_NAME% taskkill sem STOPPED. Status=!SERVICE_STATE!"
    exit /b 1
)

exit /b 1

:GET_STATE
set "SERVICE_STATE=UNKNOWN"
for /f "tokens=4" %%A in ('sc.exe %SC_TARGET% query "%~1" ^| findstr /I "STATE"') do (
    set "SERVICE_STATE=%%A"
)
exit /b 0

:GET_PID
set "SERVICE_PID=0"
for /f "tokens=3" %%A in ('sc.exe %SC_TARGET% queryex "%~1" ^| findstr /I "PID"') do (
    set "SERVICE_PID=%%A"
)
exit /b 0

:WAIT_STATE
set "WAIT_SERVICE=%~1"
set "EXPECTED_STATE=%~2"
set /a WAIT_SECONDS=%~3
if "%WAIT_SECONDS%"=="" set /a WAIT_SECONDS=30
set /a COUNT=0
:WAIT_LOOP
call :GET_STATE "%WAIT_SERVICE%"
if /I "!SERVICE_STATE!"=="%EXPECTED_STATE%" exit /b 0
if !COUNT! GEQ %WAIT_SECONDS% exit /b 1
set /a COUNT+=1
timeout /t 1 /nobreak >nul
goto :WAIT_LOOP

:LOG
if not "%LOG_FILE%"=="" (
    echo [%date% %time%] %~1>>"%LOG_FILE%"
)
exit /b 0

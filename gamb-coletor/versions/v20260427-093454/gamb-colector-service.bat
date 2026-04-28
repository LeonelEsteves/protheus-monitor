@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM GAMB Coletor de Servico (Windows Server friendly)
REM Uso:
REM   gamb-colector-service.bat [FILTRO_NOME] [OUTPUT_DIR] [INTERVAL_SECONDS]
REM Exemplo:
REM   gamb-colector-service.bat TOTVS,TSS C:\gamb-coletor 5
REM ============================================================

set "COLLECTOR_VERSION=v20260427-093454"
set "FILTER_TERM=TOTVS,TSS"
set "OUTPUT_DIR=C:\gamb-coletor"
set "INTERVAL=5"
title GAMB Coletor - %COLLECTOR_VERSION%
mode con cols=100 lines=30 >nul 2>&1
set /a LOOP_COUNT=0
set "LAST_RESULT=Aguardando primeira coleta"
set "LAST_TOTAL_SERVICOS=0"
set "LAST_RUN_AT=-"

if not "%~1"=="" set "FILTER_TERM=%~1"
if not "%~2"=="" set "OUTPUT_DIR=%~2"
if not "%~3"=="" set "INTERVAL=%~3"

set "OUTPUT_FILE=%OUTPUT_DIR%\status-servico.json"
set "LOG_FILE=%OUTPUT_DIR%\coletor.log"
set "COLLECTOR_PS1=%~dp0gamb-colector-service.ps1"

if "%FILTER_TERM%"=="/?" goto :Usage
if "%FILTER_TERM%"=="-h" goto :Usage
if "%FILTER_TERM%"=="--help" goto :Usage

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%" 2>nul
if not exist "%OUTPUT_DIR%" (
    call :Log "ERRO: nao foi possivel criar %OUTPUT_DIR%"
    exit /b 1
)

set "SERVER_NAME=%COMPUTERNAME%"
call :ResolveServerIp
if not defined SERVER_IP set "SERVER_IP="

call :Log "--------------------------------------------------"
call :Log "GAMB COLETOR iniciado"
call :Log "Versao: %COLLECTOR_VERSION%"
call :Log "Servidor: %SERVER_NAME%"
call :Log "IP: %SERVER_IP%"
call :Log "Filtro servico: %FILTER_TERM%"
call :Log "JSON: %OUTPUT_FILE%"
call :Log "Intervalo: %INTERVAL%s"

:Loop
set /a LOOP_COUNT+=1
if not defined SERVER_IP call :ResolveServerIp
if not defined SERVER_IP set "SERVER_IP=127.0.0.1"

call :RedrawScreen
call :WriteJsonTotvs

timeout /t %INTERVAL% /nobreak >nul
goto :Loop

:Usage
cls
call :PrintHeader
echo.
echo  Versao: %COLLECTOR_VERSION%
echo.
echo  Uso: %~nx0 [FILTRO_NOME] [OUTPUT_DIR] [INTERVAL_SECONDS]
echo.
echo  Exemplo: %~nx0 TOTVS,TSS C:\gamb-coletor 5
echo.
echo  ----------------------------------------------------------------
exit /b 0

:ResolveServerIp
set "SERVER_IP="

REM Estrategia unificada: tenta NetTCPIP, DNS e WMI/CIM (compatibilidade ampla)
for /f "usebackq delims=" %%A in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$list=@(); if(Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue){$list += (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress })}; try{$list += ([System.Net.Dns]::GetHostAddresses($env:COMPUTERNAME) | Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } | ForEach-Object { $_.IPAddressToString })}catch{}; try{$list += (Get-CimInstance Win32_NetworkAdapterConfiguration -Filter \"IPEnabled=True\" -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress } | Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' })}catch{}; $ip=$list | Where-Object { $_ -and $_ -notmatch '^(127\.|169\.254\.)' } | Select-Object -First 1; if($ip){$ip}"`) do (
    set "SERVER_IP=%%A"
)
if defined SERVER_IP exit /b 0

REM Fallback 1: ipconfig (independente de locale PT/EN)
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4"') do (
    set "CANDIDATE_IP=%%A"
    set "CANDIDATE_IP=!CANDIDATE_IP: =!"
    for /f "tokens=1 delims=(" %%B in ("!CANDIDATE_IP!") do set "CANDIDATE_IP=%%B"
    if not "!CANDIDATE_IP!"=="" (
        if /I not "!CANDIDATE_IP:~0,4!"=="127." (
            if /I not "!CANDIDATE_IP:~0,8!"=="169.254." (
                set "SERVER_IP=!CANDIDATE_IP!"
                exit /b 0
            )
        )
    )
)

REM Fallback 2: ping no nome da maquina
for /f "tokens=2 delims=[]" %%A in ('ping -4 -n 1 %COMPUTERNAME% ^| findstr /R /C:"\["') do (
    set "SERVER_IP=%%A"
    exit /b 0
)
exit /b 0

:WriteJsonTotvs
set "TOTAL_SERVICOS=0"

if not exist "%COLLECTOR_PS1%" (
    set "LAST_RESULT=ERRO - script PowerShell nao encontrado"
    call :Log "ERRO: script PowerShell nao encontrado em %COLLECTOR_PS1%"
    exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%COLLECTOR_PS1%" -FilterTerm "%FILTER_TERM%" -OutputFile "%OUTPUT_FILE%" -ServerName "%SERVER_NAME%" -ServerIp "%SERVER_IP%" -CollectorVersion "%COLLECTOR_VERSION%"`) do (
    set "TOTAL_SERVICOS=%%A"
)

if errorlevel 1 (
    set "LAST_RESULT=ERRO - falha ao atualizar o JSON"
    call :Log "ERRO ao atualizar JSON"
) else (
    set "LAST_RESULT=SUCESSO - JSON atualizado"
    set "LAST_TOTAL_SERVICOS=%TOTAL_SERVICOS%"
    call :Log "JSON atualizado - Servicos filtrados: %TOTAL_SERVICOS%"
)
for /f "usebackq delims=" %%A in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"`) do (
    set "LAST_RUN_AT=%%A"
)
exit /b 0

:PrintHeader
echo.
echo  ======================================================================
echo                           GAMB COLETOR
echo.
echo                    Coleta operacional de servicos TOTVS/TSS
echo                    Atualizacao continua do status-servico.json
echo  ======================================================================
exit /b 0

:RedrawScreen
cls
call :PrintHeader
echo.
echo  STATUS ATUAL
echo  ----------------------------------------------------------------------
echo  Versao em execucao: %COLLECTOR_VERSION%
echo.
echo  Servidor monitorado: %SERVER_NAME%
echo.
echo  IP do servidor....: %SERVER_IP%
echo.
echo  Ciclo atual ......: !LOOP_COUNT!
echo.
echo  Ultima execucao ..: !LAST_RUN_AT!
echo  ----------------------------------------------------------------------
echo.
echo  Ultimo resultado .: !LAST_RESULT!
echo.
echo  Servicos lidos ...: !LAST_TOTAL_SERVICOS!
echo.
echo  Filtro ...........: %FILTER_TERM%
echo.
echo  Destino JSON .....: %OUTPUT_FILE%
echo.
echo  Intervalo ........: %INTERVAL%s
echo.
echo  Atualizando coleta...
echo.
echo  ----------------------------------------------------------------------
echo.
exit /b 0

:Log
set "NOW="
for /f "usebackq delims=" %%A in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"`) do (
    set "NOW=%%A"
)
echo [%NOW%] %~1
>> "%LOG_FILE%" echo [%NOW%] %~1
exit /b 0

from concurrent.futures import ThreadPoolExecutor
from collections import deque
from datetime import datetime
from functools import wraps
import json
import os
import re
import smtplib
import subprocess
import base64
import socket
import time
import threading
import uuid

from email.mime.text import MIMEText
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import win32service
import win32serviceutil

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("APP_SECRET_KEY", "protheus-monitor-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

LOG_FILE = "events_log.json"
USERS_FILE = "users.json"
ENVIRONMENTS_FILE = "environments.json"

# ===== CONFIG =====
TEAMS_WEBHOOK = ""
EMAIL_FROM = ""
EMAIL_TO = ""
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = ""
SMTP_PASS = ""
GIT_SAFE_DIRECTORY = os.path.abspath(os.getcwd()).replace("\\", "/")

DEFAULT_ADMIN_USERNAME = os.getenv("PROTHEUS_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("PROTHEUS_ADMIN_PASSWORD", "admin123")

# ===== AMBIENTES =====
DEFAULT_ENVIRONMENTS = [
    {
        "id": "apex-hml3",
        "name": "APEX-HML3",
        "environment_type": "homologacao",
        "host": "127.0.0.1",
        "services": [
            {"name": "TOTVS-Appserver12-APEX-HML3", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-REST", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-SCHED", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WF", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS2", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
        ],
        "infra_services": [],
    },
    {
        "id": "infra",
        "name": "INFRA",
        "environment_type": "desenvolvimento",
        "host": "127.0.0.1",
        "services": [
            {"name": "licenseVirtual", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSDBAccess64", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSDBAccess64TSS", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSservice", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"},
        ],
        "infra_services": [],
    },
]

ALLOWED_ROLES = {"admin", "technical", "operator"}
SERVICE_PRIORITIES = {"baixa", "media", "alta"}
ACTION_EXECUTOR = ThreadPoolExecutor(max_workers=12)
ACTION_JOBS = {}
ACTION_JOBS_LOCK = threading.Lock()


def normalize_username(username):
    return (username or "").strip().lower()


def is_valid_username(username):
    return bool(re.fullmatch(r"[a-z0-9._-]{3,40}", username or ""))


def slugify_environment_name(name):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return base[:50] or "ambiente"


def normalize_port(value):
    return str(value or "").strip()


def normalize_service_priority(value):
    normalized = (value or "").strip().lower()
    mapping = {
        "baixa": "baixa",
        "low": "baixa",
        "media": "media",
        "média": "media",
        "medium": "media",
        "alta": "alta",
        "high": "alta",
    }
    return mapping.get(normalized, "media")


def infer_environment_type(name):
    normalized = (name or "").strip().lower()
    if any(token in normalized for token in ["prd", "prod", "producao", "produção"]):
        return "producao"
    if any(token in normalized for token in ["hml", "homolog", "qa", "teste"]):
        return "homologacao"
    return "desenvolvimento"


def normalize_environment_type(value, fallback_name=""):
    normalized = (value or "").strip().lower()
    mapping = {
        "producao": "producao",
        "produção": "producao",
        "prod": "producao",
        "homologacao": "homologacao",
        "homologação": "homologacao",
        "hml": "homologacao",
        "desenvolvimento": "desenvolvimento",
        "dev": "desenvolvimento",
    }
    return mapping.get(normalized, infer_environment_type(fallback_name))


def sanitize_service(service):
    if isinstance(service, str):
        service = {"name": service}
    elif not isinstance(service, dict):
        service = {}

    legacy_port = service.get("port")
    name = (service.get("name") or "").strip()
    display_name = (service.get("display_name") or service.get("displayName") or "").strip()
    if not display_name:
        display_name = name

    return {
        "name": name,
        "display_name": display_name,
        "path_executable": (service.get("path_executable") or service.get("executable_path") or service.get("exe_path") or "").strip(),
        "tcp_port": normalize_port(service.get("tcp_port") or legacy_port),
        "webapp_port": normalize_port(service.get("webapp_port")),
        "rest_port": normalize_port(service.get("rest_port")),
        "service_ip": (service.get("service_ip") or service.get("ip_address") or service.get("ip") or "").strip(),
        "console_log_file": (service.get("console_log_file") or service.get("console_log") or service.get("log_file") or "").strip(),
        "priority": normalize_service_priority(service.get("priority")),
    }


def sanitize_environment(environment, existing_id=None):
    services = [sanitize_service(service) for service in environment.get("services", [])]
    services = [service for service in services if service["name"]]
    infra_services = [sanitize_service(service) for service in environment.get("infra_services", [])]
    infra_services = [service for service in infra_services if service["name"]]
    for infra_service in infra_services:
        infra_service["priority"] = "alta"

    return {
        "id": existing_id or slugify_environment_name(environment.get("name")),
        "name": (environment.get("name") or "").strip(),
        "environment_type": normalize_environment_type(environment.get("environment_type"), environment.get("name")),
        "host": (environment.get("host") or "").strip(),
        "app_url": (environment.get("app_url") or "").strip(),
        "rest_url": (environment.get("rest_url") or "").strip(),
        "services": services,
        "infra_services": infra_services,
    }


def ensure_users_file():
    if os.path.exists(USERS_FILE):
        return

    default_users = [
        {
            "username": normalize_username(DEFAULT_ADMIN_USERNAME),
            "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "active": True,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    ]
    save_users(default_users)


def ensure_environments_file():
    if os.path.exists(ENVIRONMENTS_FILE):
        return
    save_environments(DEFAULT_ENVIRONMENTS)


def load_users():
    ensure_users_file()
    with open(USERS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as file:
        json.dump(users, file, indent=2, ensure_ascii=False)


def load_environments():
    ensure_environments_file()
    with open(ENVIRONMENTS_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    normalized = []
    changed = False
    for item in data:
        infra_list = item.get("infra_services", [])
        if isinstance(infra_list, list) and infra_list and isinstance(infra_list[0], str):
            item["infra_services"] = [{"name": service_name, "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"} for service_name in infra_list]
            changed = True

        if isinstance(item.get("services", []), list) and item.get("services") and isinstance(item["services"][0], str):
            item = {
                "id": item.get("id") or slugify_environment_name(item.get("name")),
                "name": item.get("name"),
                "host": item.get("host", "127.0.0.1"),
                "services": [{"name": service_name, "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "service_ip": "", "console_log_file": "", "priority": "media"} for service_name in item["services"]],
                "infra_services": item.get("infra_services", []),
            }
            changed = True

        for service in (item.get("services") or []) + (item.get("infra_services") or []):
            if not isinstance(service, dict):
                continue
            if "port" in service:
                changed = True
            if (
                "display_name" not in service
                or
                "path_executable" not in service
                or
                "tcp_port" not in service
                or "webapp_port" not in service
                or "rest_port" not in service
                or "service_ip" not in service
                or "console_log_file" not in service
                or "priority" not in service
            ):
                changed = True

        if "infra_services" not in item:
            item["infra_services"] = []
            changed = True
        if "environment_type" not in item:
            item["environment_type"] = infer_environment_type(item.get("name"))
            changed = True
        if "app_url" not in item:
            item["app_url"] = ""
            changed = True
        if "rest_url" not in item:
            item["rest_url"] = ""
            changed = True

        normalized.append(sanitize_environment(item, item.get("id") or slugify_environment_name(item.get("name"))))
        if any((service.get("priority") or "") != "alta" for service in normalized[-1].get("infra_services", [])):
            changed = True

    if changed:
        save_environments(normalized)

    return normalized


def save_environments(environments):
    with open(ENVIRONMENTS_FILE, "w", encoding="utf-8") as file:
        json.dump(environments, file, indent=2, ensure_ascii=False)


def find_user(username):
    target = normalize_username(username)
    for user in load_users():
        if normalize_username(user.get("username")) == target:
            return user
    return None


def find_environment(environment_id):
    for environment in load_environments():
        if environment["id"] == environment_id:
            return environment
    return None


def safe_decode_bytes(raw_bytes):
    if raw_bytes is None:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except Exception:
            continue
    return raw_bytes.decode("latin-1", errors="replace")


def parse_appserver_ini(text):
    content = (text or "").replace("\r\n", "\n")
    if not content.strip():
        return {}

    def extract_section_value(section_name, key_name):
        # Busca robusta por seção+chave sem depender de parser INI estrito
        section_pattern = re.compile(
            rf"(?ims)^\s*\[{re.escape(section_name)}\]\s*$" rf"(.*?)(?=^\s*\[.*?\]\s*$|\Z)"
        )
        for section_match in section_pattern.finditer(content):
            section_body = section_match.group(1) or ""
            value_match = re.search(
                rf"(?im)^\s*{re.escape(key_name)}\s*=\s*([^;\r\n#]+)",
                section_body,
            )
            if value_match:
                return value_match.group(1).strip()
        return ""

    tcp_port = extract_section_value("TCP", "Port")
    webapp_port = extract_section_value("WEBAPP", "Port")
    rest_port = extract_section_value("httprest", "port")

    console_log_file = ""
    console_match = re.search(r"(?im)^\s*console(?:\s|_|)file\s*=\s*([^\r\n;#]+)", content)
    if console_match:
        console_log_file = console_match.group(1).strip()

    return {
        "tcp_port": normalize_port(tcp_port),
        "webapp_port": normalize_port(webapp_port),
        "rest_port": normalize_port(rest_port),
        "console_log_file": console_log_file,
    }


def is_valid_remote_host(value):
    target = (value or "").strip()
    if not target or len(target) > 253:
        return False
    return bool(re.fullmatch(r"[a-zA-Z0-9.-]+", target))


def is_ipv4_address(value):
    text = (value or "").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", text):
        return False
    parts = text.split(".")
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except Exception:
        return False


def resolve_hostname_for_ip(ip_address):
    if not is_ipv4_address(ip_address):
        return ""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        return (hostname or "").strip()
    except Exception:
        return ""


def run_powershell(script):
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def discover_services_on_hosts(hosts, credential=None):
    normalized_hosts = [host.strip() for host in (hosts or []) if is_valid_remote_host(host)]
    if not normalized_hosts:
        return [], {"error": "Nenhum host válido informado."}

    # Descoberta via PowerShell Remoting (Invoke-Command). Usa as credenciais do usuário que está executando o app.
    # Se WinRM não estiver habilitado nos servidores, retornará erro.
    targets = []
    step_logs = []
    for host in normalized_hosts:
        connect = host
        if is_ipv4_address(host):
            resolved = resolve_hostname_for_ip(host)
            if resolved:
                connect = resolved
        targets.append({"input": host, "connect": connect})
        if connect != host:
            step_logs.append(f"[{host}] Hostname resolvido automaticamente para {connect}.")
        else:
            step_logs.append(f"[{host}] Usando destino de conexão {connect}.")

    targets_literal = ",".join(
        [
            "@{ input='" + item["input"].replace("'", "''") + "'; connect='" + item["connect"].replace("'", "''") + "' }"
            for item in targets
        ]
    )

    username = ""
    password = ""
    if isinstance(credential, dict):
        username = str(credential.get("username") or "").strip()
        password = str(credential.get("password") or "")

    username_literal = username.replace("'", "''")
    password_literal = password.replace("'", "''")
    use_credential = bool(username and password)
    use_credential_literal = "$true" if use_credential else "$false"
    script = rf"""
$ErrorActionPreference = 'Stop'
$targets = @({targets_literal})

$useCredential = {use_credential_literal}
$cred = $null
if ($useCredential) {{
    $username = '{username_literal}'
    $plain = '{password_literal}'
    $secure = ConvertTo-SecureString $plain -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($username, $secure)
}}

$results = @()
foreach ($t in $targets) {{
    $inputHost = $t.input
    $connectHost = $t.connect
    try {{
        $invokeParams = @{{
            ComputerName = $connectHost
            ScriptBlock  = {{
            # Serviços TOTVS por DisplayName OU Name (contains), excluindo desabilitados.
            $cimServices = Get-CimInstance Win32_Service | Where-Object {{
                $nameText = ([string]$_.Name).ToLowerInvariant()
                $displayText = ([string]$_.DisplayName).ToLowerInvariant()
                (([string]$_.StartMode) -notmatch '(?i)^disabled$') -and ($nameText.Contains('totvs') -or $displayText.Contains('totvs'))
            }}

            function Find-AppserverIniPath($exeDir) {{
                if (-not $exeDir) {{ return $null }}

                $roots = @($exeDir, (Split-Path -Parent $exeDir), (Split-Path -Parent (Split-Path -Parent $exeDir))) | Where-Object {{ $_ }} | Select-Object -Unique
                foreach ($root in $roots) {{
                    $candidate = Join-Path $root 'bin\\appserver.ini'
                    if (Test-Path -LiteralPath $candidate) {{ return $candidate }}
                }}

                foreach ($root in $roots) {{
                    try {{
                        $all = Get-ChildItem -LiteralPath $root -Recurse -Filter 'appserver.ini' -File -ErrorAction SilentlyContinue
                        $preferred = $all | Where-Object {{ $_.FullName -match '\\\\bin\\\\appserver\\.ini$' }} | Select-Object -First 1
                        if ($preferred) {{ return $preferred.FullName }}
                        $any = $all | Select-Object -First 1
                        if ($any) {{ return $any.FullName }}
                    }} catch {{
                        # Ignorar erros de permissão/pastas inacessíveis
                    }}
                }}

                return $null
            }}

            function Resolve-ExePathFromPathName($pathName) {{
                if (-not $pathName) {{ return $null }}
                if ($pathName -match '\"([^\"]+\.exe)\"') {{ return $Matches[1] }}
                if ($pathName -match '(?i)^\s*([^\r\n]+?\.exe)\b') {{ return $Matches[1].Trim() }}
                return $pathName
            }}

            $out = @()
            foreach ($cim in $cimServices) {{
                $pathName = $cim.PathName
                $exePath = Resolve-ExePathFromPathName $pathName
                $exeDir = Split-Path -Parent $exePath
                $exeExists = $false
                if ($exePath) {{
                    try {{
                        $exeExists = Test-Path -LiteralPath $exePath
                    }} catch {{
                        $exeExists = $false
                    }}
                }}

                if (-not $exeExists) {{
                    $out += [PSCustomObject]@{{
                        host = $env:COMPUTERNAME
                        service_name = $cim.Name
                        display_name = $cim.DisplayName
                        service_state = $cim.State
                        start_mode = $cim.StartMode
                        path_name = $pathName
                        exe_path = $exePath
                        exe_dir = $exeDir
                        exe_exists = $false
                        skipped = $true
                        skip_reason = 'ExecutablePathNotFound'
                        ini_path = $null
                        ini_base64 = $null
                    }}
                    continue
                }}

                $iniPath = Find-AppserverIniPath $exeDir
                $iniB64 = $null
                if ($iniPath) {{
                    try {{
                        $bytes = [System.IO.File]::ReadAllBytes($iniPath)
                        $iniB64 = [Convert]::ToBase64String($bytes)
                    }} catch {{
                        $iniB64 = $null
                    }}
                }}

                $out += [PSCustomObject]@{{
                    host = $env:COMPUTERNAME
                    service_name = $cim.Name
                    display_name = $cim.DisplayName
                    service_state = $cim.State
                    start_mode = $cim.StartMode
                    path_name = $pathName
                    exe_path = $exePath
                    exe_dir = $exeDir
                    exe_exists = $true
                    skipped = $false
                    skip_reason = $null
                    ini_path = $iniPath
                    ini_base64 = $iniB64
                }}
            }}
            return $out
            }}
        }}

        if ($useCredential -and $cred) {{
            $invokeParams.Credential = $cred
            $invokeParams.Authentication = 'Negotiate'
        }}

        $rows = Invoke-Command @invokeParams

        foreach ($r in $rows) {{
            $results += $r | Add-Member -NotePropertyName 'server' -NotePropertyValue $inputHost -PassThru
            $results += $r | Add-Member -NotePropertyName 'connect_host' -NotePropertyValue $connectHost -PassThru
        }}
    }} catch {{
        $results += [PSCustomObject]@{{ server = $inputHost; connect_host = $connectHost; error = $_.Exception.Message }}
    }}
}}
if ($results.Count -eq 0) {{
    Write-Output '[]'
}} else {{
    $results | ConvertTo-Json -Depth 6
}}
"""

    code, stdout, stderr = run_powershell(script)
    if code != 0:
        step_logs.append("Execução do script de descoberta finalizada com erro no PowerShell.")
        return [], {"error": (stderr or stdout or "Falha ao executar PowerShell.").strip(), "steps": step_logs}

    raw = (stdout or "").strip()
    if not raw:
        # Em alguns cenários o PowerShell pode não emitir saída mesmo com execução bem-sucedida.
        # Tratamos como "nenhum serviço encontrado" para não quebrar o fluxo da busca automática.
        step_logs.append("Execução concluída sem saída do script remoto.")
        return [], {"errors": [], "steps": step_logs}

    try:
        data = json.loads(raw)
    except Exception:
        step_logs.append("Falha ao interpretar saída JSON da descoberta.")
        return [], {"error": "Não foi possível interpretar o retorno da descoberta.", "details": raw[:5000], "steps": step_logs}

    if isinstance(data, dict):
        data = [data]

    discovered = []
    errors = []
    for row in data:
        if not isinstance(row, dict):
            continue
        if row.get("error"):
            raw_error = str(row.get("error") or "")
            hint = ""
            if "TrustedHosts" in raw_error and "WinRM" in raw_error and "IP address" in raw_error:
                server = (row.get("server") or "").strip()
                hint = (
                    "Use hostname (não IP) se possível, ou adicione o destino em TrustedHosts no servidor que executa o monitor "
                    f"(ex.: `Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value \"{server}\" -Concatenate -Force`) "
                    "e garanta que o WinRM/PSRemoting esteja habilitado no destino (ex.: `Enable-PSRemoting -Force`)."
                )
            server = row.get("server")
            errors.append({"server": server, "error": raw_error, "hint": hint})
            step_logs.append(f"[{server}] Falha ao conectar/consultar: {raw_error}")
            continue

        if row.get("skipped"):
            server = (row.get("server") or "").strip()
            service_name = (row.get("service_name") or "").strip()
            exe_path = (row.get("exe_path") or "").strip()
            reason = str(row.get("skip_reason") or "Skipped").strip()
            step_logs.append(
                f"[{server}] Serviço ignorado ({reason}): {service_name}. Executável informado: {exe_path or '-'}."
            )
            continue

        ini_payload = {}
        ini_b64 = row.get("ini_base64")
        start_mode = str(row.get("start_mode") or "").strip()
        if start_mode.lower() == "disabled":
            step_logs.append(
                f"[{row.get('server')}] Serviço ignorado por startup type desabilitado: {(row.get('service_name') or '').strip()}."
            )
            continue
        if ini_b64:
            try:
                ini_bytes = base64.b64decode(ini_b64)
                ini_text = safe_decode_bytes(ini_bytes)
                ini_payload = parse_appserver_ini(ini_text)
            except Exception:
                ini_payload = {}

        server = (row.get("server") or "").strip()
        service_name = (row.get("service_name") or "").strip()
        ini_path = (row.get("ini_path") or "").strip()
        exe_path = (row.get("exe_path") or "").strip()
        exe_dir = (row.get("exe_dir") or "").strip()
        service_state = (row.get("service_state") or "").strip()
        normalized_state = service_state.upper()
        running_label = "SIM" if normalized_state == "RUNNING" else "NÃO"

        step_logs.append(f"[{server}] Serviço detectado: {service_name}.")
        if exe_path:
            step_logs.append(f"[{server}] Executável: {exe_path}")
        if exe_dir:
            step_logs.append(f"[{server}] Pasta do serviço: {exe_dir}")
        if ini_path:
            step_logs.append(f"[{server}] appserver.ini localizado: {ini_path}")
        else:
            step_logs.append(f"[{server}] appserver.ini não localizado para {service_name}.")

        step_logs.append(
            f"[{server}] Campos lidos para {service_name}: TCP={ini_payload.get('tcp_port', '') or '-'}, "
            f"WEBAPP={ini_payload.get('webapp_port', '') or '-'}, REST={ini_payload.get('rest_port', '') or '-'}, "
            f"ConsoleFile={ini_payload.get('console_log_file', '') or '-'}."
        )
        step_logs.append(
            f"[{server}] Status atual do serviço {service_name}: {normalized_state or 'UNKNOWN'} (Rodando: {running_label})."
        )

        if not exe_path:
            step_logs.append(f"[{server}] Serviço ignorado: {service_name} sem path executable válido.")
            continue

        discovered.append(
            {
                "name": service_name,
                "display_name": (row.get("display_name") or "").strip(),
                "service_ip": server,
                "path_executable": exe_path,
                "tcp_port": ini_payload.get("tcp_port", ""),
                "webapp_port": ini_payload.get("webapp_port", ""),
                "rest_port": ini_payload.get("rest_port", ""),
                "console_log_file": ini_payload.get("console_log_file", ""),
                "priority": "media",
                "_meta": {
                    "display_name": row.get("display_name"),
                    "path_name": row.get("path_name"),
                    "exe_path": row.get("exe_path"),
                    "exe_dir": row.get("exe_dir"),
                    "ini_path": row.get("ini_path"),
                    "host": row.get("host"),
                    "service_state": normalized_state or service_state,
                },
            }
        )

    if not discovered and not errors:
        step_logs.append("Nenhum serviço TOTVS elegível foi encontrado nos hosts informados.")
    elif discovered:
        step_logs.append("Resumo final de execução (serviço está rodando?):")
        for item in discovered:
            meta_state = str((item.get("_meta") or {}).get("service_state") or "").upper()
            running_label = "SIM" if meta_state == "RUNNING" else "NÃO"
            step_logs.append(
                f"[{item.get('service_ip')}] {item.get('name')}: {meta_state or 'UNKNOWN'} (Rodando: {running_label})."
            )

    payload = {"steps": step_logs}
    if errors:
        payload["errors"] = errors
    return discovered, payload


def build_status_service(service, host):
    resolved_host = (service or {}).get("service_ip") or host
    base = dict(service or {})
    base["name"] = service["name"]
    base["status"] = get_service_status_for_host(service["name"], resolved_host, service.get("display_name", ""))
    return base


def build_environment_status(environment):
    host = environment.get("host")
    services = environment.get("services", [])
    infra_services = environment.get("infra_services", [])
    all_services = [("services", service) for service in services] + [("infra_services", service) for service in infra_services]

    max_workers = min(max(len(all_services), 1), 12)
    built_services = {"services": [], "infra_services": []}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [(service_type, executor.submit(build_status_service, service, host)) for service_type, service in all_services]
        for service_type, future in futures:
            built_services[service_type].append(future.result())

    return {
        "id": environment["id"],
        "environment": environment["name"],
        "environment_type": environment.get("environment_type", infer_environment_type(environment["name"])),
        "host": host or "",
        "app_url": environment.get("app_url", ""),
        "rest_url": environment.get("rest_url", ""),
        "services": built_services["services"],
        "infra_services": built_services["infra_services"],
    }


def resolve_service_machine(host):
    normalized = (host or "").strip().lower()
    if normalized in {"", "127.0.0.1", "localhost", ".", "(local)"}:
        return None
    return host


def _is_local_machine_host(host):
    normalized = (host or "").strip().lower()
    return normalized in {"", "127.0.0.1", "localhost", ".", "(local)"}


def _get_service_pid_via_sc(service_name, host):
    if not service_name:
        return 0
    command = ["sc"]
    if not _is_local_machine_host(host):
        command.append(f"\\\\{host}")
    command.extend(["queryex", service_name])
    completed = subprocess.run(command, capture_output=True, text=True)
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    match = re.search(r"PID\s*:\s*(\d+)", output, flags=re.IGNORECASE)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _force_kill_service_process(service_name, host):
    pid = _get_service_pid_via_sc(service_name, host)
    if pid <= 0:
        return False, "PID do serviço não encontrado para forçar parada."

    command = ["taskkill"]
    if not _is_local_machine_host(host):
        command.extend(["/S", host])
    command.extend(["/PID", str(pid), "/F"])
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        return False, details or f"Falha ao executar taskkill para PID {pid}."
    return True, f"Parada forçada executada via taskkill no PID {pid}."


def stop_service_with_force(service_name, host, timeout_seconds=8):
    # Regra solicitada: sempre parar usando taskkill para maior velocidade.
    killed, details = _force_kill_service_process(service_name, host)
    if not killed:
        return {"success": False, "forced": False, "message": f"Falha no taskkill: {details}"}

    deadline = time.time() + max(timeout_seconds, 3)
    while time.time() < deadline:
        current_status = get_service_status_for_host(service_name, host)
        if current_status == "STOPPED":
            return {"success": True, "forced": True, "message": details}
        time.sleep(0.5)

    return {"success": False, "forced": True, "message": "Taskkill executado, mas o serviço ainda não está STOPPED."}


def find_service_in_environment(environment, service_name, service_ip=""):
    all_environment_services = environment.get("services", []) + environment.get("infra_services", [])
    if service_ip:
        return next(
            (
                item
                for item in all_environment_services
                if item.get("name") == service_name and (item.get("service_ip") or "").strip() == service_ip
            ),
            None,
        )
    return next((item for item in all_environment_services if item.get("name") == service_name), None)


def read_local_console_log_tail(log_path, max_lines=300):
    if not os.path.exists(log_path):
        return {"success": False, "error": "Arquivo de log não encontrado para o serviço.", "exists": False}

    stats = os.stat(log_path)
    with open(log_path, "r", encoding="utf-8", errors="replace") as file:
        content = "".join(deque(file, maxlen=max_lines))

    return {
        "success": True,
        "exists": True,
        "size": int(stats.st_size),
        "last_write_utc": datetime.utcfromtimestamp(stats.st_mtime).isoformat() + "Z",
        "content": content,
    }


def local_path_to_unc(host, path_value):
    if not host or not path_value:
        return ""
    text = str(path_value).strip()
    # Converte "C:\pasta\arquivo.log" em "\\host\C$\pasta\arquivo.log"
    match = re.match(r"^([a-zA-Z]):\\(.*)$", text)
    if not match:
        return ""
    drive = match.group(1).upper()
    suffix = match.group(2).replace("/", "\\")
    return f"\\\\{host}\\{drive}$\\{suffix}"


def read_unc_console_log_tail(unc_path, max_lines=300):
    if not unc_path:
        return {"success": False, "error": "Caminho UNC inválido."}
    if not os.path.exists(unc_path):
        return {"success": False, "error": "Arquivo UNC não encontrado.", "exists": False}

    stats = os.stat(unc_path)
    with open(unc_path, "r", encoding="utf-8", errors="replace") as file:
        content = "".join(deque(file, maxlen=max_lines))

    return {
        "success": True,
        "exists": True,
        "size": int(stats.st_size),
        "last_write_utc": datetime.utcfromtimestamp(stats.st_mtime).isoformat() + "Z",
        "content": content,
    }


def read_remote_console_log_tail(host, log_path, max_lines=300):
    if not is_valid_remote_host(host):
        return {"success": False, "error": "Host remoto inválido para leitura do log."}

    candidate_hosts = [host]
    if is_ipv4_address(host):
        resolved_hostname = resolve_hostname_for_ip(host)
        if resolved_hostname and resolved_hostname not in candidate_hosts:
            candidate_hosts.insert(0, resolved_hostname)

    errors = []
    for current_host in candidate_hosts:
        host_literal = current_host.replace("'", "''")
        path_literal = log_path.replace("'", "''")
        script = rf"""
$ErrorActionPreference = 'Stop'
$hostName = '{host_literal}'
$logPath = '{path_literal}'
$tail = {int(max_lines)}

try {{
    $result = Invoke-Command -ComputerName $hostName -ScriptBlock {{
        param($logPath, $tail)
        if (-not (Test-Path -LiteralPath $logPath)) {{
            return [PSCustomObject]@{{
                success = $false
                exists = $false
                error = 'Arquivo de log não encontrado para o serviço.'
            }}
        }}

        $item = Get-Item -LiteralPath $logPath -ErrorAction Stop
        $lines = Get-Content -LiteralPath $logPath -Tail $tail -ErrorAction Stop
        $text = ($lines -join "`n")
        return [PSCustomObject]@{{
            success = $true
            exists = $true
            size = [int64]$item.Length
            last_write_utc = $item.LastWriteTimeUtc.ToString('o')
            content = $text
        }}
    }} -ArgumentList $logPath, $tail

    $result | ConvertTo-Json -Depth 6
}} catch {{
    [PSCustomObject]@{{
        success = $false
        error = $_.Exception.Message
    }} | ConvertTo-Json -Depth 6
}}
"""

        code, stdout, stderr = run_powershell(script)
        if code != 0:
            errors.append(f"[{current_host}] {(stderr or stdout or 'Falha ao ler log remoto.').strip()}")
            continue

        raw = (stdout or "").strip()
        if not raw:
            errors.append(f"[{current_host}] Sem retorno na leitura do log remoto.")
            continue

        try:
            data = json.loads(raw)
        except Exception:
            errors.append(f"[{current_host}] Retorno inválido na leitura do log remoto.")
            continue

        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            errors.append(f"[{current_host}] Formato inesperado na leitura do log remoto.")
            continue

        if data.get("success"):
            return data

        errors.append(f"[{current_host}] {data.get('error', 'Falha ao ler log remoto via WinRM.')}")

    # Fallback sem WinRM: tentativa via SMB/UNC para evitar exigir autenticação explícita.
    for current_host in candidate_hosts:
        unc_path = local_path_to_unc(current_host, log_path)
        if not unc_path:
            continue
        unc_result = read_unc_console_log_tail(unc_path, max_lines=max_lines)
        if unc_result.get("success"):
            unc_result["transport"] = "SMB"
            return unc_result
        if unc_result.get("error"):
            errors.append(f"[{current_host}] {unc_result.get('error')}")

    return {"success": False, "error": "Falha ao ler log remoto.", "details": "\n".join(errors[:8])}


def current_user():
    username = session.get("username")
    if not username:
        return None
    return find_user(username)


def can_user_access_environment(user, environment):
    if not user or not environment:
        return False
    role = user.get("role", "operator")
    environment_type = environment.get("environment_type") or infer_environment_type(environment.get("name"))
    if role == "operator" and environment_type == "producao":
        return False
    return True


def is_license_service(service_name="", display_name=""):
    name_text = (service_name or "").strip().lower()
    display_text = (display_name or "").strip().lower()
    return "license" in name_text or "license" in display_text


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not current_user():
            if request.path != "/":
                return jsonify({"success": False, "error": "Sessão expirada."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"success": False, "error": "Sessão expirada."}), 401
        if user.get("role") != "admin":
            return jsonify({"success": False, "error": "Acesso negado."}), 403
        return view(*args, **kwargs)

    return wrapped_view


def get_service_status_for_host(service_name, host, display_name=""):
    def status_label(status_code):
        mapping = {
            win32service.SERVICE_RUNNING: "RUNNING",
            win32service.SERVICE_STOPPED: "STOPPED",
            win32service.SERVICE_START_PENDING: "STARTING",
            win32service.SERVICE_STOP_PENDING: "STOPPING",
        }
        return mapping.get(status_code, "UNKNOWN")

    def query_status_by_name(name_to_query):
        status_code = win32serviceutil.QueryServiceStatus(name_to_query, machine=resolve_service_machine(host))[1]
        return status_label(status_code)

    def find_service_name_by_display_name(display_name):
        if not display_name:
            return ""
        try:
            scm = win32service.OpenSCManager(
                resolve_service_machine(host),
                None,
                win32service.SC_MANAGER_ENUMERATE_SERVICE,
            )
            try:
                items = win32service.EnumServicesStatus(
                    scm,
                    win32service.SERVICE_WIN32,
                    win32service.SERVICE_STATE_ALL,
                )
                normalized_target = (display_name or "").strip().lower()
                for item in items:
                    candidate_name = item[0]
                    candidate_display = item[1]
                    if (candidate_display or "").strip().lower() == normalized_target:
                        return candidate_name
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception:
            return ""
        return ""

    try:
        return query_status_by_name(service_name)
    except Exception:
        pass

    resolved_by_display = find_service_name_by_display_name(display_name)
    if resolved_by_display and resolved_by_display.lower() != (service_name or "").strip().lower():
        try:
            return query_status_by_name(resolved_by_display)
        except Exception:
            pass

    service_name_text = (service_name or "").strip().lower()
    display_name_text = (display_name or "").strip().lower()
    if "license" in service_name_text or "license" in display_name_text:
        for alias in ("licenseVirtual", "TOTVSLicenseVirtual", "license"):
            if alias.lower() == service_name_text:
                continue
            try:
                return query_status_by_name(alias)
            except Exception:
                continue

    return "NOT FOUND"


def save_log(service, action, result, user):
    log = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "service": service,
        "action": action,
        "result": result,
        "user": user,
    }

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as file:
            json.dump([], file)

    with open(LOG_FILE, "r+", encoding="utf-8") as file:
        try:
            data = json.load(file)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        data.insert(0, log)
        file.seek(0)
        json.dump(data[:200], file, indent=2, ensure_ascii=False)
        file.truncate()


def save_environment_log(environment_name, host, service, action, result, user):
    target = f"{environment_name} ({host or 'local'}) :: {service}"
    save_log(target, action, result, user)


def save_admin_environment_log(environment_name, action, result, user):
    target = f"AMBIENTE :: {environment_name}"
    save_log(target, action, result, user)


def _normalize_service_key(value):
    return (value or "").strip().lower()


def _build_service_registry_target(environment_name, section, service):
    section_label = "Infra" if section == "infra_services" else "Aplicacao"
    service_name = (service.get("display_name") or service.get("name") or "servico-sem-nome").strip()
    service_ip = (service.get("service_ip") or "").strip() or "-"
    return f"SERVICO :: {environment_name} :: {section_label} :: {service_name} :: {service_ip}"


def _service_snapshot(environment):
    snapshot = {}
    if not environment:
        return snapshot

    for section in ("services", "infra_services"):
        for raw_service in environment.get(section, []) or []:
            service = sanitize_service(raw_service)
            key = f"{section}|{_normalize_service_key(service.get('name'))}|{_normalize_service_key(service.get('service_ip'))}"
            if not _normalize_service_key(service.get("name")):
                continue
            snapshot[key] = (section, service)
    return snapshot


def save_service_registry_changes_log(environment_name, before_environment, after_environment, user):
    before = _service_snapshot(before_environment)
    after = _service_snapshot(after_environment)
    keys = sorted(set(before) | set(after))

    for key in keys:
        before_item = before.get(key)
        after_item = after.get(key)

        if before_item and not after_item:
            section, service = before_item
            save_log(_build_service_registry_target(environment_name, section, service), "SERVICE_DELETE", "SUCCESS", user)
            continue

        if after_item and not before_item:
            section, service = after_item
            save_log(_build_service_registry_target(environment_name, section, service), "SERVICE_CREATE", "SUCCESS", user)
            continue

        before_section, before_service = before_item
        after_section, after_service = after_item
        if before_section != after_section or before_service != after_service:
            save_log(_build_service_registry_target(environment_name, after_section, after_service), "SERVICE_UPDATE", "SUCCESS", user)


def run_git_command(args):
    try:
        completed = subprocess.run(
            ["git", "-c", f"safe.directory={GIT_SAFE_DIRECTORY}", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=os.getcwd(),
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def get_app_version():
    commit = run_git_command(["rev-parse", "--short", "HEAD"])
    if not commit:
        return "versao-local"

    dirty = bool(run_git_command(["status", "--short"]))
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "branch-local"
    return f"{branch}@{commit}{'-dirty' if dirty else ''}"


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _set_action_job(job_key, **fields):
    with ACTION_JOBS_LOCK:
        current = ACTION_JOBS.get(job_key, {})
        current.update(fields)
        ACTION_JOBS[job_key] = current


def _run_service_action(environment, resolved_host, service, action_type, username):
    machine = resolve_service_machine(resolved_host)
    forced_stop = False
    if action_type == "start":
        win32serviceutil.StartService(service, machine=machine)
    elif action_type == "stop":
        stop_result = stop_service_with_force(service, resolved_host)
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("message") or "Falha ao parar serviço.")
        forced_stop = bool(stop_result.get("forced"))
    elif action_type == "restart":
        stop_result = stop_service_with_force(service, resolved_host)
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("message") or "Falha ao parar serviço para reinício.")
        forced_stop = bool(stop_result.get("forced"))
        win32serviceutil.StartService(service, machine=machine)
    else:
        raise ValueError("Ação inválida.")

    result_label = "SUCCESS_FORCED" if forced_stop else "SUCCESS"
    save_environment_log(environment["name"], resolved_host, service, action_type, result_label, username)
    return {"success": True, "service_ip": resolved_host, "forced_stop": forced_stop}


def _normalize_bulk_priority(value):
    normalized = (value or "").strip().lower()
    normalized = normalized.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    if normalized in {"1", "p1", "prioridade 1"}:
        return "p1"
    if normalized in {"2", "p2", "prioridade 2", "media", "medio", "medium"}:
        return "media"
    if normalized in {"3", "p3", "prioridade 3", "alta", "high"}:
        return "alta"
    if normalized in {"baixa", "low"}:
        return "baixa"
    return "media"


def _build_bulk_ordered_services(environment, action_type):
    services = [item for item in (environment.get("services", []) + environment.get("infra_services", [])) if item.get("name")]
    if action_type == "start":
        sequence = ["alta", "media"]
    else:
        sequence = ["p1", "baixa", "media", "alta"]

    ordered = []
    for priority in sequence:
        for service in services:
            if _normalize_bulk_priority(service.get("priority")) == priority:
                ordered.append(service)
    return ordered


def send_teams(message):
    if not TEAMS_WEBHOOK:
        return
    try:
        import requests

        requests.post(TEAMS_WEBHOOK, json={"text": message}, timeout=10)
    except Exception:
        pass


def send_email(message):
    if not SMTP_USER:
        return
    try:
        msg = MIMEText(message)
        msg["Subject"] = "Alerta Protheus"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
    except Exception:
        pass


def serialize_user(user):
    return {
        "username": user["username"],
        "role": user.get("role", "operator"),
        "active": user.get("active", True),
        "created_at": user.get("created_at"),
    }


@app.context_processor
def inject_app_version():
    return {"app_version": get_app_version()}


@app.before_request
def sync_session_user():
    username = session.get("username")
    if not username:
        return

    user = find_user(username)
    if not user or not user.get("active", True):
        session.clear()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user():
            return redirect(url_for("index"))
        return render_template("login.html")

    data = request.get_json(silent=True) or request.form
    username = normalize_username(data.get("username"))
    password = data.get("password", "")

    user = find_user(username)
    if not user or not user.get("active", True):
        return jsonify({"success": False, "error": "Usuário ou senha inválidos."}), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"success": False, "error": "Usuário ou senha inválidos."}), 401

    session.clear()
    session["username"] = user["username"]

    return jsonify({"success": True, "user": serialize_user(user)})


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/session")
def session_info():
    user = current_user()
    return jsonify({"authenticated": bool(user), "user": serialize_user(user) if user else None})


@app.route("/")
@login_required
def index():
    user = current_user()
    environments = [environment for environment in load_environments() if can_user_access_environment(user, environment)]
    initial_environments = []

    for environment in environments:
        initial_environments.append(
            {
                "id": environment["id"],
                "environment": environment["name"],
                "environment_type": environment.get("environment_type", infer_environment_type(environment["name"])),
                "host": environment.get("host", ""),
                "app_url": environment.get("app_url", ""),
                "rest_url": environment.get("rest_url", ""),
                "services": [
                    {
                        "name": service["name"],
                        "display_name": service.get("display_name", ""),
                        "path_executable": service.get("path_executable", ""),
                        "tcp_port": service.get("tcp_port", ""),
                        "webapp_port": service.get("webapp_port", ""),
                        "rest_port": service.get("rest_port", ""),
                        "service_ip": service.get("service_ip", ""),
                        "console_log_file": service.get("console_log_file", ""),
                        "priority": service.get("priority", "media"),
                        "status": "LOADING",
                    }
                    for service in environment.get("services", [])
                ],
                "infra_services": [
                    {
                        "name": service["name"],
                        "display_name": service.get("display_name", ""),
                        "path_executable": service.get("path_executable", ""),
                        "tcp_port": service.get("tcp_port", ""),
                        "webapp_port": service.get("webapp_port", ""),
                        "rest_port": service.get("rest_port", ""),
                        "service_ip": service.get("service_ip", ""),
                        "console_log_file": service.get("console_log_file", ""),
                        "priority": service.get("priority", "media"),
                        "status": "LOADING",
                    }
                    for service in environment.get("infra_services", [])
                ],
            }
        )

    return render_template("index.html", user=user, initial_environments=initial_environments)


@app.route("/admin")
@admin_required
def admin_panel():
    return render_template("admin.html", user=current_user())


@app.route("/status")
@login_required
def status():
    user = current_user()
    environment_id = request.args.get("environment_id", "").strip()
    if environment_id:
        environment = find_environment(environment_id)
        if not environment:
            return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404
        if not can_user_access_environment(user, environment):
            return jsonify({"success": False, "error": "Acesso negado ao ambiente de produção."}), 403
        return jsonify(build_environment_status(environment))

    environments = [environment for environment in load_environments() if can_user_access_environment(user, environment)]
    max_workers = min(max(len(environments), 1), 8)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        result = list(executor.map(build_environment_status, environments))

    return jsonify(result)


@app.route("/action", methods=["POST"])
@login_required
def action():
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    service = data.get("service")
    service_ip = (data.get("service_ip") or "").strip()
    action_type = data.get("action")
    async_requested = _as_bool(data.get("async"))
    user = current_user()
    environment = find_environment(environment_id)

    if not environment_id or not service or not action_type:
        return jsonify({"success": False, "error": "Ambiente, serviço e ação são obrigatórios."}), 400

    if not environment:
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404

    if not can_user_access_environment(user, environment):
        return jsonify({"success": False, "error": "Acesso negado ao ambiente de produção."}), 403

    all_environment_services = environment.get("services", []) + environment.get("infra_services", [])
    if not any(item["name"] == service for item in all_environment_services):
        return jsonify({"success": False, "error": "Serviço não cadastrado para o ambiente."}), 404

    resolved_service = find_service_in_environment(environment, service, service_ip=service_ip)

    if not resolved_service:
        return jsonify({"success": False, "error": "Serviço não cadastrado para o IP informado."}), 404

    resolved_host = (resolved_service.get("service_ip") or environment.get("host") or "").strip()
    if action_type not in {"start", "stop", "restart"}:
        return jsonify({"success": False, "error": "Ação inválida."}), 400

    if (
        action_type in {"stop", "restart"}
        and user.get("role") != "admin"
        and (environment.get("environment_type") or infer_environment_type(environment.get("name"))) == "producao"
        and is_license_service(service, resolved_service.get("display_name"))
    ):
        action_label = "parar" if action_type == "stop" else "reiniciar"
        return jsonify({"success": False, "error": f"Somente administrador pode {action_label} o serviço de license em produção."}), 403

    if async_requested:
        job_id = uuid.uuid4().hex
        _set_action_job(
            job_id,
            job_id=job_id,
            status="queued",
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            environment_id=environment_id,
            environment=environment["name"],
            service=service,
            service_ip=resolved_host,
            action=action_type,
            requested_by=user["username"],
        )

        def _worker():
            _set_action_job(job_id, status="running", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            try:
                result = _run_service_action(environment, resolved_host, service, action_type, user["username"])
                _set_action_job(
                    job_id,
                    status="completed",
                    success=True,
                    forced_stop=bool(result.get("forced_stop")),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:
                target = f"{environment['name']} [{resolved_host or 'local'}] - {service}"
                msg = f"ERRO: {target} - {action_type}"
                save_environment_log(environment["name"], resolved_host, service, action_type, "ERROR", user["username"])
                send_teams(msg)
                send_email(msg)
                _set_action_job(
                    job_id,
                    status="failed",
                    success=False,
                    error=str(exc),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )

        ACTION_EXECUTOR.submit(_worker)
        return jsonify({"success": True, "queued": True, "job_id": job_id, "service_ip": resolved_host})

    try:
        return jsonify(_run_service_action(environment, resolved_host, service, action_type, user["username"]))
    except Exception as exc:
        target = f"{environment['name']} [{resolved_host or 'local'}] - {service}"
        msg = f"ERRO: {target} - {action_type}"
        save_environment_log(environment["name"], resolved_host, service, action_type, "ERROR", user["username"])
        send_teams(msg)
        send_email(msg)
        return jsonify({"success": False, "error": str(exc), "service_ip": resolved_host}), 500


@app.route("/action-job/<job_id>")
@login_required
def action_job(job_id):
    user = current_user()
    with ACTION_JOBS_LOCK:
        job = dict(ACTION_JOBS.get(job_id) or {})

    if not job:
        return jsonify({"success": False, "error": "Ação não encontrada."}), 404

    if job.get("requested_by") != user.get("username") and user.get("role") != "admin":
        return jsonify({"success": False, "error": "Acesso negado."}), 403

    return jsonify({"success": True, "job": job})


@app.route("/action-bulk", methods=["POST"])
@login_required
def action_bulk():
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    action_type = data.get("action")
    user = current_user()
    environment = find_environment(environment_id)

    if not environment_id or action_type not in {"start", "stop"}:
        return jsonify({"success": False, "error": "Ambiente e ação (start/stop) são obrigatórios."}), 400

    if not environment:
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404

    if not can_user_access_environment(user, environment):
        return jsonify({"success": False, "error": "Acesso negado ao ambiente de produção."}), 403

    ordered_services = _build_bulk_ordered_services(environment, action_type)
    if action_type == "stop" and user.get("role") != "admin" and (environment.get("environment_type") or infer_environment_type(environment.get("name"))) == "producao":
        ordered_services = [
            service for service in ordered_services
            if not is_license_service(service.get("name"), service.get("display_name"))
        ]

    if not ordered_services:
        return jsonify({"success": False, "error": "Nenhum serviço elegível para execução em lote."}), 400

    job_id = uuid.uuid4().hex
    _set_action_job(
        job_id,
        job_id=job_id,
        status="queued",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        environment_id=environment_id,
        environment=environment["name"],
        action=action_type,
        requested_by=user["username"],
        total_services=len(ordered_services),
        success_count=0,
        fail_count=0,
    )

    def _bulk_worker():
        _set_action_job(job_id, status="running", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        success_count = 0
        fail_count = 0
        errors = []

        for service in ordered_services:
            service_name = service.get("name")
            resolved_host = (service.get("service_ip") or environment.get("host") or "").strip()
            try:
                _run_service_action(environment, resolved_host, service_name, action_type, user["username"])
                success_count += 1
            except Exception as exc:
                fail_count += 1
                if len(errors) < 20:
                    errors.append(f"{service_name}: {str(exc)}")

            _set_action_job(job_id, success_count=success_count, fail_count=fail_count)

        _set_action_job(
            job_id,
            status="completed",
            success=fail_count == 0,
            success_count=success_count,
            fail_count=fail_count,
            errors=errors,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    ACTION_EXECUTOR.submit(_bulk_worker)
    return jsonify({"success": True, "queued": True, "job_id": job_id, "total_services": len(ordered_services)})


@app.route("/service-console-log", methods=["POST"])
@login_required
def service_console_log():
    data = request.get_json(silent=True) or {}
    environment_id = (data.get("environment_id") or "").strip()
    service_name = (data.get("service") or "").strip()
    service_ip = (data.get("service_ip") or "").strip()
    last_signature = (data.get("last_signature") or "").strip()
    max_lines = int(data.get("max_lines") or 300)

    if not environment_id or not service_name:
        return jsonify({"success": False, "error": "Ambiente e serviço são obrigatórios."}), 400

    user = current_user()
    environment = find_environment(environment_id)
    if not environment:
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404
    if not can_user_access_environment(user, environment):
        return jsonify({"success": False, "error": "Acesso negado ao ambiente de produção."}), 403

    resolved_service = find_service_in_environment(environment, service_name, service_ip=service_ip)
    if not resolved_service:
        return jsonify({"success": False, "error": "Serviço não cadastrado para o IP informado."}), 404

    log_path = (resolved_service.get("console_log_file") or "").strip()
    if not log_path:
        return jsonify({"success": False, "error": "Console log file não cadastrado para este serviço."}), 400

    resolved_host = (resolved_service.get("service_ip") or environment.get("host") or "").strip()
    if resolve_service_machine(resolved_host) is None:
        read_result = read_local_console_log_tail(log_path, max_lines=max_lines)
    else:
        read_result = read_remote_console_log_tail(resolved_host, log_path, max_lines=max_lines)

    if not read_result.get("success"):
        return jsonify({"success": False, "error": read_result.get("error", "Falha ao ler log do serviço."), "details": read_result.get("details")}), 400

    signature = f"{read_result.get('size','0')}::{read_result.get('last_write_utc','')}"
    changed = signature != last_signature

    return jsonify(
        {
            "success": True,
            "changed": changed,
            "signature": signature,
            "service_ip": resolved_host,
            "content": read_result.get("content", "") if changed else "",
            "size": read_result.get("size", 0),
            "last_write_utc": read_result.get("last_write_utc", ""),
        }
    )


@app.route("/logs")
@login_required
def logs():
    if not os.path.exists(LOG_FILE):
        return jsonify([])

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, list):
                return jsonify(data)
    except Exception:
        pass
    return jsonify([])


@app.route("/users")
@admin_required
def users():
    return jsonify([serialize_user(user) for user in load_users()])


@app.route("/users", methods=["POST"])
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = normalize_username(data.get("username"))
    password = data.get("password", "")
    role = data.get("role", "operator")

    if not username or not password:
        return jsonify({"success": False, "error": "Usuário e senha são obrigatórios."}), 400

    if not is_valid_username(username):
        return jsonify({"success": False, "error": "Usuário deve ter de 3 a 40 caracteres: letras, números, ponto, hífen ou underscore."}), 400

    if role not in ALLOWED_ROLES:
        return jsonify({"success": False, "error": "Perfil inválido."}), 400

    users_data = load_users()
    if any(normalize_username(item["username"]) == username for item in users_data):
        return jsonify({"success": False, "error": "Usuário já cadastrado."}), 409

    new_user = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "role": role,
        "active": True,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    users_data.append(new_user)
    save_users(users_data)

    return jsonify({"success": True, "user": serialize_user(new_user)}), 201


@app.route("/users/<username>", methods=["PUT"])
@admin_required
def update_user(username):
    target_username = normalize_username(username)
    data = request.get_json(silent=True) or {}
    users_data = load_users()
    actor = current_user()

    for user in users_data:
        if normalize_username(user["username"]) != target_username:
            continue

        new_role = data.get("role", user.get("role", "operator"))
        new_active = bool(data["active"]) if "active" in data else user.get("active", True)

        if new_role not in ALLOWED_ROLES:
            return jsonify({"success": False, "error": "Perfil inválido."}), 400

        if normalize_username(actor["username"]) == target_username and not new_active:
            return jsonify({"success": False, "error": "Você não pode desativar o próprio usuário."}), 400

        simulated_users = []
        for item in users_data:
            if normalize_username(item["username"]) == target_username:
                updated_item = dict(item)
                updated_item["role"] = new_role
                updated_item["active"] = new_active
                simulated_users.append(updated_item)
            else:
                simulated_users.append(item)

        active_admins = sum(1 for item in simulated_users if item.get("role") == "admin" and item.get("active", True))
        if active_admins == 0:
            return jsonify({"success": False, "error": "Deve existir ao menos um administrador ativo."}), 400

        user["role"] = new_role
        user["active"] = new_active
        if data.get("password"):
            user["password_hash"] = generate_password_hash(data["password"])

        save_users(users_data)
        return jsonify({"success": True, "user": serialize_user(user)})

    return jsonify({"success": False, "error": "Usuário não encontrado."}), 404


@app.route("/users/<username>", methods=["DELETE"])
@admin_required
def delete_user(username):
    target_username = normalize_username(username)
    users_data = load_users()
    actor = current_user()

    if normalize_username(actor["username"]) == target_username:
        return jsonify({"success": False, "error": "Você não pode excluir o próprio usuário."}), 400

    deleted_user = next((item for item in users_data if normalize_username(item.get("username")) == target_username), None)
    if not deleted_user:
        return jsonify({"success": False, "error": "Usuário não encontrado."}), 404

    filtered_users = [item for item in users_data if normalize_username(item.get("username")) != target_username]
    active_admins = sum(1 for item in filtered_users if item.get("role") == "admin" and item.get("active", True))
    if active_admins == 0:
        return jsonify({"success": False, "error": "Deve existir ao menos um administrador ativo."}), 400

    save_users(filtered_users)
    save_log(f"USUARIO :: {deleted_user.get('username')}", "DELETE", "SUCCESS", actor["username"])
    return jsonify({"success": True})


@app.route("/environments")
@admin_required
def environments():
    return jsonify(load_environments())


@app.route("/environments", methods=["POST"])
@admin_required
def create_environment():
    data = request.get_json(silent=True) or {}
    environment = sanitize_environment(data)
    actor = current_user()

    if not environment["name"] or not environment["host"]:
        return jsonify({"success": False, "error": "Nome do ambiente e endereço IP são obrigatórios."}), 400

    environments_data = load_environments()
    existing_ids = {item["id"] for item in environments_data}
    base_id = environment["id"]
    suffix = 1

    while environment["id"] in existing_ids:
        suffix += 1
        environment["id"] = f"{base_id}-{suffix}"

    environments_data.append(environment)
    save_environments(environments_data)
    save_admin_environment_log(environment["name"], "CREATE", "SUCCESS", actor["username"])
    save_service_registry_changes_log(environment["name"], None, environment, actor["username"])
    return jsonify({"success": True, "environment": environment}), 201


@app.route("/environments/<environment_id>", methods=["PUT"])
@admin_required
def update_environment(environment_id):
    data = request.get_json(silent=True) or {}
    environments_data = load_environments()
    actor = current_user()

    for index, environment in enumerate(environments_data):
        if environment["id"] != environment_id:
            continue

        updated = sanitize_environment(data, existing_id=environment_id)
        if not updated["name"] or not updated["host"]:
            return jsonify({"success": False, "error": "Nome do ambiente e endereço IP são obrigatórios."}), 400

        environments_data[index] = updated
        save_environments(environments_data)
        save_admin_environment_log(updated["name"], "UPDATE", "SUCCESS", actor["username"])
        save_service_registry_changes_log(updated["name"], environment, updated, actor["username"])
        return jsonify({"success": True, "environment": updated})

    return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404


@app.route("/environments/<environment_id>", methods=["DELETE"])
@admin_required
def delete_environment(environment_id):
    environments_data = load_environments()
    actor = current_user()
    environment = next((item for item in environments_data if item["id"] == environment_id), None)
    filtered = [environment_item for environment_item in environments_data if environment_item["id"] != environment_id]

    if len(filtered) == len(environments_data):
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404

    save_environments(filtered)
    if environment:
        save_admin_environment_log(environment["name"], "DELETE", "SUCCESS", actor["username"])
        save_service_registry_changes_log(environment["name"], environment, None, actor["username"])
    return jsonify({"success": True})


@app.route("/discover-services", methods=["POST"])
@admin_required
def discover_services():
    try:
        data = request.get_json(silent=True) or {}
        hosts = data.get("hosts") or []
        actor = current_user()

        if isinstance(hosts, str):
            hosts = [item.strip() for item in hosts.split(",") if item.strip()]

        discovered, extra = discover_services_on_hosts(hosts, credential=None)
        if not discovered and extra.get("error"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": extra.get("error"),
                        "details": extra.get("details"),
                        "errors": extra.get("errors"),
                    }
                ),
                400,
            )

        infra_keywords = {"dbaccess", "broker", "license", "webagent"}
        infra = []
        services = []
        for item in discovered:
            name = (item.get("name") or "").lower()
            if not (item.get("path_executable") or "").strip():
                continue
            if any(keyword in name for keyword in infra_keywords):
                infra.append(item)
            else:
                services.append(item)

        save_log("DISCOVER", "AUTO_DISCOVER", "SUCCESS", actor["username"])
        return jsonify({"success": True, "services": services, "infra_services": infra, **extra})
    except Exception as exc:
        return jsonify({"success": False, "error": "Erro inesperado na busca automática.", "details": str(exc)}), 500


if __name__ == "__main__":
    ensure_users_file()
    ensure_environments_file()
    app.run(host="0.0.0.0", port=5000, debug=False)

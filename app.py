from concurrent.futures import ThreadPoolExecutor
from collections import deque
from datetime import date, datetime
from functools import wraps
import json
import os
import re
import shutil
import smtplib
import subprocess
import base64
import socket
import time
import threading
import uuid
from html import escape

from email.mime.text import MIMEText
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, has_request_context
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
except Exception:  # pragma: no cover
    ProxyFix = None
from werkzeug.security import check_password_hash, generate_password_hash
import win32service
import win32serviceutil

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("APP_SECRET_KEY", "protheus-monitor-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

DATA_DIR = "data"
LOG_FILE = os.path.join(DATA_DIR, "events_log.json")
EXECUTION_TRACE_FILE = os.path.join(DATA_DIR, "execution_trace.json")
LOG_MAX_ENTRIES = 1000
EXECUTION_TRACE_MAX_ENTRIES = 4000
LOG_DEDUP_WINDOWS_SECONDS = {
    "COLLECTOR_HEALTH": 21600,
    "ALERTS": 1800,
    "INVENTORY": 1800,
}
USERS_FILE = os.path.join(DATA_DIR, "users.json")
ENVIRONMENTS_FILE = os.path.join(DATA_DIR, "environments.json")
SERVERS_FILE = os.path.join(DATA_DIR, "servers.json")
ALERT_SETTINGS_FILE = os.path.join(DATA_DIR, "alert_settings.json")
SECRET_SETTINGS_FILE = os.path.join(DATA_DIR, "secret_settings.json")
ALERT_DELIVERY_STATE_FILE = os.path.join(DATA_DIR, "alert_delivery_state.json")

# ===== CONFIG =====
TEAMS_WEBHOOK = (os.getenv("TEAMS_WEBHOOK") or "").strip()
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
            {"name": "TOTVS-Appserver12-APEX-HML3", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-REST", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-SCHED", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WF", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS2", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
        ],
        "infra_services": [],
    },
    {
        "id": "infra",
        "name": "INFRA",
        "environment_type": "desenvolvimento",
        "host": "127.0.0.1",
        "services": [
            {"name": "licenseVirtual", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSDBAccess64", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSDBAccess64TSS", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
            {"name": "TOTVSservice", "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"},
        ],
        "infra_services": [],
    },
]

ALLOWED_ROLES = {"admin", "technical", "operator"}
SERVICE_PRIORITIES = {"baixa", "media", "alta"}
ACTION_EXECUTOR = ThreadPoolExecutor(max_workers=12)
ACTION_JOBS = {}
ACTION_JOBS_LOCK = threading.Lock()
SERVICE_STATUS_CACHE = {}
SERVICE_STATUS_CACHE_LOCK = threading.Lock()
SERVICE_STATUS_CACHE_TTL_SECONDS = 15
SERVICE_STATUS_MONITOR_INTERVAL_SECONDS = 5
SERVICE_STATUS_MONITOR_THREAD = None
SERVICE_STATUS_MONITOR_LOCK = threading.Lock()
ENVIRONMENT_STATUS_CACHE = {}
ENVIRONMENT_STATUS_CACHE_LOCK = threading.Lock()
SERVER_INVENTORY_CACHE = {}
SERVER_INVENTORY_CACHE_LOCK = threading.Lock()
SERVER_INVENTORY_CACHE_TTL_SECONDS = 300
COLLECTOR_STATUS_PATH = r"C:\gamb-coletor\status-servico.json"
COLLECTOR_DEPLOY_ROOT = r"C:\gamb-coletor"
COLLECTOR_VERSION_MARKER_PATH = os.path.join(COLLECTOR_DEPLOY_ROOT, "collector-version.json")
COLLECTOR_REPO_VERSIONS_DIR = os.path.join("gamb-coletor", "versions")
COLLECTOR_BULK_ACTION_BAT = "gamb-bulk-services.bat"
COLLECTOR_BULK_ACTION_BAT_PATH = os.path.join("gamb-coletor", COLLECTOR_BULK_ACTION_BAT)
COLLECTOR_SERVICE_NAME = "GambColetorService"
COLLECTOR_VERSION_HISTORY_LIMIT = 20
COLLECTOR_DATA_CACHE = {}
COLLECTOR_DATA_CACHE_LOCK = threading.Lock()
COLLECTOR_DATA_CACHE_TTL_SECONDS = 15
COLLECTOR_STALE_SECONDS = 180
COLLECTOR_HEALTH_STATE = {}
COLLECTOR_HEALTH_STATE_LOCK = threading.Lock()
LOCAL_IP_CACHE = {"generated_at": 0.0, "values": {"127.0.0.1"}}
LOCAL_IP_CACHE_LOCK = threading.Lock()
LOCAL_IP_CACHE_TTL_SECONDS = 60
HOST_AVAILABILITY_CACHE = {}
HOST_AVAILABILITY_CACHE_LOCK = threading.Lock()
HOST_AVAILABILITY_CACHE_TTL_SECONDS = 30
ALERT_DISPATCH_LOCK = threading.Lock()
ALERT_LAST_DISPATCH_TS = 0.0

DEFAULT_ALERT_SETTINGS = {
    "disk_free_below_10": True,
    "high_priority_services_stopped": True,
    "production_services_stopped": True,
    "windows_updates_pending": True,
    "collector_json_missing": True,
    "teams_enabled": False,
    "teams_webhook_active": "production",
    "teams_schedule_full_time": True,
    "teams_schedule_days": [0, 1, 2, 3, 4, 5, 6],
    "teams_schedule_start": "00:00",
    "teams_schedule_end": "23:59",
    "teams_alert_severities": ["critical", "warning", "info"],
}

TEAMS_ALERT_SEVERITY_OPTIONS = {"critical", "warning", "info"}

ALERTS_MAX_ITEMS = 100
ALERT_TEAMS_DEDUP_SECONDS = 1800
ALERT_TEAMS_WINDOWS_UPDATES_DEDUP_SECONDS = 7 * 24 * 60 * 60
ALERT_TEAMS_WINDOWS_UPDATES_WEEKDAY = 0  # segunda-feira
ALERT_DISPATCH_INTERVAL_SECONDS = 60
SERVICE_ALERT_SUPPRESSION_SECONDS = 180
README_FILE = "README.md"

_FORCE_HTTPS_ENV = os.getenv("GAMB_FORCE_HTTPS")
GAMB_BEHIND_PROXY = os.getenv("GAMB_BEHIND_PROXY", "0").strip() == "1"
GAMB_SSL_CERT_FILE = (os.getenv("GAMB_SSL_CERT_FILE") or "").strip()
GAMB_SSL_KEY_FILE = (os.getenv("GAMB_SSL_KEY_FILE") or "").strip()
APP_PUBLIC_BASE_URL = (os.getenv("APP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
TEAMS_ACTION_TOKEN_MAX_AGE_SECONDS = 6 * 60 * 60

_HAS_TLS_FILES = bool(
    GAMB_SSL_CERT_FILE
    and GAMB_SSL_KEY_FILE
    and os.path.exists(GAMB_SSL_CERT_FILE)
    and os.path.exists(GAMB_SSL_KEY_FILE)
)

if _FORCE_HTTPS_ENV is None:
    GAMB_FORCE_HTTPS = bool(GAMB_BEHIND_PROXY or _HAS_TLS_FILES)
else:
    GAMB_FORCE_HTTPS = _FORCE_HTTPS_ENV.strip() == "1"

app.config["SESSION_COOKIE_SECURE"] = GAMB_FORCE_HTTPS
app.config["PREFERRED_URL_SCHEME"] = "https" if GAMB_FORCE_HTTPS else "http"

if GAMB_BEHIND_PROXY and ProxyFix:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


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


def get_default_database_update_date(environment_type):
    return date.today().isoformat() if environment_type == "producao" else ""


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
        "server_ip": (
            service.get("server_ip")
            or service.get("ip_address")
            or service.get("ip")
            or ""
        ).strip(),
        "console_log_file": (service.get("console_log_file") or service.get("console_log") or service.get("log_file") or "").strip(),
        "priority": normalize_service_priority(service.get("priority")),
    }


def get_service_server_ip(service, default_host=""):
    if not isinstance(service, dict):
        return str(default_host or "").strip()
    return str(service.get("server_ip") or default_host or "").strip()


def is_infra_service(service):
    if isinstance(service, dict):
        name = (service.get("name") or "").strip().lower()
        display_name = (service.get("display_name") or service.get("displayName") or "").strip().lower()
    else:
        name = str(service or "").strip().lower()
        display_name = ""
    combined = f"{name} {display_name}"
    return any(keyword in combined for keyword in ("dbaccess", "broker", "balance master", "balance", "license", "webagent"))


def sanitize_environment(environment, existing_id=None):
    environment_type = normalize_environment_type(environment.get("environment_type"), environment.get("name"))
    database_update_date = (environment.get("database_update_date") or environment.get("database_updated_at") or "").strip()
    if not database_update_date:
        database_update_date = get_default_database_update_date(environment_type)

    raw_services = list(environment.get("services", []))
    raw_infra_services = list(environment.get("infra_services", []))
    services = []
    infra_services = []

    for raw_service in raw_services + raw_infra_services:
        provided_priority = ""
        if isinstance(raw_service, dict):
            provided_priority = str(raw_service.get("priority") or "").strip()

        service = sanitize_service(raw_service)
        if not service["name"]:
            continue
        if is_infra_service(service):
            if not provided_priority:
                service["priority"] = "alta"
            infra_services.append(service)
        else:
            services.append(service)

    return {
        "id": existing_id or slugify_environment_name(environment.get("name")),
        "name": (environment.get("name") or "").strip(),
        "environment_type": environment_type,
        "host": (environment.get("host") or "").strip(),
        "app_url": (environment.get("app_url") or "").strip(),
        "rest_url": (environment.get("rest_url") or "").strip(),
        "erp_version": (environment.get("erp_version") or "").strip(),
        "database_update_date": database_update_date,
        "services": services,
        "infra_services": infra_services,
    }


def ensure_users_file():
    os.makedirs(DATA_DIR, exist_ok=True)
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
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(ENVIRONMENTS_FILE):
        return
    save_environments(DEFAULT_ENVIRONMENTS)


def normalize_server_list(raw_value):
    if isinstance(raw_value, list):
        raw_items = raw_value
    else:
        raw_items = re.split(r"[\r\n,;]+", str(raw_value or ""))

    normalized = []
    seen = set()
    for item in raw_items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def ensure_servers_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SERVERS_FILE):
        return
    save_servers([])


def sanitize_alert_settings(settings):
    merged = dict(DEFAULT_ALERT_SETTINGS)
    if isinstance(settings, dict):
        if "collector_json_missing" not in settings and "collector_sync_stale" in settings:
            settings = dict(settings)
            settings["collector_json_missing"] = bool(settings.get("collector_sync_stale"))
        if "production_services_stopped" not in settings and "high_priority_services_stopped" in settings:
            settings = dict(settings)
            settings["production_services_stopped"] = bool(settings.get("high_priority_services_stopped"))
        for key in DEFAULT_ALERT_SETTINGS:
            if key not in settings:
                continue
            if key == "teams_webhook_active":
                active_target = str(settings.get(key) or "").strip().lower()
                merged[key] = active_target if active_target in {"production", "homologation"} else DEFAULT_ALERT_SETTINGS[key]
                continue
            if key == "teams_schedule_days":
                days = []
                raw_days = settings.get(key)
                if isinstance(raw_days, list):
                    for day in raw_days:
                        try:
                            day_number = int(day)
                        except Exception:
                            continue
                        if 0 <= day_number <= 6 and day_number not in days:
                            days.append(day_number)
                merged[key] = days or list(DEFAULT_ALERT_SETTINGS[key])
                continue
            if key in {"teams_schedule_start", "teams_schedule_end"}:
                time_value = str(settings.get(key) or "").strip()
                merged[key] = time_value if re.fullmatch(r"\d{2}:\d{2}", time_value) else DEFAULT_ALERT_SETTINGS[key]
                continue
            if key == "teams_alert_severities":
                raw_severities = settings.get(key)
                if raw_severities is None and "teams_alert_kinds" in settings:
                    raw_severities = DEFAULT_ALERT_SETTINGS[key]
                if isinstance(raw_severities, str):
                    raw_severities = [raw_severities]
                severities = []
                if isinstance(raw_severities, list):
                    for severity in raw_severities:
                        normalized_severity = str(severity or "").strip().lower()
                        if normalized_severity in TEAMS_ALERT_SEVERITY_OPTIONS and normalized_severity not in severities:
                            severities.append(normalized_severity)
                merged[key] = severities or list(DEFAULT_ALERT_SETTINGS[key])
                continue
            merged[key] = bool(settings.get(key))
    return merged


def ensure_alert_settings_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(ALERT_SETTINGS_FILE):
        return
    save_alert_settings(DEFAULT_ALERT_SETTINGS)


def load_secret_settings():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SECRET_SETTINGS_FILE):
        return {}
    try:
        with open(SECRET_SETTINGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_secret_settings(settings):
    os.makedirs(DATA_DIR, exist_ok=True)
    normalized = settings if isinstance(settings, dict) else {}
    with open(SECRET_SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
    return normalized


def load_servers():
    ensure_servers_file()
    with open(SERVERS_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, dict):
        data = data.get("servers", [])
    return normalize_server_list(data)


def save_servers(servers):
    os.makedirs(DATA_DIR, exist_ok=True)
    normalized = normalize_server_list(servers)
    with open(SERVERS_FILE, "w", encoding="utf-8") as file:
        json.dump({"servers": normalized}, file, indent=2, ensure_ascii=False)
    invalidate_server_inventory_cache()


def load_alert_settings():
    ensure_alert_settings_file()
    with open(ALERT_SETTINGS_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)
    legacy_webhook = ""
    if isinstance(data, dict):
        legacy_webhook = str(data.get("teams_webhook_url") or "").strip()
    normalized = sanitize_alert_settings(data)
    secret_settings = load_secret_settings()
    changed = normalized != data
    if legacy_webhook and not str(secret_settings.get("teams_webhook_url") or "").strip():
        secret_settings["teams_webhook_url"] = legacy_webhook
        save_secret_settings(secret_settings)
        changed = True
    if changed:
        save_alert_settings(
            {
                **normalized,
                "teams_webhook_production_url": str(secret_settings.get("teams_webhook_url") or "").strip(),
                "teams_webhook_homologation_url": str(secret_settings.get("teams_webhook_homologation_url") or "").strip(),
            }
        )
    secret_settings = load_secret_settings()
    normalized["teams_webhook_url"] = str(secret_settings.get("teams_webhook_url") or "").strip()
    normalized["teams_webhook_production_url"] = normalized["teams_webhook_url"]
    normalized["teams_webhook_homologation_url"] = str(secret_settings.get("teams_webhook_homologation_url") or "").strip()
    return normalized


def save_alert_settings(settings):
    os.makedirs(DATA_DIR, exist_ok=True)
    production_webhook_url = ""
    homologation_webhook_url = ""
    if isinstance(settings, dict):
        production_webhook_url = str(
            settings.get("teams_webhook_production_url")
            or settings.get("teams_webhook_url")
            or ""
        ).strip()
        homologation_webhook_url = str(settings.get("teams_webhook_homologation_url") or "").strip()
    normalized = sanitize_alert_settings(settings)
    with open(ALERT_SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
    secret_settings = load_secret_settings()
    secret_settings["teams_webhook_url"] = production_webhook_url
    secret_settings["teams_webhook_homologation_url"] = homologation_webhook_url
    save_secret_settings(secret_settings)
    normalized["teams_webhook_url"] = str(secret_settings.get("teams_webhook_url") or "").strip()
    normalized["teams_webhook_production_url"] = normalized["teams_webhook_url"]
    normalized["teams_webhook_homologation_url"] = str(secret_settings.get("teams_webhook_homologation_url") or "").strip()
    return normalized


def load_users():
    ensure_users_file()
    with open(USERS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_users(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as file:
        json.dump(users, file, indent=2, ensure_ascii=False)


def load_environments():
    ensure_environments_file()
    with open(ENVIRONMENTS_FILE, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    normalized = []
    changed = False
    for item in data:
        infra_list = item.get("infra_services", [])
        if isinstance(infra_list, list) and infra_list and isinstance(infra_list[0], str):
            item["infra_services"] = [{"name": service_name, "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"} for service_name in infra_list]
            changed = True

        if isinstance(item.get("services", []), list) and item.get("services") and isinstance(item["services"][0], str):
            item = {
                "id": item.get("id") or slugify_environment_name(item.get("name")),
                "name": item.get("name"),
                "host": item.get("host", "127.0.0.1"),
                "services": [{"name": service_name, "display_name": "", "path_executable": "", "tcp_port": "", "webapp_port": "", "rest_port": "", "server_ip": "", "console_log_file": "", "priority": "media"} for service_name in item["services"]],
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
                or "server_ip" not in service
                or "console_log_file" not in service
                or "priority" not in service
            ):
                changed = True

        if any(is_infra_service(service) for service in (item.get("services") or [])):
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
        if "erp_version" not in item:
            item["erp_version"] = ""
            changed = True
        if "database_update_date" not in item and "database_updated_at" not in item:
            item["database_update_date"] = get_default_database_update_date(
                normalize_environment_type(item.get("environment_type"), item.get("name"))
            )
            changed = True

        normalized.append(sanitize_environment(item, item.get("id") or slugify_environment_name(item.get("name"))))

    if changed:
        save_environments(normalized)

    return normalized


def save_environments(environments):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ENVIRONMENTS_FILE, "w", encoding="utf-8") as file:
        json.dump(environments, file, indent=2, ensure_ascii=False)
    invalidate_environment_status_cache()


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


def build_remote_targets(hosts):
    normalized_hosts = [host.strip() for host in (hosts or []) if is_valid_remote_host(host)]
    if not normalized_hosts:
        return [], ["Nenhum host válido informado."]

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
    return targets, step_logs


def get_winrm_troubleshooting_hint(server, raw_error):
    if "TrustedHosts" in raw_error and "WinRM" in raw_error and "IP address" in raw_error:
        return (
            "Use hostname (não IP) se possível, ou adicione o destino em TrustedHosts no servidor que executa o monitor "
            f"(ex.: `Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value \"{server}\" -Concatenate -Force`) "
            "e garanta que o WinRM/PSRemoting esteja habilitado no destino (ex.: `Enable-PSRemoting -Force`)."
        )
    return ""


def get_cached_server_inventory(hosts):
    normalized_hosts = normalize_server_list(hosts)
    with SERVER_INVENTORY_CACHE_LOCK:
        generated_at = float(SERVER_INVENTORY_CACHE.get("generated_at") or 0)
        cached_hosts = normalize_server_list(SERVER_INVENTORY_CACHE.get("hosts") or [])
        if not generated_at or cached_hosts != normalized_hosts:
            return None
        if (time.time() - generated_at) > SERVER_INVENTORY_CACHE_TTL_SECONDS:
            return None
        return dict(SERVER_INVENTORY_CACHE)


def set_cached_server_inventory(hosts, payload):
    with SERVER_INVENTORY_CACHE_LOCK:
        SERVER_INVENTORY_CACHE.clear()
        SERVER_INVENTORY_CACHE.update(
            {
                "hosts": normalize_server_list(hosts),
                "generated_at": time.time(),
                **payload,
            }
        )


def invalidate_server_inventory_cache():
    with SERVER_INVENTORY_CACHE_LOCK:
        SERVER_INVENTORY_CACHE.clear()


def build_server_alerts_payload(force_refresh=False):
    servers = load_servers()
    if not servers:
        return {
            "success": True,
            "alerts": [],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cached": False,
        }

    payload = None
    if not force_refresh:
        payload = get_cached_server_inventory(servers)
    if not payload:
        payload = collect_server_inventory(servers)
        payload["cached"] = False
        if payload.get("success"):
            set_cached_server_inventory(servers, payload)

    items = list(payload.get("items") or [])
    alerts = []
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "success":
            continue

        server_name = str(item.get("device_name") or item.get("server") or "").strip()
        server_ip = ", ".join([str(ip).strip() for ip in (item.get("ip_addresses") or []) if str(ip).strip()]) or str(item.get("server") or "").strip()

        if item.get("has_pending_updates") is True:
            alerts.append(
                {
                    "server_name": server_name,
                    "server_ip": server_ip,
                    "type": "updates",
                    "message": f"{server_name or server_ip} possui {int(item.get('pending_update_count') or 0)} atualização(ões) de software pendente(s).",
                }
            )

        for disk in (item.get("disks") or []):
            if not isinstance(disk, dict):
                continue
            total_bytes = float(disk.get("total_bytes") or 0)
            free_bytes = float(disk.get("free_bytes") or 0)
            if total_bytes <= 0:
                continue
            free_percent = round((free_bytes * 100.0) / total_bytes, 2)
            if free_percent <= 50:
                drive_name = str(disk.get("drive") or "").strip() or "Disco"
                alerts.append(
                    {
                        "server_name": server_name,
                        "server_ip": server_ip,
                        "type": "disk",
                        "drive": drive_name,
                        "free_percent": free_percent,
                        "message": f"{server_name or server_ip} está com {free_percent:.2f}% livre no disco {drive_name}.",
                    }
                )

    return {
        "success": True,
        "alerts": alerts,
        "generated_at": payload.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cached": bool(payload.get("cached")),
    }


def _parse_float_pt_br(value):
    try:
        return float(str(value or "").strip().replace(".", "").replace(",", "."))
    except Exception:
        return None


def extract_collector_disk_units(collector_server):
    units = []
    seen = set()
    raw_text = str((collector_server or {}).get("disk_space") or "").strip()
    if raw_text:
        for match in re.finditer(r"([A-Za-z]:)\s*([\d.,]+)\s*%\s*livre", raw_text, flags=re.IGNORECASE):
            drive = match.group(1).upper()
            free_percent = _parse_float_pt_br(match.group(2))
            if free_percent is None:
                continue
            key = drive.lower()
            if key in seen:
                continue
            seen.add(key)
            units.append({"drive": drive, "free_percent": free_percent})

    if units:
        return units

    disk_total_gb = collector_server.get("disk_total_gb")
    disk_free_gb = collector_server.get("disk_free_gb")
    try:
        total = float(disk_total_gb or 0)
        free = float(disk_free_gb or 0)
    except Exception:
        total = 0
        free = 0
    if total > 0:
        units.append({"drive": "Disco", "free_percent": round((free * 100.0) / total, 2)})
    return units


def service_status_is_stopped(status_text):
    normalized = str(status_text or "").strip().upper()
    return normalized in {"PARADO", "STOPPED"}


def collector_payload_missing(payload):
    if not isinstance(payload, dict):
        return True
    server = payload.get("server") or {}
    services_by_name = payload.get("services_by_name") or {}
    return not server and not services_by_name


def get_collector_sync_state(payload, host_online=None):
    if host_online is False:
        return "offline"
    if collector_payload_missing(payload):
        return "unreachable"
    collector_server = (payload or {}).get("server") or {}
    if is_collector_stale(collector_server):
        return "stale"
    return "healthy"


def build_alert_signature(alert):
    return json.dumps(
            {
                "kind": alert.get("kind"),
                "severity": alert.get("severity"),
                "environment_id": alert.get("environment_id"),
                "host": alert.get("host"),
                "server_ip": alert.get("server_ip"),
                "service_name": alert.get("service_name"),
                "drive": alert.get("drive"),
                "windows_updates_pending": alert.get("windows_updates_pending"),
                "message": alert.get("message"),
            },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_teams_alert_signature(alert):
    if str((alert or {}).get("kind") or "").strip() == "windows_updates":
        return json.dumps(
            {
                "kind": alert.get("kind"),
                "severity": alert.get("severity"),
                "environment_id": alert.get("environment_id"),
                "host": alert.get("host"),
                "server_ip": alert.get("server_ip"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    return build_alert_signature(alert)


def get_teams_alert_dedup_seconds(alert):
    if str((alert or {}).get("kind") or "").strip() == "windows_updates":
        return ALERT_TEAMS_WINDOWS_UPDATES_DEDUP_SECONDS
    return ALERT_TEAMS_DEDUP_SECONDS


def is_teams_windows_updates_delivery_day(when=None):
    when = when or datetime.now()
    return when.weekday() == ALERT_TEAMS_WINDOWS_UPDATES_WEEKDAY


def build_service_alert_state_key(kind, environment_id, host, service_name):
    return json.dumps(
        {
            "kind": str(kind or "").strip(),
            "environment_id": str(environment_id or "").strip(),
            "host": str(host or "").strip(),
            "service_name": str(service_name or "").strip(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_service_recovery_alert(service_state):
    display_name = str(
        service_state.get("display_name")
        or service_state.get("service_name")
        or "Serviço"
    ).strip() or "Serviço"
    environment_name = str(service_state.get("environment_name") or "Ambiente").strip() or "Ambiente"
    host = str(service_state.get("host") or "-").strip() or "-"
    return {
        "kind": "service_recovered",
        "severity": "info",
        "environment_id": service_state.get("environment_id"),
        "environment_name": environment_name,
        "host": host,
        "server_ip": service_state.get("server_ip") or host,
        "service_name": str(service_state.get("service_name") or "").strip(),
        "title": "Serviço voltou a funcionar",
        "message": f"{display_name} voltou a funcionar no ambiente {environment_name}.",
    }


def build_service_stopped_alert_from_state(service_state):
    kind = str(service_state.get("kind") or "").strip()
    display_name = str(
        service_state.get("display_name")
        or service_state.get("service_name")
        or "Serviço"
    ).strip() or "Serviço"
    environment_name = str(service_state.get("environment_name") or "Ambiente").strip() or "Ambiente"
    host = str(service_state.get("host") or "-").strip() or "-"
    title = "Serviço parado em produção" if kind == "production_service_stopped" else "Serviço crítico parado"
    return {
        "kind": kind,
        "severity": "critical",
        "environment_id": service_state.get("environment_id"),
        "environment_name": environment_name,
        "host": host,
        "server_ip": service_state.get("server_ip") or host,
        "service_name": str(service_state.get("service_name") or "").strip(),
        "title": title,
        "message": f"{display_name} está parado no ambiente {environment_name}.",
    }


def load_alert_delivery_state():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(ALERT_DELIVERY_STATE_FILE):
        with open(ALERT_DELIVERY_STATE_FILE, "w", encoding="utf-8") as file:
            json.dump({"teams": {}}, file, indent=2, ensure_ascii=False)
        return {"teams": {}}
    try:
        with open(ALERT_DELIVERY_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {"teams": {}}
        teams = data.get("teams")
        if not isinstance(teams, dict):
            data["teams"] = {}
        return data
    except Exception:
        return {"teams": {}}


def save_alert_delivery_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERT_DELIVERY_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state or {"teams": {}}, file, indent=2, ensure_ascii=False)


def clear_operational_logs():
    os.makedirs(DATA_DIR, exist_ok=True)
    targets = [
        (LOG_FILE, []),
        (EXECUTION_TRACE_FILE, []),
        (ALERT_DELIVERY_STATE_FILE, {"teams": {}}),
    ]
    cleared = []
    for file_path, empty_payload in targets:
        previous_count = 0
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8-sig") as file:
                    current_payload = json.load(file)
                if isinstance(current_payload, list):
                    previous_count = len(current_payload)
                elif isinstance(current_payload, dict):
                    previous_count = sum(
                        len(value) for value in current_payload.values()
                        if isinstance(value, dict)
                    )
            except Exception:
                previous_count = 0
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(empty_payload, file, indent=2, ensure_ascii=False)
        cleared.append(
            {
                "file": os.path.basename(file_path),
                "previous_count": previous_count,
            }
        )
    return cleared


def get_teams_webhook_url(settings=None):
    if isinstance(settings, dict):
        active_target = str(settings.get("teams_webhook_active") or "production").strip().lower()
        if active_target == "homologation":
            configured = str(settings.get("teams_webhook_homologation_url") or "").strip()
        else:
            configured = str(settings.get("teams_webhook_production_url") or settings.get("teams_webhook_url") or "").strip()
        if configured:
            return configured
    return TEAMS_WEBHOOK


def get_teams_action_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="teams-service-action")


def get_public_app_base_url():
    if APP_PUBLIC_BASE_URL:
        return APP_PUBLIC_BASE_URL
    if has_request_context():
        return request.url_root.rstrip("/")
    return ""


def build_teams_service_action_token(environment_id, service_name, host, action_type="start"):
    payload = {
        "environment_id": str(environment_id or "").strip(),
        "service_name": str(service_name or "").strip(),
        "host": str(host or "").strip(),
        "action": str(action_type or "start").strip().lower(),
    }
    return get_teams_action_serializer().dumps(payload)


def load_teams_service_action_token(token, max_age=TEAMS_ACTION_TOKEN_MAX_AGE_SECONDS):
    try:
        return get_teams_action_serializer().loads(str(token or "").strip(), max_age=max_age)
    except SignatureExpired as exc:
        raise ValueError("O link de ação do Teams expirou.") from exc
    except BadSignature as exc:
        raise ValueError("O link de ação do Teams é inválido.") from exc


def build_teams_service_action_url(alert, action_type="start"):
    base_url = get_public_app_base_url()
    if not base_url:
        return ""
    environment_id = str((alert or {}).get("environment_id") or "").strip()
    service_name = str((alert or {}).get("service_name") or "").strip()
    host = str((alert or {}).get("host") or "").strip()
    if not environment_id or not service_name:
        return ""
    token = build_teams_service_action_token(environment_id, service_name, host, action_type=action_type)
    return f"{base_url}/teams/service-action?token={token}"


def get_environment_collector_target_hosts(environment, environment_status=None):
    hosts = []

    def add_host(value):
        host_value = str(value or "").strip()
        if host_value:
            hosts.append(host_value)

    add_host((environment or {}).get("host"))
    for service in ((environment or {}).get("services") or []) + ((environment or {}).get("infra_services") or []):
        add_host(get_service_server_ip(service))
    if isinstance(environment_status, dict):
        for service in (environment_status.get("services") or []) + (environment_status.get("infra_services") or []):
            add_host(get_service_server_ip(service))

    unique_hosts = []
    seen_hosts = set()
    for host_value in hosts:
        host_key = _normalize_service_lookup_key(host_value)
        if host_key in seen_hosts:
            continue
        seen_hosts.add(host_key)
        unique_hosts.append(host_value)
    return unique_hosts


def build_windows_update_alerts_for_environment(environment, environment_status, environment_name, default_host):
    alerts = []
    seen_server_ips = set()
    for target_host in get_environment_collector_target_hosts(environment, environment_status):
        collector_payload = load_collector_status_for_host(target_host, use_cache=False)
        collector_server = (collector_payload or {}).get("server") or {}
        if collector_payload_missing(collector_payload) or is_collector_stale(collector_server):
            continue
        if is_host_online(target_host, use_cache=True) is False:
            continue

        server_ip = str(collector_server.get("server_ip") or target_host or default_host).strip() or default_host
        server_key = _normalize_service_lookup_key(server_ip)
        if server_key in seen_server_ips:
            continue
        seen_server_ips.add(server_key)

        pending_updates = read_collector_pending_updates(collector_server)
        if not pending_updates or pending_updates <= 0:
            continue
        alerts.append(
            {
                "kind": "windows_updates",
                "severity": "info",
                "environment_id": (environment_status or {}).get("id") or (environment or {}).get("id"),
                "environment_name": environment_name,
                "host": server_ip,
                "server_ip": server_ip,
                "server_name": str(collector_server.get("server_name") or "").strip(),
                "windows_updates_pending": pending_updates,
                "title": "Atualizações pendentes do Windows",
                "message": f"{server_ip} possui {pending_updates} atualização(ões) de software pendente(s) no Windows.",
            }
        )
    return alerts


def build_monitor_alerts_payload(user=None, include_all=False):
    settings = load_alert_settings()
    alerts = []
    service_alert_states = {}
    environments = load_environments()
    accessible_environments = [
        environment
        for environment in environments
        if include_all or can_user_access_environment(user, environment)
    ]

    severity_order = {"critical": 0, "warning": 1, "info": 2}

    for environment in accessible_environments:
        environment_status = build_environment_status(environment)
        environment_name = str(environment_status.get("environment") or environment.get("name") or "").strip() or "Ambiente"
        host = str(environment_status.get("host") or environment.get("host") or "").strip() or "local"
        collector_server = environment_status.get("collector_server") or {}
        collector_hosts_status = environment_status.get("collector_hosts") or []
        collector_stale = any(str(item.get("sync_state") or "") == "stale" for item in collector_hosts_status if isinstance(item, dict))

        if settings.get("collector_json_missing"):
            checked_hosts = set()
            collector_hosts = get_environment_collector_target_hosts(environment, environment_status)
            for collector_host in collector_hosts:
                normalized_host = collector_host.lower()
                if normalized_host in checked_hosts:
                    continue
                checked_hosts.add(normalized_host)
                collector_payload = load_collector_status_for_host(collector_host, use_cache=True)
                if not collector_payload_missing(collector_payload):
                    continue
                host_online = is_host_online(collector_host, use_cache=True)
                sync_state = get_collector_sync_state(collector_payload, host_online)
                alerts.append(
                    {
                        "kind": "collector_host_offline" if sync_state == "offline" else "collector_json_missing",
                        "severity": "critical",
                        "environment_id": environment_status.get("id"),
                        "environment_name": environment_name,
                        "host": collector_host,
                        "title": "Servidor possivelmente desligado" if sync_state == "offline" else "JSON do coletor inacessível",
                        "message": (
                            f"{environment_name} não conseguiu sincronizar com o host {collector_host}; o servidor pode estar desligado ou inacessível."
                            if sync_state == "offline"
                            else f"{environment_name} não conseguiu ler o status-servico.json no host {collector_host}."
                        ),
                    }
                )

        if settings.get("windows_updates_pending"):
            alerts.extend(build_windows_update_alerts_for_environment(environment, environment_status, environment_name, host))

        if collector_stale:
            continue

        if settings.get("disk_free_below_10"):
            for disk in extract_collector_disk_units(collector_server):
                free_percent = float(disk.get("free_percent") or 0)
                if free_percent > 10:
                    continue
                drive = str(disk.get("drive") or "Disco").strip() or "Disco"
                alerts.append(
                    {
                        "kind": "disk",
                        "severity": "critical",
                        "environment_id": environment_status.get("id"),
                        "environment_name": environment_name,
                        "host": host,
                        "drive": drive,
                        "free_percent": round(free_percent, 2),
                        "title": "Espaço em disco crítico",
                        "message": f"{environment_name} está com {free_percent:.1f}% livre na unidade {drive}.",
                    }
                )

        environment_type = normalize_environment_type(
            environment.get("environment_type"),
            environment.get("name"),
        )
        is_production = environment_type == "producao"

        if settings.get("production_services_stopped") and is_production:
            for service in (environment_status.get("services") or []) + (environment_status.get("infra_services") or []):
                if str(service.get("collector_sync_state") or "") != "healthy":
                    continue
                if should_suppress_stopped_service_alert(environment, environment_status, service):
                    continue
                display_name = str(service.get("display_name") or service.get("name") or "Serviço").strip() or "Serviço"
                server_ip = get_service_server_ip(service, host)
                is_stopped = service_status_is_stopped(service.get("status"))
                state_key = build_service_alert_state_key(
                    "production_service_stopped",
                    environment_status.get("id"),
                    server_ip,
                    service.get("name"),
                )
                service_alert_states[state_key] = {
                    "kind": "production_service_stopped",
                    "environment_id": environment_status.get("id"),
                    "environment_name": environment_name,
                    "host": server_ip,
                    "server_ip": server_ip,
                    "service_name": str(service.get("name") or "").strip(),
                    "display_name": display_name,
                    "is_active": is_stopped,
                }
                if not is_stopped:
                    continue
                alerts.append(
                    {
                        "kind": "production_service_stopped",
                        "severity": "critical",
                        "environment_id": environment_status.get("id"),
                        "environment_name": environment_name,
                        "host": server_ip,
                        "service_name": str(service.get("name") or "").strip(),
                        "title": "Serviço parado em produção",
                        "message": f"{display_name} está parado no ambiente {environment_name}.",
                    }
                )

        if settings.get("high_priority_services_stopped") and not is_production:
            for service in (environment_status.get("services") or []) + (environment_status.get("infra_services") or []):
                if str(service.get("collector_sync_state") or "") != "healthy":
                    continue
                if should_suppress_stopped_service_alert(environment, environment_status, service):
                    continue
                if normalize_service_priority(service.get("priority")) != "alta":
                    continue
                display_name = str(service.get("display_name") or service.get("name") or "Serviço").strip() or "Serviço"
                server_ip = get_service_server_ip(service, host)
                is_stopped = service_status_is_stopped(service.get("status"))
                state_key = build_service_alert_state_key(
                    "high_priority_service",
                    environment_status.get("id"),
                    server_ip,
                    service.get("name"),
                )
                service_alert_states[state_key] = {
                    "kind": "high_priority_service",
                    "environment_id": environment_status.get("id"),
                    "environment_name": environment_name,
                    "host": server_ip,
                    "server_ip": server_ip,
                    "service_name": str(service.get("name") or "").strip(),
                    "display_name": display_name,
                    "is_active": is_stopped,
                }
                if not is_stopped:
                    continue
                alerts.append(
                    {
                        "kind": "high_priority_service",
                        "severity": "critical",
                        "environment_id": environment_status.get("id"),
                        "environment_name": environment_name,
                        "host": server_ip,
                        "service_name": str(service.get("name") or "").strip(),
                        "title": "Serviço crítico parado",
                        "message": f"{display_name} está parado no ambiente {environment_name}.",
                    }
                )

    alerts.sort(
        key=lambda item: (
            severity_order.get(item.get("severity"), 9),
            str(item.get("environment_name") or ""),
            str(item.get("title") or ""),
            str(item.get("message") or ""),
        )
    )

    unique_alerts = []
    seen_alerts = set()
    for alert in alerts:
        signature = build_alert_signature(alert)
        if signature in seen_alerts:
            continue
        seen_alerts.add(signature)
        unique_alerts.append(alert)

    return {
        "success": True,
        "settings": settings,
        "alerts": unique_alerts[:ALERTS_MAX_ITEMS],
        "service_alert_states": service_alert_states,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_alerts_signature(alerts):
    normalized = []
    for alert in alerts if isinstance(alerts, list) else []:
        if not isinstance(alert, dict):
            continue
        normalized.append(
            {
                "kind": alert.get("kind"),
                "severity": alert.get("severity"),
                "environment_id": alert.get("environment_id"),
                "service_name": alert.get("service_name"),
                "drive": alert.get("drive"),
                "message": alert.get("message"),
            }
        )
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def collect_server_inventory(hosts):
    targets, step_logs = build_remote_targets(hosts)
    if not targets:
        return {"success": True, "items": [], "steps": step_logs, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    targets_literal = ",".join(
        [
            "@{ input='" + item["input"].replace("'", "''") + "'; connect='" + item["connect"].replace("'", "''") + "' }"
            for item in targets
        ]
    )

    script = rf"""
$ErrorActionPreference = 'Stop'
$targets = @({targets_literal})
$results = @()

function Get-ServerInventoryByWmi($computerName) {{
    $computerSystem = Get-WmiObject -Class Win32_ComputerSystem -ComputerName $computerName -ErrorAction Stop
    $os = Get-WmiObject -Class Win32_OperatingSystem -ComputerName $computerName -ErrorAction Stop

    $diskRows = @()
    try {{
        $disks = Get-WmiObject -Class Win32_LogicalDisk -ComputerName $computerName -Filter "DriveType = 3" -ErrorAction Stop | Sort-Object DeviceID
        foreach ($disk in $disks) {{
            $size = [int64]($disk.Size | ForEach-Object {{ $_ }})
            $free = [int64]($disk.FreeSpace | ForEach-Object {{ $_ }})
            $used = $size - $free
            $percentUsed = if ($size -gt 0) {{ [Math]::Round((($used * 100.0) / $size), 2) }} else {{ 0 }}
            $diskRows += [PSCustomObject]@{{
                drive = [string]$disk.DeviceID
                volume_name = [string]$disk.VolumeName
                total_bytes = $size
                used_bytes = $used
                free_bytes = $free
                percent_used = $percentUsed
            }}
        }}
    }} catch {{
        $diskRows = @()
    }}

    $ipAddresses = @()
    try {{
        $ipAddresses = Get-WmiObject -Class Win32_NetworkAdapterConfiguration -ComputerName $computerName -Filter "IPEnabled = True" -ErrorAction Stop |
            ForEach-Object {{ $_.IPAddress }} |
            Where-Object {{ $_ -match '^\d{{1,3}}(\.\d{{1,3}}){{3}}$' -and $_ -ne '127.0.0.1' }} |
            Select-Object -Unique
    }} catch {{
        $ipAddresses = @()
    }}

    $lastUpdateDate = ''
    try {{
        $lastHotfix = Get-WmiObject -Class Win32_QuickFixEngineering -ComputerName $computerName -ErrorAction Stop |
            Where-Object {{ $_.InstalledOn }} |
            Sort-Object InstalledOn -Descending |
            Select-Object -First 1
        if ($lastHotfix -and $lastHotfix.InstalledOn) {{
            $lastUpdateDate = (Get-Date $lastHotfix.InstalledOn).ToString('yyyy-MM-dd')
        }}
    }} catch {{
        $lastUpdateDate = ''
    }}

    $lastRestart = ''
    try {{
        if ($os.LastBootUpTime) {{
            $lastRestart = ([System.Management.ManagementDateTimeConverter]::ToDateTime($os.LastBootUpTime)).ToString('yyyy-MM-dd HH:mm:ss')
        }}
    }} catch {{
        $lastRestart = ''
    }}

    return [PSCustomObject]@{{
        device_name = [string]($computerSystem.Name)
        ip_addresses = @($ipAddresses)
        disks = @($diskRows)
        last_windows_update = $lastUpdateDate
        has_pending_updates = $null
        pending_update_count = $null
        pending_updates_error = 'Não foi possível verificar atualizações pendentes sem acesso remoto via WinRM.'
        last_restart = $lastRestart
        collection_method = 'WMI'
    }}
}}

foreach ($t in $targets) {{
    $inputHost = $t.input
    $connectHost = $t.connect
    $candidateHosts = @($connectHost, $inputHost) | Where-Object {{ $_ }} | Select-Object -Unique
    $lastError = $null
    $connectedBy = $null
    foreach ($candidateHost in $candidateHosts) {{
        try {{
            $rows = Invoke-Command -ComputerName $candidateHost -ScriptBlock {{
            $computerSystem = Get-CimInstance Win32_ComputerSystem
            $os = Get-CimInstance Win32_OperatingSystem
            $diskRows = @()
            try {{
                $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType = 3" | Sort-Object DeviceID
                foreach ($disk in $disks) {{
                    $size = [int64]($disk.Size | ForEach-Object {{ $_ }})
                    $free = [int64]($disk.FreeSpace | ForEach-Object {{ $_ }})
                    $used = $size - $free
                    $percentUsed = if ($size -gt 0) {{ [Math]::Round((($used * 100.0) / $size), 2) }} else {{ 0 }}
                    $diskRows += [PSCustomObject]@{{
                        drive = [string]$disk.DeviceID
                        volume_name = [string]$disk.VolumeName
                        total_bytes = $size
                        used_bytes = $used
                        free_bytes = $free
                        percent_used = $percentUsed
                    }}
                }}
            }} catch {{
                $diskRows = @()
            }}

            $ipAddresses = @()
            try {{
                $ipAddresses = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled = True" |
                    ForEach-Object {{ $_.IPAddress }} |
                    Where-Object {{ $_ -match '^\d{{1,3}}(\.\d{{1,3}}){{3}}$' -and $_ -ne '127.0.0.1' }} |
                    Select-Object -Unique
            }} catch {{
                $ipAddresses = @()
            }}

            $lastUpdateDate = ''
            try {{
                $lastHotfix = Get-HotFix | Where-Object {{ $_.InstalledOn }} | Sort-Object InstalledOn -Descending | Select-Object -First 1
                if ($lastHotfix -and $lastHotfix.InstalledOn) {{
                    $lastUpdateDate = (Get-Date $lastHotfix.InstalledOn).ToString('yyyy-MM-dd')
                }}
            }} catch {{
                $lastUpdateDate = ''
            }}

            $pendingCount = $null
            $pendingError = ''
            try {{
                $updateSession = New-Object -ComObject Microsoft.Update.Session
                $updateSearcher = $updateSession.CreateUpdateSearcher()
                $searchResult = $updateSearcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
                $pendingCount = [int]$searchResult.Updates.Count
            }} catch {{
                $pendingError = $_.Exception.Message
            }}

            $lastRestart = ''
            try {{
                if ($os.LastBootUpTime) {{
                    $lastRestart = ([System.Management.ManagementDateTimeConverter]::ToDateTime($os.LastBootUpTime)).ToString('yyyy-MM-dd HH:mm:ss')
                }}
            }} catch {{
                $lastRestart = ''
            }}

            [PSCustomObject]@{{
                device_name = [string]($computerSystem.Name)
                ip_addresses = @($ipAddresses)
                disks = @($diskRows)
                last_windows_update = $lastUpdateDate
                has_pending_updates = if ($pendingCount -eq $null) {{ $null }} else {{ [bool]($pendingCount -gt 0) }}
                pending_update_count = $pendingCount
                pending_updates_error = $pendingError
                last_restart = $lastRestart
                collection_method = 'WinRM'
            }}
            }}

            foreach ($r in $rows) {{
                $r | Add-Member -NotePropertyName 'server' -NotePropertyValue $inputHost -Force
                $r | Add-Member -NotePropertyName 'connect_host' -NotePropertyValue $candidateHost -Force
                $results += $r
            }}
            $connectedBy = $candidateHost
            break
        }} catch {{
            $lastError = $_.Exception.Message
            try {{
                $wmiRow = Get-ServerInventoryByWmi $candidateHost
                $wmiRow | Add-Member -NotePropertyName 'server' -NotePropertyValue $inputHost -Force
                $wmiRow | Add-Member -NotePropertyName 'connect_host' -NotePropertyValue $candidateHost -Force
                $wmiRow | Add-Member -NotePropertyName 'fallback_reason' -NotePropertyValue $lastError -Force
                $results += $wmiRow
                $connectedBy = $candidateHost
                break
            }} catch {{
                $lastError = "$lastError | WMI fallback: $($_.Exception.Message)"
            }}
        }}
    }}

    if (-not $connectedBy) {{
        $results += [PSCustomObject]@{{ server = $inputHost; connect_host = $connectHost; tried_hosts = @($candidateHosts); error = $lastError }}
    }}
}}

if ($results.Count -eq 0) {{
    Write-Output '[]'
}} else {{
    $results | ConvertTo-Json -Depth 8
}}
"""

    code, stdout, stderr = run_powershell(script)
    if code != 0:
        return {
            "success": False,
            "error": (stderr or stdout or "Falha ao executar PowerShell.").strip(),
            "items": [],
            "steps": step_logs,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    raw = (stdout or "").strip()
    if not raw:
        step_logs.append("Execução concluída sem retorno dos servidores.")
        return {"success": True, "items": [], "steps": step_logs, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    try:
        data = json.loads(raw)
    except Exception:
        return {
            "success": False,
            "error": "Não foi possível interpretar o retorno do inventário de servidores.",
            "details": raw[:5000],
            "items": [],
            "steps": step_logs,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    if isinstance(data, dict):
        data = [data]

    items = []
    errors = []
    for row in data:
        if not isinstance(row, dict):
            continue

        server = str(row.get("server") or "").strip()
        connect_host = str(row.get("connect_host") or "").strip()
        if row.get("error"):
            raw_error = str(row.get("error") or "").strip()
            hint = get_winrm_troubleshooting_hint(server, raw_error)
            tried_hosts = row.get("tried_hosts") or []
            if isinstance(tried_hosts, str):
                tried_hosts = [tried_hosts]
            tried_hosts = [str(item).strip() for item in tried_hosts if str(item).strip()]
            step_logs.append(f"[{server}] Falha ao consultar inventário: {raw_error}")
            items.append(
                {
                    "server": server,
                    "connect_host": connect_host,
                    "status": "error",
                    "error": raw_error,
                    "hint": hint,
                    "tried_hosts": tried_hosts,
                }
            )
            errors.append({"server": server, "error": raw_error, "hint": hint})
            continue

        disks = row.get("disks") or []
        if isinstance(disks, dict):
            disks = [disks]
        normalized_disks = []
        for disk in disks:
            if not isinstance(disk, dict):
                continue
            normalized_disks.append(
                {
                    "drive": str(disk.get("drive") or "").strip(),
                    "volume_name": str(disk.get("volume_name") or "").strip(),
                    "total_bytes": int(float(disk.get("total_bytes") or 0)),
                    "used_bytes": int(float(disk.get("used_bytes") or 0)),
                    "free_bytes": int(float(disk.get("free_bytes") or 0)),
                    "percent_used": float(disk.get("percent_used") or 0),
                }
            )

        ip_addresses = row.get("ip_addresses") or []
        if isinstance(ip_addresses, str):
            ip_addresses = [ip_addresses]
        ip_addresses = [str(item).strip() for item in ip_addresses if str(item).strip()]
        if server and server not in ip_addresses and is_ipv4_address(server):
            ip_addresses.insert(0, server)

        pending_count = row.get("pending_update_count")
        if pending_count in ("", None):
            pending_count = None
        else:
            try:
                pending_count = int(pending_count)
            except Exception:
                pending_count = None

        item = {
            "server": server,
            "connect_host": connect_host,
            "status": "success",
            "device_name": str(row.get("device_name") or "").strip() or connect_host or server,
            "ip_addresses": ip_addresses,
            "disks": normalized_disks,
            "last_windows_update": str(row.get("last_windows_update") or "").strip(),
            "has_pending_updates": row.get("has_pending_updates"),
            "pending_update_count": pending_count,
            "pending_updates_error": str(row.get("pending_updates_error") or "").strip(),
            "last_restart": str(row.get("last_restart") or "").strip(),
            "collection_method": str(row.get("collection_method") or "").strip() or "WinRM",
            "fallback_reason": str(row.get("fallback_reason") or "").strip(),
        }
        items.append(item)
        step_logs.append(
            f"[{server}] Inventário carregado: dispositivo {item['device_name']}, {len(normalized_disks)} disco(s), "
            f"última atualização {item['last_windows_update'] or 'não informada'}."
        )
        if item["collection_method"] == "WMI" and item["fallback_reason"]:
            step_logs.append(f"[{server}] Coleta obtida via fallback WMI após falha WinRM: {item['fallback_reason']}")

    return {
        "success": True,
        "items": items,
        "errors": errors,
        "steps": step_logs,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


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

    discovered = []
    discovered_keys = set()
    errors = []
    host_results = []

    for target in targets:
        source_host = (target.get("input") or "").strip()
        connect_host = (target.get("connect") or "").strip()
        host_result = {
            "host": source_host,
            "connect_host": connect_host,
            "status": "error",
            "services": 0,
            "infra_services": 0,
            "ignored_services": 0,
            "message": "",
        }
        collector_payload = load_collector_status_for_host(connect_host or source_host, use_cache=False)
        collector_services = (collector_payload.get("services") or [])
        collector_server_ip = ((collector_payload.get("server") or {}).get("server_ip") or "").strip()
        if collector_services:
            step_logs.append(f"[{source_host}] status-servico.json carregado com sucesso.")
            added_services = 0
            added_infra = 0
            ignored_without_path = 0
            for service in collector_services:
                name = (service.get("name") or "").strip()
                if not name:
                    continue
                path_executable = (service.get("path_executable") or "").strip()
                if not path_executable:
                    step_logs.append(f"[{source_host}] Serviço ignorado sem path_executable no JSON do coletor: {name}.")
                    ignored_without_path += 1
                    continue

                row = {
                    "name": name,
                    "display_name": (service.get("display_name") or "").strip(),
                    "server_ip": collector_server_ip or source_host,
                    "path_executable": path_executable,
                    "tcp_port": service.get("tcp_port", ""),
                    "webapp_port": service.get("webapp_port", ""),
                    "rest_port": service.get("rest_port", ""),
                    "console_log_file": service.get("console_log_file", ""),
                    "priority": "media",
                    "_meta": {
                        "source": "collector_json",
                        "host": source_host,
                        "connect_host": connect_host,
                        "service_state": (service.get("status") or "").upper(),
                    },
                }
                key = (_normalize_service_lookup_key(row["server_ip"]), _normalize_service_lookup_key(row["name"]))
                if key in discovered_keys:
                    continue
                discovered_keys.add(key)
                discovered.append(row)
                if is_infra_service(row):
                    added_infra += 1
                else:
                    added_services += 1
            host_result.update(
                {
                    "status": "success",
                    "services": added_services,
                    "infra_services": added_infra,
                    "ignored_services": ignored_without_path,
                    "message": (
                        f"Sucesso: {added_services} serviço(s), {added_infra} infra, "
                        f"{ignored_without_path} ignorado(s)."
                    ),
                }
            )
            step_logs.append(
                f"[{source_host}] Busca bem-sucedida: {added_services} serviço(s), "
                f"{added_infra} infra e {ignored_without_path} ignorado(s)."
            )
        else:
            errors.append(
                {
                    "server": source_host,
                    "error": "Arquivo do gamb-coletor nao encontrado, vazio ou sem servicos validos.",
                    "hint": "Garanta que o coletor esteja executando no servidor e atualizando C:\\gamb-coletor\\status-servico.json.",
                }
            )
            step_logs.append(f"[{source_host}] Falha: status-servico.json indisponivel no gamb-coletor.")
            host_result["message"] = "Falha: arquivo ausente, vazio ou sem serviços válidos."
        host_results.append(host_result)

    success_hosts = sum(1 for item in host_results if item.get("status") == "success")
    failed_hosts = len(host_results) - success_hosts
    service_total = sum(int(item.get("services") or 0) for item in host_results)
    infra_total = sum(int(item.get("infra_services") or 0) for item in host_results)
    ignored_total = sum(int(item.get("ignored_services") or 0) for item in host_results)

    if success_hosts and not failed_hosts:
        result_status = "success"
        result_label = "SUCESSO"
    elif success_hosts and failed_hosts:
        result_status = "partial"
        result_label = "SUCESSO PARCIAL"
    else:
        result_status = "error"
        result_label = "FALHA"

    step_logs.append(
        f"Resultado final: {result_label}. Hosts consultados={len(host_results)}, sucesso={success_hosts}, falha={failed_hosts}."
    )
    step_logs.append(
        f"Totais encontrados: Serviços={service_total}, Infra={infra_total}, Ignorados={ignored_total}."
    )
    if discovered:
        step_logs.append("Busca automática concluída usando exclusivamente dados do gamb-coletor.")
    else:
        step_logs.append("Nenhum serviço TOTVS/TSS elegível foi encontrado no gamb-coletor dos hosts informados.")

    payload = {
        "steps": step_logs,
        "summary": {
            "status": result_status,
            "label": result_label,
            "total_hosts": len(host_results),
            "success_hosts": success_hosts,
            "failed_hosts": failed_hosts,
            "services": service_total,
            "infra_services": infra_total,
            "ignored_services": ignored_total,
        },
        "host_results": host_results,
    }
    if errors:
        payload["errors"] = errors
    return discovered, payload

    targets_literal = ",".join(
        [
            "@{ input='" + item["input"].replace("'", "''") + "'; connect='" + item["connect"].replace("'", "''") + "' }"
            for item in remote_targets
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
            # Serviços TOTVS/TSS por DisplayName OU Name (contains), excluindo desabilitados.
            $cimServices = Get-CimInstance Win32_Service | Where-Object {{
                $nameText = ([string]$_.Name).ToLowerInvariant()
                $displayText = ([string]$_.DisplayName).ToLowerInvariant()
                (([string]$_.StartMode) -notmatch '(?i)^disabled$') -and (
                    $nameText.Contains('totvs') -or
                    $displayText.Contains('totvs') -or
                    $nameText.Contains('tss') -or
                    $displayText.Contains('tss')
                )
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
        running_label = "SIM" if normalized_state in {"RUNNING", "RODANDO"} else "NÃO"

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

        row_data = {
            "name": service_name,
            "display_name": (row.get("display_name") or "").strip(),
            "server_ip": server,
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
                "source": "winrm",
            },
        }
        key = (_normalize_service_lookup_key(row_data["server_ip"]), _normalize_service_lookup_key(row_data["name"]))
        if key in discovered_keys:
            continue
        discovered_keys.add(key)
        discovered.append(row_data)

    if not discovered and not errors:
        step_logs.append("Nenhum serviço TOTVS/TSS elegível foi encontrado nos hosts informados.")
    elif discovered:
        step_logs.append("Resumo final de execução (serviço está rodando?):")
        for item in discovered:
            meta_state = str((item.get("_meta") or {}).get("service_state") or "").upper()
            running_label = "SIM" if meta_state in {"RUNNING", "RODANDO"} else "NÃO"
            step_logs.append(
                f"[{item.get('server_ip')}] {item.get('name')}: {meta_state or 'UNKNOWN'} (Rodando: {running_label})."
            )

    payload = {"steps": step_logs}
    if errors:
        payload["errors"] = errors
    return discovered, payload


def build_status_service(service, host):
    resolved_host = get_service_server_ip(service, host)
    base = dict(service or {})
    base["name"] = service["name"]
    base["status"] = get_service_status_for_host(service["name"], resolved_host, service.get("display_name", ""))
    return base


def _normalize_service_lookup_key(value):
    return (value or "").strip().lower()


def map_collector_status(status_text):
    return str(status_text or "").strip().upper() or "UNKNOWN"


def read_collector_pending_updates(server_info):
    if not isinstance(server_info, dict):
        return None
    for field in (
        "windows_updates_pending",
        "windows_update_pending",
        "windows_updates",
        "software_updates_pending",
        "updates_pending",
        "pending_updates",
    ):
        value = server_info.get(field)
        if value is None or str(value).strip() == "":
            continue
        try:
            return int(value)
        except Exception:
            continue
    return None


def parse_collector_status_payload(payload):
    server_info = {}
    services = []
    if isinstance(payload, dict):
        server_info = payload.get("server") if isinstance(payload.get("server"), dict) else {}
        if isinstance(payload.get("services"), list):
            services = payload.get("services") or []
        elif payload.get("service_name") or payload.get("name"):
            services = [payload]
    elif isinstance(payload, list):
        services = payload

    payload_server_ip = (server_info.get("server_ip") or "").strip()
    by_name = {}
    normalized_services = []
    for raw_service in services:
        if not isinstance(raw_service, dict):
            continue
        service_name = (raw_service.get("service_name") or raw_service.get("name") or "").strip()
        if not service_name:
            continue
        normalized = {
            "name": service_name,
            "display_name": (raw_service.get("display_name") or "").strip(),
            "path_executable": (raw_service.get("path_executable") or raw_service.get("install_folder") or "").strip(),
            "tcp_port": normalize_port(raw_service.get("tcp_port")),
            "webapp_port": normalize_port(raw_service.get("webapp_port")),
            "rest_port": normalize_port(raw_service.get("rest_port")),
            "server_ip": payload_server_ip,
            "console_log_file": (raw_service.get("console_log_file") or raw_service.get("console_log") or "").strip(),
            "sourcepath": (raw_service.get("sourcepath") or "").strip(),
            "rpocustom": (raw_service.get("rpocustom") or "").strip(),
            "status": map_collector_status(raw_service.get("status_atual") or raw_service.get("status")),
        }
        normalized_services.append(normalized)
        by_name[_normalize_service_lookup_key(service_name)] = normalized

    server = {
        "server_name": (server_info.get("server_name") or "").strip(),
        "server_ip": (server_info.get("server_ip") or "").strip(),
        "collector_version": (server_info.get("collector_version") or "").strip(),
        "os_version": (server_info.get("os_version") or "").strip(),
        "os_build": (server_info.get("os_build") or "").strip(),
        "disk_space": (server_info.get("disk_space") or "").strip(),
        "disk_total_gb": server_info.get("disk_total_gb"),
        "disk_free_gb": server_info.get("disk_free_gb"),
        "windows_updates_pending": read_collector_pending_updates(server_info),
        "timestamp": (server_info.get("timestamp") or "").strip(),
    }
    return {"server": server, "services_by_name": by_name, "services": normalized_services}


def _parse_collector_timestamp(timestamp_text):
    text = str(timestamp_text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def is_collector_stale(collector_server):
    timestamp_text = str((collector_server or {}).get("timestamp") or "").strip()
    collector_dt = _parse_collector_timestamp(timestamp_text)
    if collector_dt is None:
        return False
    age_seconds = (datetime.now() - collector_dt).total_seconds()
    return age_seconds > COLLECTOR_STALE_SECONDS


def register_collector_health_event(environment, collector_server):
    host = str((environment or {}).get("host") or "").strip() or "local"
    server_ip = str((collector_server or {}).get("server_ip") or "").strip()
    timestamp_text = str((collector_server or {}).get("timestamp") or "").strip()
    is_stale = is_collector_stale(collector_server)
    if not timestamp_text:
        return

    current_state = "PARADO" if is_stale else "RODANDO"
    state_key = _normalize_service_lookup_key(server_ip or host) or host.lower()

    with COLLECTOR_HEALTH_STATE_LOCK:
        previous_state = COLLECTOR_HEALTH_STATE.get(state_key)
        if previous_state == current_state:
            return
        COLLECTOR_HEALTH_STATE[state_key] = current_state

    environment_name = str((environment or {}).get("name") or "").strip() or host
    target = f"COLETOR :: {environment_name} ({server_ip or host})"
    if current_state == "PARADO":
        if timestamp_text:
            result = f"PARADO - sem sincronizacao recente (ultima: {timestamp_text})"
        else:
            result = "PARADO - timestamp indisponivel no gamb-coletor"
        save_log(target, "COLLECTOR_HEALTH", result, "system")


def _collector_status_candidate_hosts(host):
    normalized_host = (host or "").strip()
    if not normalized_host:
        return []
    candidates = [normalized_host]
    if is_ipv4_address(normalized_host):
        resolved = resolve_hostname_for_ip(normalized_host)
        if resolved and resolved not in candidates:
            candidates.insert(0, resolved)
    return candidates


def load_collector_status_for_host(host, use_cache=True):
    cache_key = _normalize_service_lookup_key(host) or "__local__"
    now_ts = time.time()

    if use_cache:
        with COLLECTOR_DATA_CACHE_LOCK:
            cached = COLLECTOR_DATA_CACHE.get(cache_key)
            if cached and (now_ts - float(cached.get("generated_at") or 0)) <= COLLECTOR_DATA_CACHE_TTL_SECONDS:
                return cached.get("payload") or {"server": {}, "services_by_name": {}}

    parsed_payload = {"server": {}, "services_by_name": {}}
    candidate_paths = []
    if _is_local_machine_host(host):
        candidate_paths = [
            COLLECTOR_STATUS_PATH,
            os.path.join("gamb-coletor", "status-servico.json"),
            os.path.join("gamb-coletor", "out", "status-servico.json"),
        ]
    else:
        for candidate_host in _collector_status_candidate_hosts(host):
            unc = local_path_to_unc(candidate_host, COLLECTOR_STATUS_PATH)
            if unc:
                candidate_paths.append(unc)

    for path_value in candidate_paths:
        try:
            if not os.path.exists(path_value):
                continue
            with open(path_value, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
            parsed_payload = parse_collector_status_payload(data)
            break
        except Exception:
            continue

    with COLLECTOR_DATA_CACHE_LOCK:
        COLLECTOR_DATA_CACHE[cache_key] = {"generated_at": now_ts, "payload": parsed_payload}
    return parsed_payload


def refresh_collector_cache_for_environment(environment):
    target_hosts = {
        (environment or {}).get("host", "").strip()
    }
    for service in ((environment or {}).get("services") or []):
        target_hosts.add(get_service_server_ip(service))
    for service in ((environment or {}).get("infra_services") or []):
        target_hosts.add(get_service_server_ip(service))

    for host in sorted(target_hosts):
        load_collector_status_for_host(host, use_cache=False)


def list_available_collector_versions():
    if not os.path.isdir(COLLECTOR_REPO_VERSIONS_DIR):
        return []

    versions = []
    try:
        for entry in os.scandir(COLLECTOR_REPO_VERSIONS_DIR):
            if not entry.is_dir():
                continue
            version_name = str(entry.name or "").strip()
            if not version_name:
                continue
            versions.append(
                {
                    "version": version_name,
                    "path": entry.path,
                    "has_bat": os.path.exists(os.path.join(entry.path, "gamb-colector-service.bat")),
                    "has_ps1": os.path.exists(os.path.join(entry.path, "gamb-colector-service.ps1")),
                    "has_readme": os.path.exists(os.path.join(entry.path, "README.md")),
                }
            )
    except Exception:
        return []

    versions.sort(key=lambda item: str(item.get("version") or "").lower(), reverse=True)
    return versions


def get_collector_version_info(version_name):
    target_version = str(version_name or "").strip()
    if not target_version:
        return None
    for item in list_available_collector_versions():
        if str(item.get("version") or "").strip() == target_version:
            return item
    return None


def _collect_environment_hosts_for_collector(environment):
    hosts = []
    seen = set()
    local_aliases = {"localhost", "127.0.0.1", ".", "(local)"}

    def add_host(value):
        host_value = str(value or "").strip()
        if not host_value:
            return
        normalized = _normalize_service_lookup_key(host_value)
        if normalized in seen:
            return
        seen.add(normalized)
        hosts.append(host_value)

    add_host((environment or {}).get("host"))
    for service in ((environment or {}).get("services") or []):
        add_host(get_service_server_ip(service))
    for service in ((environment or {}).get("infra_services") or []):
        add_host(get_service_server_ip(service))
    non_local_hosts = [
        host
        for host in hosts
        if _normalize_service_lookup_key(host) not in local_aliases
    ]
    if non_local_hosts:
        return non_local_hosts
    return hosts


def _collector_candidate_paths_for_host(host, base_local_path):
    if _is_local_machine_host(host):
        return [base_local_path]
    candidate_paths = []
    for candidate_host in _collector_status_candidate_hosts(host):
        unc = local_path_to_unc(candidate_host, base_local_path)
        if unc:
            candidate_paths.append(unc)
    return candidate_paths


def _read_json_from_candidate_paths(candidate_paths):
    for path_value in candidate_paths:
        try:
            if not os.path.exists(path_value):
                continue
            with open(path_value, "r", encoding="utf-8-sig") as file:
                return json.load(file)
        except Exception:
            continue
    return {}


def read_collector_version_marker_for_host(host):
    return _read_json_from_candidate_paths(_collector_candidate_paths_for_host(host, COLLECTOR_VERSION_MARKER_PATH))


def _collector_destination_path_for_host(host, relative_name):
    destination = os.path.join(COLLECTOR_DEPLOY_ROOT, relative_name)
    if _is_local_machine_host(host):
        return destination
    return local_path_to_unc(host, destination)


def _write_json_file(path_value, payload):
    os.makedirs(os.path.dirname(path_value), exist_ok=True)
    with open(path_value, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _copy_file_to_host(host, source_path, destination_name):
    destination_path = _collector_destination_path_for_host(host, destination_name)
    if not destination_path:
        raise RuntimeError("Nao foi possivel resolver o caminho de destino do coletor.")
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        shutil.copy2(source_path, destination_path)
    except PermissionError as exc:
        raise RuntimeError(
            f"Sem permissao para gravar em {destination_path}. "
            "Execute o monitor com permissao administrativa ou libere escrita no compartilhamento administrativo do host."
        ) from exc
    return destination_path


def _is_access_denied_message(text):
    normalized = str(text or "").strip().lower()
    return "access is denied" in normalized or "acesso negado" in normalized


def _restart_collector_service_for_host(host):
    target = str(host or "").strip()
    sc_target = [] if _is_local_machine_host(target) else [f"\\\\{target}"]
    query_cmd = ["sc.exe", *sc_target, "query", COLLECTOR_SERVICE_NAME]
    query_result = subprocess.run(query_cmd, capture_output=True, text=True)
    if query_result.returncode != 0:
        query_output = (query_result.stderr or query_result.stdout or "").strip()
        if _is_access_denied_message(query_output):
            return {
                "status": "permission_denied",
                "message": "Arquivos atualizados, mas sem permissao para consultar/reiniciar o servico do coletor neste host.",
                "details": query_output,
            }
        return {"status": "not_installed", "message": "Servico do coletor nao encontrado."}

    stop_cmd = ["sc.exe", *sc_target, "stop", COLLECTOR_SERVICE_NAME]
    start_cmd = ["sc.exe", *sc_target, "start", COLLECTOR_SERVICE_NAME]
    stop_result = subprocess.run(stop_cmd, capture_output=True, text=True)
    stop_output = (stop_result.stderr or stop_result.stdout or "").strip()
    if stop_result.returncode != 0 and _is_access_denied_message(stop_output):
        return {
            "status": "permission_denied",
            "message": "Arquivos atualizados, mas sem permissao para parar/iniciar o servico do coletor neste host.",
            "details": stop_output,
        }
    time.sleep(2)
    start_result = subprocess.run(start_cmd, capture_output=True, text=True)
    start_output = (start_result.stderr or start_result.stdout or "").strip()
    if start_result.returncode == 0:
        return {"status": "restarted", "message": "Servico do coletor reiniciado."}
    if _is_access_denied_message(start_output):
        return {
            "status": "permission_denied",
            "message": "Arquivos atualizados, mas sem permissao para iniciar o servico do coletor neste host.",
            "details": start_output,
        }
    return {
        "status": "restart_failed",
        "message": (start_output or stop_output or "Falha ao reiniciar o servico.").strip(),
    }


def build_environment_collector_deployment_status(environment, latest_version=""):
    host_rows = []
    current_versions = set()
    has_unknown_versions = False
    seen_display_hosts = set()
    latest_version = str(latest_version or "").strip()

    for host in _collect_environment_hosts_for_collector(environment):
        marker = read_collector_version_marker_for_host(host)
        collector_payload = load_collector_status_for_host(host, use_cache=True)
        collector_server = (collector_payload or {}).get("server") or {}
        display_host = str(collector_server.get("server_ip") or host).strip() or host
        normalized_display_host = _normalize_service_lookup_key(display_host)
        if normalized_display_host in seen_display_hosts:
            continue
        seen_display_hosts.add(normalized_display_host)
        current_version = str(marker.get("current_version") or collector_server.get("collector_version") or "").strip()
        if current_version:
            current_versions.add(current_version)
        else:
            has_unknown_versions = True
        host_rows.append(
            {
                "host": display_host,
                "server_ip": display_host,
                "server_name": str(collector_server.get("server_name") or "").strip(),
                "current_version": current_version,
                "current_version_label": current_version or "Nao identificado",
                "updated_at": str(marker.get("updated_at") or "").strip(),
                "updated_by": str(marker.get("updated_by") or "").strip(),
                "update_available": bool(latest_version and current_version and current_version != latest_version),
            }
        )

    if len(current_versions) == 1 and not has_unknown_versions:
        current_version_label = next(iter(current_versions))
        current_version = current_version_label
    elif current_versions or has_unknown_versions:
        current_version_label = "Misto"
        current_version = ""
    else:
        current_version_label = "Nao identificado"
        current_version = ""

    update_available = bool(latest_version and ((current_version and current_version != latest_version) or current_version_label == "Misto"))

    return {
        "environment_id": environment.get("id"),
        "environment_name": environment.get("name"),
        "current_version": current_version,
        "current_version_label": current_version_label,
        "latest_version": latest_version,
        "update_available": update_available,
        "hosts": host_rows,
    }


def deploy_collector_version_to_host(host, version_name, actor_username):
    version_info = get_collector_version_info(version_name)
    if not version_info:
        raise RuntimeError("Versao do coletor nao encontrada.")

    source_dir = version_info["path"]
    source_files = [
        name
        for name in ("gamb-colector-service.bat", "gamb-colector-service.ps1", COLLECTOR_BULK_ACTION_BAT, "README.md")
        if os.path.exists(os.path.join(source_dir, name))
    ]
    if not source_files:
        raise RuntimeError("Arquivos da versao selecionada nao encontrados.")

    marker = read_collector_version_marker_for_host(host)
    previous_version = str(marker.get("current_version") or "").strip()
    history = marker.get("history") if isinstance(marker.get("history"), list) else []
    if previous_version and previous_version != version_name:
        history.insert(
            0,
            {
                "version": previous_version,
                "updated_at": str(marker.get("updated_at") or "").strip(),
                "updated_by": str(marker.get("updated_by") or "").strip(),
            },
        )
    history = history[:COLLECTOR_VERSION_HISTORY_LIMIT]

    copied_files = []
    for file_name in source_files:
        destination_path = _copy_file_to_host(host, os.path.join(source_dir, file_name), file_name)
        copied_files.append(destination_path)

    marker_payload = {
        "current_version": version_name,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_by": actor_username,
        "history": history,
    }
    marker_path = _collector_destination_path_for_host(host, "collector-version.json")
    if not marker_path:
        raise RuntimeError("Nao foi possivel resolver o arquivo de versao do coletor.")
    _write_json_file(marker_path, marker_payload)

    restart_info = _restart_collector_service_for_host(host)
    return {
        "host": host,
        "target_version": version_name,
        "previous_version": previous_version,
        "current_version": version_name,
        "copied_files": copied_files,
        "service_restart": restart_info,
    }


def _build_service_status_snapshot(host):
    machine = resolve_service_machine(host)
    snapshot = {
        "by_name": {},
        "by_display_name": {},
    }

    scm = win32service.OpenSCManager(
        machine,
        None,
        win32service.SC_MANAGER_ENUMERATE_SERVICE,
    )
    try:
        items = win32service.EnumServicesStatus(
            scm,
            win32service.SERVICE_WIN32,
            win32service.SERVICE_STATE_ALL,
        )
    finally:
        win32service.CloseServiceHandle(scm)

    status_mapping = {
        win32service.SERVICE_RUNNING: "RUNNING",
        win32service.SERVICE_STOPPED: "STOPPED",
        win32service.SERVICE_START_PENDING: "STARTING",
        win32service.SERVICE_STOP_PENDING: "STOPPING",
    }

    for item in items:
        service_name = item[0]
        display_name = item[1]
        service_status = item[2] or ()
        current_state = service_status[1] if isinstance(service_status, tuple) and len(service_status) > 1 else service_status
        status_label = status_mapping.get(current_state, "UNKNOWN")
        normalized_name = _normalize_service_lookup_key(service_name)
        normalized_display_name = _normalize_service_lookup_key(display_name)
        if normalized_name:
            snapshot["by_name"][normalized_name] = status_label
        if normalized_display_name:
            snapshot["by_display_name"][normalized_display_name] = {
                "name": service_name,
                "status": status_label,
            }

    return snapshot


def _get_cached_service_status_snapshot(host, use_cache=True):
    cache_key = _normalize_service_lookup_key(host) or "__local__"
    now = time.time()

    if use_cache:
        with SERVICE_STATUS_CACHE_LOCK:
            cached = SERVICE_STATUS_CACHE.get(cache_key)
            if cached and now - cached["created_at"] < SERVICE_STATUS_CACHE_TTL_SECONDS:
                return cached["snapshot"]

    try:
        snapshot = _build_service_status_snapshot(host)
    except Exception:
        with SERVICE_STATUS_CACHE_LOCK:
            SERVICE_STATUS_CACHE[cache_key] = {
                "created_at": now,
                "snapshot": None,
            }
        return None

    with SERVICE_STATUS_CACHE_LOCK:
        SERVICE_STATUS_CACHE[cache_key] = {
            "created_at": now,
            "snapshot": snapshot,
        }
    return snapshot


def invalidate_service_status_cache(host):
    cache_key = _normalize_service_lookup_key(host) or "__local__"
    with SERVICE_STATUS_CACHE_LOCK:
        SERVICE_STATUS_CACHE.pop(cache_key, None)


def invalidate_environment_status_cache(environment_id=None):
    with ENVIRONMENT_STATUS_CACHE_LOCK:
        if environment_id:
            ENVIRONMENT_STATUS_CACHE.pop(environment_id, None)
            return
        ENVIRONMENT_STATUS_CACHE.clear()


def _collect_monitored_hosts(environments=None):
    environments = environments if environments is not None else load_environments()
    hosts = set()
    for environment in environments:
        environment_host = (environment.get("host") or "").strip()
        if environment_host:
            hosts.add(environment_host)
        for service in (environment.get("services", []) + environment.get("infra_services", [])):
            service_host = get_service_server_ip(service)
            if service_host:
                hosts.add(service_host)
    if not hosts:
        hosts.add("")
    return sorted(hosts)


def refresh_service_status_cache(hosts=None):
    target_hosts = hosts if hosts is not None else _collect_monitored_hosts()
    for host in target_hosts:
        try:
            _get_cached_service_status_snapshot(host, use_cache=False)
        except Exception:
            continue


def refresh_environment_status_cache(environments=None):
    environments = environments if environments is not None else load_environments()
    refreshed = {}
    for environment in environments:
        try:
            refreshed[environment["id"]] = build_environment_status(environment)
        except Exception:
            continue
    with ENVIRONMENT_STATUS_CACHE_LOCK:
        ENVIRONMENT_STATUS_CACHE.clear()
        ENVIRONMENT_STATUS_CACHE.update(refreshed)
    return refreshed


def get_cached_environment_status(environment_id):
    with ENVIRONMENT_STATUS_CACHE_LOCK:
        cached = ENVIRONMENT_STATUS_CACHE.get(environment_id)
        return dict(cached) if isinstance(cached, dict) else None


def get_all_cached_environment_statuses():
    with ENVIRONMENT_STATUS_CACHE_LOCK:
        return [dict(item) for item in ENVIRONMENT_STATUS_CACHE.values()]


def _service_status_monitor_loop():
    while True:
        try:
            environments = load_environments()
            refresh_service_status_cache(_collect_monitored_hosts(environments))
            refresh_environment_status_cache(environments)
            dispatch_monitor_alerts()
        except Exception:
            pass
        time.sleep(SERVICE_STATUS_MONITOR_INTERVAL_SECONDS)


def ensure_service_status_monitor_started():
    global SERVICE_STATUS_MONITOR_THREAD
    with SERVICE_STATUS_MONITOR_LOCK:
        if SERVICE_STATUS_MONITOR_THREAD and SERVICE_STATUS_MONITOR_THREAD.is_alive():
            return
        SERVICE_STATUS_MONITOR_THREAD = threading.Thread(
            target=_service_status_monitor_loop,
            name="service-status-monitor",
            daemon=True,
        )
        SERVICE_STATUS_MONITOR_THREAD.start()


def _build_previous_status_lookup(cached_environment):
    lookup = {}
    if not cached_environment:
        return lookup
    for section in ("services", "infra_services"):
        for service in cached_environment.get(section, []) or []:
            key = (
                section,
                _normalize_service_lookup_key(service.get("name")),
                _normalize_service_lookup_key(get_service_server_ip(service)),
            )
            lookup[key] = service.get("status", "UNKNOWN")
    return lookup


def build_environment_status(environment):
    host = environment.get("host")
    services = environment.get("services", [])
    infra_services = environment.get("infra_services", [])
    all_services = [("services", service) for service in services] + [("infra_services", service) for service in infra_services]
    built_services = {"services": [], "infra_services": []}
    previous_status_lookup = _build_previous_status_lookup(get_cached_environment_status(environment["id"]))

    collector_by_host = {}
    host_availability_by_host = {}
    target_hosts = sorted(
        {
            current_host
            for current_host in (
                [str(host or "").strip()]
                + [get_service_server_ip(service, host) for _, service in all_services]
            )
            if current_host
        }
    )
    for target_host in target_hosts:
        collector_by_host[target_host] = load_collector_status_for_host(target_host, use_cache=True)
        host_availability_by_host[target_host] = is_host_online(target_host, use_cache=True)

    for service_type, service in all_services:
        resolved_host = get_service_server_ip(service, host)
        base = dict(service or {})
        base["name"] = service["name"]
        collector_payload = collector_by_host.get((resolved_host or "").strip()) or {}
        collector_server = collector_payload.get("server") or {}
        collector_sync_state = get_collector_sync_state(
            collector_payload,
            host_availability_by_host.get((resolved_host or "").strip()),
        )
        collector_server_ip = str(collector_server.get("server_ip") or resolved_host or "").strip()
        if collector_server_ip:
            base["server_ip"] = collector_server_ip
        base.pop("service" + "_ip", None)
        collector_is_stale = collector_sync_state == "stale"
        base["collector_sync_state"] = collector_sync_state
        collector_service = (collector_payload.get("services_by_name") or {}).get(_normalize_service_lookup_key(service.get("name")))
        if collector_service:
            for field in (
                "display_name",
                "path_executable",
                "tcp_port",
                "webapp_port",
                "rest_port",
                "console_log_file",
                "sourcepath",
                "rpocustom",
            ):
                if collector_service.get(field):
                    base[field] = collector_service.get(field)
        if collector_is_stale:
            base["status"] = "COLETOR PARADO"
        elif collector_service and collector_service.get("status"):
            base["status"] = collector_service.get("status")
        else:
            fallback_key = (
                service_type,
                _normalize_service_lookup_key(service.get("name")),
                _normalize_service_lookup_key(get_service_server_ip(service)),
            )
            # Regra operacional: status vem sempre do gamb-coletor; sem fallback ao SCM/Windows.
            base["status"] = previous_status_lookup.get(fallback_key, "UNKNOWN")
        built_services[service_type].append(base)

    environment_collector = load_collector_status_for_host(host, use_cache=True).get("server") or {}
    # O total do ambiente deve ser recalculado pelos hosts validos abaixo,
    # sem reaproveitar um valor agregado antigo do JSON base.
    environment_collector.pop("windows_updates_pending", None)
    total_pending_updates = 0
    has_pending_updates_value = False
    collector_hosts_summary = []
    collector_hosts_seen = set()
    offline_hosts = []
    unsynced_hosts = []
    for target_host, collector_payload in collector_by_host.items():
        collector_server = (collector_payload or {}).get("server") or {}
        summary_server_ip = str(collector_server.get("server_ip") or target_host).strip() or target_host
        summary_key = _normalize_service_lookup_key(summary_server_ip or target_host)
        if summary_key in collector_hosts_seen:
            continue
        collector_hosts_seen.add(summary_key)
        host_online = host_availability_by_host.get(target_host)
        payload_missing = collector_payload_missing(collector_payload)
        collector_sync_state = get_collector_sync_state(collector_payload, host_online)
        host_stale = collector_sync_state == "stale"
        try:
            pending_updates = int(collector_server.get("windows_updates_pending"))
        except Exception:
            pending_updates = None
        if pending_updates is None:
            refreshed_payload = load_collector_status_for_host(target_host, use_cache=False)
            refreshed_server = (refreshed_payload or {}).get("server") or {}
            try:
                refreshed_pending_updates = int(refreshed_server.get("windows_updates_pending"))
            except Exception:
                refreshed_pending_updates = None
            if refreshed_pending_updates is not None:
                pending_updates = refreshed_pending_updates
                collector_payload = refreshed_payload
                collector_server = refreshed_server
                summary_server_ip = str(collector_server.get("server_ip") or target_host).strip() or target_host
                payload_missing = collector_payload_missing(collector_payload)
                collector_sync_state = get_collector_sync_state(collector_payload, host_online)
                host_stale = collector_sync_state == "stale"
        valid_updates_source = collector_sync_state == "healthy"
        if pending_updates is not None and valid_updates_source:
            total_pending_updates += pending_updates
            has_pending_updates_value = True
        collector_hosts_summary.append(
            {
                "host": target_host,
                "server_ip": summary_server_ip,
                "server_name": str(collector_server.get("server_name") or "").strip(),
                "disk_space": str(collector_server.get("disk_space") or "").strip(),
                "disk_total_gb": collector_server.get("disk_total_gb"),
                "disk_free_gb": collector_server.get("disk_free_gb"),
                "windows_updates_pending": pending_updates,
                "windows_updates_valid": valid_updates_source,
                "timestamp": str(collector_server.get("timestamp") or "").strip(),
                "is_stale": host_stale,
                "payload_missing": payload_missing,
                "host_online": host_online,
                "sync_state": collector_sync_state,
            }
        )
        if collector_sync_state == "offline":
            offline_hosts.append(summary_server_ip)
        elif collector_sync_state in {"unreachable", "stale"}:
            unsynced_hosts.append(summary_server_ip)
    if has_pending_updates_value:
        environment_collector["windows_updates_pending"] = total_pending_updates
    else:
        environment_collector["windows_updates_pending"] = None
    environment_collector["windows_updates_by_host"] = [
        {
            "host": item.get("host"),
            "server_ip": item.get("server_ip"),
            "windows_updates_pending": item.get("windows_updates_pending"),
            "windows_updates_valid": item.get("windows_updates_valid"),
            "is_stale": item.get("is_stale"),
            "payload_missing": item.get("payload_missing"),
            "host_online": item.get("host_online"),
        }
        for item in collector_hosts_summary
    ]
    environment_collector["any_host_offline"] = bool(offline_hosts)
    environment_collector["offline_hosts"] = offline_hosts
    environment_collector["any_host_unsynced"] = bool(unsynced_hosts)
    environment_collector["unsynced_hosts"] = unsynced_hosts
    register_collector_health_event(environment, environment_collector)
    return {
        "id": environment["id"],
        "environment": environment["name"],
        "environment_type": environment.get("environment_type", infer_environment_type(environment["name"])),
        "host": host or "",
        "app_url": environment.get("app_url", ""),
        "rest_url": environment.get("rest_url", ""),
        "erp_version": environment.get("erp_version", ""),
        "database_update_date": environment.get("database_update_date", get_default_database_update_date(environment.get("environment_type", infer_environment_type(environment["name"])))),
        "collector_server": environment_collector,
        "collector_hosts": collector_hosts_summary,
        "services": built_services["services"],
        "infra_services": built_services["infra_services"],
    }


def build_initial_environment_payload(environment):
    return {
        "id": environment["id"],
        "environment": environment["name"],
        "environment_type": environment.get("environment_type", infer_environment_type(environment["name"])),
        "host": environment.get("host", ""),
        "app_url": environment.get("app_url", ""),
        "rest_url": environment.get("rest_url", ""),
        "erp_version": environment.get("erp_version", ""),
        "database_update_date": environment.get("database_update_date", get_default_database_update_date(environment.get("environment_type", infer_environment_type(environment["name"])))),
        "services": [
            {
                "name": service["name"],
                "display_name": service.get("display_name", ""),
                "path_executable": service.get("path_executable", ""),
                "tcp_port": service.get("tcp_port", ""),
                "webapp_port": service.get("webapp_port", ""),
                "rest_port": service.get("rest_port", ""),
                "server_ip": get_service_server_ip(service),
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
                "server_ip": get_service_server_ip(service),
                "console_log_file": service.get("console_log_file", ""),
                "priority": service.get("priority", "media"),
                "status": "LOADING",
            }
            for service in environment.get("infra_services", [])
        ],
    }


def resolve_service_machine(host):
    normalized = (host or "").strip().lower()
    if normalized in {"", "127.0.0.1", "localhost", ".", "(local)"}:
        return None
    return host


def _get_local_ipv4_addresses():
    now_ts = time.time()
    with LOCAL_IP_CACHE_LOCK:
        if (now_ts - float(LOCAL_IP_CACHE.get("generated_at") or 0)) <= LOCAL_IP_CACHE_TTL_SECONDS:
            return set(LOCAL_IP_CACHE.get("values") or {"127.0.0.1"})

    addresses = {"127.0.0.1"}
    try:
        _, _, ip_list = socket.gethostbyname_ex(socket.gethostname())
        for ip in ip_list or []:
            if is_ipv4_address(ip):
                addresses.add(ip.strip())
    except Exception:
        pass

    try:
        code, stdout, _ = run_powershell(
            "(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Where-Object { $_.IPAddress -and $_.IPAddress -ne '127.0.0.1' } | "
            "Select-Object -ExpandProperty IPAddress) -join \"`n\""
        )
        if code == 0:
            for line in (stdout or "").splitlines():
                ip = (line or "").strip()
                if is_ipv4_address(ip):
                    addresses.add(ip)
    except Exception:
        pass

    with LOCAL_IP_CACHE_LOCK:
        LOCAL_IP_CACHE["generated_at"] = now_ts
        LOCAL_IP_CACHE["values"] = set(addresses)
    return addresses


def _is_local_machine_host(host):
    normalized = (host or "").strip().lower()
    if normalized in {"", "127.0.0.1", "localhost", ".", "(local)"}:
        return True

    try:
        local_hostnames = {socket.gethostname().lower(), socket.getfqdn().lower()}
        if normalized in local_hostnames:
            return True
    except Exception:
        pass

    return normalized in {ip.lower() for ip in _get_local_ipv4_addresses()}


def is_host_online(host, use_cache=True):
    normalized = str(host or "").strip()
    if not normalized:
        return None

    cache_key = normalized.lower()
    now_ts = time.time()
    if use_cache:
        with HOST_AVAILABILITY_CACHE_LOCK:
            cached = HOST_AVAILABILITY_CACHE.get(cache_key)
            if cached and (now_ts - float(cached.get("generated_at") or 0)) <= HOST_AVAILABILITY_CACHE_TTL_SECONDS:
                return cached.get("is_online")

    if _is_local_machine_host(normalized):
        is_online = True
    else:
        command = ["ping", "-n", "1", "-w", "1200", normalized]
        completed = subprocess.run(command, capture_output=True, text=True)
        is_online = completed.returncode == 0

    with HOST_AVAILABILITY_CACHE_LOCK:
        HOST_AVAILABILITY_CACHE[cache_key] = {
            "generated_at": now_ts,
            "is_online": is_online,
        }
    return is_online


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


def _get_service_status_from_windows_direct(service_name, host):
    status_code = win32serviceutil.QueryServiceStatus(service_name, machine=resolve_service_machine(host))[1]
    mapping = {
        win32service.SERVICE_RUNNING: "RUNNING",
        win32service.SERVICE_STOPPED: "STOPPED",
        win32service.SERVICE_START_PENDING: "STARTING",
        win32service.SERVICE_STOP_PENDING: "STOPPING",
    }
    return mapping.get(status_code, "UNKNOWN")


def _force_kill_service_process(service_name, host):
    pid = _get_service_pid_via_sc(service_name, host)
    if pid <= 0:
        return False, "PID do serviço não encontrado para forçar parada.", 0

    command = ["taskkill"]
    if not _is_local_machine_host(host):
        command.extend(["/S", host])
    command.extend(["/PID", str(pid), "/F"])
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        return False, details or f"Falha ao executar taskkill para PID {pid}.", pid
    return True, f"Parada forçada executada via taskkill no PID {pid}.", pid


def stop_service_with_force(service_name, host, display_name="", timeout_seconds=8):
    # Regra solicitada: sempre parar usando taskkill para maior velocidade.
    kill_result = _force_kill_service_process(service_name, host)
    killed = bool(kill_result[0])
    details = kill_result[1]
    killed_pid = kill_result[2] if len(kill_result) > 2 else 0
    if not killed:
        return {"success": False, "forced": False, "message": f"Falha no taskkill: {details}"}

    ok, current_status = wait_for_windows_service_status(
        service_name,
        host,
        expected_statuses={"STOPPED"},
        display_name=display_name,
        timeout_seconds=max(timeout_seconds, 6),
        poll_interval=0.8,
    )
    if ok:
        return {"success": True, "forced": True, "message": details, "status": current_status}

    current_pid = _get_service_pid_via_sc(service_name, host)
    if killed_pid > 0 and current_pid != killed_pid:
        status_label = current_status
        if current_pid > 0 and current_status == "RUNNING":
            status_label = "RESTARTED"
        return {
            "success": True,
            "forced": True,
            "message": f"{details} PID atual: {current_pid or 'nenhum'}.",
            "status": status_label,
        }

    return {
        "success": False,
        "forced": True,
        "message": f"Taskkill executado, mas o Windows ainda reporta status {current_status}.",
        "status": current_status,
    }


def find_service_in_environment(environment, service_name, server_ip=""):
    # Regra operacional: toda ação deve consultar o gamb-coletor antes de executar.
    environment = hydrate_environment_from_collector(environment, use_cache=False)

    all_environment_services = environment.get("services", []) + environment.get("infra_services", [])
    if server_ip:
        return next(
            (
                item
                for item in all_environment_services
                if item.get("name") == service_name and get_service_server_ip(item) == server_ip
            ),
            None,
        )
    return next((item for item in all_environment_services if item.get("name") == service_name), None)


def hydrate_environment_from_collector(environment, use_cache=False):
    if not environment:
        return environment

    hydrated = dict(environment)
    environment_host = (environment.get("host") or "").strip()
    collector_by_host = {}

    def merge_service(raw_service):
        base = dict(raw_service or {})
        service_name = (base.get("name") or "").strip()
        if not service_name:
            return base

        target_host = get_service_server_ip(base, environment_host)
        cache_key = _normalize_service_lookup_key(target_host)
        if cache_key not in collector_by_host:
            collector_by_host[cache_key] = load_collector_status_for_host(target_host, use_cache=use_cache)

        collector_payload = collector_by_host.get(cache_key) or {}
        collector_service = (collector_payload.get("services_by_name") or {}).get(_normalize_service_lookup_key(service_name))
        if not collector_service:
            return base
        collector_server_ip = str((collector_payload.get("server") or {}).get("server_ip") or target_host).strip()
        if collector_server_ip:
            base["server_ip"] = collector_server_ip

        mapping = {
            "display_name": "display_name",
            "path_executable": "path_executable",
            "tcp_port": "tcp_port",
            "webapp_port": "webapp_port",
            "rest_port": "rest_port",
            "console_log_file": "console_log_file",
            "sourcepath": "sourcepath",
            "rpocustom": "rpocustom",
        }
        for target_field, source_field in mapping.items():
            incoming = collector_service.get(source_field)
            if incoming not in (None, ""):
                base[target_field] = incoming
        return base

    hydrated["services"] = [merge_service(item) for item in (environment.get("services") or [])]
    hydrated["infra_services"] = [merge_service(item) for item in (environment.get("infra_services") or [])]
    return hydrated


def get_service_status_from_windows(service_name, host, display_name=""):
    try:
        return _get_service_status_from_windows_direct(service_name, host)
    except Exception:
        return get_service_status_for_host(service_name, host, display_name=display_name, snapshot=None)


def wait_for_windows_service_status(service_name, host, expected_statuses, display_name="", timeout_seconds=20, poll_interval=0.8):
    expected = {str(item or "").strip().upper() for item in (expected_statuses or []) if str(item or "").strip()}
    if not expected:
        return False, "UNKNOWN"

    deadline = time.time() + max(timeout_seconds, 3)
    latest_status = "UNKNOWN"
    while time.time() < deadline:
        latest_status = get_service_status_from_windows(service_name, host, display_name=display_name)
        if latest_status in expected:
            return True, latest_status
        time.sleep(max(0.2, poll_interval))
    return False, latest_status


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


def get_request_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return (request.remote_addr or "").strip() or "unknown"


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


def get_service_status_for_host(service_name, host, display_name="", snapshot=None):
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

    def get_snapshot():
        if snapshot is not None:
            return snapshot
        try:
            return _get_cached_service_status_snapshot(host, use_cache=True)
        except Exception:
            return None

    def find_service_name_by_display_name(display_name_value):
        if not display_name_value:
            return ""
        current_snapshot = get_snapshot()
        if not current_snapshot:
            return ""
        entry = current_snapshot["by_display_name"].get(_normalize_service_lookup_key(display_name_value))
        if not entry:
            return ""
        return entry.get("name") or ""

    current_snapshot = get_snapshot()
    normalized_service_name = _normalize_service_lookup_key(service_name)
    if current_snapshot and normalized_service_name in current_snapshot["by_name"]:
        return current_snapshot["by_name"][normalized_service_name]

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
            if current_snapshot and alias.lower() in current_snapshot["by_name"]:
                return current_snapshot["by_name"][alias.lower()]
            try:
                return query_status_by_name(alias)
            except Exception:
                continue

    return "NOT FOUND"


def save_log(service, action, result, user, **extra):
    log = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "service": service,
        "action": action,
        "result": result,
        "user": user,
    }
    for key, value in (extra or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        log[key] = value

    os.makedirs(DATA_DIR, exist_ok=True)
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

        dedup_window_seconds = LOG_DEDUP_WINDOWS_SECONDS.get(str(action or "").strip())
        if dedup_window_seconds and data:
            now = datetime.now()
            comparable_log = {key: value for key, value in log.items() if key != "datetime"}
            for existing in data[:50]:
                if not isinstance(existing, dict):
                    continue
                existing_dt = str(existing.get("datetime") or "").strip()
                try:
                    existing_when = datetime.strptime(existing_dt, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if (now - existing_when).total_seconds() > dedup_window_seconds:
                    continue
                comparable_existing = {key: value for key, value in existing.items() if key != "datetime"}
                if comparable_existing == comparable_log:
                    return

        data.insert(0, log)
        file.seek(0)
        json.dump(data[:LOG_MAX_ENTRIES], file, indent=2, ensure_ascii=False)
        file.truncate()


def save_execution_trace(environment_name, host, service, action, result, user, **extra):
    entry = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "environment": str(environment_name or "").strip() or "-",
        "host": str(host or "").strip() or "local",
        "service": str(service or "").strip() or "-",
        "action": str(action or "").strip() or "-",
        "result": str(result or "").strip() or "-",
        "user": str(user or "").strip() or "system",
    }
    for key, value in (extra or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        entry[key] = value

    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(EXECUTION_TRACE_FILE):
        with open(EXECUTION_TRACE_FILE, "w", encoding="utf-8") as file:
            json.dump([], file)

    try:
        with open(EXECUTION_TRACE_FILE, "r", encoding="utf-8-sig") as file:
            data = json.load(file)
            if not isinstance(data, list):
                data = []
    except Exception:
        data = []

    data.insert(0, entry)
    with open(EXECUTION_TRACE_FILE, "w", encoding="utf-8") as file:
        json.dump(data[:EXECUTION_TRACE_MAX_ENTRIES], file, indent=2, ensure_ascii=False)


def save_environment_log(environment_name, host, service, action, result, user):
    target = f"{environment_name} ({host or 'local'}) :: {service}"
    save_log(target, action, result, user)


def save_admin_environment_log(environment_name, action, result, user):
    target = f"AMBIENTE :: {environment_name}"
    save_log(target, action, result, user)


def _normalize_service_key(value):
    return (value or "").strip().lower()


def _parse_trace_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def should_suppress_stopped_service_alert(environment, environment_status, service):
    service_name = _normalize_service_key(service.get("name"))
    if not service_name:
        return False

    environment_name = _normalize_service_key(
        (environment_status or {}).get("environment") or (environment or {}).get("name")
    )
    resolved_host = _normalize_service_key(
        get_service_server_ip(service, (environment_status or {}).get("host") or (environment or {}).get("host"))
    )
    now_dt = datetime.now()

    with ACTION_JOBS_LOCK:
        active_jobs = list((ACTION_JOBS or {}).values())

    for job in active_jobs:
        if not isinstance(job, dict):
            continue
        if _normalize_service_key(job.get("environment")) != environment_name:
            continue
        if _normalize_service_key(job.get("service")) != service_name:
            continue
        if _normalize_service_key(job.get("server_ip")) != resolved_host:
            continue
        if _normalize_service_key(job.get("action")) not in {"start", "restart"}:
            continue
        if _normalize_service_key(job.get("status")) in {"queued", "running"}:
            return True

    try:
        with open(EXECUTION_TRACE_FILE, "r", encoding="utf-8-sig") as file:
            entries = json.load(file)
        if not isinstance(entries, list):
            entries = []
    except Exception:
        entries = []

    for entry in entries[:250]:
        if not isinstance(entry, dict):
            continue
        if _normalize_service_key(entry.get("environment")) != environment_name:
            continue
        if _normalize_service_key(entry.get("service")) != service_name:
            continue
        if _normalize_service_key(entry.get("host")) != resolved_host:
            continue
        if _normalize_service_key(entry.get("action")) not in {"start", "restart"}:
            continue
        if not _normalize_service_key(entry.get("result")).startswith("success"):
            continue
        when = _parse_trace_datetime(entry.get("datetime"))
        if not when:
            continue
        if (now_dt - when).total_seconds() <= SERVICE_ALERT_SUPPRESSION_SECONDS:
            return True
        break

    return False


def _build_service_registry_target(environment_name, section, service):
    section_label = "Infra" if section == "infra_services" else "Aplicacao"
    service_name = (service.get("display_name") or service.get("name") or "servico-sem-nome").strip()
    server_ip = get_service_server_ip(service) or "-"
    return f"SERVICO :: {environment_name} :: {section_label} :: {service_name} :: {server_ip}"


def _service_snapshot(environment):
    snapshot = {}
    if not environment:
        return snapshot

    for section in ("services", "infra_services"):
        for raw_service in environment.get(section, []) or []:
            service = sanitize_service(raw_service)
            key = f"{section}|{_normalize_service_key(service.get('name'))}|{_normalize_service_key(get_service_server_ip(service))}"
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


def service_status_is_running(status_text):
    normalized = str(status_text or "").strip().upper()
    return normalized in {"RODANDO", "RUNNING"}


def _run_service_action(environment, resolved_host, service, action_type, username):
    machine = resolve_service_machine(resolved_host)
    forced_stop = False
    final_status = "UNKNOWN"
    resolved_service = find_service_in_environment(environment, service, server_ip=resolved_host) or {}
    display_name = resolved_service.get("display_name", "")
    if action_type == "start":
        win32serviceutil.StartService(service, machine=machine)
        ok, windows_status = wait_for_windows_service_status(
            service,
            resolved_host,
            expected_statuses={"RUNNING"},
            display_name=display_name,
            timeout_seconds=20,
            poll_interval=0.8,
        )
        if not ok:
            raise RuntimeError(
                f"Start executado, mas o Windows ainda reporta status {windows_status}."
            )
        final_status = windows_status
    elif action_type == "stop":
        stop_result = stop_service_with_force(service, resolved_host, display_name=display_name)
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("message") or "Falha ao parar serviço.")
        forced_stop = bool(stop_result.get("forced"))
        final_status = str(stop_result.get("status") or "PARADO")
    elif action_type == "restart":
        stop_result = stop_service_with_force(service, resolved_host, display_name=display_name)
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("message") or "Falha ao parar serviço para reinício.")
        forced_stop = bool(stop_result.get("forced"))
        win32serviceutil.StartService(service, machine=machine)
        ok, windows_status = wait_for_windows_service_status(
            service,
            resolved_host,
            expected_statuses={"RUNNING"},
            display_name=display_name,
            timeout_seconds=20,
            poll_interval=0.8,
        )
        if not ok:
            raise RuntimeError(
                f"Restart executado, mas o Windows ainda reporta status {windows_status}."
            )
        final_status = windows_status
    else:
        raise ValueError("Ação inválida.")

    invalidate_service_status_cache(resolved_host)
    invalidate_environment_status_cache(environment.get("id"))
    result_label = "SUCCESS_FORCED" if forced_stop else "SUCCESS"
    save_environment_log(environment["name"], resolved_host, service, action_type, result_label, username)
    save_execution_trace(
        environment.get("name"),
        resolved_host,
        service,
        action_type,
        result_label,
        username,
        status=final_status,
        forced_stop=forced_stop,
    )
    return {"success": True, "server_ip": resolved_host, "forced_stop": forced_stop, "status": final_status}


def _safe_bulk_file_token(value):
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return token.strip("._") or "local"


def _parse_collector_bulk_output(stdout, stderr=""):
    results = []
    fatals = []
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("GAMB_BULK_RESULT|"):
            parts = line.split("|", 5)
            if len(parts) >= 6:
                results.append(
                    {
                        "service": parts[1].strip(),
                        "action": parts[2].strip(),
                        "result": parts[3].strip(),
                        "status": parts[4].strip(),
                        "message": parts[5].strip(),
                    }
                )
        elif line.startswith("GAMB_BULK_FATAL|"):
            fatals.append(line.split("|", 1)[1].strip())

    stderr_text = str(stderr or "").strip()
    if stderr_text:
        fatals.append(stderr_text)
    return results, fatals


def _run_collector_bulk_action_for_host(environment, host, services, action_type, username, job_id):
    script_path = os.path.abspath(COLLECTOR_BULK_ACTION_BAT_PATH)
    if not os.path.exists(script_path):
        raise RuntimeError(f"BAT de lote do coletor nao encontrado: {script_path}")

    os.makedirs(DATA_DIR, exist_ok=True)
    host_label = str(host or "").strip() or "localhost"
    file_token = _safe_bulk_file_token(f"{job_id}-{host_label}")
    list_path = os.path.abspath(os.path.join(DATA_DIR, f"bulk-services-{file_token}.txt"))
    log_path = os.path.abspath(os.path.join(DATA_DIR, f"bulk-services-{file_token}.log"))
    service_names = [str(service.get("name") or "").strip() for service in services if str(service.get("name") or "").strip()]

    with open(list_path, "w", encoding="utf-8") as file:
        file.write("\n".join(service_names))
        file.write("\n")

    try:
        completed = subprocess.run(
            ["cmd.exe", "/c", script_path, action_type, host_label, list_path, log_path],
            capture_output=True,
            text=True,
            timeout=max(90, len(service_names) * 70),
        )
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass

    parsed_results, fatal_errors = _parse_collector_bulk_output(completed.stdout, completed.stderr)
    results_by_service = {
        _normalize_service_lookup_key(item.get("service")): item
        for item in parsed_results
        if item.get("service")
    }
    fallback_error = "; ".join(fatal_errors) or "BAT de lote nao retornou resultado para o servico."
    output_tail = "\n".join(
        [str(completed.stdout or "").strip(), str(completed.stderr or "").strip()]
    ).strip()[-3000:]

    rows = []
    for service in services:
        service_name = str(service.get("name") or "").strip()
        result = results_by_service.get(_normalize_service_lookup_key(service_name))
        if not result:
            result = {
                "service": service_name,
                "action": action_type,
                "result": "ERROR",
                "status": "UNKNOWN",
                "message": fallback_error,
            }
            if output_tail:
                result["details"] = output_tail
        result["server_ip"] = host_label
        rows.append(result)

    invalidate_service_status_cache(host_label)
    invalidate_environment_status_cache(environment.get("id"))
    return rows


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
    services = [
        item
        for item in (environment.get("services", []) + environment.get("infra_services", []))
        if item.get("name") and not is_license_service(item.get("name"), item.get("display_name"))
    ]
    environment_type = normalize_environment_type(
        (environment or {}).get("environment_type"),
        (environment or {}).get("name"),
    )
    is_production = environment_type == "producao"
    if action_type == "start":
        sequence = ["alta", "media", "baixa", "p1"] if is_production else ["alta", "media"]
    else:
        sequence = ["p1", "baixa", "media", "alta"]

    ordered = []
    seen = set()
    for priority in sequence:
        for service in services:
            service_key = (
                str(service.get("name") or "").strip().lower(),
                get_service_server_ip(service).lower(),
            )
            if service_key in seen:
                continue
            if _normalize_bulk_priority(service.get("priority")) == priority:
                ordered.append(service)
                seen.add(service_key)

    if is_production:
        for service in services:
            service_key = (
                str(service.get("name") or "").strip().lower(),
                get_service_server_ip(service).lower(),
            )
            if service_key in seen:
                continue
            ordered.append(service)
            seen.add(service_key)

    return ordered


def build_teams_adaptive_card(title, message):
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {
            "width": "Full"
        },
        "body": [
            {
                "type": "TextBlock",
                "text": str(title or "Protheus Monitor").strip() or "Protheus Monitor",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": str(message or "").strip(),
                "wrap": True
            }
        ]
    }


def get_teams_alert_icon(alert):
    kind = str((alert or {}).get("kind") or "").strip()
    severity = str((alert or {}).get("severity") or "").strip().lower()
    if kind == "windows_updates":
        return "🪟"
    if kind == "disk":
        return "💾"
    if kind in {"collector_json_missing", "collector_host_offline"}:
        return "🖥️"
    if kind in {"production_service_stopped", "high_priority_service"}:
        return "⚙️"
    if kind == "service_recovered":
        return "✅"
    if severity == "critical":
        return "🚨"
    if severity == "warning":
        return "⚠️"
    return "ℹ️"


def get_teams_alert_color(alert):
    severity = str((alert or {}).get("severity") or "").strip().lower()
    if severity == "critical":
        return "Attention"
    if severity == "warning":
        return "Warning"
    return "Accent"


def get_teams_alert_style(alert):
    severity = str((alert or {}).get("severity") or "").strip().lower()
    if severity == "critical":
        return "attention"
    if severity == "warning":
        return "warning"
    return "accent"


def build_teams_alert_card(alert):
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    kind = str(alert.get("kind") or "").strip()
    severity = str(alert.get("severity") or "info").strip().upper() or "INFO"
    title = str(alert.get("title") or "Alerta").strip() or "Alerta"
    environment_name = str(alert.get("environment_name") or "Ambiente").strip() or "Ambiente"
    host = str(alert.get("host") or "-").strip() or "-"
    message = str(alert.get("message") or "").strip()
    icon = get_teams_alert_icon(alert)

    facts = [
        {"title": "Severidade", "value": severity},
        {"title": "Ambiente", "value": environment_name},
        {"title": "Host", "value": host},
    ]

    if kind == "windows_updates":
        facts = [
            {"title": "Severidade", "value": severity},
            {"title": "Ambiente", "value": environment_name},
            {"title": "Server IP", "value": str(alert.get("server_ip") or host).strip() or host},
            {"title": "Updates software", "value": str(alert.get("windows_updates_pending") if alert.get("windows_updates_pending") is not None else "-")},
        ]
    elif kind == "disk":
        facts.append({"title": "Unidade", "value": str(alert.get("drive") or "-")})
        if alert.get("free_percent") is not None:
            facts.append({"title": "Livre", "value": f"{alert.get('free_percent')}%"})
    elif kind in {"production_service_stopped", "high_priority_service", "service_recovered"}:
        facts.append({"title": "Serviço", "value": str(alert.get("service_name") or "-")})
    elif kind in {"collector_json_missing", "collector_host_offline"}:
        facts.append({"title": "Coletor", "value": "Sem sincronização válida"})

    facts.append({"title": "Gerado em", "value": timestamp})

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {
            "width": "Full"
        },
        "body": [
            {
                "type": "Container",
                "style": get_teams_alert_style(alert),
                "bleed": True,
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": icon,
                                        "size": "Large",
                                        "wrap": True
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"Protheus Monitor | {title}",
                                        "weight": "Bolder",
                                        "size": "Medium",
                                        "color": get_teams_alert_color(alert),
                                        "wrap": True
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": environment_name,
                                        "isSubtle": True,
                                        "spacing": "None",
                                        "wrap": True
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True,
                "spacing": "Medium"
            },
            {
                "type": "FactSet",
                "facts": facts
            }
        ]
    }

    if kind in {"production_service_stopped", "high_priority_service"}:
        action_url = build_teams_service_action_url(alert, action_type="start")
        if action_url:
            card["actions"] = [
                {
                    "type": "Action.OpenUrl",
                    "title": "Iniciar serviço",
                    "url": action_url,
                }
            ]

    return card


def send_teams(message, webhook_url="", title="Protheus Monitor"):
    target_webhook = str(webhook_url or "").strip() or TEAMS_WEBHOOK
    if not target_webhook:
        return False, "Webhook do Teams não configurado."
    try:
        import requests

        payload = message if isinstance(message, dict) else build_teams_adaptive_card(title, message)
        response = requests.post(target_webhook, json=payload, timeout=10)
        if 200 <= response.status_code < 300:
            return True, ""
        return False, f"Teams respondeu com HTTP {response.status_code}."
    except Exception as exc:
        return False, str(exc)


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


def format_teams_alert_digest(alerts):
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    lines = [f"Protheus Monitor | {len(alerts)} novo(s) alerta(s)", f"Gerado em: {timestamp}", ""]
    for alert in alerts[:20]:
        severity = str(alert.get("severity") or "").strip().upper() or "INFO"
        environment_name = str(alert.get("environment_name") or "Ambiente").strip()
        host = str(alert.get("host") or "-").strip()
        title = str(alert.get("title") or "Alerta").strip()
        message = str(alert.get("message") or "").strip()
        lines.append(f"[{severity}] {environment_name} | {host}")
        lines.append(f"{title}: {message}")
        lines.append("")
    if len(alerts) > 20:
        lines.append(f"... e mais {len(alerts) - 20} alerta(s).")
    return "\n".join(lines).strip()


def format_single_teams_alert(alert):
    severity = str(alert.get("severity") or "").strip().upper() or "INFO"
    environment_name = str(alert.get("environment_name") or "Ambiente").strip()
    host = str(alert.get("host") or "-").strip()
    title = str(alert.get("title") or "Alerta").strip()
    message = str(alert.get("message") or "").strip()
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if str(alert.get("kind") or "").strip() == "windows_updates":
        server_ip = str(alert.get("server_ip") or host).strip() or host
        pending_updates = alert.get("windows_updates_pending")
        return "\n".join(
            [
                f"Severidade: {severity}",
                f"Ambiente: {environment_name}",
                f"Server IP: {server_ip}",
                f"Updates de software pendentes: {pending_updates}",
                f"Mensagem: {message}",
                f"Gerado em: {timestamp}",
            ]
        )
    return "\n".join(
        [
            f"Severidade: {severity}",
            f"Ambiente: {environment_name}",
            f"Host: {host}",
            f"Mensagem: {message}",
            f"Gerado em: {timestamp}",
        ]
    )


def parse_hhmm_to_minutes(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        return None
    hour, minute = [int(part) for part in text.split(":", 1)]
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def is_teams_alert_schedule_active(settings, when=None):
    when = when or datetime.now()
    days = settings.get("teams_schedule_days")
    if not isinstance(days, list):
        days = DEFAULT_ALERT_SETTINGS["teams_schedule_days"]
    try:
        allowed_days = {int(day) for day in days}
    except Exception:
        allowed_days = set(DEFAULT_ALERT_SETTINGS["teams_schedule_days"])
    if when.weekday() not in allowed_days:
        return False

    if settings.get("teams_schedule_full_time", True):
        return True

    start_minutes = parse_hhmm_to_minutes(settings.get("teams_schedule_start"))
    end_minutes = parse_hhmm_to_minutes(settings.get("teams_schedule_end"))
    if start_minutes is None or end_minutes is None:
        return True

    current_minutes = when.hour * 60 + when.minute
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def filter_alerts_for_teams(alerts, settings):
    allowed_severities = settings.get("teams_alert_severities") or DEFAULT_ALERT_SETTINGS["teams_alert_severities"]
    allowed_severities = {str(severity or "").strip().lower() for severity in allowed_severities}
    return [
        alert for alert in (alerts or [])
        if str(alert.get("severity") or "").strip().lower() in allowed_severities
    ]


def dispatch_monitor_alerts():
    global ALERT_LAST_DISPATCH_TS

    now = time.time()
    dispatch_time = datetime.now()
    if now - ALERT_LAST_DISPATCH_TS < ALERT_DISPATCH_INTERVAL_SECONDS:
        return

    with ALERT_DISPATCH_LOCK:
        now = time.time()
        dispatch_time = datetime.now()
        if now - ALERT_LAST_DISPATCH_TS < ALERT_DISPATCH_INTERVAL_SECONDS:
            return
        ALERT_LAST_DISPATCH_TS = now

        settings = load_alert_settings()
        if not settings.get("teams_enabled"):
            return
        if not is_teams_alert_schedule_active(settings):
            return

        webhook_url = get_teams_webhook_url(settings)
        if not webhook_url:
            return

        payload = build_monitor_alerts_payload(include_all=True)
        alerts = filter_alerts_for_teams(payload.get("alerts") or [], settings)
        service_alert_states = payload.get("service_alert_states") if isinstance(payload, dict) else {}
        if not isinstance(service_alert_states, dict):
            service_alert_states = {}

        state = load_alert_delivery_state()
        teams_state = state.get("teams") if isinstance(state, dict) else {}
        if not isinstance(teams_state, dict):
            teams_state = {}
        service_state = state.get("service_alerts") if isinstance(state, dict) else {}
        if not isinstance(service_state, dict):
            service_state = {}

        recovery_alerts = []
        for state_key, current_state in service_alert_states.items():
            if not isinstance(current_state, dict):
                continue
            previous_state = service_state.get(state_key) if isinstance(service_state.get(state_key), dict) else {}
            is_active = bool(current_state.get("is_active"))
            was_active = bool(previous_state.get("is_active"))
            if not previous_state:
                prior_stopped_alert = build_service_stopped_alert_from_state(current_state)
                prior_signature = build_teams_alert_signature(prior_stopped_alert)
                was_active = prior_signature in teams_state
            if was_active and not is_active:
                recovery_alerts.append(build_service_recovery_alert(current_state))
            service_state[state_key] = {
                "is_active": is_active,
                "updated_at": now,
                "kind": current_state.get("kind"),
                "environment_id": current_state.get("environment_id"),
                "host": current_state.get("host"),
                "server_ip": current_state.get("server_ip"),
                "service_name": current_state.get("service_name"),
                "display_name": current_state.get("display_name"),
                "environment_name": current_state.get("environment_name"),
            }

        recovery_alerts = filter_alerts_for_teams(recovery_alerts, settings)
        alerts = list(alerts) + list(recovery_alerts)
        if not alerts:
            state["teams"] = teams_state
            state["service_alerts"] = service_state
            save_alert_delivery_state(state)
            return

        max_cutoff = now - max(ALERT_TEAMS_DEDUP_SECONDS, ALERT_TEAMS_WINDOWS_UPDATES_DEDUP_SECONDS)
        teams_state = {
            signature: sent_at
            for signature, sent_at in teams_state.items()
            if isinstance(sent_at, (int, float)) and sent_at >= max_cutoff
        }

        new_alerts = []
        for alert in alerts:
            if (
                str((alert or {}).get("kind") or "").strip() == "windows_updates"
                and not is_teams_windows_updates_delivery_day(dispatch_time)
            ):
                continue
            dedup_seconds = get_teams_alert_dedup_seconds(alert)
            cutoff = now - dedup_seconds
            signature = build_teams_alert_signature(alert)
            sent_at = teams_state.get(signature, 0)
            if isinstance(sent_at, (int, float)) and sent_at >= cutoff:
                continue
            new_alerts.append(alert)
            teams_state[signature] = now

        if not new_alerts:
            state["teams"] = teams_state
            state["service_alerts"] = service_state
            save_alert_delivery_state(state)
            return

        sent_count = 0
        errors = []
        for alert in new_alerts:
            sent, error = send_teams(
                build_teams_alert_card(alert),
                webhook_url=webhook_url,
            )
            if sent:
                sent_count += 1
            else:
                errors.append(error)

        if sent_count:
            state["teams"] = teams_state
            state["service_alerts"] = service_state
            save_alert_delivery_state(state)
            save_log("ALERTAS", "TEAMS", "SUCCESS", "system", count=sent_count)
        if errors:
            save_log("ALERTAS", "TEAMS", "ERROR", "system", error="; ".join(errors[:3]))


def send_all_teams_alerts_now(actor="system"):
    settings = load_alert_settings()
    if not settings.get("teams_enabled"):
        return {
            "success": False,
            "error": "Webhook do Teams desativado na rotina de alertas.",
            "sent_count": 0,
            "errors": [],
        }

    webhook_url = get_teams_webhook_url(settings)
    if not webhook_url:
        return {
            "success": False,
            "error": "Webhook do Teams não configurado.",
            "sent_count": 0,
            "errors": [],
        }

    payload = build_monitor_alerts_payload(include_all=True)
    alerts = filter_alerts_for_teams(payload.get("alerts") or [], settings)
    if not alerts:
        save_log("ALERTAS", "TEAMS_MANUAL", "SUCCESS", actor, count=0)
        return {
            "success": True,
            "sent_count": 0,
            "errors": [],
            "message": "Nenhum alerta elegível para envio.",
        }

    sent_count = 0
    errors = []
    for alert in alerts:
        sent, error = send_teams(
            build_teams_alert_card(alert),
            webhook_url=webhook_url,
        )
        if sent:
            sent_count += 1
        else:
            errors.append(error)

    state = load_alert_delivery_state()
    teams_state = state.get("teams") if isinstance(state, dict) else {}
    if not isinstance(teams_state, dict):
        teams_state = {}
    now = time.time()
    for alert in alerts:
        teams_state[build_teams_alert_signature(alert)] = now
    state["teams"] = teams_state
    save_alert_delivery_state(state)

    if sent_count:
        save_log("ALERTAS", "TEAMS_MANUAL", "SUCCESS", actor, count=sent_count)
    if errors:
        save_log("ALERTAS", "TEAMS_MANUAL", "ERROR", actor, error="; ".join(errors[:3]))

    return {
        "success": not errors,
        "sent_count": sent_count,
        "errors": errors,
        "message": f"{sent_count} alerta(s) enviado(s).",
    }


def trigger_monitor_alert_dispatch_async():
    thread = threading.Thread(
        target=dispatch_monitor_alerts,
        name="teams-alert-dispatch",
        daemon=True,
    )
    thread.start()


def serialize_user(user):
    return {
        "username": user["username"],
        "role": user.get("role", "operator"),
        "active": user.get("active", True),
        "created_at": user.get("created_at"),
    }


def render_readme_to_html():
    if not os.path.exists(README_FILE):
        return "<p class=\"text-sm text-slate-400\">Documentação não disponível no momento.</p>"

    with open(README_FILE, "r", encoding="utf-8") as file:
        lines = file.read().splitlines()

    html_parts = []
    in_list = False
    in_code = False
    code_lines = []
    current_section_open = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    def close_code():
        nonlocal in_code, code_lines
        if in_code:
            code_html = "\n".join(escape(line) for line in code_lines)
            html_parts.append(f"<pre class=\"overflow-x-auto rounded-2xl border border-slate-700 bg-slate-950/80 p-4 text-xs text-slate-200\"><code>{code_html}</code></pre>")
            in_code = False
            code_lines = []

    def close_section():
        nonlocal current_section_open
        close_list()
        close_code()
        if current_section_open:
            html_parts.append("</section>")
            current_section_open = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            close_list()
            if in_code:
                close_code()
            else:
                in_code = True
                code_lines = []
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            close_list()
            continue

        if stripped.startswith("# "):
            close_section()
            html_parts.append(f"<h1 class=\"text-2xl font-bold text-slate-100\">{escape(stripped[2:])}</h1>")
            continue
        if stripped.startswith("## "):
            close_section()
            html_parts.append("<section class=\"rounded-3xl border border-slate-700 bg-slate-900/40 p-5 shadow-sm\">")
            html_parts.append(f"<h2 class=\"text-xl font-semibold text-slate-100\">{escape(stripped[3:])}</h2>")
            current_section_open = True
            continue
        if stripped.startswith("### "):
            close_list()
            html_parts.append(f"<h3 class=\"mt-5 text-base font-semibold text-slate-100\">{escape(stripped[4:])}</h3>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                html_parts.append("<ul class=\"space-y-2 text-sm leading-6 text-slate-300\">")
                in_list = True
            html_parts.append(f"<li>{escape(stripped[2:])}</li>")
            continue

        close_list()
        html_parts.append(f"<p class=\"text-sm leading-7 text-slate-300\">{escape(stripped)}</p>")

    close_section()
    return (
        "<div class=\"space-y-5\">"
        + "".join(html_parts)
        + "</div>"
    ) or "<p class=\"text-sm text-slate-400\">Documentação não disponível no momento.</p>"


def get_readme_last_updated_label():
    if not os.path.exists(README_FILE):
        return ""
    updated_at = datetime.fromtimestamp(os.path.getmtime(README_FILE))
    return updated_at.strftime("%d/%m/%Y %H:%M")


@app.context_processor
def inject_app_version():
    return {"app_version": get_app_version()}


@app.before_request
def enforce_https():
    if not GAMB_FORCE_HTTPS:
        return
    if request.is_secure:
        return
    url = request.url.replace("http://", "https://", 1)
    return redirect(url, code=302)


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
            next_url = (request.args.get("next") or "").strip()
            if next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("index"))
        return render_template("login.html")

    data = request.get_json(silent=True) or request.form
    username = normalize_username(data.get("username"))
    password = data.get("password", "")

    user = find_user(username)
    if not user:
        return jsonify({"success": False, "error": "Usuário ou senha inválidos."}), 401

    if not user.get("active", True):
        return jsonify({"success": False, "error": "Usuário desativado. Procure um administrador."}), 403

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"success": False, "error": "Usuário ou senha inválidos."}), 401

    session.clear()
    session["username"] = user["username"]
    save_log(
        "AUTENTICACAO",
        "LOGIN",
        "SUCCESS",
        user["username"],
        ip=get_request_client_ip(),
        path=request.path,
        method=request.method,
    )

    return jsonify({"success": True, "user": serialize_user(user)})


@app.route("/teams/service-action", methods=["GET", "POST"])
def teams_service_action():
    token = (request.values.get("token") or "").strip()
    if not token:
        return render_template(
            "teams_service_action.html",
            action_context=None,
            error_message="Link de ação do Teams não informado.",
            success_message="",
            already_running=False,
        ), 400

    try:
        action_payload = load_teams_service_action_token(token)
    except ValueError as exc:
        return render_template(
            "teams_service_action.html",
            action_context=None,
            error_message=str(exc),
            success_message="",
            already_running=False,
        ), 400

    environment_id = str(action_payload.get("environment_id") or "").strip()
    service_name = str(action_payload.get("service_name") or "").strip()
    action_type = str(action_payload.get("action") or "start").strip().lower()
    token_host = str(action_payload.get("host") or "").strip()
    environment = find_environment(environment_id)
    user = current_user()

    if not user:
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    if not environment:
        return render_template(
            "teams_service_action.html",
            action_context=None,
            error_message="Ambiente não encontrado para esta ação.",
            success_message="",
            already_running=False,
        ), 404

    if not can_user_access_environment(user, environment):
        return render_template(
            "teams_service_action.html",
            action_context=None,
            error_message="Seu usuário não tem permissão para operar este ambiente.",
            success_message="",
            already_running=False,
        ), 403

    hydrated_environment = hydrate_environment_from_collector(environment, use_cache=False)
    resolved_service = find_service_in_environment(hydrated_environment, service_name, server_ip=token_host)
    if not resolved_service:
        resolved_service = find_service_in_environment(hydrated_environment, service_name)
    if not resolved_service:
        return render_template(
            "teams_service_action.html",
            action_context=None,
            error_message="Serviço não encontrado no ambiente informado.",
            success_message="",
            already_running=False,
        ), 404

    resolved_host = get_service_server_ip(resolved_service, hydrated_environment.get("host"))
    current_status = str(resolved_service.get("status") or "").strip().upper() or "UNKNOWN"
    action_context = {
        "environment_name": str(hydrated_environment.get("name") or environment_id).strip(),
        "environment_id": environment_id,
        "service_name": str(resolved_service.get("name") or service_name).strip(),
        "display_name": str(resolved_service.get("display_name") or resolved_service.get("name") or service_name).strip(),
        "host": resolved_host,
        "current_status": current_status,
        "token": token,
        "action": action_type,
    }

    if request.method == "GET":
        return render_template(
            "teams_service_action.html",
            action_context=action_context,
            error_message="",
            success_message="",
            already_running=service_status_is_running(current_status),
        )

    if action_type != "start":
        return render_template(
            "teams_service_action.html",
            action_context=action_context,
            error_message="Somente a ação de iniciar serviço está disponível no card do Teams.",
            success_message="",
            already_running=False,
        ), 400

    if service_status_is_running(current_status):
        return render_template(
            "teams_service_action.html",
            action_context=action_context,
            error_message="",
            success_message="O serviço já estava em execução.",
            already_running=True,
        )

    try:
        result = _run_service_action(
            hydrated_environment,
            resolved_host,
            action_context["service_name"],
            "start",
            user["username"],
        )
        final_status = str(result.get("status") or "RUNNING").strip().upper()
        action_context["current_status"] = final_status
        return render_template(
            "teams_service_action.html",
            action_context=action_context,
            error_message="",
            success_message=f"Serviço iniciado com sucesso. Status confirmado: {final_status}.",
            already_running=False,
        )
    except Exception as exc:
        save_execution_trace(
            hydrated_environment.get("name"),
            resolved_host,
            action_context["service_name"],
            "start",
            "ERROR",
            user["username"],
            error=str(exc),
            mode="teams_card",
        )
        return render_template(
            "teams_service_action.html",
            action_context=action_context,
            error_message=str(exc),
            success_message="",
            already_running=False,
        ), 500


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    user = current_user()
    save_log(
        "AUTENTICACAO",
        "LOGOUT",
        "SUCCESS",
        (user or {}).get("username", "anonymous"),
        ip=get_request_client_ip(),
        path=request.path,
        method=request.method,
    )
    session.clear()
    return jsonify({"success": True})


@app.route("/session")
def session_info():
    user = current_user()
    return jsonify({"authenticated": bool(user), "user": serialize_user(user) if user else None})


@app.route("/servers", methods=["GET"])
@admin_required
def get_servers():
    servers = load_servers()
    return jsonify({"success": True, "servers": servers, "raw": ", ".join(servers)})


@app.route("/servers/inventory", methods=["GET"])
@admin_required
def get_servers_inventory():
    refresh = _as_bool(request.args.get("refresh"))
    servers = load_servers()
    if not servers:
        payload = {
            "success": True,
            "items": [],
            "errors": [],
            "steps": ["Nenhum servidor cadastrado para consulta."],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cached": False,
        }
        return jsonify(payload)

    if not refresh:
        cached = get_cached_server_inventory(servers)
        if cached:
            cached_payload = dict(cached)
            cached_payload["cached"] = True
            cached_payload.pop("hosts", None)
            return jsonify(cached_payload)

    payload = collect_server_inventory(servers)
    payload["cached"] = False
    if payload.get("success"):
        set_cached_server_inventory(servers, payload)
    result_label = "SUCCESS" if payload.get("success") and not payload.get("errors") else "WARNING"
    save_log("SERVERS", "INVENTORY", result_label, current_user()["username"])
    return jsonify(payload)


@app.route("/admin/clear-logs", methods=["POST"])
@admin_required
def clear_logs():
    data = request.get_json(silent=True) or {}
    confirmation = str(data.get("confirmation") or "").strip().upper()
    if confirmation != "LIMPAR":
        return jsonify({"success": False, "error": "Confirmação inválida. Digite LIMPAR para executar."}), 400

    cleared = clear_operational_logs()
    return jsonify({"success": True, "cleared": cleared})


@app.route("/server-alerts", methods=["GET"])
@admin_required
def get_server_alerts():
    refresh = _as_bool(request.args.get("refresh"))
    payload = build_server_alerts_payload(force_refresh=refresh)
    result_label = "SUCCESS" if payload.get("success") else "WARNING"
    save_log("SERVERS", "ALERTS", result_label, current_user()["username"])
    return jsonify(payload)


@app.route("/alert-settings", methods=["GET"])
@admin_required
def get_alert_settings():
    return jsonify({"success": True, "settings": load_alert_settings()})


@app.route("/alert-settings", methods=["PUT"])
@admin_required
def update_alert_settings():
    data = request.get_json(silent=True) or {}
    actor = current_user()
    settings = save_alert_settings(data)
    save_log("ALERTAS", "UPDATE_SETTINGS", "SUCCESS", actor.get("username", "unknown"))
    return jsonify({"success": True, "settings": settings})


@app.route("/alerts/teams/send-now", methods=["POST"])
@admin_required
def send_teams_alerts_now():
    actor = current_user()
    result = send_all_teams_alerts_now(actor.get("username", "unknown"))
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/alerts", methods=["GET"])
@login_required
def get_monitor_alerts():
    trigger_monitor_alert_dispatch_async()
    return jsonify(build_monitor_alerts_payload(current_user()))


@app.route("/alerts/summary", methods=["GET"])
@login_required
def get_monitor_alerts_summary():
    payload = build_monitor_alerts_payload(current_user())
    alerts = payload.get("alerts") or []
    return jsonify(
        {
            "success": True,
            "count": len(alerts),
            "signature": get_alerts_signature(alerts),
        }
    )


@app.route("/documentation", methods=["GET"])
@login_required
def documentation():
    return jsonify(
        {
            "success": True,
            "html": render_readme_to_html(),
            "updated_at": get_readme_last_updated_label(),
        }
    )


@app.route("/")
@login_required
def index():
    ensure_service_status_monitor_started()
    user = current_user()
    environments = [environment for environment in load_environments() if can_user_access_environment(user, environment)]
    initial_environments = []

    for environment in environments:
        cached_environment = get_cached_environment_status(environment["id"])
        initial_environments.append(cached_environment or build_initial_environment_payload(environment))

    return render_template(
        "index.html",
        user=user,
        initial_environments=initial_environments,
        documentation_html=render_readme_to_html(),
        documentation_updated_at=get_readme_last_updated_label(),
    )


@app.route("/admin")
@admin_required
def admin_panel():
    return render_template("admin.html", user=current_user())


@app.route("/server-inventory")
@admin_required
def server_inventory_page():
    return render_template("server_inventory.html", user=current_user(), initial_servers=load_servers())


@app.route("/status")
@login_required
def status():
    ensure_service_status_monitor_started()
    user = current_user()
    environment_id = request.args.get("environment_id", "").strip()
    refresh = _as_bool(request.args.get("refresh"))
    if environment_id:
        environment = find_environment(environment_id)
        if not environment:
            return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404
        if not can_user_access_environment(user, environment):
            return jsonify({"success": False, "error": "Acesso negado ao ambiente de produção."}), 403
        cached_environment = get_cached_environment_status(environment_id)
        if cached_environment and not refresh:
            return jsonify(cached_environment)
        if refresh:
            refresh_collector_cache_for_environment(environment)
        fresh_environment = build_environment_status(environment)
        with ENVIRONMENT_STATUS_CACHE_LOCK:
            ENVIRONMENT_STATUS_CACHE[environment_id] = fresh_environment
        return jsonify(fresh_environment)

    environments = [environment for environment in load_environments() if can_user_access_environment(user, environment)]
    cached_items = get_all_cached_environment_statuses()
    if cached_items:
        cached_by_id = {item.get("id"): item for item in cached_items if item.get("id")}
        ordered_cached = [cached_by_id[environment["id"]] for environment in environments if environment["id"] in cached_by_id]
        if ordered_cached:
            return jsonify(ordered_cached)

    max_workers = min(max(len(environments), 1), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        result = list(executor.map(build_environment_status, environments))
    with ENVIRONMENT_STATUS_CACHE_LOCK:
        ENVIRONMENT_STATUS_CACHE.clear()
        for item in result:
            ENVIRONMENT_STATUS_CACHE[item["id"]] = item
    return jsonify(result)


@app.route("/action", methods=["POST"])
@login_required
def action():
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    service = data.get("service")
    server_ip = (data.get("server_ip") or "").strip()
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

    resolved_service = find_service_in_environment(environment, service, server_ip=server_ip)

    if not resolved_service:
        return jsonify({"success": False, "error": "Serviço não cadastrado para o servidor informado."}), 404

    resolved_host = get_service_server_ip(resolved_service, environment.get("host"))
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
            server_ip=resolved_host,
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
                    server_ip=result.get("server_ip") or resolved_host,
                    confirmed_status=result.get("status"),
                    forced_stop=bool(result.get("forced_stop")),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:
                target = f"{environment['name']} [{resolved_host or 'local'}] - {service}"
                msg = f"ERRO: {target} - {action_type}"
                save_environment_log(environment["name"], resolved_host, service, action_type, "ERROR", user["username"])
                save_execution_trace(
                    environment.get("name"),
                    resolved_host,
                    service,
                    action_type,
                    "ERROR",
                    user["username"],
                    error=str(exc),
                    mode="single_async",
                )
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
        return jsonify({"success": True, "queued": True, "job_id": job_id, "server_ip": resolved_host})

    try:
        return jsonify(_run_service_action(environment, resolved_host, service, action_type, user["username"]))
    except Exception as exc:
        target = f"{environment['name']} [{resolved_host or 'local'}] - {service}"
        msg = f"ERRO: {target} - {action_type}"
        save_environment_log(environment["name"], resolved_host, service, action_type, "ERROR", user["username"])
        save_execution_trace(
            environment.get("name"),
            resolved_host,
            service,
            action_type,
            "ERROR",
            user["username"],
            error=str(exc),
            mode="single_sync",
        )
        send_teams(msg)
        send_email(msg)
        return jsonify({"success": False, "error": str(exc), "server_ip": resolved_host}), 500


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

    # Regra operacional: toda ação deve consultar o gamb-coletor antes de executar.
    environment = hydrate_environment_from_collector(environment, use_cache=False)

    ordered_services = _build_bulk_ordered_services(environment, action_type)
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
        skipped_count = 0
        errors = []
        services_by_host = {}

        for service in ordered_services:
            service_name = service.get("name")
            resolved_host = get_service_server_ip(service, environment.get("host"))
            try:
                resolved_service = find_service_in_environment(environment, service_name, server_ip=resolved_host)
                if not resolved_service:
                    raise ValueError("Servico nao encontrado no ambiente para o servidor informado.")
                host_key = resolved_host or "localhost"
                services_by_host.setdefault(host_key, []).append(resolved_service)
            except Exception as exc:
                fail_count += 1
                save_execution_trace(
                    environment.get("name"),
                    resolved_host,
                    service_name,
                    action_type,
                    "ERROR",
                    user["username"],
                    error=str(exc),
                    mode="bulk",
                    job_id=job_id,
                )
                if len(errors) < 20:
                    errors.append(f"{service_name} [{resolved_host or 'local'}]: {str(exc)}")

            _set_action_job(job_id, success_count=success_count, fail_count=fail_count, skipped_count=skipped_count)

        for host, host_services in services_by_host.items():
            try:
                batch_rows = _run_collector_bulk_action_for_host(
                    environment,
                    host,
                    host_services,
                    action_type,
                    user["username"],
                    job_id,
                )
            except Exception as exc:
                for service in host_services:
                    service_name = service.get("name")
                    fail_count += 1
                    save_execution_trace(
                        environment.get("name"),
                        host,
                        service_name,
                        action_type,
                        "ERROR",
                        user["username"],
                        error=str(exc),
                        mode="bulk_bat",
                        job_id=job_id,
                    )
                    if len(errors) < 20:
                        errors.append(f"{service_name} [{host or 'local'}]: {str(exc)}")
                _set_action_job(job_id, success_count=success_count, fail_count=fail_count, skipped_count=skipped_count)
                continue

            for row in batch_rows:
                service_name = row.get("service") or ""
                result_label = str(row.get("result") or "ERROR").strip().upper()
                status_label = str(row.get("status") or "").strip().upper()
                message = str(row.get("message") or "").strip()

                if result_label.startswith("SKIPPED"):
                    skipped_count += 1
                    success_count += 1
                    save_execution_trace(
                        environment.get("name"),
                        host,
                        service_name,
                        action_type,
                        result_label,
                        user["username"],
                        status=status_label,
                        mode="bulk_bat",
                        job_id=job_id,
                    )
                elif result_label == "SUCCESS":
                    success_count += 1
                    save_environment_log(environment["name"], host, service_name, action_type, "SUCCESS", user["username"])
                    save_execution_trace(
                        environment.get("name"),
                        host,
                        service_name,
                        action_type,
                        "SUCCESS",
                        user["username"],
                        status=status_label,
                        forced_stop=action_type == "stop",
                        mode="bulk_bat",
                        job_id=job_id,
                    )
                else:
                    fail_count += 1
                    save_execution_trace(
                        environment.get("name"),
                        host,
                        service_name,
                        action_type,
                        "ERROR",
                        user["username"],
                        status=status_label,
                        error=message or row.get("details") or "Falha na execucao do BAT de lote.",
                        mode="bulk_bat",
                        job_id=job_id,
                    )
                    if len(errors) < 20:
                        errors.append(f"{service_name} [{host or 'local'}]: {message or 'Falha na execucao do BAT de lote.'}")

            _set_action_job(job_id, success_count=success_count, fail_count=fail_count, skipped_count=skipped_count)

        _set_action_job(
            job_id,
            status="completed",
            success=fail_count == 0,
            success_count=success_count,
            fail_count=fail_count,
            skipped_count=skipped_count,
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
    server_ip = (data.get("server_ip") or "").strip()
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

    # Regra operacional: toda ação deve consultar o gamb-coletor antes de executar.
    environment = hydrate_environment_from_collector(environment, use_cache=False)

    resolved_service = find_service_in_environment(environment, service_name, server_ip=server_ip)
    if not resolved_service:
        return jsonify({"success": False, "error": "Serviço não cadastrado para o servidor informado."}), 404

    log_path = (resolved_service.get("console_log_file") or "").strip()
    if not log_path:
        return jsonify({"success": False, "error": "Console log file não cadastrado para este serviço."}), 400

    resolved_host = get_service_server_ip(resolved_service, environment.get("host"))
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
            "server_ip": resolved_host,
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


@app.route("/execution-trace")
@admin_required
def execution_trace():
    limit = int(request.args.get("limit") or 200)
    limit = max(1, min(limit, 1000))

    if not os.path.exists(EXECUTION_TRACE_FILE):
        return jsonify([])

    try:
        with open(EXECUTION_TRACE_FILE, "r", encoding="utf-8-sig") as file:
            data = json.load(file)
            if not isinstance(data, list):
                data = []
    except Exception:
        data = []
    return jsonify(data[:limit])


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


@app.route("/collector/deployments")
@admin_required
def collector_deployments():
    versions = list_available_collector_versions()
    latest_version = versions[0]["version"] if versions else ""
    environments_data = load_environments()
    return jsonify(
        {
            "success": True,
            "versions": versions,
            "latest_version": latest_version,
            "environments": [build_environment_collector_deployment_status(environment, latest_version) for environment in environments_data],
        }
    )


@app.route("/collector/deployments/<environment_id>", methods=["POST"])
@admin_required
def deploy_collector_to_environment(environment_id):
    data = request.get_json(silent=True) or {}
    version_name = str(data.get("version") or "").strip()
    actor = current_user()

    if not version_name:
        return jsonify({"success": False, "error": "Versao do coletor obrigatoria."}), 400

    version_info = get_collector_version_info(version_name)
    if not version_info:
        return jsonify({"success": False, "error": "Versao do coletor nao encontrada."}), 404

    environment = find_environment(environment_id)
    if not environment:
        return jsonify({"success": False, "error": "Ambiente nao encontrado."}), 404

    target_hosts = _collect_environment_hosts_for_collector(environment)
    if not target_hosts:
        return jsonify({"success": False, "error": "Nenhum host configurado para o ambiente."}), 400

    results = []
    failures = []
    for host in target_hosts:
        try:
            results.append(deploy_collector_version_to_host(host, version_name, actor["username"]))
        except Exception as exc:
            failures.append({"host": host, "error": str(exc)})

    result_label = "SUCCESS" if not failures else ("PARTIAL" if results else "ERROR")
    error_message = ""
    if failures and not results:
        error_message = " | ".join(
            f"{item.get('host')}: {item.get('error')}"
            for item in failures[:2]
            if item.get("error")
        )
    save_log(
        f"COLETOR :: {environment.get('name')}",
        f"DEPLOY::{version_name}",
        result_label,
        actor["username"],
        hosts=target_hosts,
        failures=failures,
    )

    return jsonify(
        {
            "success": True if results or not failures else False,
            "environment_id": environment_id,
            "environment_name": environment.get("name"),
            "target_version": version_name,
            "error": error_message,
            "results": results,
            "failures": failures,
            "current_status": build_environment_collector_deployment_status(environment, version_name),
        }
    )


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

        infra = []
        services = []
        for item in discovered:
            if not (item.get("path_executable") or "").strip():
                continue
            if is_infra_service(item):
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
    ensure_alert_settings_file()
    ssl_context = None
    if GAMB_SSL_CERT_FILE and GAMB_SSL_KEY_FILE and os.path.exists(GAMB_SSL_CERT_FILE) and os.path.exists(GAMB_SSL_KEY_FILE):
        ssl_context = (GAMB_SSL_CERT_FILE, GAMB_SSL_KEY_FILE)
    app.run(host="0.0.0.0", port=5000, debug=False, ssl_context=ssl_context)



from datetime import datetime
from functools import wraps
import json
import os
import re
import smtplib

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

DEFAULT_ADMIN_USERNAME = os.getenv("PROTHEUS_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("PROTHEUS_ADMIN_PASSWORD", "admin123")

# ===== AMBIENTES =====
DEFAULT_ENVIRONMENTS = [
    {
        "id": "apex-hml3",
        "name": "APEX-HML3",
        "host": "127.0.0.1",
        "services": [
            {"name": "TOTVS-Appserver12-APEX-HML3", "port": ""},
            {"name": "TOTVS-Appserver12-APEX-HML3-REST", "port": ""},
            {"name": "TOTVS-Appserver12-APEX-HML3-SCHED", "port": ""},
            {"name": "TOTVS-Appserver12-APEX-HML3-WF", "port": ""},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS", "port": ""},
            {"name": "TOTVS-Appserver12-APEX-HML3-WS2", "port": ""},
        ],
    },
    {
        "id": "infra",
        "name": "INFRA",
        "host": "127.0.0.1",
        "services": [
            {"name": "licenseVirtual", "port": ""},
            {"name": "TOTVSDBAccess64", "port": ""},
            {"name": "TOTVSDBAccess64TSS", "port": ""},
            {"name": "TOTVSservice", "port": ""},
        ],
    },
]


def normalize_username(username):
    return (username or "").strip().lower()


def is_valid_username(username):
    return bool(re.fullmatch(r"[a-z0-9._-]{3,40}", username or ""))


def slugify_environment_name(name):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return base[:50] or "ambiente"


def normalize_port(value):
    return str(value or "").strip()


def sanitize_service(service):
    return {
        "name": (service.get("name") or "").strip(),
        "port": normalize_port(service.get("port")),
    }


def sanitize_environment(environment, existing_id=None):
    services = [sanitize_service(service) for service in environment.get("services", [])]
    services = [service for service in services if service["name"]]

    return {
        "id": existing_id or slugify_environment_name(environment.get("name")),
        "name": (environment.get("name") or "").strip(),
        "host": (environment.get("host") or "").strip(),
        "services": services,
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
        if isinstance(item.get("services", []), list) and item.get("services") and isinstance(item["services"][0], str):
            item = {
                "id": item.get("id") or slugify_environment_name(item.get("name")),
                "name": item.get("name"),
                "host": item.get("host", "127.0.0.1"),
                "services": [{"name": service_name, "port": ""} for service_name in item["services"]],
            }
            changed = True

        normalized.append(sanitize_environment(item, item.get("id") or slugify_environment_name(item.get("name"))))

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


def resolve_service_machine(host):
    normalized = (host or "").strip().lower()
    if normalized in {"", "127.0.0.1", "localhost", ".", "(local)"}:
        return None
    return host


def current_user():
    username = session.get("username")
    if not username:
        return None
    return find_user(username)


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


def get_service_status_for_host(service_name, host):
    try:
        status = win32serviceutil.QueryServiceStatus(service_name, machine=resolve_service_machine(host))[1]

        mapping = {
            win32service.SERVICE_RUNNING: "RUNNING",
            win32service.SERVICE_STOPPED: "STOPPED",
            win32service.SERVICE_START_PENDING: "STARTING",
            win32service.SERVICE_STOP_PENDING: "STOPPING",
        }

        return mapping.get(status, "UNKNOWN")
    except Exception:
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
        data = json.load(file)
        data.insert(0, log)
        file.seek(0)
        json.dump(data[:200], file, indent=2, ensure_ascii=False)
        file.truncate()


def save_environment_log(environment_name, host, service, action, result, user):
    target = f"{environment_name} ({host or 'local'}) :: {service}"
    save_log(target, action, result, user)


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
    environments = load_environments()
    initial_environments = []

    for environment in environments:
        initial_environments.append(
            {
                "id": environment["id"],
                "environment": environment["name"],
                "host": environment.get("host", ""),
                "services": [
                    {
                        "name": service["name"],
                        "port": service.get("port", ""),
                        "status": "LOADING",
                    }
                    for service in environment.get("services", [])
                ],
            }
        )

    return render_template("index.html", user=current_user(), initial_environments=initial_environments)


@app.route("/admin")
@admin_required
def admin_panel():
    return render_template("admin.html", user=current_user())


@app.route("/status")
@login_required
def status():
    result = []

    for environment in load_environments():
        services = []
        for service in environment["services"]:
            services.append(
                {
                    "name": service["name"],
                    "port": service.get("port", ""),
                    "status": get_service_status_for_host(service["name"], environment.get("host")),
                }
            )

        result.append(
            {
                "id": environment["id"],
                "environment": environment["name"],
                "host": environment.get("host", ""),
                "services": services,
            }
        )

    return jsonify(result)


@app.route("/action", methods=["POST"])
@login_required
def action():
    data = request.get_json(silent=True) or {}
    environment_id = data.get("environment_id")
    service = data.get("service")
    action_type = data.get("action")
    user = current_user()
    environment = find_environment(environment_id)

    if not environment_id or not service or not action_type:
        return jsonify({"success": False, "error": "Ambiente, serviço e ação são obrigatórios."}), 400

    if not environment:
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404

    if not any(item["name"] == service for item in environment.get("services", [])):
        return jsonify({"success": False, "error": "Serviço não cadastrado para o ambiente."}), 404

    machine = resolve_service_machine(environment.get("host"))

    try:
        if action_type == "start":
            win32serviceutil.StartService(service, machine=machine)
        elif action_type == "stop":
            win32serviceutil.StopService(service, machine=machine)
        elif action_type == "restart":
            win32serviceutil.StopService(service, machine=machine)
            win32serviceutil.WaitForServiceStatus(service, win32service.SERVICE_STOPPED, 30, machine=machine)
            win32serviceutil.StartService(service, machine=machine)
        else:
            return jsonify({"success": False, "error": "Ação inválida."}), 400

        save_environment_log(environment["name"], environment.get("host"), service, action_type, "SUCCESS", user["username"])
        return jsonify({"success": True})
    except Exception as exc:
        target = f"{environment['name']} [{environment.get('host') or 'local'}] - {service}"
        msg = f"ERRO: {target} - {action_type}"
        save_environment_log(environment["name"], environment.get("host"), service, action_type, "ERROR", user["username"])
        send_teams(msg)
        send_email(msg)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/logs")
@login_required
def logs():
    if not os.path.exists(LOG_FILE):
        return jsonify([])

    with open(LOG_FILE, "r", encoding="utf-8") as file:
        return jsonify(json.load(file))


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

    if role not in {"admin", "operator"}:
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

        if new_role not in {"admin", "operator"}:
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


@app.route("/environments")
@admin_required
def environments():
    return jsonify(load_environments())


@app.route("/environments", methods=["POST"])
@admin_required
def create_environment():
    data = request.get_json(silent=True) or {}
    environment = sanitize_environment(data)

    if not environment["name"] or not environment["host"]:
        return jsonify({"success": False, "error": "Nome do ambiente e endereço IP são obrigatórios."}), 400

    if not environment["services"]:
        return jsonify({"success": False, "error": "Cadastre ao menos um serviço para o ambiente."}), 400

    environments_data = load_environments()
    existing_ids = {item["id"] for item in environments_data}
    base_id = environment["id"]
    suffix = 1

    while environment["id"] in existing_ids:
        suffix += 1
        environment["id"] = f"{base_id}-{suffix}"

    environments_data.append(environment)
    save_environments(environments_data)
    return jsonify({"success": True, "environment": environment}), 201


@app.route("/environments/<environment_id>", methods=["PUT"])
@admin_required
def update_environment(environment_id):
    data = request.get_json(silent=True) or {}
    environments_data = load_environments()

    for index, environment in enumerate(environments_data):
        if environment["id"] != environment_id:
            continue

        updated = sanitize_environment(data, existing_id=environment_id)
        if not updated["name"] or not updated["host"]:
            return jsonify({"success": False, "error": "Nome do ambiente e endereço IP são obrigatórios."}), 400
        if not updated["services"]:
            return jsonify({"success": False, "error": "Cadastre ao menos um serviço para o ambiente."}), 400

        environments_data[index] = updated
        save_environments(environments_data)
        return jsonify({"success": True, "environment": updated})

    return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404


@app.route("/environments/<environment_id>", methods=["DELETE"])
@admin_required
def delete_environment(environment_id):
    environments_data = load_environments()
    filtered = [environment for environment in environments_data if environment["id"] != environment_id]

    if len(filtered) == len(environments_data):
        return jsonify({"success": False, "error": "Ambiente não encontrado."}), 404

    save_environments(filtered)
    return jsonify({"success": True})


if __name__ == "__main__":
    ensure_users_file()
    ensure_environments_file()
    app.run(host="0.0.0.0", port=5000, debug=False)

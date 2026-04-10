from flask import Flask, render_template, jsonify, request
import win32serviceutil
import win32service

app = Flask(__name__, template_folder='templates')

# CONFIGURE SEUS AMBIENTES AQUI
ENVIRONMENTS = [
    {
        "name": "APEX-HML3",
        "services": [
            "TOTVSDBAccess64",
            "TOTVS-Appserver12-APEX-HML3",
            "TOTVS-Appserver12-APEX-HML3-SCHED",
            "TOTVS-Appserver12-APEX-HML3-SCHED",
            "TOTVS-Appserver12-APEX-HML3-REST"
        ]
    },
    {
        "name": "APEX-PROD",
        "services": [
            "TOTVSAppServer_PROD",
            "TOTVSBroker_PROD"
        ]
    }
]


def get_service_status(service_name):
    try:
        status = win32serviceutil.QueryServiceStatus(service_name)[1]

        mapping = {
            win32service.SERVICE_RUNNING: "RUNNING",
            win32service.SERVICE_STOPPED: "STOPPED",
            win32service.SERVICE_START_PENDING: "STARTING",
            win32service.SERVICE_STOP_PENDING: "STOPPING",
        }

        return mapping.get(status, "UNKNOWN")

    except Exception:
        return "NOT FOUND"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status():
    result = []

    for env in ENVIRONMENTS:
        services = []
        for s in env["services"]:
            services.append({
                "name": s,
                "status": get_service_status(s)
            })

        result.append({
            "environment": env["name"],
            "services": services
        })

    return jsonify(result)


@app.route("/action", methods=["POST"])
def action():
    data = request.json
    service = data.get("service")
    action = data.get("action")

    try:
        if action == "start":
            win32serviceutil.StartService(service)

        elif action == "stop":
            win32serviceutil.StopService(service)

        elif action == "restart":
            win32serviceutil.StopService(service)
            win32serviceutil.WaitForServiceStatus(service, win32service.SERVICE_STOPPED, 30)
            win32serviceutil.StartService(service)

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
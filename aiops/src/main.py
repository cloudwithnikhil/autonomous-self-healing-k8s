from fastapi import FastAPI, Request
from datetime import datetime, timezone
import logging

app = FastAPI(
    title="Autonomous Self-Healing AIOps Controller",
    version="0.1.0",
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiops-controller")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "aiops-controller",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request):
    payload = await request.json()

    logger.info("Received Alertmanager webhook")

    alerts = payload.get("alerts", [])

    incidents = []

    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        incident = {
            "alertname": labels.get("alertname"),
            "severity": labels.get("severity"),
            "service": labels.get("service"),
            "status": alert.get("status"),
            "summary": annotations.get("summary"),
            "description": annotations.get("description"),
            "startsAt": alert.get("startsAt"),
        }

        incidents.append(incident)

        logger.info(
            "Incident received: alert=%s service=%s severity=%s status=%s",
            incident["alertname"],
            incident["service"],
            incident["severity"],
            incident["status"],
        )

    return {
        "status": "received",
        "alerts_received": len(alerts),
        "incidents": incidents,
    }
from datetime import datetime, timezone
import logging

from fastapi import FastAPI, Request

from .analyzer import PrometheusAnalyzer


app = FastAPI(
    title="Autonomous Self-Healing AIOps Controller",
    version="0.2.0",
)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("aiops-controller")

prometheus = PrometheusAnalyzer()


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

        alertname = labels.get("alertname")
        severity = labels.get("severity")
        service = labels.get("service")
        status = alert.get("status")

        incident = {
            "alertname": alertname,
            "severity": severity,
            "service": service,
            "status": status,
            "summary": annotations.get("summary"),
            "description": annotations.get("description"),
            "startsAt": alert.get("startsAt"),
        }

        logger.info(
            "Incident received: alert=%s service=%s severity=%s status=%s",
            alertname,
            service,
            severity,
            status,
        )

        if alertname == "SelfHealingAPIHighErrorRate":
            try:
                analysis = await prometheus.analyze(
                    namespace="self-healing"
                )

                incident["analysis"] = analysis

                logger.info(
                    "Prometheus analysis: %s",
                    analysis,
                )

            except Exception as exc:
                logger.exception(
                    "Prometheus analysis failed: %s",
                    exc,
                )

                incident["analysis_error"] = str(exc)

        incidents.append(incident)

    return {
        "status": "received",
        "alerts_received": len(alerts),
        "incidents": incidents,
    }
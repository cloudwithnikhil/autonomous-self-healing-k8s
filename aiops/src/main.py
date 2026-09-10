from datetime import datetime, timezone
import logging

from fastapi import FastAPI, Request

from .analyzer import PrometheusAnalyzer
from .k8s_analyzer import KubernetesAnalyzer
from .decision import DecisionEngine
from .remediation import GitOpsRemediationEngine

app = FastAPI(
title="Autonomous Self-Healing AIOps Controller",
version="0.5.0",
)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("aiops-controller")

prometheus = PrometheusAnalyzer()
kubernetes = KubernetesAnalyzer()
decision_engine = DecisionEngine()
remediation_engine = GitOpsRemediationEngine()

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

            # -----------------------------------------
            # Stage 2B: Prometheus analysis
            # -----------------------------------------
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

            # -----------------------------------------
            # Stage 2C: Kubernetes analysis
            # -----------------------------------------
            try:
                k8s_analysis = kubernetes.analyze(
                    namespace="self-healing",
                    deployment_name="self-healing-api",
                    label_selector="app=self-healing-api",
                )

                incident["kubernetes"] = k8s_analysis

                logger.info(
                    "Kubernetes analysis: %s",
                    k8s_analysis,
                )

                # -----------------------------------------
                # Stage 2D: Confidence-based decision
                # -----------------------------------------
                error_rate = None

                if "analysis" in incident:
                    error_rate = incident["analysis"].get(
                        "error_rate"
                    )

                decision = decision_engine.evaluate(
                    alert_status=status,
                    error_rate=error_rate,
                    kubernetes_analysis=k8s_analysis,
                )

                incident["decision"] = {
                    "decision": decision.decision,
                    "confidence": decision.confidence,
                    "reasons": decision.reasons,
                }
                if (
                    decision.decision == "RECOMMEND_ROLLBACK"
                    and decision.confidence >= 0.80
                ):
                    try:
                        remediation = remediation_engine.plan_rollback()

                        incident["remediation"] = {
                            "action": remediation.action,
                            "dry_run": remediation.dry_run,
                            "current_revision": remediation.current_revision,
                            "target_revision": remediation.target_revision,
                            "reason": remediation.reason,
                            "metadata": remediation.metadata,
                        }

                        logger.info(
                            "Remediation plan: action=%s dry_run=%s current=%s target=%s",
                            remediation.action,
                            remediation.dry_run,
                            remediation.current_revision,
                            remediation.target_revision,
                        )

                    except Exception as exc:
                        logger.exception(
                            "Remediation planning failed: %s",
                            exc,
                        )

                        incident["remediation_error"] = str(exc)

                logger.info(
                    "Decision: %s confidence=%.3f",
                    decision.decision,
                    decision.confidence,
                )

            except Exception as exc:
                logger.exception(
                    "Kubernetes analysis or decision evaluation failed: %s",
                    exc,
                )

                incident["kubernetes_analysis_error"] = str(exc)

        incidents.append(incident)

    return {
        "status": "received",
        "alerts_received": len(alerts),
        "incidents": incidents,
    }


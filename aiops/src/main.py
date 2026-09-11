from datetime import datetime, timezone
import logging

from fastapi import FastAPI, Request

from .analyzer import PrometheusAnalyzer
from .k8s_analyzer import KubernetesAnalyzer
from .decision import DecisionEngine
from .remediation import GitOpsRemediationEngine

from .github_actions import GitHubActionsClient
from .config import ARGOCD_SOURCE_BRANCH

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
github_actions = GitHubActionsClient()


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
            # Stage 2C + 2D: Kubernetes analysis
            # + confidence-based decision
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

                logger.info(
                    "Decision: %s confidence=%.3f",
                    decision.decision,
                    decision.confidence,
                )

                # -----------------------------------------
                # Stage 2E: GitOps remediation planning
                # + GitHub Actions workflow dispatch
                # -----------------------------------------
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
                            "validation": remediation.validation,
                            "metadata": remediation.metadata,
                        }

                        logger.info(
                            "Remediation plan: action=%s dry_run=%s current=%s target=%s",
                            remediation.action,
                            remediation.dry_run,
                            remediation.current_revision,
                            remediation.target_revision,
                        )

                        # -----------------------------------------
                        # Stage 2F: GitHub Actions GitOps dispatch
                        # -----------------------------------------
                        if (
                            remediation.action == "ROLLBACK_PROPOSED"
                            and remediation.target_revision
                            and remediation.current_revision
                        ):
                            dispatch_result = (
                                await github_actions.dispatch_workflow(
                                    source_branch=ARGOCD_SOURCE_BRANCH,
                                    current_revision=remediation.current_revision,
                                    target_revision=remediation.target_revision,
                                    dry_run=remediation.dry_run,
                                )
                            )

                            incident["remediation"][
                                "workflow_dispatch"
                            ] = dispatch_result

                            logger.info(
                                "GitHub Actions workflow dispatched: %s",
                                dispatch_result,
                            )

                    except Exception as exc:
                        logger.exception(
                            "Remediation execution failed: %s",
                            exc,
                        )

                        incident["remediation_error"] = str(exc)

            except Exception as exc:
                logger.exception(
                    "Kubernetes analysis or decision evaluation failed: %s",
                    exc,
                )

                incident["kubernetes_analysis_error"] = str(exc)

        # -----------------------------------------
        # Add completed incident to response
        # -----------------------------------------
        incidents.append(incident)

    return {
        "status": "received",
        "alerts_received": len(alerts),
        "incidents": incidents,
    }

from datetime import datetime, timezone
import asyncio
import logging
import time

from fastapi import FastAPI, Request

from .analyzer import PrometheusAnalyzer
from .k8s_analyzer import KubernetesAnalyzer
from .decision import DecisionEngine
from .remediation import GitOpsRemediationEngine
from .github_actions import GitHubActionsClient
from .config import (
    ARGOCD_SOURCE_BRANCH,
    RECOVERY_ERROR_RATE_THRESHOLD,
    RECOVERY_POLL_SECONDS,
    RECOVERY_TIMEOUT_SECONDS,
)

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


async def wait_for_recovery(
    current_revision: str,
    target_revision: str,
    expected_revision: str,
) -> dict:
    deadline = time.monotonic() + RECOVERY_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        state = remediation_engine.get_application_state()

        sync_ok = (
            state["sync_status"] == "Synced"
            and state["health_status"] == "Healthy"
            and state["operation_phase"] == "Succeeded"
        )

        deployed_revision = state["last_successful_revision"]

        revision_ok = (
            deployed_revision is not None
            and deployed_revision == expected_revision
        )

        try:
            analysis = await prometheus.analyze(
                namespace="self-healing"
            )

            error_rate = analysis.get("error_rate")

        except Exception as exc:
            logger.exception(
                "Recovery Prometheus check failed: %s",
                exc,
            )

            error_rate = None

        recovery_ok = (
            sync_ok
            and revision_ok
            and error_rate is not None
            and error_rate < RECOVERY_ERROR_RATE_THRESHOLD
        )

        logger.info(
            "Recovery check: sync=%s revision_ok=%s "
            "revision=%s expected_revision=%s error_rate=%s recovered=%s",
            state["sync_status"],
            revision_ok,
            deployed_revision,
            expected_revision,
            error_rate,
            recovery_ok,
        )

        if recovery_ok:
            return {
                "status": "RECOVERED",
                "argocd": state,
                "error_rate": error_rate,
                "original_revision": current_revision,
                "rollback_target_revision": target_revision,
                "expected_deployed_revision": expected_revision,
                "deployed_revision": deployed_revision,
            }
        await asyncio.sleep(RECOVERY_POLL_SECONDS)

    return {
        "status": "RECOVERY_TIMEOUT",
        "argocd": remediation_engine.get_application_state(),
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
                            "Remediation plan: action=%s dry_run=%s "
                            "current=%s target=%s",
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
                                "GitHub Actions remediation completed: %s",
                                dispatch_result,
                            )

                            # -----------------------------------------
                            # Stage 2G: Post-remediation recovery
                            # -----------------------------------------
                            if not remediation.dry_run:
                                rollback_revision = dispatch_result.get("rollback_revision")

                                if not rollback_revision:
                                    raise RuntimeError(
                                        "GitHub Actions did not return a rollback revision"
                                    )

                                recovery = await wait_for_recovery(
                                    current_revision=remediation.current_revision,
                                    target_revision=remediation.target_revision,
                                    expected_revision=rollback_revision,
                                )
                                incident["remediation"][
                                    "recovery"
                                ] = recovery

                                logger.info(
                                    "Recovery verification: %s",
                                    recovery,
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

from dataclasses import dataclass

from .config import ERROR_RATE_THRESHOLD


@dataclass
class DecisionResult:
    decision: str
    confidence: float
    reasons: list[str]


class DecisionEngine:
    def evaluate(
        self,
        alert_status: str,
        error_rate: float | None,
        kubernetes_analysis: dict,
    ) -> DecisionResult:

        score = 0.0
        reasons = []

        # 1. Alert is actively firing.
        if alert_status == "firing":
            score += 0.20
            reasons.append("Alert is actively firing")

        # 2. Error rate is significantly above threshold.
        if error_rate is not None:
            if error_rate >= ERROR_RATE_THRESHOLD * 5:
                score += 0.35
                reasons.append(
                    f"Error rate is {error_rate:.1%}, "
                    f"well above the {ERROR_RATE_THRESHOLD:.1%} threshold"
                )
            elif error_rate > ERROR_RATE_THRESHOLD:
                score += 0.20
                reasons.append(
                    f"Error rate is {error_rate:.1%}, "
                    f"above the {ERROR_RATE_THRESHOLD:.1%} threshold"
                )

        # 3. Kubernetes availability.
        deployment = kubernetes_analysis.get("deployment", {})

        desired = deployment.get("desired_replicas", 0)
        ready = deployment.get("ready_replicas", 0)
        available = deployment.get("available_replicas", 0)

        if desired > 0 and ready == desired and available == desired:
            score += 0.15
            reasons.append(
                f"Kubernetes reports {ready}/{desired} replicas ready"
            )
        else:
            score -= 0.10
            reasons.append(
                "Kubernetes reports unhealthy replica availability"
            )

        # 4. Restart evidence.
        summary = kubernetes_analysis.get("summary", {})
        total_restarts = summary.get("total_restarts", 0)

        if total_restarts == 0:
            score += 0.10
            reasons.append("No pod restart or crash evidence detected")
        else:
            reasons.append(
                f"{total_restarts} pod/container restarts detected; "
                "restart history alone is not sufficient to classify the "
                "incident as infrastructure failure"
            )

        # 5. Application-level failure with healthy infrastructure.
        if (
            error_rate is not None
            and error_rate > ERROR_RATE_THRESHOLD
            and ready == desired
        ):
            score += 0.20
            reasons.append(
                "Evidence indicates an application-level regression "
                "because the error rate is elevated while all desired "
                "replicas remain healthy"
            )

        confidence = max(0.0, min(score, 1.0))

        if confidence >= 0.80:
            decision = "RECOMMEND_ROLLBACK"
        elif confidence >= 0.50:
            decision = "ALERT_ONLY"
        else:
            decision = "NO_ACTION"

        return DecisionResult(
            decision=decision,
            confidence=round(confidence, 3),
            reasons=reasons,
        )
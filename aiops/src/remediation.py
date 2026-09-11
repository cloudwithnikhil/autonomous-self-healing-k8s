from dataclasses import dataclass
from typing import Any

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from .config import (
    AIOPS_DRY_RUN,
    ARGOCD_APPLICATION,
    ARGOCD_NAMESPACE,
)


@dataclass
class RemediationResult:
    action: str
    dry_run: bool
    current_revision: str | None
    target_revision: str | None
    reason: str
    validation: dict[str, bool]
    metadata: dict[str, Any]


class GitOpsRemediationEngine:
    """
    Read-only GitOps remediation planner.

    Phase 4B.1:
    - Reads the Argo CD Application.
    - Reads deployment history.
    - Identifies the previous successful deployment.
    - Validates the rollback candidate.
    - Produces an auditable rollback proposal.

    This class does NOT modify Git, Argo CD, or Kubernetes.
    """

    def __init__(self):
        self._load_kubernetes_config()
        self.custom_api = client.CustomObjectsApi()

    @staticmethod
    def _load_kubernetes_config() -> None:
        """Prefer in-cluster authentication with local fallback."""
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()

    def _get_application(self) -> dict[str, Any]:
        return self.custom_api.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=ARGOCD_NAMESPACE,
            plural="applications",
            name=ARGOCD_APPLICATION,
        )

    def get_application_state(self) -> dict[str, Any]:
        application = self._get_application()

        status = application.get("status", {})
        operation_state = status.get("operationState", {}) or {}
        sync_result = operation_state.get("syncResult", {}) or {}

        return {
            "sync_status": (
                status.get("sync", {}).get("status")
                if isinstance(status.get("sync"), dict)
                else None
            ),
            "health_status": (
                status.get("health", {}).get("status")
                if isinstance(status.get("health"), dict)
                else None
            ),
            "last_successful_revision": sync_result.get("revision"),
            "operation_phase": operation_state.get("phase"),
        }

    @staticmethod
    def _get_current_revision(
        application: dict[str, Any],
    ) -> str | None:
        """
        Return the Git revision that was successfully deployed.

        Argo CD may report a newer observed/source revision under
        status.sync.revision while the cluster is still running the
        previously successful deployment. For remediation, we need the
        revision that was actually synced successfully.
        """
        status = application.get("status", {})

        operation_state = status.get("operationState", {}) or {}
        sync_result = operation_state.get("syncResult", {}) or {}

        return sync_result.get("revision")

    @staticmethod
    def _get_history(
        application: dict[str, Any],
    ) -> list[dict[str, Any]]:
        history = (
            application
            .get("status", {})
            .get("history", [])
        )

        return history if isinstance(history, list) else []

    @staticmethod
    def _find_current_history_entry(
        history: list[dict[str, Any]],
        current_revision: str,
    ) -> dict[str, Any] | None:
        for entry in history:
            if entry.get("revision") == current_revision:
                return entry

        return None

    @staticmethod
    def _find_previous_entry(
        history: list[dict[str, Any]],
        current_revision: str,
    ) -> dict[str, Any] | None:
        """
        Return the deployment immediately preceding the current deployment.

        Argo CD history is ordered chronologically, with the newest
        deployment at the end.
        """
        current_index = None

        for index, entry in enumerate(history):
            if entry.get("revision") == current_revision:
                current_index = index
                break

        if current_index is None or current_index == 0:
            return None

        for index in range(current_index - 1, -1, -1):
            entry = history[index]

            if entry.get("revision"):
                return entry

        return None

    @staticmethod
    def _validate_target(
        current_revision: str | None,
        target_entry: dict[str, Any] | None,
    ) -> tuple[dict[str, bool], str | None]:
        target_revision = (
            target_entry.get("revision")
            if target_entry
            else None
        )

        validation = {
            "current_revision_exists": bool(current_revision),
            "target_revision_exists": bool(target_revision),
            "target_differs_from_current": bool(
                current_revision
                and target_revision
                and target_revision != current_revision
            ),
            "target_has_deployment_timestamp": bool(
                target_entry
                and target_entry.get("deployedAt")
            ),
            "target_has_source": bool(
                target_entry
                and target_entry.get("source")
            ),
        }

        return validation, target_revision

    def plan_rollback(self) -> RemediationResult:
        application = self._get_application()

        current_revision = self._get_current_revision(application)
        history = self._get_history(application)

        if not current_revision:
            return RemediationResult(
                action="NO_ACTION",
                dry_run=AIOPS_DRY_RUN,
                current_revision=None,
                target_revision=None,
                reason=(
                    "Argo CD does not report a last successful sync revision."
                ),
                validation={
                    "current_revision_exists": False,
                    "target_revision_exists": False,
                    "target_differs_from_current": False,
                    "target_has_deployment_timestamp": False,
                    "target_has_source": False,
                },
                metadata={
                    "application": ARGOCD_APPLICATION,
                    "argocd_namespace": ARGOCD_NAMESPACE,
                    "history_count": len(history),
                },
            )

        current_entry = self._find_current_history_entry(
            history,
            current_revision,
        )

        target_entry = self._find_previous_entry(
            history,
            current_revision,
        )

        validation, target_revision = self._validate_target(
            current_revision=current_revision,
            target_entry=target_entry,
        )

        safe_to_propose = all(validation.values())

        if not safe_to_propose:
            failed_checks = [
                name
                for name, passed in validation.items()
                if not passed
            ]

            return RemediationResult(
                action="NO_ACTION",
                dry_run=AIOPS_DRY_RUN,
                current_revision=current_revision,
                target_revision=target_revision,
                reason=(
                    "Rollback candidate failed validation: "
                    + ", ".join(failed_checks)
                ),
                validation=validation,
                metadata={
                    "application": ARGOCD_APPLICATION,
                    "argocd_namespace": ARGOCD_NAMESPACE,
                    "history_count": len(history),
                    "current_history_id": (
                        current_entry.get("id")
                        if current_entry
                        else None
                    ),
                },
            )

        return RemediationResult(
            action="ROLLBACK_PROPOSED",
            dry_run=AIOPS_DRY_RUN,
            current_revision=current_revision,
            target_revision=target_revision,
            reason=(
                "Previous Argo CD deployment passed rollback-target "
                "validation and is eligible for dry-run remediation."
            ),
            validation=validation,
            metadata={
                "application": ARGOCD_APPLICATION,
                "argocd_namespace": ARGOCD_NAMESPACE,
                "current_history_id": (
                    current_entry.get("id")
                    if current_entry
                    else None
                ),
                "target_history_id": target_entry.get("id"),
                "target_deployed_at": target_entry.get("deployedAt"),
                "target_initiated_by": target_entry.get("initiatedBy"),
                "target_source": target_entry.get("source"),
            },
        )

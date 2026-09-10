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
    metadata: dict[str, Any]


class GitOpsRemediationEngine:
    """
    Phase 4A remediation planner.

    The planner is intentionally read-only.

    It:
    - reads the Argo CD Application
    - reads Argo CD deployment history
    - identifies the previous deployed revision
    - proposes a rollback target

    It does NOT modify:
    - Git
    - Argo CD
    - Kubernetes
    """

    def __init__(self):
        self._load_kubernetes_config()
        self.custom_api = client.CustomObjectsApi()

    @staticmethod
    def _load_kubernetes_config() -> None:
        """
        Prefer in-cluster authentication.

        Fall back to the local kubeconfig when running
        outside Kubernetes during development.
        """
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

    @staticmethod
    def _get_revision(
        application: dict[str, Any],
    ) -> str | None:
        return (
            application
            .get("status", {})
            .get("sync", {})
            .get("revision")
        )

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

    def plan_rollback(self) -> RemediationResult:
        application = self._get_application()

        current_revision = self._get_revision(application)
        history = self._get_history(application)

        if not current_revision:
            return RemediationResult(
                action="NO_ACTION",
                dry_run=AIOPS_DRY_RUN,
                current_revision=None,
                target_revision=None,
                reason=(
                    "Argo CD does not report a current sync revision."
                ),
                metadata={
                    "application": ARGOCD_APPLICATION,
                    "argocd_namespace": ARGOCD_NAMESPACE,
                },
            )

        candidates = []

        for entry in history:
            revision = entry.get("revision")

            if not revision:
                continue

            if revision == current_revision:
                continue

            candidates.append(entry)

        if not candidates:
            return RemediationResult(
                action="NO_ACTION",
                dry_run=AIOPS_DRY_RUN,
                current_revision=current_revision,
                target_revision=None,
                reason=(
                    "No previous Argo CD deployment revision "
                    "is available."
                ),
                metadata={
                    "application": ARGOCD_APPLICATION,
                    "history_count": len(history),
                },
            )

        previous = candidates[-1]
        target_revision = previous.get("revision")

        return RemediationResult(
            action="ROLLBACK_PROPOSED",
            dry_run=AIOPS_DRY_RUN,
            current_revision=current_revision,
            target_revision=target_revision,
            reason=(
                "A previous Argo CD deployment revision was "
                "identified as the rollback candidate."
            ),
            metadata={
                "application": ARGOCD_APPLICATION,
                "argocd_namespace": ARGOCD_NAMESPACE,
                "history_id": previous.get("id"),
                "deployed_at": previous.get("deployedAt"),
                "initiated_by": previous.get("initiatedBy"),
                "source": previous.get("source"),
            },
        )
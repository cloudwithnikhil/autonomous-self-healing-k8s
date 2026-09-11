import os

PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://localhost:9090",
)

ERROR_RATE_THRESHOLD = float(
    os.getenv("ERROR_RATE_THRESHOLD", "0.05")
)

AIOPS_DRY_RUN = os.getenv("AIOPS_DRY_RUN", "true").lower() == "true"

ARGOCD_NAMESPACE = os.getenv("ARGOCD_NAMESPACE", "argocd")
ARGOCD_APPLICATION = os.getenv("ARGOCD_APPLICATION", "self-healing")

ARGOCD_SOURCE_BRANCH = os.getenv(
    "ARGOCD_SOURCE_BRANCH",
    "test/broken-release",
)

RECOVERY_TIMEOUT_SECONDS = int(
    os.getenv("RECOVERY_TIMEOUT_SECONDS", "300")
)

RECOVERY_POLL_SECONDS = int(
    os.getenv("RECOVERY_POLL_SECONDS", "10")
)

RECOVERY_ERROR_RATE_THRESHOLD = float(
    os.getenv("RECOVERY_ERROR_RATE_THRESHOLD", "0.05")
)

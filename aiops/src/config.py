import os


PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://localhost:9090",
)

ERROR_RATE_THRESHOLD = float(
    os.getenv("ERROR_RATE_THRESHOLD", "0.05")
)
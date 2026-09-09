from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import random
import os
import time

app = FastAPI(title="Self-Healing Demo API")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

ERROR_COUNT = Counter(
    "http_requests_errors_total",
    "Total HTTP errors",
    ["method", "endpoint"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "version": os.getenv("APP_VERSION", "v1")
    }


@app.get("/api/orders")
def orders():
    start = time.time()

    version = os.getenv("APP_VERSION", "v1")

    # Failure simulation.
    # v2 intentionally generates HTTP 500 responses.
    if version == "v2":
        failure_rate = float(os.getenv("FAILURE_RATE", "0.10"))

        if random.random() < failure_rate:
            REQUEST_COUNT.labels(
                method="GET",
                endpoint="/api/orders",
                status="500",
            ).inc()

            ERROR_COUNT.labels(
                method="GET",
                endpoint="/api/orders",
            ).inc()

            REQUEST_LATENCY.labels(
                method="GET",
                endpoint="/api/orders",
            ).observe(time.time() - start)

            return Response(
                content='{"error":"simulated application failure"}',
                status_code=500,
                media_type="application/json",
            )

    REQUEST_COUNT.labels(
        method="GET",
        endpoint="/api/orders",
        status="200",
    ).inc()

    REQUEST_LATENCY.labels(
        method="GET",
        endpoint="/api/orders",
    ).observe(time.time() - start)

    return {
        "status": "success",
        "version": version,
        "orders": [
            {"id": 1001, "status": "completed"},
            {"id": 1002, "status": "processing"},
        ],
    }


@app.get("/metrics")
def metrics():
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
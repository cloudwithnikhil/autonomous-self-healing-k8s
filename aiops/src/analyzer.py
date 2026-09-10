import math

import httpx

from .config import PROMETHEUS_URL


class PrometheusAnalyzer:
    def __init__(self):
        self.base_url = PROMETHEUS_URL.rstrip("/")

    async def query(self, promql: str):
        url = f"{self.base_url}/api/v1/query"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                params={"query": promql},
            )

            response.raise_for_status()

            payload = response.json()

        if payload.get("status") != "success":
            raise RuntimeError(
                f"Prometheus query failed: {payload}"
            )

        results = payload.get("data", {}).get("result", [])

        if not results:
            return None

        value = results[0].get("value", [])

        if len(value) < 2:
            return None

        raw_value = value[1]

        try:
            parsed_value = float(raw_value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(parsed_value):
            return None

        return parsed_value

    async def get_error_rate(self, namespace: str):
        query = f"""
            sum(
                rate(
                    http_requests_total{{
                        namespace="{namespace}",
                        status="500"
                    }}[2m]
                )
            )
            /
            sum(
                rate(
                    http_requests_total{{
                        namespace="{namespace}"
                    }}[2m]
                )
            )
        """

        return await self.query(query)

    async def get_http_500_rate(self, namespace: str):
        query = f"""
            sum(
                rate(
                    http_requests_total{{
                        namespace="{namespace}",
                        status="500"
                    }}[2m]
                )
            )
        """

        return await self.query(query)

    async def get_total_request_rate(self, namespace: str):
        query = f"""
            sum(
                rate(
                    http_requests_total{{
                        namespace="{namespace}"
                    }}[2m]
                )
            )
        """

        return await self.query(query)

    async def analyze(self, namespace: str):
        error_rate = await self.get_error_rate(namespace)
        error_rate_500 = await self.get_http_500_rate(namespace)
        total_request_rate = await self.get_total_request_rate(namespace)

        return {
            "namespace": namespace,
            "error_rate": error_rate,
            "http_500_rate": error_rate_500,
            "total_request_rate": total_request_rate,
        }
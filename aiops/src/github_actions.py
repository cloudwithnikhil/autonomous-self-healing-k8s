import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx


class GitHubActionsClient:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        self.repository = os.getenv("GITHUB_REPOSITORY")
        self.workflow = os.getenv(
            "GITHUB_WORKFLOW",
            "aiops-remediation.yml",
        )

        self.workflow_timeout_seconds = int(
            os.getenv("GITHUB_WORKFLOW_TIMEOUT_SECONDS", "180")
        )

        self.workflow_poll_seconds = int(
            os.getenv("GITHUB_WORKFLOW_POLL_SECONDS", "5")
        )

        self.branch_advance_timeout_seconds = int(
            os.getenv("GITHUB_BRANCH_ADVANCE_TIMEOUT_SECONDS", "120")
        )

        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is not configured")

        if not self.repository:
            raise RuntimeError("GITHUB_REPOSITORY is not configured")

        self.base_url = (
            f"https://api.github.com/repos/{self.repository}"
        )

        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict | None = None,
    ) -> dict:
        response = await client.get(
            url,
            headers=self.headers,
            params=params,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"GitHub API GET failed: HTTP "
                f"{response.status_code}: {response.text}"
            )

        return response.json()

    @staticmethod
    def _parse_github_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    async def _wait_for_workflow_run(
        self,
        client: httpx.AsyncClient,
        source_branch: str,
        current_revision: str,
        dispatched_at: datetime,
    ) -> dict:
        url = (
            f"{self.base_url}/actions/workflows/"
            f"{self.workflow}/runs"
        )

        deadline = asyncio.get_running_loop().time() + (
            self.workflow_timeout_seconds
        )

        search_not_before = dispatched_at - timedelta(seconds=10)

        while asyncio.get_running_loop().time() < deadline:
            payload = await self._get_json(
                client,
                url,
                params={
                    "branch": source_branch,
                    "event": "workflow_dispatch",
                    "per_page": 20,
                },
            )

            runs = payload.get("workflow_runs", [])

            for run in runs:
                created_at_raw = run.get("created_at")

                if not created_at_raw:
                    continue

                created_at = self._parse_github_timestamp(
                    created_at_raw
                )

                if created_at < search_not_before:
                    continue

                if run.get("head_branch") != source_branch:
                    continue

                if run.get("head_sha") != current_revision:
                    continue

                return run

            await asyncio.sleep(self.workflow_poll_seconds)

        raise RuntimeError(
            "Timed out waiting for GitHub Actions workflow run "
            f"for branch '{source_branch}'"
        )

    async def _wait_for_workflow_completion(
        self,
        client: httpx.AsyncClient,
        run_id: int,
    ) -> dict:
        url = f"{self.base_url}/actions/runs/{run_id}"

        deadline = asyncio.get_running_loop().time() + (
            self.workflow_timeout_seconds
        )

        while asyncio.get_running_loop().time() < deadline:
            run = await self._get_json(
                client,
                url,
            )

            status = run.get("status")
            conclusion = run.get("conclusion")

            if status == "completed":
                if conclusion != "success":
                    raise RuntimeError(
                        "GitHub Actions workflow failed: "
                        f"run_id={run_id} "
                        f"conclusion={conclusion}"
                    )

                return run

            await asyncio.sleep(self.workflow_poll_seconds)

        raise RuntimeError(
            "Timed out waiting for GitHub Actions workflow "
            f"completion: run_id={run_id}"
        )

    async def _wait_for_branch_advance(
        self,
        client: httpx.AsyncClient,
        source_branch: str,
        current_revision: str,
    ) -> str:
        url = (
            f"{self.base_url}/git/ref/heads/"
            f"{source_branch}"
        )

        deadline = asyncio.get_running_loop().time() + (
            self.branch_advance_timeout_seconds
        )

        while asyncio.get_running_loop().time() < deadline:
            payload = await self._get_json(
                client,
                url,
            )

            new_revision = (
                payload.get("object", {}).get("sha")
            )

            if new_revision and new_revision != current_revision:
                return new_revision

            await asyncio.sleep(self.workflow_poll_seconds)

        raise RuntimeError(
            "Timed out waiting for Git branch advancement: "
            f"branch={source_branch} "
            f"current_revision={current_revision}"
        )

    async def dispatch_workflow(
        self,
        source_branch: str,
        current_revision: str,
        target_revision: str,
        dry_run: bool,
    ) -> dict:
        url = (
            f"{self.base_url}/actions/workflows/"
            f"{self.workflow}/dispatches"
        )

        payload = {
            "ref": source_branch,
            "inputs": {
                "source_branch": source_branch,
                "current_revision": current_revision,
                "target_revision": target_revision,
                "dry_run": str(dry_run).lower(),
            },
        }

        dispatched_at = datetime.now(timezone.utc)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers=self.headers,
                json=payload,
            )

            if response.status_code != 204:
                raise RuntimeError(
                    "GitHub workflow dispatch failed: "
                    f"HTTP {response.status_code}: "
                    f"{response.text}"
                )

            result = {
                "status": "dispatched",
                "workflow": self.workflow,
                "repository": self.repository,
                "source_branch": source_branch,
                "current_revision": current_revision,
                "target_revision": target_revision,
                "dry_run": dry_run,
            }

            if dry_run:
                return result

            workflow_run = await self._wait_for_workflow_run(
                client,
                source_branch=source_branch,
                current_revision=current_revision,
                dispatched_at=dispatched_at,
            )

            completed_run = await self._wait_for_workflow_completion(
                client,
                run_id=int(workflow_run["id"]),
            )

            rollback_revision = await self._wait_for_branch_advance(
                client,
                source_branch=source_branch,
                current_revision=current_revision,
            )

            result.update(
                {
                    "workflow_run_id": completed_run["id"],
                    "workflow_run_status": completed_run["status"],
                    "workflow_run_conclusion": completed_run[
                        "conclusion"
                    ],
                    "rollback_revision": rollback_revision,
                }
            )

            return result
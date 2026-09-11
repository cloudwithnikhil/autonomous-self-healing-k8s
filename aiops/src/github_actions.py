import os

import httpx


class GitHubActionsClient:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        self.repository = os.getenv("GITHUB_REPOSITORY")
        self.workflow = os.getenv("GITHUB_WORKFLOW", "aiops-remediation.yml")

        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is not configured")

        if not self.repository:
            raise RuntimeError("GITHUB_REPOSITORY is not configured")

        self.base_url = (
            f"https://api.github.com/repos/{self.repository}"
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

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        payload = {
            "ref": source_branch,
            "inputs": {
                "source_branch": source_branch,
                "current_revision": current_revision,
                "target_revision": target_revision,
                "dry_run": str(dry_run).lower(),
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

        if response.status_code != 204:
            raise RuntimeError(
                "GitHub workflow dispatch failed: "
                f"HTTP {response.status_code}: {response.text}"
            )

        return {
            "status": "dispatched",
            "workflow": self.workflow,
            "repository": self.repository,
            "source_branch": source_branch,
            "current_revision": current_revision,
            "target_revision": target_revision,
            "dry_run": dry_run,
        }
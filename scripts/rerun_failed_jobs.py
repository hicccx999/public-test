#!/usr/bin/env python3
"""Rerun failed GitHub Actions jobs after a delay without consuming Actions minutes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.github.com"
FAIL_JOB_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "startup_failure",
    "action_required",
    "stale",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    def __init__(self, token: str, repo: str) -> None:
        self.token = token
        self.repo = repo

    def _request(
        self,
        method: str,
        path: str,
        query: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = Request(
            url=url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "public-test-rerun-failed-jobs",
            },
        )

        with urlopen(req, timeout=30) as resp:
            payload = resp.read()
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))

    def list_workflow_runs(
        self, workflow_file: str, status: str = "completed", per_page: int = 100
    ) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self.repo}/actions/workflows/{workflow_file}/runs",
            query={"status": status, "per_page": per_page},
        )
        return data.get("workflow_runs", [])

    def list_run_jobs(self, run_id: int, attempt: int) -> List[Dict[str, Any]]:
        page = 1
        jobs: List[Dict[str, Any]] = []
        while True:
            data = self._request(
                "GET",
                f"/repos/{self.repo}/actions/runs/{run_id}/attempts/{attempt}/jobs",
                query={"per_page": 100, "page": page},
            )
            batch = data.get("jobs", [])
            jobs.extend(batch)
            total = int(data.get("total_count") or 0)
            if len(jobs) >= total or not batch:
                break
            page += 1
        return jobs

    def rerun_failed_jobs(self, run_id: int) -> None:
        self._request(
            "POST",
            f"/repos/{self.repo}/actions/runs/{run_id}/rerun-failed-jobs",
        )


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"triggered_attempts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"triggered_attempts": {}}
    if not isinstance(data, dict):
        return {"triggered_attempts": {}}
    data.setdefault("triggered_attempts", {})
    return data


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def attempt_key(run_id: int, attempt: int) -> str:
    return f"{run_id}:{attempt}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rerun failed jobs for a workflow run after a delay."
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPO", ""),
        help="GitHub repo in owner/name format. Env: GITHUB_REPO",
    )
    parser.add_argument(
        "--workflow",
        default=os.getenv("GITHUB_WORKFLOW_FILE", "download-data.yml"),
        help="Workflow file name. Env: GITHUB_WORKFLOW_FILE",
    )
    parser.add_argument(
        "--delay-minutes",
        type=int,
        default=int(os.getenv("RETRY_DELAY_MINUTES", "30")),
        help="Minutes to wait after run completion before rerun. Env: RETRY_DELAY_MINUTES",
    )
    parser.add_argument(
        "--max-run-attempt",
        type=int,
        default=int(os.getenv("MAX_RUN_ATTEMPT", "96")),
        help="Do not rerun if run_attempt is >= this value. Env: MAX_RUN_ATTEMPT",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=int(os.getenv("LOOKBACK_HOURS", "72")),
        help="Only process runs newer than this window. Env: LOOKBACK_HOURS",
    )
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "RETRY_STATE_FILE", ".cache/github-actions-rerun-failed-state.json"
        ),
        help="Local state file to avoid duplicate reruns. Env: RETRY_STATE_FILE",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidates but do not call rerun API.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        print("ERROR: missing GITHUB_TOKEN", file=sys.stderr)
        return 2
    if not args.repo:
        print("ERROR: missing --repo or GITHUB_REPO", file=sys.stderr)
        return 2

    client = GitHubClient(token=token, repo=args.repo)
    state_path = Path(args.state_file)
    state = load_state(state_path)
    triggered = state.setdefault("triggered_attempts", {})

    now = now_utc()
    lookback_cutoff = now - timedelta(hours=args.lookback_hours)
    delay = timedelta(minutes=args.delay_minutes)

    print(
        f"[{now.isoformat()}] scan repo={args.repo} workflow={args.workflow} "
        f"delay={args.delay_minutes}m max_attempt={args.max_run_attempt}"
    )

    try:
        runs = client.list_workflow_runs(args.workflow, status="completed", per_page=100)
    except (HTTPError, URLError) as exc:
        print(f"ERROR: failed to list workflow runs: {exc}", file=sys.stderr)
        return 1

    rerun_count = 0
    for run in sorted(runs, key=lambda x: x.get("updated_at", "")):
        run_id = int(run["id"])
        attempt = int(run.get("run_attempt") or 1)
        conclusion = run.get("conclusion")
        updated_at_raw = run.get("updated_at")
        if not updated_at_raw:
            continue

        completed_at = parse_utc(updated_at_raw)
        if completed_at < lookback_cutoff:
            continue
        if conclusion != "failure":
            continue
        if attempt >= args.max_run_attempt:
            print(f"skip run_id={run_id} attempt={attempt}: hit max_run_attempt")
            continue

        key = attempt_key(run_id, attempt)
        if key in triggered:
            continue

        wait_left = delay - (now - completed_at)
        if wait_left.total_seconds() > 0:
            print(
                f"wait run_id={run_id} attempt={attempt}: "
                f"{int(wait_left.total_seconds())}s left"
            )
            continue

        try:
            jobs = client.list_run_jobs(run_id, attempt)
        except (HTTPError, URLError) as exc:
            print(
                f"ERROR: failed to list jobs for run_id={run_id} attempt={attempt}: {exc}",
                file=sys.stderr,
            )
            continue

        failed_jobs = [
            job
            for job in jobs
            if job.get("conclusion") in FAIL_JOB_CONCLUSIONS
        ]
        if not failed_jobs:
            print(f"skip run_id={run_id} attempt={attempt}: no failed jobs")
            continue

        print(
            f"rerun run_id={run_id} attempt={attempt}: "
            f"failed_jobs={len(failed_jobs)}"
        )
        if args.dry_run:
            continue

        try:
            client.rerun_failed_jobs(run_id)
        except (HTTPError, URLError) as exc:
            print(
                f"ERROR: failed to trigger rerun for run_id={run_id}: {exc}",
                file=sys.stderr,
            )
            continue

        triggered[key] = now.isoformat()
        rerun_count += 1

    if not args.dry_run:
        save_state(state_path, state)
    print(f"done rerun_count={rerun_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

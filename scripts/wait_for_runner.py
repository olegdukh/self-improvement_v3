#!/usr/bin/env python3
"""Wait until the self-hosted runner with the requested label is online."""

from __future__ import annotations

import os
import sys
import time

import requests


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: wait_for_runner.py <runner-label>")

    label = sys.argv[1]
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Missing GH_PAT or GITHUB_TOKEN")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/actions/runners"

    timeout = int(os.getenv("RUNNER_WAIT_TIMEOUT", "600"))
    deadline = time.time() + timeout

    while time.time() < deadline:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        for runner in response.json().get("runners", []):
            labels = {item.get("name") for item in runner.get("labels", [])}
            if label in labels and runner.get("status") == "online":
                print(f"Runner is online: {runner.get('name')}")
                return 0
        print("Waiting for runner to become online...")
        time.sleep(10)

    raise SystemExit(f"Runner with label {label} did not become online within {timeout} seconds")


if __name__ == "__main__":
    raise SystemExit(main())

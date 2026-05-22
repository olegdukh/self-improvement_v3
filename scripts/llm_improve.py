#!/usr/bin/env python3
"""OpenAI-based repository self-improvement agent.

The agent creates a new branch, asks OpenAI for a small safe improvement,
writes the proposed files, commits the change, pushes the branch and opens a PR.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FILES = [
    "app/calculator.py",
    "tests/test_calculator.py",
    "README.md",
    "IMPROVEMENTS.md",
]
PROTECTED_SIGNATURES = [
    "def add(a: int | float, b: int | float) -> int | float:",
    "def subtract(a: int | float, b: int | float) -> int | float:",
    "def multiply(a: int | float, b: int | float) -> int | float:",
    "def divide(a: int | float, b: int | float) -> int | float:",
]


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check, capture_output=False)


def read_file(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from model output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def validate_files(files: dict[str, str]) -> None:
    for path in files:
        if path not in ALLOWED_FILES:
            raise ValueError(f"LLM attempted to modify forbidden file: {path}")

    calculator = files.get("app/calculator.py")
    if calculator:
        for signature in PROTECTED_SIGNATURES:
            if signature not in calculator:
                raise ValueError(f"Protected function signature was changed or removed: {signature}")


def call_openai() -> dict[str, str]:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    context = "\n\n".join(
        f"--- {path} ---\n{read_file(path)}" for path in ALLOWED_FILES
    )

    prompt = f"""
You are a careful Python maintainer. Improve this small calculator repository.

Rules:
1. Make ONE small useful improvement only.
2. You may edit only these files: {ALLOWED_FILES}.
3. DO NOT change function names.
4. DO NOT change the number of function arguments.
5. DO NOT change these exact signatures in app/calculator.py:
{chr(10).join(PROTECTED_SIGNATURES)}
6. Keep pytest tests passing.
7. Prefer improving documentation, comments, edge-case tests, type hints, or small code clarity.
8. Return JSON only, no markdown.

JSON schema:
{{
  "summary": "short summary",
  "files": {{
    "relative/path": "complete new file content"
  }}
}}

Current repository content:
{context}
""".strip()

    response = client.responses.create(model=model, input=prompt)
    data = extract_json(response.output_text)
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Model did not return any files")
    validate_files(files)
    return {str(k): str(v) for k, v in files.items()}


def write_files(files: dict[str, str]) -> None:
    for path, content in files.items():
        file_path = ROOT / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def has_changes() -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True)
    return bool(result.stdout.strip())


def create_pull_request(branch: str) -> None:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/pulls"
    payload = {
        "title": f"AI self-improvement: {branch}",
        "head": branch,
        "base": os.getenv("BASE_BRANCH", "main"),
        "body": "Automated OpenAI-generated self-improvement PR. Function names and argument counts are protected by the agent prompt and validation.",
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Failed to create PR: {response.status_code} {response.text}")
    print("Created PR:", response.json().get("html_url"))


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = f"ai-improvement-{timestamp}"

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "checkout", "-b", branch])

    files = call_openai()
    write_files(files)

    if not has_changes():
        print("No changes generated. Nothing to commit.")
        return 0

    run(["python", "-m", "pytest"])
    run(["git", "add", *files.keys()])
    run(["git", "commit", "-m", "AI self-improvement"])
    run(["git", "push", "origin", branch])
    create_pull_request(branch)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

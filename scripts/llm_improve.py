#!/usr/bin/env python3
"""Gemini-based repository self-improvement agent."""

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
from google import genai

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
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check)


def read_file(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def extract_json(text: str) -> dict[str, Any]:
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
                raise ValueError(
                    f"Protected function signature was changed or removed: {signature}"
                )


def fallback_improvement() -> dict[str, str]:
    improvements = read_file("IMPROVEMENTS.md")

    if not improvements.strip():
        improvements = "# Improvements\n"

    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "IMPROVEMENTS.md": (
            improvements.rstrip()
            + f"\n- {timestamp} fallback automated improvement "
            + "because Gemini API was unavailable.\n"
        )
    }


def call_gemini() -> dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY secret is required")

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

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

    response = client.models.generate_content(model=model, contents=prompt)
    data = extract_json(response.text or "")

    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Model did not return any files")

    normalized_files = {str(k): str(v) for k, v in files.items()}
    validate_files(normalized_files)

    return normalized_files


def write_files(files: dict[str, str]) -> None:
    for path, content in files.items():
        file_path = ROOT / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def has_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return bool(result.stdout.strip())


def create_pull_request(branch: str) -> None:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]

    url = f"https://api.github.com/repos/{repo}/pulls"

    payload = {
        "title": f"AI self-improvement: {branch}",
        "head": branch,
        "base": os.getenv("BASE_BRANCH", "main"),
        "body": (
            "Automated Gemini-generated self-improvement PR.\n\n"
            "Function names and argument counts are protected by the agent "
            "prompt and validation.\n\n"
            "If Gemini API quota is unavailable, the agent uses a safe "
            "fallback improvement so the automation pipeline remains testable."
        ),
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
        raise RuntimeError(
            f"Failed to create PR: {response.status_code} {response.text}"
        )

    print("Created PR:", response.json().get("html_url"))


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = f"ai-improvement-{timestamp}"

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "checkout", "-b", branch])

    try:
        files = call_gemini()
    except Exception as exc:
        print(f"Gemini unavailable: {exc}")
        print("Using fallback improvement")
        files = fallback_improvement()

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
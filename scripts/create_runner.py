#!/usr/bin/env python3
"""Create temporary Hetzner VPS and register it as GitHub self-hosted runner."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

HCLOUD_API = "https://api.hetzner.cloud/v1"
GITHUB_API = "https://api.github.com"


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def hcloud_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {required_env('HETZNER_TOKEN')}",
        "Content-Type": "application/json",
    }


def github_headers() -> dict[str, str]:
    token = required_env("GH_PAT")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=60)

    if response.status_code >= 300:
        raise RuntimeError(
            f"POST {url} failed: {response.status_code} {response.text}"
        )

    return response.json()


def delete_json(url: str, headers: dict[str, str]) -> None:
    response = requests.delete(url, headers=headers, timeout=60)

    if response.status_code not in (200, 202, 204, 404):
        raise RuntimeError(
            f"DELETE {url} failed: {response.status_code} {response.text}"
        )


def get_runner_registration_token(repo: str) -> str:
    url = f"{GITHUB_API}/repos/{repo}/actions/runners/registration-token"
    data = post_json(url, github_headers(), {})
    return data["token"]


def create_firewall(name: str) -> int:
    """Create firewall without public SSH access.

    Inbound:
      - no public SSH
      - no inbound ports required

    Outbound:
      - allowed, because GitHub runner and Tailscale need outbound access
    """

    payload = {
        "name": f"{name}-fw",
        "rules": [
            {
                "direction": "out",
                "protocol": "tcp",
                "destination_ips": ["0.0.0.0/0", "::/0"],
                "port": "any",
            },
            {
                "direction": "out",
                "protocol": "udp",
                "destination_ips": ["0.0.0.0/0", "::/0"],
                "port": "any",
            },
            {
                "direction": "out",
                "protocol": "icmp",
                "destination_ips": ["0.0.0.0/0", "::/0"],
            },
        ],
    }

    data = post_json(f"{HCLOUD_API}/firewalls", hcloud_headers(), payload)
    return data["firewall"]["id"]


def build_cloud_init(runner_name: str, repo: str, registration_token: str) -> str:
    tailscale_authkey = os.getenv("TAILSCALE_AUTHKEY", "")

    tailscale_block = ""
    if tailscale_authkey:
        tailscale_block = f"""
    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up --authkey "{tailscale_authkey}" --hostname "{runner_name}" --ssh=false
"""

    return f"""#cloud-config
package_update: true
package_upgrade: false

packages:
  - curl
  - jq
  - tar
  - gzip
  - git
  - sudo
  - ca-certificates
  - python3
  - python3-pip
  - python3-venv
  - python3-full
  - build-essential

runcmd:
  - |
    set -euxo pipefail

    useradd -m -s /bin/bash runner || true
    mkdir -p /opt/actions-runner
    chown -R runner:runner /opt/actions-runner

    cd /opt/actions-runner

    RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | jq -r '.tag_name' | sed 's/^v//')
    curl -L -o actions-runner-linux-x64.tar.gz "https://github.com/actions/runner/releases/download/v${{RUNNER_VERSION}}/actions-runner-linux-x64-${{RUNNER_VERSION}}.tar.gz"
    tar xzf actions-runner-linux-x64.tar.gz
    chown -R runner:runner /opt/actions-runner

    ./bin/installdependencies.sh

{tailscale_block}

    sudo -u runner ./config.sh \\
      --url "https://github.com/{repo}" \\
      --token "{registration_token}" \\
      --name "{runner_name}" \\
      --labels "hetzner,cx23,ephemeral" \\
      --unattended \\
      --ephemeral \\
      --replace

    ./svc.sh install runner
    ./svc.sh start
"""


def create_server(
    name: str,
    firewall_id: int,
    user_data: str,
    location: str,
) -> int:
    server_type = os.getenv("HCLOUD_SERVER_TYPE", "cx23")
    image = os.getenv("HCLOUD_IMAGE", "ubuntu-24.04")

    payload = {
        "name": name,
        "server_type": server_type,
        "image": image,
        "location": location,
        "user_data": user_data,
        "ssh_keys": [],
        "firewalls": [
            {
                "firewall": firewall_id,
            }
        ],
        "labels": {
            "managed-by": "github-actions",
            "purpose": "ephemeral-self-hosted-runner",
            "runner-name": name,
        },
    }

    data = post_json(f"{HCLOUD_API}/servers", hcloud_headers(), payload)
    return data["server"]["id"]


def create_server_with_fallback(
    name: str,
    firewall_id: int,
    user_data: str,
) -> tuple[int, str]:
    locations = os.getenv("HCLOUD_LOCATIONS", "fsn1,nbg1,hel1").split(",")

    last_error: Exception | None = None

    for location in locations:
        location = location.strip()
        if not location:
            continue

        try:
            print(f"Trying to create Hetzner server in location: {location}")
            server_id = create_server(name, firewall_id, user_data, location)
            print(f"Created server {server_id} in location {location}")
            return server_id, location
        except Exception as exc:
            last_error = exc
            print(f"Failed to create server in {location}: {exc}")

    raise RuntimeError(f"Failed to create server in all locations: {last_error}")


def main() -> int:
    if len(sys.argv) < 2:
        raise RuntimeError("Usage: create_runner.py <runner-name>")

    name = sys.argv[1]
    repo = required_env("GITHUB_REPOSITORY")

    registration_token = get_runner_registration_token(repo)
    firewall_id = create_firewall(name)
    user_data = build_cloud_init(name, repo, registration_token)

    try:
        server_id, location = create_server_with_fallback(name, firewall_id, user_data)
    except Exception:
        delete_json(f"{HCLOUD_API}/firewalls/{firewall_id}", hcloud_headers())
        raise

    result = {
        "server_id": server_id,
        "firewall_id": firewall_id,
        "runner_name": name,
        "location": location,
    }

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
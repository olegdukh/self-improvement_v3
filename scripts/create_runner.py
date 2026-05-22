#!/usr/bin/env python3
"""Create a temporary Hetzner Cloud VM and register it as a GitHub runner.

The VM is created without public SSH access. Inbound firewall rules are empty,
Tailscale is installed through cloud-init, and the GitHub Actions runner connects
outbound to GitHub.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from textwrap import dedent
from typing import Any

import requests

HCLOUD_API = "https://api.hetzner.cloud/v1"
GITHUB_API = "https://api.github.com"


def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def hcloud_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {require('HETZNER_TOKEN')}",
        "Content-Type": "application/json",
    }


def github_headers() -> dict[str, str]:
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Missing GH_PAT or GITHUB_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code >= 300:
        raise RuntimeError(f"POST {url} failed: {response.status_code} {response.text}")
    return response.json()


def get_runner_registration_token(repo: str) -> str:
    data = post_json(
        f"{GITHUB_API}/repos/{repo}/actions/runners/registration-token",
        github_headers(),
        {},
    )
    return data["token"]


def create_firewall(name: str) -> int:
    # Empty inbound rules = no public inbound access, including SSH/22.
    data = post_json(
        f"{HCLOUD_API}/firewalls",
        hcloud_headers(),
        {"name": name, "rules": []},
    )
    return int(data["firewall"]["id"])


def build_cloud_init(repo: str, runner_token: str, runner_label: str) -> str:
    tailscale_authkey = require("TAILSCALE_AUTHKEY")
    repo_url = f"https://github.com/{repo}"
    runner_name = f"hcloud-{runner_label}"

    setup_script = f"""#!/usr/bin/env bash
set -euxo pipefail

useradd -m -s /bin/bash runner || true
mkdir -p /opt/actions-runner
cd /opt/actions-runner

RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | jq -r '.tag_name' | sed 's/^v//')
curl -L -o actions-runner-linux-x64.tar.gz "https://github.com/actions/runner/releases/download/v${{RUNNER_VERSION}}/actions-runner-linux-x64-${{RUNNER_VERSION}}.tar.gz"
tar xzf actions-runner-linux-x64.tar.gz
chown -R runner:runner /opt/actions-runner

sudo -u runner ./config.sh \
  --url "{repo_url}" \
  --token "{runner_token}" \
  --name "{runner_name}" \
  --labels "{runner_label}" \
  --unattended \
  --ephemeral

cat >/etc/systemd/system/github-runner.service <<'EOF'
[Unit]
Description=Ephemeral GitHub Actions Runner
After=network-online.target
Wants=network-online.target

[Service]
User=runner
WorkingDirectory=/opt/actions-runner
ExecStart=/opt/actions-runner/run.sh
Restart=no

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now github-runner.service
"""

    encoded_script = base64.b64encode(setup_script.encode()).decode()

    return dedent(
        f"""\
        #cloud-config
        package_update: true
        package_upgrade: false
        packages:
          - curl
          - jq
          - git
          - python3
          - python3-pip
          - ca-certificates
          - sudo
        write_files:
          - path: /root/setup-github-runner.sh
            permissions: '0755'
            encoding: b64
            content: {encoded_script}
        runcmd:
          - curl -fsSL https://tailscale.com/install.sh | sh
          - tailscale up --auth-key={tailscale_authkey} --hostname={runner_name} --ssh --accept-dns=false
          - systemctl disable --now ssh || true
          - systemctl disable --now sshd || true
          - /root/setup-github-runner.sh
        """
    )


def create_server(name: str, firewall_id: int, user_data: str, location: str) -> int:
    payload = {
        "name": name,
        "server_type": os.getenv("HETZNER_SERVER_TYPE", "cx23"),
        "image": os.getenv("HETZNER_IMAGE", "ubuntu-24.04"),
        "location": location,
        "user_data": user_data,
        "firewalls": [{"firewall": firewall_id}],
        "labels": {
            "purpose": "github-actions-runner",
            "managed_by": "self-improvement",
        },
    }
    data = post_json(f"{HCLOUD_API}/servers", hcloud_headers(), payload)
    return int(data["server"]["id"])


def create_server_with_fallback(name: str, firewall_id: int, user_data: str) -> int:
    """Try several Hetzner locations when one location has no capacity."""
    locations_raw = os.getenv("HETZNER_LOCATIONS") or os.getenv("HETZNER_LOCATION") or "fsn1,nbg1,hel1"
    locations = [location.strip() for location in locations_raw.split(",") if location.strip()]

    if not locations:
        raise RuntimeError("No Hetzner locations configured")

    last_error: Exception | None = None

    for location in locations:
        try:
            print(f"Trying Hetzner location: {location}", file=sys.stderr)
            server_id = create_server(name, firewall_id, user_data, location)
            print(f"Created server in location: {location}", file=sys.stderr)
            return server_id
        except RuntimeError as exc:
            last_error = exc
            print(f"Failed to create server in {location}: {exc}", file=sys.stderr)

    raise RuntimeError(f"Failed to create server in all configured locations: {last_error}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_runner.py <runner-label>")

    runner_label = sys.argv[1]
    repo = require("GITHUB_REPOSITORY")
    runner_token = get_runner_registration_token(repo)

    name = f"gha-{runner_label}"[:63]
    firewall_id = create_firewall(f"fw-{name}"[:63])
    user_data = build_cloud_init(repo, runner_token, runner_label)
    server_id = create_server_with_fallback(name, firewall_id, user_data)

    print(
        json.dumps(
            {
                "server_id": server_id,
                "firewall_id": firewall_id,
                "runner_label": runner_label,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

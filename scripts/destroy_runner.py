#!/usr/bin/env python3
"""Delete temporary Hetzner server and firewall."""

from __future__ import annotations

import os
import sys
import time

import requests

HCLOUD_API = "https://api.hetzner.cloud/v1"


def headers() -> dict[str, str]:
    token = os.getenv("HETZNER_TOKEN")
    if not token:
        raise SystemExit("Missing HETZNER_TOKEN")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def delete_resource(path: str) -> None:
    url = f"{HCLOUD_API}{path}"
    response = requests.delete(url, headers=headers(), timeout=60)
    if response.status_code in (200, 202, 204, 404):
        print(f"Deleted or already gone: {path}")
        return
    print(f"WARNING: failed to delete {path}: {response.status_code} {response.text}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: destroy_runner.py <server-id> [firewall-id]")

    server_id = sys.argv[1]
    firewall_id = sys.argv[2] if len(sys.argv) > 2 else ""

    if server_id and server_id != "null":
        delete_resource(f"/servers/{server_id}")
        time.sleep(5)
    if firewall_id and firewall_id != "null":
        delete_resource(f"/firewalls/{firewall_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

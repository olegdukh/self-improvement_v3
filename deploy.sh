#!/usr/bin/env bash
set -euo pipefail

# One-click helper for the Hetzner ephemeral self-hosted runner.
# Usage:
#   ./deploy.sh create <runner-label>
#   ./deploy.sh destroy <server-id> <firewall-id>

COMMAND="${1:-}"

case "$COMMAND" in
  create)
    LABEL="${2:-}"
    if [[ -z "$LABEL" ]]; then
      echo "Usage: ./deploy.sh create <runner-label>" >&2
      exit 1
    fi
    python3 -m pip install --quiet --upgrade requests
    python3 scripts/create_runner.py "$LABEL"
    ;;
  destroy)
    SERVER_ID="${2:-}"
    FIREWALL_ID="${3:-}"
    if [[ -z "$SERVER_ID" ]]; then
      echo "Usage: ./deploy.sh destroy <server-id> <firewall-id>" >&2
      exit 1
    fi
    python3 -m pip install --quiet --upgrade requests
    python3 scripts/destroy_runner.py "$SERVER_ID" "$FIREWALL_ID"
    ;;
  *)
    cat >&2 <<'EOF'
Usage:
  ./deploy.sh create <runner-label>
  ./deploy.sh destroy <server-id> <firewall-id>

Required env vars for create:
  HETZNER_TOKEN
  TAILSCALE_AUTHKEY
  GITHUB_REPOSITORY
  GH_PAT or GITHUB_TOKEN

Optional env vars:
  HETZNER_SERVER_TYPE=cx23
  HETZNER_IMAGE=ubuntu-24.04
  HETZNER_LOCATION=fsn1
EOF
    exit 1
    ;;
esac

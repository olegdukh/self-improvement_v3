# self-improvement

Minimal DevOps/Python project for two related tasks:

1. **Git automation task**: an OpenAI-based agent improves this repository every 2 hours and creates a Pull Request.
2. **Scripting task**: tests for that Pull Request run on a temporary Hetzner Cloud VPS registered as a GitHub self-hosted runner. The VPS has no public SSH access and is deleted after tests.

## Project structure

```text
self-improvement/
├── app/
│   ├── __init__.py
│   └── calculator.py
├── tests/
│   └── test_calculator.py
├── scripts/
│   ├── create_runner.py
│   ├── destroy_runner.py
│   ├── llm_improve.py
│   └── wait_for_runner.py
├── .github/workflows/
│   ├── ai-improve.yml
│   └── pr-tests-on-hetzner.yml
├── deploy.sh
├── pytest.ini
├── requirements.txt
└── README.md
```

## What it does

### Task 1: Git automation

The workflow `.github/workflows/ai-improve.yml` runs:

```yaml
schedule:
  - cron: "0 */2 * * *"
```

Every 2 hours it:

1. Checks out the repository.
2. Runs `scripts/llm_improve.py`.
3. Sends the current calculator project to OpenAI.
4. Asks OpenAI to make one small improvement.
5. Protects function names and argument count.
6. Creates a new branch.
7. Commits the change.
8. Opens a Pull Request.

The agent is intentionally restricted. It may only modify:

```text
app/calculator.py
tests/test_calculator.py
README.md
IMPROVEMENTS.md
```

It must not change these function signatures:

```python
def add(a: int | float, b: int | float) -> int | float:
def subtract(a: int | float, b: int | float) -> int | float:
def multiply(a: int | float, b: int | float) -> int | float:
def divide(a: int | float, b: int | float) -> int | float:
```

### Task 2: Hetzner ephemeral self-hosted runner

When a Pull Request is created, `.github/workflows/pr-tests-on-hetzner.yml`:

1. Creates a temporary Hetzner Cloud VPS.
2. Uses server type `cx23` by default.
3. Creates a Hetzner Firewall with no inbound rules.
4. Does not attach any public SSH key.
5. Installs Tailscale through cloud-init.
6. Disables SSH service inside the VM.
7. Registers the VM as a GitHub self-hosted runner.
8. Runs `pytest` on the Pull Request code.
9. Deletes the Hetzner VM and firewall after the test job.

Cleanup uses:

```yaml
if: always()
```

So the VM is deleted even if tests fail.

## Required GitHub Secrets

Add these secrets in GitHub:

```text
OPENAI_API_KEY
HETZNER_TOKEN
TAILSCALE_AUTHKEY
GH_PAT
```

### OPENAI_API_KEY

Your OpenAI API key used by the LLM agent.

### HETZNER_TOKEN

Hetzner Cloud API token with read/write access to the Hetzner project.

### TAILSCALE_AUTHKEY

Reusable or ephemeral Tailscale auth key.

Recommended: use an ephemeral auth key if available.

### GH_PAT

GitHub Personal Access Token.

Recommended permissions:

```text
Repository contents: read/write
Pull requests: read/write
Actions: read/write
Administration or self-hosted runner management permission if required by your token type
```

`GITHUB_TOKEN` is enough for creating PRs in many cases, but a PAT is usually more reliable for self-hosted runner registration API calls.

## Local test

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Expected result:

```text
5 passed
```

## One-click Hetzner runner script

Create runner manually:

```bash
export HETZNER_TOKEN="your_hetzner_token"
export TAILSCALE_AUTHKEY="your_tailscale_auth_key"
export GH_PAT="your_github_pat"
export GITHUB_REPOSITORY="your-user/self-improvement"

./deploy.sh create hcloud-manual-test
```

Destroy runner manually:

```bash
./deploy.sh destroy <server_id> <firewall_id>
```

In normal usage you do not run this manually. GitHub Actions runs it automatically for Pull Requests.

## Security notes

The Hetzner VPS is designed to have no public SSH access:

- No SSH key is attached to the server.
- Hetzner Firewall has no inbound rules.
- `ssh` / `sshd` service is disabled by cloud-init.
- Tailscale is installed for tunnel-based access.
- GitHub runner connects outbound to GitHub.

The self-hosted runner is ephemeral:

```bash
./config.sh --ephemeral
```

After one job, it stops accepting more jobs.

## Cost optimization

The VM is created only for PR tests and then deleted. This avoids keeping a monthly VPS running all the time.

Default server type:

```text
cx23
```

You can override it:

```bash
export HETZNER_SERVER_TYPE=cx23
```

## End-to-end flow

```text
OpenAI agent workflow runs every 2 hours
        ↓
Agent creates branch and PR
        ↓
PR test workflow starts
        ↓
GitHub-hosted runner creates Hetzner VPS
        ↓
VPS registers as self-hosted runner
        ↓
pytest runs on PR branch
        ↓
cleanup job deletes VPS and firewall
        ↓
You manually review and merge PR if tests passed
```

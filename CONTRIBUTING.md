# Contributing to SSHand

Thanks for your interest in contributing! This document covers how to set up a dev environment, run tests, and submit changes.

---

## Development setup

```bash
git clone https://github.com/muradmalik23/sshand
cd sshand

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS / Linux
.\.venv\Scripts\activate        # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

You can then run the server directly with `python server.py` or `sshand`.

---

## Running tests

```bash
pytest tests/ -v
```

`tests/test_host_config.py` and `tests/test_ssh_client.py` cover the YAML inventory manager and the path/command/auth-building logic in the SSH client using fakes and mocks — no live host required. They run in well under a second.

What they intentionally **don't** cover: actually opening a TCP/SSH connection or talking SFTP to a real server. For that, the MCP Inspector workflow below is still the real end-to-end verification step — use it to confirm every tool works against a live host before opening a PR or cutting a release.

Contributions that extend the unit tests (more edge cases in `host_config.py`/`ssh_client.py`) or that add coverage for `server.py`'s tool wrappers are very welcome.

---

## Testing with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) lets you interact with all 11 tools directly in a browser UI — no Claude Desktop needed. It's the fastest way to verify a change works end-to-end.

**From a published release (PyPI):**
```bash
npx @modelcontextprotocol/inspector uvx sshand
```

**From your local checkout:**
```bash
npx @modelcontextprotocol/inspector uv --directory . run server.py
```

The Inspector opens at `http://localhost:5173`. Use the **Tools** tab to call any `ssh_*` tool with custom inputs and inspect the raw response. The **Notifications** pane shows server-side log output in real time.

> **Tip:** Make sure `hosts.yaml` has at least one entry (copy from `hosts.yaml.example`) and that `ssh_test_connection` passes before testing the other tools.

---

## Project layout

```
sshand/
├── server.py          # FastMCP server — all tools + CLI entry point
├── ssh_client.py      # Async paramiko wrapper (command exec + SFTP)
├── host_config.py     # YAML inventory manager (Pydantic models)
├── setup_wizard.py    # Interactive first-run wizard
├── platform_utils.py  # Windows SSH agent helpers
├── hosts.yaml.example # Safe template — copy to hosts.yaml
├── INTEGRATIONS.md    # Guide: Claude.ai and ChatGPT native extensions
├── pyproject.toml
├── requirements.txt
├── CHANGELOG.md
├── CONTRIBUTING.md    # ← you are here
├── LICENSE
└── README.md
```

---

## Making changes

1. **Fork** the repo and create a branch from `main`:
   ```bash
   git checkout -b feature/my-improvement
   ```
2. Make your changes. Keep commits focused — one logical change per commit.
3. Add or update tests if the change affects tool behaviour.
4. Run `pytest` and confirm tests pass.
5. Open a **Pull Request** against `main`. Include a clear description of what changed and why.

---

## Code style

- Python 3.10+ with `from __future__ import annotations`.
- Type hints on all public functions and Pydantic models.
- Docstrings on all MCP tool functions — these show up in client UIs.
- Keep tool docstrings in the established format: Args block, Returns block, Examples block.

---

## Adding a new tool

1. Define a Pydantic input model in `server.py` (or import from a new module).
2. Decorate the async function with `@mcp.tool(name=..., annotations={...})`.
3. Add the appropriate sync helper in `ssh_client.py` and expose an async wrapper.
4. Document the new tool in `README.md` (tools table + example conversation).
5. Add an entry to `CHANGELOG.md` under `[Unreleased]`.

---

## Reporting bugs

Open a GitHub Issue with:
- Your OS and Python version
- The sshand version (`pip show sshand`)
- Steps to reproduce
- The full error output (redact any real hostnames or passwords)

---

## Security disclosures

Please **do not** open a public issue for security vulnerabilities. Email the maintainer directly (address in `pyproject.toml`) or use GitHub's private security advisory feature. We aim to respond within 48 hours.

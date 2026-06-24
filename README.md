# SSHand

An open MCP server that gives **any AI agent** SSH access to remote Linux/Unix machines — shell commands, file read/write, and SFTP transfers.

Works with **Claude.ai**, **Claude Desktop**, **ChatGPT**, **Cursor**, **VS Code Copilot**, **OpenAI Agents SDK**, and any other [MCP-compatible client](https://modelcontextprotocol.io/clients).

---

## Quick start

```bash
# 1. Install
pip install sshand

# 2. First-run setup: add a host, test it, print client config
sshand setup

# 3. Manage hosts any time (add / test / remove + reprint config)
sshand manage
```

Both commands open the same clean interactive terminal UI — use the **arrow keys** to move and **Enter** to select. `setup` runs the guided first-run flow; `manage` is the ongoing host manager.

---

## Setup guide

`sshand setup` walks you through three steps:

**1. Add a host.** You'll be asked for:

- **Alias** — a short nickname like `webserver` or `db-prod`.
- **Hostname / IP**, **port** (default `22`), and **username**.
- **Authentication method:**
  - **SSH key file** (recommended) — path to your private key, plus an optional passphrase.
  - **Password** — convenient for dev/test, avoid on internet-facing hosts.
  - **SSH agent** — delegates to your running `ssh-agent`; no credentials stored. On Windows the wizard also checks whether the OpenSSH Authentication Agent service is running and offers to start it.

The host is saved to `hosts.yaml` (or the path in `SSH_MCP_HOSTS_FILE`). An existing host is never overwritten without confirmation.

**2. Test the connection.** SSHand immediately connects and runs a no-op command, so you find out right away if something is wrong (bad key path, wrong port, unreachable host) instead of mid-conversation later. The host is saved either way — if the test fails, fix the issue and run `sshand setup` again.

**3. Print client config.** Pick a client (or **All of them**) and SSHand prints a ready-to-paste config snippet with the correct absolute paths already filled in:

> Claude Desktop · Cursor · VS Code (GitHub Copilot Chat) · OpenAI (Agents SDK / ChatGPT Desktop) · Hermes Agent · OpenClaw (via MCPorter) · Other (HTTP)

Full per-client instructions are in [Connecting to your AI client](#connecting-to-your-ai-client) below.

> Run `sshand setup` again any time to add another host or reprint a snippet — it won't touch your existing hosts.

---

## Managing your hosts

`sshand manage` opens the interactive host manager — a live table of your configured hosts plus a menu:

- **List hosts** — refresh the table.
- **Add a host** — the same flow as setup, with an optional connection test afterwards.
- **Test a host** — connect and report success or failure.
- **Remove a host** — delete an entry (with confirmation).
- **Client config snippets** — reprint the paste-ready config for any client, prefaced with the list of hosts the agent will be able to reach.

The screen refreshes in place after each action, with the result of your last action shown above the menu. Press **q** / choose **Quit** to exit.

---

## Installation options

### Option A — pip (recommended for most users)

```bash
pip install sshand        # from PyPI
pip install -e .            # from source, editable install
```

### Option B — uvx (zero-install, no venv needed)

[uv](https://docs.astral.sh/uv/) is the modern Python package manager. With it installed you can run SSHand without any manual install step:

```bash
uvx sshand                # run server directly
uvx sshand setup          # run setup wizard
```

This is the cleanest option to recommend to non-technical users.

### Option C — plain Python (no install)

```bash
git clone https://github.com/muradmalik23/sshand
cd sshand
pip install -r requirements.txt
python server.py            # start server
python manage.py setup      # run the setup wizard
python manage.py            # interactive host manager
```

---

## Connecting to your AI client

### Claude.ai and ChatGPT (web + desktop)

For Claude.ai web and ChatGPT, SSHand runs as an **HTTP server** and you connect it through each app's native integrations UI.

**→ See [INTEGRATIONS.md](INTEGRATIONS.md) for the full step-by-step guide**, including how to expose the server publicly using ngrok or Cloudflare Tunnel, and how to add it to Claude.ai Integrations and ChatGPT Desktop.

---

### Claude Desktop

Add to your `claude_desktop_config.json`:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ssh": {
      "command": "uvx",
      "args": ["sshand"]
    }
  }
}
```

Or with plain Python:

```json
{
  "mcpServers": {
    "ssh": {
      "command": "python",
      "args": ["/absolute/path/to/sshand/server.py"]
    }
  }
}
```

No env var needed for either option — hosts are stored at `~/.sshand/hosts.yaml` automatically. See [Host inventory](#host-inventory) below if you want a different location.

Restart Claude Desktop after saving.

---

### Cursor

Create or update `.cursor/mcp.json` in your project (or the global Cursor MCP settings):

```json
{
  "mcpServers": {
    "ssh": {
      "command": "uvx",
      "args": ["sshand"]
    }
  }
}
```

No env var needed — hosts are stored at `~/.sshand/hosts.yaml` automatically.

---

### VS Code (GitHub Copilot Chat)

Add to `.vscode/mcp.json` or your workspace `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "ssh": {
        "type": "stdio",
        "command": "uvx",
        "args": ["sshand"]
      }
    }
  }
}
```

No env var needed — hosts are stored at `~/.sshand/hosts.yaml` automatically.

---

### OpenAI Agents SDK

```bash
# Terminal 1 — keep this running
sshand --transport http --port 8000
```

```python
from agents import Agent
from agents.mcp import MCPServerStreamableHttp

ssh_server = MCPServerStreamableHttp(url="http://localhost:8000/mcp")
agent = Agent(name="ops-agent", mcp_servers=[ssh_server])
```

---

### Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) reads MCP server config from `~/.hermes/config.yaml` under the `mcp_servers` key — same `command`/`args`/`env` shape as everywhere else:

```yaml
mcp_servers:
  ssh:
    command: "uvx"
    args: ["sshand"]
```

If you installed SSHand from source instead of via `uvx`, point `command` at `python` and add `["/absolute/path/to/sshand/server.py"]` as `args`, same as the Claude Desktop snippet above.

No env var needed either way — hosts are stored at `~/.sshand/hosts.yaml` automatically.

Start (or reload) Hermes to pick it up:

```bash
hermes chat          # fresh start
/reload-mcp          # or, from inside a running session
```

Hermes prefixes every tool with `mcp_<server_name>_`, so e.g. `ssh_run_command` shows up as `mcp_ssh_ssh_run_command` — you won't normally need the prefixed name, Hermes picks the right tool from your prompt on its own.

---

### OpenClaw

OpenClaw doesn't take MCP servers directly — it calls them through [MCPorter](https://github.com/openclaw/mcporter), a separate CLI that OpenClaw shells out to for schema discovery and tool calls. Install MCPorter first:

```bash
npm install -g mcporter
```

Then register SSHand with it:

```bash
mcporter config add ssh --command uvx --args sshand
```

That writes an entry to `config/mcporter.json` (or `~/.mcporter/mcporter.json` for a machine-wide install) in the same `mcpServers` shape used everywhere else:

```jsonc
{
  "mcpServers": {
    "ssh": {
      "command": "uvx",
      "args": ["sshand"]
    }
  }
}
```

No env var needed — hosts are stored at `~/.sshand/hosts.yaml` automatically.

Confirm MCPorter can see it and list the tools:

```bash
mcporter list ssh --schema
```

No further OpenClaw-side config is needed — just ask it to do something that needs SSH (e.g. *"check disk usage on webserver"*) and OpenClaw will invoke `mcporter call ssh.ssh_run_command ...` on its own.

---

### Any other MCP client (HTTP)

```bash
sshand --transport http --port 8000
```

MCP endpoint: `http://localhost:8000/mcp`

For remote access, put a reverse proxy (nginx / Caddy) in front with TLS. Never expose port 8000 directly on a public interface.

---

## Host inventory

Hosts are stored in `~/.sshand/hosts.yaml`, created automatically on startup regardless of how SSHand was installed (`pip`, `uvx`, or from source) — no env var or extra config required. You can edit the file directly or let your agent call `ssh_add_host`.

Want a different location instead? Set `SSH_MCP_HOSTS_FILE` to override it, e.g. `"env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/hosts.yaml" }` in any of the MCP configs above.

Running from a git clone and want the inventory to live next to the source instead? Point `SSH_MCP_HOSTS_FILE` at a repo-local copy:

```bash
cp hosts.yaml.example hosts.yaml
export SSH_MCP_HOSTS_FILE="$PWD/hosts.yaml"
```

### Auth types

**Key file** — most common, most secure:
```yaml
auth:
  type: key
  key_path: ~/.ssh/id_rsa       # ~ is expanded automatically
  passphrase: null              # set if the key is encrypted
```

**Password** — convenient for dev/test, avoid on internet-facing servers:
```yaml
auth:
  type: password
  password: s3cr3t
```

**SSH agent** — no credentials stored at all, delegates to the running `ssh-agent`:
```yaml
auth:
  type: agent
```

---

## Available tools

| Tool | Description | Read-only? |
|------|-------------|------------|
| `ssh_list_hosts` | List all configured SSH targets | ✅ |
| `ssh_add_host` | Register a new SSH host | ❌ |
| `ssh_remove_host` | Remove a host from inventory | ❌ |
| `ssh_test_connection` | Verify auth works for a host | ✅ |
| `ssh_run_command` | Execute a shell command + capture output | ❌ |
| `ssh_read_file` | Read a remote file's contents | ✅ |
| `ssh_write_file` | Create or overwrite a remote file | ❌ |
| `ssh_list_directory` | Browse a remote directory | ✅ |
| `ssh_upload_file` | Push a local file to the remote host (SFTP) | ❌ |
| `ssh_download_file` | Pull a remote file to this machine (SFTP) | ✅ |
| `ssh_get_local_info` | Return OS and path style of the MCP server host | ✅ |

---

## Example conversations

> *"What servers do you have access to?"*
> → `ssh_list_hosts`

> *"Check disk usage on webserver"*
> → `ssh_run_command(alias='webserver', command='df -h')`

> *"Read the nginx config on the web box"*
> → `ssh_read_file(alias='webserver', remote_path='/etc/nginx/nginx.conf')`

> *"Tail the last 100 lines of syslog on bastion"*
> → `ssh_run_command(alias='bastion', command='tail -n 100 /var/log/syslog')`

> *"Deploy this config file to devbox"*
> → `ssh_write_file(alias='devbox', remote_path='/etc/myapp/config.yaml', content='...')`

> *"Download today's DB backup from webserver"*
> → `ssh_download_file(alias='webserver', remote_path='/backups/db-today.sql.gz', local_path='/tmp/db-today.sql.gz')`

---

## CLI reference

```
sshand [subcommand] [options]

Subcommands:
  setup                  Interactive first-run wizard (add a host, test, print config)
  manage                 Interactive host manager (add / test / remove + config snippets)

Options:
  --transport {stdio,http}   Transport (default: stdio)
  --port INT                 HTTP port (default: 8000)
  --host STR                 HTTP bind address (default: 127.0.0.1)

Examples:
  sshand                    # start stdio server
  sshand setup              # first-run wizard
  sshand manage             # interactive host manager
  sshand --transport http   # start HTTP server on :8000
```

---

## Security notes

- By default your inventory lives outside the repo at `~/.sshand/hosts.yaml`, so it can't accidentally land in version control. If you've pointed `SSH_MCP_HOSTS_FILE` at a repo-local `hosts.yaml`, keep it out of git — it's already excluded by the included `.gitignore`.
- Prefer key-based or agent auth over password auth for any internet-facing host.
- The HTTP transport binds to `127.0.0.1` by default.
- When exposing the HTTP server publicly (for Claude.ai / ChatGPT web), use TLS and consider adding authentication via a reverse proxy.
- `ssh_run_command` is marked `destructiveHint: true` — MCP clients that respect annotations will prompt before running potentially dangerous commands.

---

## Project structure

```
sshand/
├── server.py           # FastMCP server — all 11 tools + CLI entry point
├── ssh_client.py       # Async paramiko wrapper (command exec + SFTP)
├── host_config.py      # YAML host inventory manager
├── manage.py           # Interactive TUI — setup wizard + host manager (rich + questionary)
├── setup_wizard.py     # Client-config snippet builders + Windows agent helpers (used by manage.py)
├── platform_utils.py   # Windows SSH agent helpers
├── hosts.yaml.example  # Safe template — for repo-local SSH_MCP_HOSTS_FILE setups
├── hosts.yaml          # Optional: only present if SSH_MCP_HOSTS_FILE points here (gitignored)
├── INTEGRATIONS.md     # Guide: Claude.ai and ChatGPT native extensions
├── pyproject.toml      # Package metadata + pip/uvx install config
├── requirements.txt    # Plain pip install fallback
└── README.md
```

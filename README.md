# SSHand

An open MCP server that gives **any AI agent** SSH access to remote Linux/Unix machines — shell commands, file read/write, and SFTP transfers.

Works with **Claude.ai**, **Claude Desktop**, **ChatGPT**, **Cursor**, **VS Code Copilot**, **OpenAI Agents SDK**, and any other [MCP-compatible client](https://modelcontextprotocol.io/clients).

---

## Quick start

```bash
# 1. Install
pip install sshand

# 2. Run the interactive setup wizard
sshand setup
```

### What the setup wizard actually does

`sshand setup` (or `python setup_wizard.py` from a checkout) runs three steps, in order:

1. **Add a host** — alias, hostname/IP, port, username, and an auth method (key file, password, or ssh-agent). On Windows it also checks whether the OpenSSH Authentication Agent service is running and offers to start it for you if you picked agent auth.
2. **Test the connection** — it immediately tries to connect with what you just entered and runs a no-op command, so you find out right away if something's wrong (bad path, wrong port, unreachable host) instead of during your first real agent session. The host is saved either way — if the test fails, fix the issue and just run `sshand setup` again.
3. **Generate client config** — pick one or more AI clients from a list (space-separated numbers, or Enter for all) and the wizard prints a ready-to-paste config snippet for each, with the correct absolute paths already filled in. Today's options: Claude Desktop, Cursor, VS Code (GitHub Copilot Chat), OpenAI (Agents SDK / ChatGPT Desktop), and a generic "Other" HTTP option for any MCP-compatible client not listed by name.

You can run the wizard again any time — to add another host, or to reprint client config snippets without touching your existing hosts. It never overwrites a host without asking first.

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
python setup_wizard.py      # run wizard
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
      "args": ["sshand"],
      "env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/hosts.yaml" }
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
      "args": ["/absolute/path/to/sshand/server.py"],
      "env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/sshand/hosts.yaml" }
    }
  }
}
```

Restart Claude Desktop after saving.

---

### Cursor

Create or update `.cursor/mcp.json` in your project (or the global Cursor MCP settings):

```json
{
  "mcpServers": {
    "ssh": {
      "command": "uvx",
      "args": ["sshand"],
      "env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/hosts.yaml" }
    }
  }
}
```

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
        "args": ["sshand"],
        "env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/hosts.yaml" }
      }
    }
  }
}
```

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
    env:
      SSH_MCP_HOSTS_FILE: "/absolute/path/to/hosts.yaml"
```

If you installed SSHand from source instead of via `uvx`, point `command` at `python` and add `["/absolute/path/to/sshand/server.py"]` as `args`, same as the Claude Desktop snippet above.

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
mcporter config add ssh --command uvx --args sshand --env SSH_MCP_HOSTS_FILE=/absolute/path/to/hosts.yaml
```

That writes an entry to `config/mcporter.json` (or `~/.mcporter/mcporter.json` for a machine-wide install) in the same `mcpServers` shape used everywhere else:

```jsonc
{
  "mcpServers": {
    "ssh": {
      "command": "uvx",
      "args": ["sshand"],
      "env": { "SSH_MCP_HOSTS_FILE": "/absolute/path/to/hosts.yaml" }
    }
  }
}
```

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

Hosts are stored in `hosts.yaml` (set a different path with the `SSH_MCP_HOSTS_FILE` env var). You can edit the file directly or let your agent call `ssh_add_host`.

Copy `hosts.yaml.example` to `hosts.yaml` to get started:

```bash
cp hosts.yaml.example hosts.yaml
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
  setup                  Interactive first-run wizard

Options:
  --transport {stdio,http}   Transport (default: stdio)
  --port INT                 HTTP port (default: 8000)
  --host STR                 HTTP bind address (default: 127.0.0.1)

Examples:
  sshand                    # start stdio server
  sshand setup              # first-run wizard
  sshand --transport http   # start HTTP server on :8000
```

---

## Security notes

- Keep `hosts.yaml` out of version control if it contains passwords — it is excluded by the included `.gitignore`. Copy `hosts.yaml.example` to `hosts.yaml` to get started.
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
├── setup_wizard.py     # Interactive first-run setup wizard
├── platform_utils.py   # Windows SSH agent helpers
├── hosts.yaml.example  # Safe template — copy to hosts.yaml and fill in your values
├── hosts.yaml          # Your SSH targets (gitignored — copy from hosts.yaml.example)
├── INTEGRATIONS.md     # Guide: Claude.ai and ChatGPT native extensions
├── pyproject.toml      # Package metadata + pip/uvx install config
├── requirements.txt    # Plain pip install fallback
└── README.md
```

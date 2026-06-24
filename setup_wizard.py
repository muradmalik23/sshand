#!/usr/bin/env python3
"""
setup_wizard.py — Interactive first-run setup for SSHand.

Run via:
    sshand setup        (after pip install)
    python setup_wizard.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# ─── ANSI colour helpers (no extra deps) ─────────────────────────────────────

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"


def bold(t: str)    -> str: return _c("1",    t)
def green(t: str)   -> str: return _c("32",   t)
def yellow(t: str)  -> str: return _c("33",   t)
def cyan(t: str)    -> str: return _c("36",   t)
def dim(t: str)     -> str: return _c("2",    t)
def red(t: str)     -> str: return _c("31",   t)


def _hr(char: str = "─", width: int = 60) -> str:
    return dim(char * width)


def _box(title: str, width: int = 60) -> str:
    pad   = width - len(title) - 2
    left  = pad // 2
    right = pad - left
    top    = "╔" + "═" * (width - 2) + "╗"
    middle = "║" + " " * left + bold(title) + " " * right + "║"
    bottom = "╚" + "═" * (width - 2) + "╝"
    return "\n".join([top, middle, bottom])


# ─── Prompt helpers ───────────────────────────────────────────────────────────

def _ask(prompt: str, default: Optional[str] = None, required: bool = False) -> str:
    """Prompt the user for input, enforcing required fields."""
    suffix = f" [{dim(default)}]" if default else ""
    while True:
        try:
            val = input(f"  {cyan('›')} {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nAborted.")
            sys.exit(0)
        if val:
            return val
        if default is not None:
            return default
        if required:
            print(f"    {yellow('⚠')}  This field is required.")
        else:
            return ""


def _ask_int(prompt: str, default: int, lo: int = 1, hi: int = 65535) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            n = int(raw)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"    {yellow('⚠')}  Please enter a number between {lo} and {hi}.")


def _ask_choice(prompt: str, choices: list[str], default: str = "1") -> str:
    """Return the user's chosen item from *choices* (1-indexed)."""
    for i, c in enumerate(choices, 1):
        print(f"    {dim(str(i))}.  {c}")
    while True:
        raw = _ask(prompt, default)
        try:
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            pass
        print(f"    {yellow('⚠')}  Enter a number between 1 and {len(choices)}.")


def _ask_multi_choice(
    prompt: str, choices: list[str], default_all: bool = True
) -> list[str]:
    """Ask the user to pick one or more items (space-separated indices)."""
    for i, c in enumerate(choices, 1):
        print(f"    {dim(f'[{i}]')}  {c}")
    default_hint = " ".join(str(i) for i in range(1, len(choices) + 1))
    while True:
        raw = _ask(prompt, default_hint if default_all else None)
        parts = raw.split()
        selected = []
        bad = False
        for p in parts:
            try:
                idx = int(p)
                if 1 <= idx <= len(choices):
                    selected.append(choices[idx - 1])
                    continue
            except ValueError:
                pass
            bad = True
            break
        if selected and not bad:
            return selected
        print(f"    {yellow('⚠')}  Enter space-separated numbers, e.g. '1 3'.")


# ─── Config snippet generators ────────────────────────────────────────────────

def _server_path() -> str:
    # Forward slashes work on Windows too and avoid double-escaping in JSON
    return Path(__file__).resolve().parent.joinpath("server.py").as_posix()


def _hosts_note() -> str:
    # Informational only — never fed into a generated snippet as an env var.
    # Hosts live at ~/.sshand/hosts.yaml (or wherever SSH_MCP_HOSTS_FILE points,
    # if the user has set that themselves) no matter how SSHand was installed,
    # so the snippets below don't need to set anything for this to work.
    import host_config as hc

    return str(hc.DEFAULT_HOSTS_FILE)


def _snippet_claude_desktop() -> str:
    config_path_mac = "~/Library/Application Support/Claude/claude_desktop_config.json"
    config_path_win = r"%APPDATA%\Claude\claude_desktop_config.json"
    snippet = {
        "mcpServers": {
            "ssh": {
                "command": "python",
                "args": [_server_path()],
            }
        }
    }
    uvx_snippet = {
        "mcpServers": {
            "ssh": {
                "command": "uvx",
                "args": ["sshand"],
            }
        }
    }
    return f"""\
  Config file locations:
    macOS   {dim(config_path_mac)}
    Windows {dim(config_path_win)}

  {bold("Option A — direct Python")} (works right now):
{_indent_json(snippet)}

  {bold("Option B — uvx")} (if you have uv installed, zero-venv):
{_indent_json(uvx_snippet)}

  No env var needed — hosts are stored at {dim(_hosts_note())}.
  Want a different location? Add {dim('"env": {"SSH_MCP_HOSTS_FILE": "/your/path/hosts.yaml"}')}.

  Then {bold("restart Claude Desktop")}.
"""


def _snippet_cursor() -> str:
    snippet = {
        "mcpServers": {
            "ssh": {
                "command": "python",
                "args": [_server_path()],
            }
        }
    }
    return f"""\
  Add to {dim('.cursor/mcp.json')} in your project root (or the global Cursor MCP settings):

{_indent_json(snippet)}

  No env var needed — hosts are stored at {dim(_hosts_note())}.
"""


def _snippet_vscode() -> str:
    snippet = {
        "mcp": {
            "servers": {
                "ssh": {
                    "type": "stdio",
                    "command": "python",
                    "args": [_server_path()],
                }
            }
        }
    }
    return f"""\
  Add to {dim('.vscode/mcp.json')} or your workspace {dim('settings.json')}:

{_indent_json(snippet)}

  No env var needed — hosts are stored at {dim(_hosts_note())}.
"""


def _snippet_openai() -> str:
    return f"""\
  OpenAI's Agents SDK and ChatGPT Desktop both support MCP via HTTP transport.

  {bold("1. Start the HTTP server")} (run this in a terminal and keep it open):

    {cyan('sshand --transport http --port 8000')}

    or:  {cyan(f'python {_server_path()} --transport http --port 8000')}

  {bold("2. Point your OpenAI code at it")}:

    {dim('# Python — openai-agents-sdk')}
    from agents import Agent
    from agents.mcp import MCPServerStreamableHttp

    ssh_server = MCPServerStreamableHttp(url="http://localhost:8000/mcp")
    agent = Agent(name="ops", mcp_servers=[ssh_server])

  {bold("3. ChatGPT Desktop")} — go to Settings → Integrations → MCP Servers
    and add:  {cyan('http://localhost:8000/mcp')}
"""


def _snippet_http() -> str:
    return f"""\
  Any MCP-compatible client that supports the Streamable-HTTP transport can
  connect once the server is running:

    {cyan('sshand --transport http --port 8000')}
    or:  {cyan(f'python {_server_path()} --transport http --port 8000')}

  MCP endpoint:  {bold('http://localhost:8000/mcp')}

  For remote access, put a reverse proxy (nginx / Caddy) in front with TLS.
  Never expose port 8000 directly on a public interface.
"""


def _indent_json(obj: dict, indent: int = 4) -> str:
    raw = json.dumps(obj, indent=2)
    prefix = " " * indent
    return "\n".join(prefix + line for line in raw.splitlines())


# ─── Windows SSH agent check ─────────────────────────────────────────────────

def _check_windows_agent() -> None:
    """
    On Windows: detect the OpenSSH Authentication Agent service state and
    offer to start it automatically (if running as Administrator) or print
    clear fix instructions.  No-op on macOS / Linux.
    """
    import platform_utils as pu

    status = pu.get_agent_status()

    if status == pu.AgentStatus.NOT_WINDOWS:
        return   # nothing to do on mac/linux

    print()
    if status == pu.AgentStatus.RUNNING:
        print(f"  {green('✓')}  OpenSSH Authentication Agent is already running.")
        return

    # Service is not running -- tell the user why and what to do
    print(f"  {yellow('⚠')}  {bold('Windows: OpenSSH Authentication Agent is not running.')}")
    print()

    if status == pu.AgentStatus.NOT_INSTALLED:
        print("  OpenSSH is not installed on this machine.")
        print()
        print("  Install it first:")
        print(f"    {cyan('Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0')}")
        print()
        return

    # Service is stopped or disabled -- offer to fix it
    if pu.is_windows_admin():
        print("  You are running as Administrator.")
        ans = _ask("  Enable and start the service now?", "y").lower()
        if ans in ("y", "yes"):
            ok, msg = pu.start_agent_service()
            if ok:
                print(f"  {green('✓')}  {msg}")
            else:
                print(f"  {red('✗')}  Could not start service automatically: {msg}")
                print()
                print(pu.WINDOWS_FIX_INSTRUCTIONS)
        else:
            print()
            print(pu.WINDOWS_FIX_INSTRUCTIONS)
    else:
        print("  This requires Administrator privileges to fix automatically.")
        print()
        print(pu.WINDOWS_FIX_INSTRUCTIONS)
        _ask("  Press Enter once the service is running to continue", "")


# ─── Connection test ──────────────────────────────────────────────────────────

def _test_connection_sync(alias: str) -> tuple[bool, str]:
    """Synchronous wrapper around the async test in ssh_client."""
    import asyncio
    try:
        import ssh_client as sc
        return asyncio.run(sc.test_connection(alias))
    except Exception as exc:
        return False, str(exc)


# ─── Main wizard ─────────────────────────────────────────────────────────────

def run() -> None:
    import host_config as hc

    print()
    print(_box("  SSHand  —  Setup Wizard  "))
    print()
    print("  Gives Claude (and other AI agents) SSH access to your servers.")
    print()
    print("  This wizard will:")
    print(f"    {dim('1.')} Add your first SSH host")
    print(f"    {dim('2.')} Verify the connection works")
    print(f"    {dim('3.')} Generate config for your AI client(s)")
    print()

    # ── STEP 1: Collect host details ─────────────────────────────────────────

    print(_hr())
    print(f"  {bold('STEP 1 / 3')}  {dim('·')}  Add a host")
    print(_hr())
    print()

    # Must match host_config.py's own default resolution exactly — otherwise
    # the host we save here ends up in a different hosts.yaml than the one
    # ssh_client.get_host() reads from when we test the connection below.
    hosts_file = hc.DEFAULT_HOSTS_FILE

    # Suggest alias if hosts.yaml already has entries
    existing = hc.list_hosts(hosts_file)
    alias_hint = None if existing else None

    alias    = _ask("Alias  (short nickname, e.g. 'webserver', 'db-prod')", required=True)
    hostname = _ask("Hostname or IP address", required=True)
    port     = _ask_int("SSH port", 22)
    username = _ask("Username", "ubuntu")

    print()
    print(f"  {bold('Authentication method:')}")
    auth_method = _ask_choice(
        "Choice",
        [
            "SSH key file   (recommended — most secure)",
            "Password       (easy, but avoid on internet-facing hosts)",
            "SSH agent      (forward from local ssh-agent)",
        ],
    )

    auth: hc.AuthConfig
    if auth_method.startswith("SSH key"):
        key_path   = _ask("Private key path", "~/.ssh/id_rsa")
        passphrase = _ask("Key passphrase    (leave blank if none)")
        auth = hc.KeyAuth(
            type="key",
            key_path=key_path,
            passphrase=passphrase or None,
        )
    elif auth_method.startswith("Password"):
        import getpass
        pw = ""
        while not pw:
            try:
                pw = getpass.getpass(f"  {cyan('›')} Password: ")
            except (EOFError, KeyboardInterrupt):
                print("\n\nAborted."); sys.exit(0)
            if not pw:
                print(f"    {yellow('⚠')}  Password cannot be empty.")
        auth = hc.PasswordAuth(type="password", password=pw)
    else:
        auth = hc.AgentAuth(type="agent")
        _check_windows_agent()   # no-op on macOS/Linux

    description = _ask("Description (optional)", "")

    entry = hc.HostEntry(
        hostname=hostname,
        port=port,
        username=username,
        auth=auth,
        description=description or None,
    )

    overwrite = False
    if alias in existing:
        print()
        print(f"  {yellow('⚠')}  A host named '{alias}' already exists.")
        ans = _ask("Overwrite it?", "n").lower()
        if ans not in ("y", "yes"):
            print("  Skipped. Keeping the existing entry.")
        else:
            overwrite = True

    hc.add_host(alias, entry, overwrite=overwrite, hosts_file=hosts_file)
    print()
    print(f"  {green('✓')}  Host '{bold(alias)}' saved to {dim(str(hosts_file))}")

    # ── STEP 2: Test connection ───────────────────────────────────────────────

    print()
    print(_hr())
    print(f"  {bold('STEP 2 / 3')}  {dim('·')}  Test connection")
    print(_hr())
    print()

    print(f"  Connecting to {bold(f'{username}@{hostname}:{port}')} …", end="", flush=True)
    ok, msg = _test_connection_sync(alias)

    if ok:
        print(f"  {green('✓')}  {msg}")
    else:
        print(f"\n\n  {red('✗')}  {msg}")
        print()
        print("  Possible fixes:")
        print("    • Double-check hostname, port, and username")
        print("    • Verify the key path exists and permissions are 600")
        if isinstance(auth, hc.PasswordAuth):
            print("    • Re-run setup with the correct password")
        print("    • Make sure port is reachable (try ssh manually first)")
        print()
        print(f"  The host was saved — run {cyan('sshand setup')} again once fixed.")
        print()

    # ── STEP 3: Client config ─────────────────────────────────────────────────

    print()
    print(_hr())
    print(f"  {bold('STEP 3 / 3')}  {dim('·')}  Configure your AI client(s)")
    print(_hr())
    print()
    print("  Which AI client(s) are you using?")
    print(f"  {dim('(space-separated numbers, or press Enter for all)')}")
    print()

    client_names = [
        "Claude Desktop",
        "Cursor",
        "VS Code  (GitHub Copilot Chat)",
        "OpenAI   (Agents SDK / ChatGPT Desktop)",
        "Other    (HTTP server — any MCP-compatible client)",
    ]
    chosen = _ask_multi_choice("Your choice", client_names)

    snippet_map = {
        "Claude Desktop":                         _snippet_claude_desktop,
        "Cursor":                                  _snippet_cursor,
        "VS Code  (GitHub Copilot Chat)":          _snippet_vscode,
        "OpenAI   (Agents SDK / ChatGPT Desktop)": _snippet_openai,
        "Other    (HTTP server — any MCP-compatible client)": _snippet_http,
    }

    print()
    for name in chosen:
        print(_hr("─"))
        print(f"  {bold(name)}")
        print(_hr("─"))
        fn = snippet_map.get(name)
        if fn:
            print(fn())

    # ── Done ──────────────────────────────────────────────────────────────────

    print(_hr("═"))
    print()
    print(f"  {green(bold('All done!'))}  SSHand is ready.")
    print()
    if ok:
        print(f"  Try asking your AI agent:")
        print(f"    {cyan(chr(34))}What can you tell me about {alias}?{cyan(chr(34))}")
        print(f"    {cyan(chr(34))}Check disk usage on {alias}{cyan(chr(34))}")
        print(f"    {cyan(chr(34))}Show me /etc/hosts on {alias}{cyan(chr(34))}")
    print()
    print(f"  Add more hosts later:  {cyan('sshand setup')}  or edit {dim(str(hosts_file))}")
    print()
    print(_hr("═"))
    print()


if __name__ == "__main__":
    run()

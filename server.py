#!/usr/bin/env python3
"""
server.py — SSHand MCP Server (FastMCP / stdio + HTTP transports).

Exposes 11 tools that give any MCP-capable agent (Claude, ChatGPT, etc.) the
ability to manage remote Linux/Unix machines over SSH without ever leaving chat.

Tools
-----
ssh_list_hosts        – show all hosts in the inventory
ssh_add_host          – register a new SSH target
ssh_remove_host       – remove a host from the inventory
ssh_test_connection   – ping a host to verify auth works
ssh_run_command       – execute a shell command on a remote host
ssh_read_file         – read a remote file's contents
ssh_write_file        – write text/bytes to a remote file
ssh_list_directory    – list the contents of a remote directory
ssh_upload_file       – push a local file to the remote host via SFTP
ssh_download_file     – pull a remote file down to the local machine via SFTP
ssh_get_local_info    – return OS / path style of the machine running this server

Usage
-----
    python server.py                        # stdio (Claude Desktop, Cursor, VS Code)
    python server.py --transport http       # streamable HTTP on :8000
"""

from __future__ import annotations

import atexit
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

# Make sure the package root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

import host_config as hc
import ssh_client as sc

# Close all cached SSH connections when the process exits (both stdio and HTTP
# transport modes). This prevents paramiko from leaving dangling transports.
atexit.register(sc.close_all_connections)

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "sshand",
    instructions="""
SSHand is an MCP server that gives you full SSH shell access and SFTP file management
for any Linux/Unix machine registered in the host inventory.

## Recommended workflow

1. **Discover** — call `ssh_list_hosts` first to see what machines are available.
2. **Verify** — after adding a new host, or when debugging, call `ssh_test_connection`.
3. **Explore** — use `ssh_run_command` for inspection tasks (ls, df, ps, tail, grep, etc.).
4. **Edit files** — prefer `ssh_read_file` + `ssh_write_file` over sed/echo one-liners in a command.
5. **Transfer** — use `ssh_upload_file` / `ssh_download_file` for large or binary files.

## Tool quick-reference

| Goal                                  | Tool                |
|---------------------------------------|---------------------|
| See all configured servers            | ssh_list_hosts      |
| Register a new server                 | ssh_add_host        |
| Verify credentials work               | ssh_test_connection |
| Run a shell command                   | ssh_run_command     |
| Read a file (config, log, script)     | ssh_read_file       |
| Create or overwrite a file            | ssh_write_file      |
| Browse a directory                    | ssh_list_directory  |
| Push a local file to the server       | ssh_upload_file     |
| Pull a remote file down               | ssh_download_file   |
| Discover OS / path style of this host | ssh_get_local_info  |

## Important behaviour notes

- **Stateless sessions** — each `ssh_run_command` call opens an independent shell.
  Environment and working directory do NOT persist between calls.
  Use the `cwd` parameter to set a directory per call, or chain commands with `&&`.

- **sudo** — pass `sudo_password` to `ssh_run_command` for privileged execution.
  The password is stripped from all output; stderr may still show the sudo prompt line.

- **Binary files** — set `encoding='raw'` in `ssh_read_file` for base64 output,
  or `encoding='base64'` in `ssh_write_file` to write decoded binary content.

- **Large directories** — use the `limit` parameter in `ssh_list_directory` to cap
  results when listing high-entry paths like /proc or /var/log.

- **Structured output** — pass `response_format='json'` to `ssh_run_command`,
  `ssh_list_hosts`, and `ssh_list_directory` when you need parseable data.

## Auth recommendations

Prefer key-based or agent auth over passwords for internet-facing hosts.
Never commit hosts.yaml to version control if it contains real credentials.
""",
)

# The hosts.yaml location can be overridden via SSH_MCP_HOSTS_FILE env var.
# Resolved through host_config.DEFAULT_HOSTS_FILE — the single source of
# truth for this default — so the server, the CLI manager, and the setup
# wizard always agree on where hosts.yaml lives.
_HOSTS_FILE = hc.DEFAULT_HOSTS_FILE

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fmt_error(msg: str) -> str:
    return f"Error: {msg}"


def _fmt_size(n: Optional[int]) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


def _fmt_mtime(ts: Optional[float]) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ssh_list_hosts",
    annotations={
        "title": "List SSH Hosts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ssh_list_hosts(
    response_format: Literal["markdown", "json"] = "markdown",
) -> str:
    """List all SSH hosts registered in the inventory.

    Returns the alias, hostname, port, username, and auth type for every
    configured host. Call this first when you don't know what machines are
    available.

    Args:
        response_format: 'markdown' (default) for a readable table, or 'json'
            for structured data.

    Returns:
        Formatted list of hosts, or a message if the inventory is empty.

    Examples:
        - "What servers can I connect to?" -> ssh_list_hosts()
        - "Show me all SSH targets as JSON" -> ssh_list_hosts(response_format='json')
    """
    try:
        hosts = hc.list_hosts(_HOSTS_FILE)
        if not hosts:
            return "No hosts configured yet. Use ssh_add_host to register your first server."

        if response_format == "json":
            out: dict[str, Any] = {}
            for alias, entry in hosts.items():
                if isinstance(entry, Exception):
                    out[alias] = {"error": str(entry)}
                else:
                    out[alias] = entry.model_dump()
            return json.dumps(out, indent=2)

        # Markdown table
        lines = ["# SSH Host Inventory", "", f"**{len(hosts)} host(s) configured**", ""]
        lines.append("| Alias | Hostname | Port | User | Auth | Note |")
        lines.append("|-------|----------|------|------|------|------|")
        for alias, entry in sorted(hosts.items()):
            if isinstance(entry, Exception):
                lines.append(f"| {alias} | *(malformed entry)* | — | — | — | {entry} |")
                continue
            auth_label = entry.auth.type
            if auth_label == "key":
                auth_label = f"key ({entry.auth.key_path})"  # type: ignore[union-attr]
            note = entry.description or ""
            lines.append(
                f"| `{alias}` | {entry.hostname} | {entry.port} "
                f"| {entry.username} | {auth_label} | {note} |"
            )
        return "\n".join(lines)

    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_add_host",
    annotations={
        "title": "Add SSH Host",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def ssh_add_host(
    alias: str,
    hostname: str,
    username: str,
    auth_type: Literal["key", "password", "agent"],
    port: int = 22,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    password: Optional[str] = None,
    description: Optional[str] = None,
    overwrite: bool = False,
) -> str:
    """Register a new SSH host in the inventory.

    Saves the host details to hosts.yaml so it can be referenced by alias in
    all other ssh_* tools. Supports key, password, and agent authentication.

    Args:
        alias: Short nickname for the host (e.g., 'webserver', 'db-prod').
            Only letters, digits, underscores, and hyphens are allowed.
        hostname: IP address or FQDN (e.g., '192.168.1.10', 'db.example.com').
        username: SSH login username (e.g., 'ubuntu', 'ec2-user').
        auth_type: Authentication method — 'key' (private key file),
            'password', or 'agent' (ssh-agent).
        port: SSH port (default 22).
        key_path: Required when auth_type='key'. Path to the private key file
            (e.g., '~/.ssh/id_rsa').
        key_passphrase: Optional passphrase to decrypt an encrypted private key.
        password: Required when auth_type='password'.
        description: Optional human-readable note about this server.
        overwrite: Set True to replace an existing host with the same alias.

    Returns:
        Success message or error description.

    Examples:
        - Add a key-based host:
            alias='webserver', hostname='10.0.0.5', username='ubuntu',
            auth_type='key', key_path='~/.ssh/id_rsa'
        - Add a password host:
            alias='legacy', hostname='old.corp.net', username='admin',
            auth_type='password', password='s3cr3t'
        - Add an agent-auth host:
            alias='jump', hostname='bastion.example.com', username='ops',
            auth_type='agent'
    """
    try:
        alias = alias.strip()
        if not re.match(r"^[A-Za-z0-9_\-]+$", alias):
            return _fmt_error(
                "alias must contain only letters, digits, underscores, and hyphens."
            )

        if auth_type == "key":
            if not key_path:
                return _fmt_error(
                    "key_path is required when auth_type='key'. "
                    "Provide the path to your private key file."
                )
            auth = hc.KeyAuth(type="key", key_path=key_path, passphrase=key_passphrase)
        elif auth_type == "password":
            if not password:
                return _fmt_error("password is required when auth_type='password'.")
            auth = hc.PasswordAuth(type="password", password=password)
        else:
            auth = hc.AgentAuth(type="agent")

        entry = hc.HostEntry(
            hostname=hostname,
            port=port,
            username=username,
            auth=auth,
            description=description,
        )
        hc.add_host(alias, entry, overwrite=overwrite, hosts_file=_HOSTS_FILE)
        return (
            f"✓ Host '{alias}' added successfully "
            f"({username}@{hostname}:{port}, auth={auth_type}).\n"
            f"Run ssh_test_connection to verify the credentials work."
        )

    except ValueError as exc:
        return _fmt_error(
            f"{exc}  Tip: pass overwrite=True to replace an existing host."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_remove_host",
    annotations={
        "title": "Remove SSH Host",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def ssh_remove_host(alias: str) -> str:
    """Remove a host from the SSH inventory permanently.

    This only removes the local config entry — it does NOT touch the remote
    server in any way.

    Args:
        alias: The host alias to remove.

    Returns:
        Confirmation or error message.
    """
    try:
        sc.close_connection(alias)  # evict any cached connection
        hc.remove_host(alias, hosts_file=_HOSTS_FILE)
        return f"✓ Host '{alias}' removed from the inventory."
    except KeyError as exc:
        return _fmt_error(f"{exc}  Use ssh_list_hosts to see available aliases.")
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_test_connection",
    annotations={
        "title": "Test SSH Connection",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_test_connection(alias: str) -> str:
    """Verify that a host is reachable and authentication succeeds.

    Attempts to open an SSH session and run a trivial echo command. Use this
    immediately after ssh_add_host to confirm your credentials are correct.

    Args:
        alias: Host alias to test (must exist in inventory).

    Returns:
        '✓ Connected …' on success, or an actionable error on failure.

    Examples:
        - After adding a new host: ssh_test_connection(alias='webserver')
        - Debugging a connection issue: ssh_test_connection(alias='db-prod')
    """
    try:
        ok, message = await sc.test_connection(alias)
        if ok:
            return f"✓ {message}"
        return _fmt_error(
            f"{message}\n"
            "Possible causes:\n"
            "  • Wrong hostname or port — verify with ssh_list_hosts\n"
            "  • Authentication failure — check key_path / password / agent\n"
            "  • Firewall blocking port — try a different network\n"
            "  • Host is down — ping it from another terminal"
        )
    except KeyError:
        return _fmt_error(
            f"Host '{alias}' not found. Run ssh_list_hosts to see configured hosts."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_run_command",
    annotations={
        "title": "Run Remote Command",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ssh_run_command(
    alias: str,
    command: str,
    timeout: int = 60,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    sudo_password: Optional[str] = None,
    response_format: Literal["markdown", "json"] = "markdown",
) -> str:
    """Execute a shell command on a remote SSH host and return the output.

    The command runs in the login user's default shell. Both stdout and stderr
    are captured and returned. The exit code is included so you can detect
    failures.

    Args:
        alias: Target host alias.
        command: Shell command to execute (e.g., 'ls -la /var/log',
            'systemctl status nginx', 'df -h').
        timeout: Maximum seconds to wait (default 60, max 3600).
        env: Optional extra environment variables dict for this command.
        cwd: Remote working directory. When set the effective invocation
            becomes 'cd <cwd> && <command>'. Use absolute POSIX paths
            (e.g. '/var/www/html'). State is NOT persisted between calls.
        sudo_password: When set, the command runs via sudo. The password is
            never echoed back in output.
        response_format: 'markdown' (default, human-readable) or 'json'.

    Returns:
        Command output (stdout + stderr) with exit code.

    Examples:
        - Inspect disk usage:  command='df -h'
        - Check a service:     command='systemctl status nginx'
        - Tail logs:           command='tail -n 50 /var/log/syslog'
        - Install a package:   command='sudo apt-get install -y htop'
    """
    try:
        exit_code, stdout, stderr = await sc.run_command(
            alias, command, timeout, env, cwd, sudo_password
        )

        cmd_label = command
        if sudo_password:
            cmd_label = f"sudo: {command}"
        cwd_label = f"  |  **cwd**: `{cwd}`" if cwd else ""

        if response_format == "json":
            return json.dumps(
                {
                    "alias": alias,
                    "command": command,
                    "cwd": cwd,
                    "sudo": sudo_password is not None,
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timed_out": False,
                },
                indent=2,
            )

        lines = [
            f"## Command: `{cmd_label}`",
            f"**Host**: {alias}{cwd_label}  |  **Exit code**: {exit_code}",
            "",
        ]
        if stdout:
            lines += ["### stdout", "```", stdout.rstrip(), "```", ""]
        else:
            lines += ["*(no stdout)*", ""]
        if stderr:
            lines += ["### stderr", "```", stderr.rstrip(), "```", ""]

        if exit_code != 0:
            lines.append(
                f"> ⚠️  Command exited with code {exit_code}. "
                "Check stderr above for clues."
            )
        return "\n".join(lines)

    except KeyError:
        return _fmt_error(
            f"Host '{alias}' not found. Run ssh_list_hosts to see configured hosts."
        )
    except TimeoutError:
        return _fmt_error(
            f"Command timed out after {timeout}s. "
            "Increase timeout or split the operation into smaller steps."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_read_file",
    annotations={
        "title": "Read Remote File",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_read_file(
    alias: str,
    remote_path: str,
    encoding: str = "utf-8",
) -> str:
    """Read the contents of a file on a remote SSH host.

    Uses SFTP to transfer the file. Suitable for config files, logs, scripts,
    etc. For binary files set encoding='raw' to get a base64-encoded string.

    Args:
        alias: Host alias.
        remote_path: Absolute path of the file to read on the remote host
            (e.g., '/etc/nginx/nginx.conf').
        encoding: Text encoding to decode the file (default 'utf-8').
            Use 'raw' to get a base64-encoded string for binary files.

    Returns:
        File contents as text, or base64-encoded bytes for encoding='raw'.
        Returns an error string on failure.

    Examples:
        - Read nginx config: alias='web', remote_path='/etc/nginx/nginx.conf'
        - Read /etc/hosts:   remote_path='/etc/hosts'
        - Read binary file:  remote_path='/usr/bin/ls', encoding='raw'
    """
    import base64

    try:
        raw = await sc.read_file(alias, remote_path)
        if encoding == "raw":
            b64 = base64.b64encode(raw).decode("ascii")
            return f"# base64-encoded content of {remote_path}\n\n{b64}"
        return raw.decode(encoding, errors="replace")
    except KeyError:
        return _fmt_error(f"Host '{alias}' not found. Run ssh_list_hosts first.")
    except FileNotFoundError:
        return _fmt_error(
            f"File not found: {remote_path}\n"
            "Use ssh_list_directory to browse the remote filesystem."
        )
    except PermissionError:
        return _fmt_error(
            f"Permission denied reading {remote_path}. "
            "Try prefixing the command with sudo via ssh_run_command, "
            "or check file permissions."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_write_file",
    annotations={
        "title": "Write Remote File",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_write_file(
    alias: str,
    remote_path: str,
    content: str,
    encoding: Literal["utf-8", "base64"] = "utf-8",
) -> str:
    """Write content to a file on a remote SSH host (create or overwrite).

    Uses SFTP to transfer the content. Missing parent directories are created
    automatically. For binary content, base64-encode it and set encoding='base64'.

    Args:
        alias: Host alias.
        remote_path: Absolute destination path on the remote host.
        content: Text to write. For binary content, encode as base64 and set
            encoding='base64'.
        encoding: 'utf-8' to write the content as text (default),
            'base64' to decode first.

    Returns:
        Success message with byte count, or an error description.

    Examples:
        - Write a cron job: remote_path='/etc/cron.d/myjob', content='...'
        - Deploy a config:  remote_path='/etc/myapp/config.yaml', content='...'
        - Write a script:   remote_path='/usr/local/bin/deploy.sh', content='...'
    """
    import base64

    try:
        if encoding == "base64":
            raw = base64.b64decode(content)
        else:
            raw = content.encode(encoding)

        await sc.write_file(alias, remote_path, raw)
        return f"✓ Wrote {_fmt_size(len(raw))} to {remote_path} on '{alias}'."
    except KeyError:
        return _fmt_error(f"Host '{alias}' not found. Run ssh_list_hosts first.")
    except PermissionError:
        return _fmt_error(
            f"Permission denied writing to {remote_path}. "
            "Check that the SSH user has write access to that path."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_list_directory",
    annotations={
        "title": "List Remote Directory",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_list_directory(
    alias: str,
    remote_path: str = "~",
    limit: Optional[int] = None,
    response_format: Literal["markdown", "json"] = "markdown",
) -> str:
    """List the contents of a directory on a remote SSH host.

    Returns file names, types, sizes, permissions, and last-modified timestamps.
    Directories are listed before files, both sorted alphabetically.

    Args:
        alias: Host alias.
        remote_path: Directory path to list (default '~' = home directory).
        limit: Maximum number of entries to return. Useful for large directories
            like /proc or /var/log. Omit to return all entries.
        response_format: 'markdown' (default) or 'json'.

    Returns:
        Directory listing with columns: Type | Name | Size | Permissions | Modified.
        JSON format: {path, total, count, truncated, entries: [{name, type, size,
        permissions, modified}]}

    Examples:
        - Browse home dir:  ssh_list_directory(alias='web')
        - List /var/log:    remote_path='/var/log'
        - List /etc/nginx:  remote_path='/etc/nginx'
    """
    try:
        entries, resolved_path = await sc.list_directory(alias, remote_path)

        if not entries:
            return f"Directory '{resolved_path}' is empty."

        total = len(entries)
        truncated = limit is not None and total > limit
        if truncated:
            entries = entries[:limit]

        if response_format == "json":
            return json.dumps(
                {
                    "path": resolved_path,
                    "total": total,
                    "count": len(entries),
                    "truncated": truncated,
                    "entries": entries,
                },
                indent=2,
            )

        shown_label = f"{len(entries)} of {total}" if truncated else str(total)
        lines = [
            f"## {resolved_path}",
            f"**Host**: {alias}  |  **{shown_label} entries**"
            + (" *(truncated — increase `limit` to see more)*" if truncated else ""),
            "",
            "| Type | Name | Size | Permissions | Modified |",
            "|------|------|------|-------------|----------|",
        ]
        for e in entries:
            icon = "📁" if e["type"] == "directory" else ("🔗" if e["type"] == "symlink" else "📄")
            lines.append(
                f"| {icon} {e['type']} | `{e['name']}` "
                f"| {_fmt_size(e['size'])} | {e['permissions']} | {_fmt_mtime(e['modified'])} |"
            )
        return "\n".join(lines)

    except KeyError:
        return _fmt_error(f"Host '{alias}' not found. Run ssh_list_hosts first.")
    except FileNotFoundError:
        return _fmt_error(
            f"Directory not found: {remote_path}. "
            "Check the path or use '~' for the home directory."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_get_local_info",
    annotations={
        "title": "Get Local Machine Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ssh_get_local_info(
    response_format: Literal["markdown", "json"] = "json",
) -> str:
    """Return OS, home directory, cwd, and path style of the machine running the MCP server.

    Call this before ssh_upload_file or ssh_download_file to discover the correct
    local_path format (Windows backslash vs POSIX forward-slash).

    Args:
        response_format: 'json' (default) or 'markdown'.

    Returns:
        OS info including: os, home, cwd, path_style ('windows' or 'posix').

    Examples:
        - Before uploading: ssh_get_local_info() → learn that local_path needs Windows format
        - Debugging path errors: confirm the server's working directory
    """
    import platform

    info = {
        "os": platform.system(),           # 'Windows', 'Linux', 'Darwin'
        "home": str(Path.home()),           # e.g. C:\Users\Murad  or  /home/murad
        "cwd": str(Path.cwd()),             # MCP server's current working directory
        "path_style": "windows" if os.name == "nt" else "posix",
    }

    if response_format == "json":
        return json.dumps(info, indent=2)

    return (
        f"**OS:** {info['os']}  \n"
        f"**Path style:** {info['path_style']}  \n"
        f"**Home:** `{info['home']}`  \n"
        f"**CWD:** `{info['cwd']}`"
    )


@mcp.tool(
    name="ssh_upload_file",
    annotations={
        "title": "Upload File to Remote Host",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_upload_file(
    alias: str,
    local_path: str,
    remote_path: str,
) -> str:
    """Upload a local file to a remote SSH host via SFTP.

    The remote parent directory is created automatically if it doesn't exist.
    Use this to deploy configs, binaries, or any large file.

    Args:
        alias: Target host alias.
        local_path: Absolute path to the local file to upload, in the format
            native to the machine running the MCP server
            (e.g. 'C:\\Users\\me\\file.txt' on Windows,
            '/home/me/file.txt' on Linux/macOS).
            Call ssh_get_local_info first if you are unsure which format to use.
        remote_path: Absolute POSIX destination path on the remote host
            (e.g. '/home/user/file.txt').

    Returns:
        Success message with byte count, or an error description.

    Examples:
        - Deploy an app binary:
            local_path='/dist/myapp', remote_path='/opt/myapp/bin/myapp'
        - Upload a TLS cert:
            local_path='/tmp/server.crt', remote_path='/etc/ssl/certs/server.crt'
    """
    try:
        local = Path(local_path)
        if not local.exists():
            return _fmt_error(
                f"Local file not found: {local_path}. "
                "Verify the path exists on this machine."
            )
        if not local.is_file():
            return _fmt_error(
                f"{local_path} is not a file. "
                "This tool transfers single files; use a tar command for directories."
            )
        bytes_sent = await sc.upload_file(alias, str(local), remote_path)
        return (
            f"✓ Uploaded {_fmt_size(bytes_sent)} "
            f"from '{local_path}' → {remote_path} on '{alias}'."
        )
    except KeyError:
        return _fmt_error(f"Host '{alias}' not found. Run ssh_list_hosts first.")
    except Exception as exc:
        return _fmt_error(str(exc))


@mcp.tool(
    name="ssh_download_file",
    annotations={
        "title": "Download File from Remote Host",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ssh_download_file(
    alias: str,
    remote_path: str,
    local_path: str,
) -> str:
    """Download a file from a remote SSH host to the local machine via SFTP.

    The local parent directory is created automatically if needed.

    Args:
        alias: Source host alias.
        remote_path: Absolute POSIX path of the file on the remote host.
        local_path: Absolute destination path on the local machine, in the
            format native to the machine running the MCP server
            (e.g. 'C:\\Users\\me\\downloads\\file.txt' on Windows,
            '/home/me/downloads/file.txt' on Linux/macOS).
            Call ssh_get_local_info first if you are unsure which format to use.

    Returns:
        Success message with byte count, or an error description.

    Examples:
        - Fetch a log:     remote_path='/var/log/app.log', local_path='/tmp/app.log'
        - Pull a DB dump:  remote_path='/backups/db.sql.gz', local_path='/tmp/db.sql.gz'
    """
    try:
        bytes_recv = await sc.download_file(alias, remote_path, local_path)
        return (
            f"✓ Downloaded {_fmt_size(bytes_recv)} "
            f"from {remote_path} on '{alias}' → '{local_path}'."
        )
    except KeyError:
        return _fmt_error(f"Host '{alias}' not found. Run ssh_list_hosts first.")
    except FileNotFoundError:
        return _fmt_error(
            f"Remote file not found: {remote_path}. "
            "Use ssh_list_directory to check the path."
        )
    except Exception as exc:
        return _fmt_error(str(exc))


# ---------------------------------------------------------------------------
# CLI entry point  (called by `sshand` console script in pyproject.toml)
# ---------------------------------------------------------------------------


def main() -> None:
    """
    sshand [subcommand] [options]

    Subcommands
    -----------
    (none)       Start the MCP server (default: stdio transport).
    setup        Interactive wizard: add a host, test it, get client config.

    Options
    -------
    --transport {stdio,http}   Transport (default: stdio).
    --port INT                 Port for HTTP transport (default: 8000).
    --host STR                 Bind address for HTTP (default: 127.0.0.1).

    Examples
    --------
        sshand                          # start stdio server
        sshand setup                    # first-run wizard
        sshand --transport http         # HTTP server on :8000
        sshand --transport http --port 9000 --host 0.0.0.0
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="sshand",
        description="SSHand — give any AI agent SSH access to remote Linux/Unix machines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser(
        "setup",
        help="Interactive wizard: add a host, test it, and get AI-client config snippets.",
    )
    sub.add_parser(
        "manage",
        help="Interactive host manager (rich + questionary): list, add, test, and remove hosts.",
    )

    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to use (default: stdio for Claude Desktop/Cursor/VS Code; "
             "use http for Claude.ai, ChatGPT, OpenAI Agents SDK, or any HTTP MCP client).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for HTTP transport (default: 127.0.0.1). "
             "WARNING: 0.0.0.0 exposes the server on all interfaces.",
    )

    args = parser.parse_args()

    # Make sure ~/.sshand/hosts.yaml (or SSH_MCP_HOSTS_FILE) exists from the
    # first run, whether that first run is the server, "setup", or "manage" —
    # don't make the user wait until they've added a host to see the file.
    hc.ensure_hosts_file(_HOSTS_FILE)

    if args.subcommand == "setup":
        from manage import run as run_manage
        run_manage("setup")
        return

    if args.subcommand == "manage":
        from manage import run as run_manage
        run_manage("menu")
        return

    if args.transport == "http":
        print(
            f"Starting SSHand MCP server (HTTP) on http://{args.host}:{args.port}/mcp",
            flush=True,
        )
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()  # stdio -- clean stdout, MCP protocol only


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ssh_client.py — Async SSH/SFTP connection manager.

Wraps paramiko (which is synchronous) using asyncio.to_thread so that the
MCP server event loop is never blocked.  A lightweight connection cache keyed
on host alias avoids opening a new TCP handshake on every tool call.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path, PurePosixPath

import paramiko

from host_config import AgentAuth, HostEntry, KeyAuth, PasswordAuth, get_host  # AgentAuth used in _enrich_error

# ---------------------------------------------------------------------------
# Connection cache
# ---------------------------------------------------------------------------

# { alias -> paramiko.SSHClient }
_connection_cache: dict[str, paramiko.SSHClient] = {}


def _is_alive(client: paramiko.SSHClient) -> bool:
    """Return True if the underlying transport is still active."""
    transport = client.get_transport()
    return transport is not None and transport.is_active()


def _open_connection(host: HostEntry) -> paramiko.SSHClient:
    """Open and return a new paramiko SSH connection for the given HostEntry."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        "hostname": host.hostname,
        "port": host.port,
        "username": host.username,
        "timeout": 15,
        "banner_timeout": 15,
        "auth_timeout": 15,
    }

    auth = host.auth
    if isinstance(auth, KeyAuth):
        connect_kwargs["key_filename"] = auth.key_path
        if auth.passphrase:
            connect_kwargs["passphrase"] = auth.passphrase
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    elif isinstance(auth, PasswordAuth):
        connect_kwargs["password"] = auth.password
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    elif isinstance(auth, AgentAuth):
        connect_kwargs["allow_agent"] = True
        connect_kwargs["look_for_keys"] = False

    client.connect(**connect_kwargs)
    return client


def _get_or_open(alias: str) -> paramiko.SSHClient:
    """Return a cached (or freshly-opened) connection for *alias*."""
    existing = _connection_cache.get(alias)
    if existing and _is_alive(existing):
        return existing
    host = get_host(alias)
    client = _open_connection(host)
    _connection_cache[alias] = client
    return client


def close_connection(alias: str) -> None:
    """Close and evict a cached connection."""
    client = _connection_cache.pop(alias, None)
    if client:
        try:
            client.close()
        except Exception:
            pass


def close_all_connections() -> None:
    """Close every cached connection (e.g. on server shutdown)."""
    for alias in list(_connection_cache):
        close_connection(alias)


# ---------------------------------------------------------------------------
# Sync helpers (run in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _sync_run_command(
    alias: str,
    command: str,
    timeout: int,
    env: dict[str, str] | None,
    cwd: str | None = None,
    sudo_password: str | None = None,
) -> tuple[int, str, str]:
    """Execute *command* on the remote host and return (exit_code, stdout, stderr).

    cwd:
        When set, the effective command becomes ``cd <cwd> && <command>``.
        The directory change is scoped to this invocation only — no state
        persists between calls.

    sudo_password:
        When set, the command is run via ``sudo -S`` with the password piped
        through stdin.  The password is never echoed in stdout/stderr.
        sudo may still emit ``[sudo] password for …:`` to stderr; that is
        normal and can be ignored.
    """
    import shlex

    actual_command = command

    if sudo_password:
        # Build the inner command (with optional cwd) then wrap in sudo -S
        inner = f"cd {shlex.quote(cwd)} && {command}" if cwd else command
        actual_command = (
            f"echo {shlex.quote(sudo_password)} | sudo -S sh -c {shlex.quote(inner)}"
        )
    elif cwd:
        actual_command = f"cd {shlex.quote(cwd)} && {command}"

    client = _get_or_open(alias)
    _, stdout_fh, stderr_fh = client.exec_command(
        actual_command, timeout=timeout, environment=env or None
    )
    exit_code: int = stdout_fh.channel.recv_exit_status()
    stdout_str = stdout_fh.read().decode("utf-8", errors="replace")
    stderr_str = stderr_fh.read().decode("utf-8", errors="replace")
    return exit_code, stdout_str, stderr_str


def _expand_remote_path(sftp: paramiko.SFTPClient, remote_path: str) -> str:
    """Expand a leading ~ to the remote user's home directory.

    SFTP's realpath / normalize() always starts in the user's home directory,
    so normalize('.') reliably returns it without any shell involvement.
    """
    if remote_path == "~":
        return sftp.normalize(".")
    if remote_path.startswith("~/"):
        home = sftp.normalize(".")
        return home.rstrip("/") + remote_path[1:]  # ~/foo → /home/user/foo
    return remote_path


def _sync_read_file(alias: str, remote_path: str) -> bytes:
    """Return the raw bytes of a remote file."""
    client = _get_or_open(alias)
    sftp = client.open_sftp()
    try:
        resolved = _expand_remote_path(sftp, remote_path)
        with sftp.open(resolved, "rb") as fh:
            return fh.read()
    finally:
        sftp.close()


def _sync_write_file(alias: str, remote_path: str, content: bytes) -> None:
    """Write *content* bytes to *remote_path*, creating parent dirs if needed."""
    client = _get_or_open(alias)
    sftp = client.open_sftp()
    try:
        # Best-effort mkdir -p for the parent directory
        # Always use PurePosixPath — the remote is Linux/Unix regardless of local OS
        parent = str(PurePosixPath(remote_path).parent)
        if parent and parent != ".":
            try:
                _sftp_makedirs(sftp, parent)
            except Exception:
                pass  # non-fatal; the write may still succeed
        with sftp.open(remote_path, "wb") as fh:
            fh.write(content)
    finally:
        sftp.close()


def _sync_list_directory(alias: str, remote_path: str) -> tuple[list[dict], str]:
    """Return (entries, resolved_path) where entries is a list of
    {name, type, size, permissions, modified} dicts.

    The resolved_path reflects tilde expansion so the caller can display
    the actual path rather than the raw '~' the user passed in.
    """
    client = _get_or_open(alias)
    sftp = client.open_sftp()
    try:
        resolved = _expand_remote_path(sftp, remote_path)
        entries = []
        for attr in sftp.listdir_attr(resolved):
            mode = attr.st_mode or 0
            if stat.S_ISDIR(mode):
                kind = "directory"
            elif stat.S_ISLNK(mode):
                kind = "symlink"
            else:
                kind = "file"
            entries.append(
                {
                    "name": attr.filename,
                    "type": kind,
                    "size": attr.st_size,
                    "permissions": oct(stat.S_IMODE(mode)),
                    "modified": attr.st_mtime,
                }
            )
        entries.sort(key=lambda e: (e["type"] != "directory", e["name"]))
        return entries, resolved
    finally:
        sftp.close()


def _sync_upload_file(alias: str, local_path: str, remote_path: str) -> int:
    """Upload *local_path* to *remote_path*.  Returns the number of bytes sent."""
    client = _get_or_open(alias)
    sftp = client.open_sftp()
    try:
        # Remote path is always POSIX (Linux/Unix target)
        parent = str(PurePosixPath(remote_path).parent)
        if parent and parent != ".":
            try:
                _sftp_makedirs(sftp, parent)
            except Exception:
                pass
        sftp.put(local_path, remote_path)
        return os.path.getsize(local_path)
    finally:
        sftp.close()


def _sync_download_file(alias: str, remote_path: str, local_path: str) -> int:
    """Download *remote_path* to *local_path*.  Returns the number of bytes received."""
    client = _get_or_open(alias)
    sftp = client.open_sftp()
    try:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        sftp.get(remote_path, local_path)
        return os.path.getsize(local_path)
    finally:
        sftp.close()


def _sync_test_connection(alias: str) -> tuple[bool, str]:
    """Try to open (or reuse) a connection. Returns (success, message)."""
    try:
        client = _get_or_open(alias)
        # Execute a trivial no-op to verify the session works
        _, stdout, _ = client.exec_command("echo ok", timeout=10)
        stdout.read()
        host = get_host(alias)
        return True, f"Connected to {host.hostname}:{host.port} as {host.username}"
    except Exception as exc:
        return False, _enrich_error(alias, exc)


# ---------------------------------------------------------------------------
# SFTP helper: recursive mkdir
# ---------------------------------------------------------------------------


def _sftp_makedirs(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    """Recursively create *remote_dir* on the SFTP server (like mkdir -p).

    Always uses PurePosixPath so that Windows-local path separators never
    bleed into the remote (Linux/Unix) directory names.
    """
    parts = PurePosixPath(remote_dir).parts
    current = ""
    for part in parts:
        current = str(PurePosixPath(current) / part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)



# ---------------------------------------------------------------------------
# Public async API (used by server.py)
# ---------------------------------------------------------------------------


async def run_command(
    alias: str,
    command: str,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    sudo_password: str | None = None,
) -> tuple[int, str, str]:
    """
    Run *command* on the SSH host named *alias*.

    Returns (exit_code, stdout, stderr).
    Raises KeyError if the alias is unknown, paramiko.SSHException on failure.

    cwd:          When set, the command runs as ``cd <cwd> && <command>``.
    sudo_password: When set, wraps the command with ``echo pw | sudo -S sh -c …``.
    """
    return await asyncio.to_thread(
        _sync_run_command, alias, command, timeout, env, cwd, sudo_password
    )


async def read_file(alias: str, remote_path: str) -> bytes:
    """Return the raw bytes of *remote_path* from the SSH host *alias*."""
    return await asyncio.to_thread(_sync_read_file, alias, remote_path)


async def write_file(alias: str, remote_path: str, content: bytes) -> None:
    """Write *content* to *remote_path* on the SSH host *alias*."""
    await asyncio.to_thread(_sync_write_file, alias, remote_path, content)


async def list_directory(alias: str, remote_path: str) -> tuple[list, str]:
    """List the contents of *remote_path* on the SSH host *alias*.

    Returns (entries, resolved_path).  resolved_path has ~ expanded to the
    actual home directory so callers can display the canonical path.
    """
    return await asyncio.to_thread(_sync_list_directory, alias, remote_path)


async def upload_file(alias: str, local_path: str, remote_path: str) -> int:
    """Upload a local file to the SSH host.  Returns bytes transferred."""
    return await asyncio.to_thread(_sync_upload_file, alias, local_path, remote_path)


async def download_file(alias: str, remote_path: str, local_path: str) -> int:
    """Download a remote file to a local path.  Returns bytes received."""
    return await asyncio.to_thread(_sync_download_file, alias, remote_path, local_path)


async def test_connection(alias: str) -> tuple[bool, str]:
    """Check whether a connection to *alias* can be established."""
    return await asyncio.to_thread(_sync_test_connection, alias)


# ---------------------------------------------------------------------------
# Error enrichment
# ---------------------------------------------------------------------------


def _enrich_error(alias: str, exc: Exception) -> str:
    """
    Return a human-readable error string.

    On Windows, when the host uses agent auth and the OpenSSH Authentication
    Agent service is not running, appends actionable fix instructions.
    """
    base = f"Connection failed: {exc}"

    try:
        import platform_utils as pu
        host = get_host(alias)
        if isinstance(host.auth, AgentAuth):
            status = pu.get_agent_status()
            if status not in (
                pu.AgentStatus.NOT_WINDOWS,
                pu.AgentStatus.RUNNING,
                pu.AgentStatus.UNKNOWN,
            ):
                hint = pu.agent_status_message(status)
                return f"{base}\n\n{hint}"
    except Exception:
        pass  # never let diagnostic code obscure the primary error

    return base

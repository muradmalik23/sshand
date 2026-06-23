"""
Unit tests for the pure-logic pieces of ssh_client.py.

Anything that actually opens a TCP/SSH connection is out of scope here (that's
what the MCP Inspector pass against a live host is for — see CONTRIBUTING.md).
These tests cover the path-handling, mkdir, command-wrapping, and
auth-to-connect-kwargs logic using fakes/mocks instead of a real paramiko
connection.
"""

from __future__ import annotations

import pytest

import ssh_client
from host_config import AgentAuth, HostEntry, KeyAuth, PasswordAuth


# ---------------------------------------------------------------------------
# _expand_remote_path
# ---------------------------------------------------------------------------


class FakeSFTP:
    """Minimal stand-in for paramiko.SFTPClient used across these tests."""

    def __init__(self, home="/home/ubuntu", existing_dirs=None):
        self.home = home
        self.existing_dirs = set(existing_dirs or [])
        self.mkdir_calls: list[str] = []

    def normalize(self, path):
        assert path == "."
        return self.home

    def stat(self, path):
        if path not in self.existing_dirs:
            raise FileNotFoundError(path)
        return object()

    def mkdir(self, path):
        self.mkdir_calls.append(path)
        self.existing_dirs.add(path)


def test_expand_remote_path_bare_tilde():
    sftp = FakeSFTP(home="/home/ubuntu")
    assert ssh_client._expand_remote_path(sftp, "~") == "/home/ubuntu"


def test_expand_remote_path_tilde_slash():
    sftp = FakeSFTP(home="/home/ubuntu")
    assert ssh_client._expand_remote_path(sftp, "~/projects/app") == "/home/ubuntu/projects/app"


def test_expand_remote_path_absolute_unchanged():
    sftp = FakeSFTP(home="/home/ubuntu")
    assert ssh_client._expand_remote_path(sftp, "/etc/nginx/nginx.conf") == "/etc/nginx/nginx.conf"


def test_expand_remote_path_relative_unchanged():
    sftp = FakeSFTP(home="/home/ubuntu")
    assert ssh_client._expand_remote_path(sftp, "relative/path") == "relative/path"


# ---------------------------------------------------------------------------
# _sftp_makedirs
# ---------------------------------------------------------------------------


def test_sftp_makedirs_creates_missing_chain():
    sftp = FakeSFTP(existing_dirs={""})
    ssh_client._sftp_makedirs(sftp, "a/b/c")
    assert sftp.mkdir_calls == ["a", "a/b", "a/b/c"]


def test_sftp_makedirs_skips_existing_prefix():
    sftp = FakeSFTP(existing_dirs={"", "a", "a/b"})
    ssh_client._sftp_makedirs(sftp, "a/b/c/d")
    assert sftp.mkdir_calls == ["a/b/c", "a/b/c/d"]


def test_sftp_makedirs_noop_when_fully_exists():
    sftp = FakeSFTP(existing_dirs={"", "a", "a/b", "a/b/c"})
    ssh_client._sftp_makedirs(sftp, "a/b/c")
    assert sftp.mkdir_calls == []


# ---------------------------------------------------------------------------
# _open_connection auth logic
# ---------------------------------------------------------------------------


class FakeSSHClient:
    """Mock paramiko.SSHClient that just records connect() args."""

    def __init__(self):
        self.connect_kwargs = None

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs


@pytest.fixture
def temp_key_file(tmp_path):
    """Create a temporary SSH key file for testing."""
    key_file = tmp_path / ".ssh"
    key_file.mkdir()
    key_path = key_file / "id_rsa"
    key_path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n...")
    return str(key_path)


def test_open_connection_password_auth(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4", username="ubuntu", auth=PasswordAuth(password="secret")
    )
    client = ssh_client._open_connection(host)

    kwargs = client.connect_kwargs
    assert kwargs["password"] == "secret"
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False
    assert "key_filename" not in kwargs


def test_open_connection_key_auth_with_passphrase(monkeypatch, temp_key_file):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4",
        username="deploy",
        auth=KeyAuth(key_path=temp_key_file, passphrase="hunter2"),
    )
    client = ssh_client._open_connection(host)

    kwargs = client.connect_kwargs
    assert kwargs["key_filename"] == temp_key_file
    assert kwargs["passphrase"] == "hunter2"
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False
    assert "password" not in kwargs


def test_open_connection_key_auth_without_passphrase_omits_it(monkeypatch, temp_key_file):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4", username="deploy", auth=KeyAuth(key_path=temp_key_file)
    )
    client = ssh_client._open_connection(host)
    assert "passphrase" not in client.connect_kwargs


def test_open_connection_agent_auth(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4", username="ubuntu", auth=AgentAuth()
    )
    client = ssh_client._open_connection(host)

    kwargs = client.connect_kwargs
    assert kwargs["allow_agent"] is True
    assert kwargs["look_for_keys"] is False
    assert "password" not in kwargs
    assert "key_filename" not in kwargs


# ---------------------------------------------------------------------------
# _sync_run_command
# ---------------------------------------------------------------------------


class FakeChannel:
    """Fake SSH channel."""
    def recv_exit_status(self):
        return 0


class FakeFH:
    """Fake file handle returned by exec_command."""
    def __init__(self):
        self.channel = FakeChannel()

    def read(self):
        return b""


class FakeClientWithExec:
    """Fake client with configurable exec_command."""
    def __init__(self, exec_impl):
        self.exec_impl = exec_impl

    def exec_command(self, cmd, **kwargs):
        return self.exec_impl(cmd, **kwargs)


def test_sync_run_command_plain(monkeypatch):
    def fake_exec_command(cmd, **kwargs):
        assert cmd == "ls -la"
        assert kwargs.get("timeout") == 10
        return None, FakeFH(), FakeFH()

    client = FakeClientWithExec(fake_exec_command)
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda _: client)
    exit_code, stdout, stderr = ssh_client._sync_run_command("alias", "ls -la", timeout=10, env=None)
    assert exit_code == 0


def test_sync_run_command_with_cwd(monkeypatch):
    def fake_exec_command(cmd, **kwargs):
        assert cmd.startswith("cd ")
        assert "ls" in cmd
        return None, FakeFH(), FakeFH()

    client = FakeClientWithExec(fake_exec_command)
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda _: client)
    ssh_client._sync_run_command("alias", "ls", timeout=10, env=None, cwd="/tmp")


def test_sync_run_command_with_sudo_hides_password_in_command_string(monkeypatch):
    captured_cmd = None

    def fake_exec_command(cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = cmd
        return None, FakeFH(), FakeFH()

    client = FakeClientWithExec(fake_exec_command)
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda _: client)
    ssh_client._sync_run_command("alias", "ls", timeout=10, env=None, sudo_password="secret123")
    assert captured_cmd is not None
    assert "sudo" in captured_cmd


def test_sync_run_command_with_cwd_and_sudo_combines_both(monkeypatch):
    captured_cmd = None

    def fake_exec_command(cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = cmd
        return None, FakeFH(), FakeFH()

    client = FakeClientWithExec(fake_exec_command)
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda _: client)
    ssh_client._sync_run_command("alias", "ls", timeout=10, env=None, cwd="/tmp", sudo_password="secret")
    assert captured_cmd is not None
    assert "cd" in captured_cmd
    assert "sudo" in captured_cmd

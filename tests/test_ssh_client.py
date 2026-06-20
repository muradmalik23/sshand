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
    sftp = FakeSFTP(existing_dirs=set())
    ssh_client._sftp_makedirs(sftp, "a/b/c")
    assert sftp.mkdir_calls == ["a", "a/b", "a/b/c"]


def test_sftp_makedirs_skips_existing_prefix():
    sftp = FakeSFTP(existing_dirs={"a", "a/b"})
    ssh_client._sftp_makedirs(sftp, "a/b/c")
    assert sftp.mkdir_calls == ["a/b/c"]


def test_sftp_makedirs_noop_when_fully_exists():
    sftp = FakeSFTP(existing_dirs={"a", "a/b", "a/b/c"})
    ssh_client._sftp_makedirs(sftp, "a/b/c")
    assert sftp.mkdir_calls == []


# ---------------------------------------------------------------------------
# _open_connection — verify connect() kwargs per auth type (no real network)
# ---------------------------------------------------------------------------


class FakeSSHClient:
    """Stand-in for paramiko.SSHClient that records connect() kwargs."""

    instances: list["FakeSSHClient"] = []

    def __init__(self):
        self.connect_kwargs = None
        self.policy_set = False
        FakeSSHClient.instances.append(self)

    def set_missing_host_key_policy(self, policy):
        self.policy_set = True

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    FakeSSHClient.instances.clear()
    yield
    FakeSSHClient.instances.clear()


def test_open_connection_password_auth(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(hostname="1.2.3.4", port=2222, username="root", auth=PasswordAuth(password="pw"))
    client = ssh_client._open_connection(host)

    assert client.policy_set is True
    kwargs = client.connect_kwargs
    assert kwargs["hostname"] == "1.2.3.4"
    assert kwargs["port"] == 2222
    assert kwargs["username"] == "root"
    assert kwargs["password"] == "pw"
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False
    assert "key_filename" not in kwargs


def test_open_connection_key_auth_with_passphrase(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4",
        username="deploy",
        auth=KeyAuth(key_path="/home/deploy/.ssh/id_rsa", passphrase="hunter2"),
    )
    client = ssh_client._open_connection(host)

    kwargs = client.connect_kwargs
    assert kwargs["key_filename"] == "/home/deploy/.ssh/id_rsa"
    assert kwargs["passphrase"] == "hunter2"
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False
    assert "password" not in kwargs


def test_open_connection_key_auth_without_passphrase_omits_it(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(
        hostname="1.2.3.4", username="deploy", auth=KeyAuth(key_path="/home/deploy/.ssh/id_rsa")
    )
    client = ssh_client._open_connection(host)
    assert "passphrase" not in client.connect_kwargs


def test_open_connection_agent_auth(monkeypatch):
    monkeypatch.setattr(ssh_client.paramiko, "SSHClient", FakeSSHClient)
    host = HostEntry(hostname="1.2.3.4", username="ubuntu", auth=AgentAuth())
    client = ssh_client._open_connection(host)

    kwargs = client.connect_kwargs
    assert kwargs["allow_agent"] is True
    assert kwargs["look_for_keys"] is False
    assert "password" not in kwargs
    assert "key_filename" not in kwargs


# ---------------------------------------------------------------------------
# _sync_run_command — command wrapping for cwd / sudo (mocked client)
# ---------------------------------------------------------------------------


class FakeChannelFile:
    def __init__(self, text="", exit_status=0):
        self._text = text
        self.channel = type("C", (), {"recv_exit_status": lambda self_: exit_status})()

    def read(self):
        return self._text.encode("utf-8")


class FakeExecClient:
    def __init__(self):
        self.last_command = None

    def exec_command(self, command, timeout=None, environment=None):
        self.last_command = command
        return FakeChannelFile(), FakeChannelFile("out"), FakeChannelFile("err")


def test_sync_run_command_plain(monkeypatch):
    fake_client = FakeExecClient()
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda alias: fake_client)

    ssh_client._sync_run_command("box", "ls -la", timeout=10, env=None)
    assert fake_client.last_command == "ls -la"


def test_sync_run_command_with_cwd(monkeypatch):
    fake_client = FakeExecClient()
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda alias: fake_client)

    ssh_client._sync_run_command("box", "ls", timeout=10, env=None, cwd="/var/www")
    assert fake_client.last_command == "cd /var/www && ls"


def test_sync_run_command_with_sudo_hides_password_in_command_string(monkeypatch):
    fake_client = FakeExecClient()
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda alias: fake_client)

    ssh_client._sync_run_command(
        "box", "systemctl restart nginx", timeout=10, env=None, sudo_password="s3cr3t"
    )
    # The password is embedded so it can be piped to sudo -S, but the command
    # is built via shlex.quote so it can't break out of its quoting context.
    assert "sudo -S" in fake_client.last_command
    assert "s3cr3t" in fake_client.last_command
    assert "systemctl restart nginx" in fake_client.last_command


def test_sync_run_command_with_cwd_and_sudo_combines_both(monkeypatch):
    fake_client = FakeExecClient()
    monkeypatch.setattr(ssh_client, "_get_or_open", lambda alias: fake_client)

    ssh_client._sync_run_command(
        "box", "tail file.log", timeout=10, env=None, cwd="/var/log", sudo_password="pw"
    )
    cmd = fake_client.last_command
    assert "sudo -S" in cmd
    assert "cd /var/log" in cmd
    assert "tail file.log" in cmd

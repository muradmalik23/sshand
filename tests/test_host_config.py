"""
Unit tests for host_config.py.

These exercise the YAML inventory manager directly — no live SSH host needed.
Each test gets its own throwaway hosts file via the tmp_path fixture so tests
never touch the real hosts.yaml.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from host_config import (
    AgentAuth,
    HostEntry,
    KeyAuth,
    PasswordAuth,
    add_host,
    get_host,
    list_hosts,
    remove_host,
)


@pytest.fixture
def hosts_file(tmp_path):
    return tmp_path / "hosts.yaml"


def make_entry(**overrides):
    defaults = dict(
        hostname="10.0.0.5",
        username="ubuntu",
        auth=PasswordAuth(password="secret"),
    )
    defaults.update(overrides)
    return HostEntry(**defaults)


# ---------------------------------------------------------------------------
# list_hosts / add_host / get_host / remove_host round trip
# ---------------------------------------------------------------------------


def test_list_hosts_empty_when_file_missing(hosts_file):
    assert list_hosts(hosts_file=hosts_file) == {}


def test_add_then_list_then_get(hosts_file):
    entry = make_entry(description="staging box")
    add_host("staging", entry, hosts_file=hosts_file)

    listed = list_hosts(hosts_file=hosts_file)
    assert set(listed) == {"staging"}
    assert listed["staging"].hostname == "10.0.0.5"
    assert listed["staging"].description == "staging box"

    fetched = get_host("staging", hosts_file=hosts_file)
    assert fetched.username == "ubuntu"
    assert isinstance(fetched.auth, PasswordAuth)


def test_add_host_rejects_duplicate_alias_without_overwrite(hosts_file):
    add_host("box", make_entry(), hosts_file=hosts_file)
    with pytest.raises(ValueError):
        add_host("box", make_entry(hostname="10.0.0.9"), hosts_file=hosts_file)


def test_add_host_overwrite_true_replaces_entry(hosts_file):
    add_host("box", make_entry(hostname="10.0.0.5"), hosts_file=hosts_file)
    add_host(
        "box", make_entry(hostname="10.0.0.9"), overwrite=True, hosts_file=hosts_file
    )
    assert get_host("box", hosts_file=hosts_file).hostname == "10.0.0.9"


def test_get_host_missing_alias_raises_keyerror(hosts_file):
    with pytest.raises(KeyError):
        get_host("nope", hosts_file=hosts_file)


def test_remove_host_roundtrip(hosts_file):
    add_host("temp", make_entry(), hosts_file=hosts_file)
    remove_host("temp", hosts_file=hosts_file)
    assert list_hosts(hosts_file=hosts_file) == {}


def test_remove_host_missing_alias_raises_keyerror(hosts_file):
    with pytest.raises(KeyError):
        remove_host("ghost", hosts_file=hosts_file)


def test_multiple_hosts_independent(hosts_file):
    add_host("a", make_entry(hostname="1.1.1.1"), hosts_file=hosts_file)
    add_host("b", make_entry(hostname="2.2.2.2"), hosts_file=hosts_file)
    listed = list_hosts(hosts_file=hosts_file)
    assert set(listed) == {"a", "b"}
    remove_host("a", hosts_file=hosts_file)
    assert set(list_hosts(hosts_file=hosts_file)) == {"b"}


def test_malformed_entry_does_not_crash_list_hosts(hosts_file):
    # Write a host with a missing required field (no username) directly,
    # bypassing the Pydantic model the way a hand-edited YAML file could.
    import yaml

    hosts_file.write_text(
        yaml.dump({"hosts": {"broken": {"hostname": "1.2.3.4", "auth": {"type": "agent"}}}}),
        encoding="utf-8",
    )
    result = list_hosts(hosts_file=hosts_file)
    assert "broken" in result
    assert isinstance(result["broken"], Exception)


# ---------------------------------------------------------------------------
# HostEntry / auth model validation
# ---------------------------------------------------------------------------


def test_hostname_cannot_be_blank():
    with pytest.raises(ValidationError):
        make_entry(hostname="   ")


def test_port_out_of_range_rejected():
    with pytest.raises(ValidationError):
        make_entry(port=70000)


def test_unknown_field_rejected_due_to_extra_forbid():
    with pytest.raises(ValidationError):
        HostEntry(
            hostname="1.2.3.4",
            username="root",
            auth=AgentAuth(),
            not_a_real_field="oops",
        )


def test_key_auth_expands_user_home(tmp_path, monkeypatch):
    # Create a real key file to test path expansion
    home = tmp_path / "home"
    home.mkdir()
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir()
    key_file = ssh_dir / "id_rsa"
    key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n...")

    monkeypatch.setenv("HOME", str(home))
    auth = KeyAuth(key_path="~/.ssh/id_rsa")
    assert "~" not in auth.key_path
    assert auth.key_path.endswith(".ssh/id_rsa") or auth.key_path.endswith(".ssh\\id_rsa")


def test_password_auth_requires_password():
    with pytest.raises(ValidationError):
        PasswordAuth()


def test_agent_auth_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AgentAuth(password="should-not-be-allowed")


def test_key_auth_validates_key_file_exists(tmp_path):
    """KeyAuth should reject paths to non-existent key files."""
    nonexistent = tmp_path / "nonexistent_key"
    with pytest.raises(ValidationError) as exc_info:
        KeyAuth(key_path=str(nonexistent))
    assert "not found" in str(exc_info.value).lower()


def test_key_auth_accepts_existing_key_file(tmp_path):
    """KeyAuth should accept paths to existing key files."""
    key_file = tmp_path / "id_rsa"
    key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n...")
    auth = KeyAuth(key_path=str(key_file))
    assert auth.key_path == str(key_file)


def test_key_auth_expands_tilde_to_existing_file(tmp_path, monkeypatch):
    """KeyAuth should expand ~ in paths and validate the file exists."""
    home = tmp_path / "home"
    home.mkdir()
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir()
    key_file = ssh_dir / "id_rsa"
    key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n...")

    monkeypatch.setenv("HOME", str(home))
    auth = KeyAuth(key_path="~/.ssh/id_rsa")
    assert auth.key_path == str(key_file)
    assert "~" not in auth.key_path


def test_key_auth_missing_file_shows_helpful_error(tmp_path):
    """KeyAuth error message should mention key file location."""
    nonexistent = tmp_path / "missing_key"
    with pytest.raises(ValidationError) as exc_info:
        KeyAuth(key_path=str(nonexistent))
    error_msg = str(exc_info.value)
    assert "not found" in error_msg.lower()

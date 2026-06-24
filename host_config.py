#!/usr/bin/env python3
"""
host_config.py — SSH host inventory management.

Reads and writes a YAML file (hosts.yaml by default) that stores named SSH
targets with their connection and authentication details.  Three auth types
are supported:
  - key      : private-key file on disk
  - password : plaintext password (stored in the YAML – handle with care)
  - agent    : delegate to the running ssh-agent process
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Default location for the hosts inventory file
#
# This is the single source of truth for "where is hosts.yaml when nobody
# says otherwise". Every entry point (server.py, manage.py, setup_wizard.py)
# must resolve the default through this constant rather than re-deriving it
# themselves — a host added via one default and looked up via a different
# default is exactly how "saved fine, then not found" bugs happen.
#
# Deliberately NOT package-directory-relative (no more Path(__file__).parent).
# A pip/uvx install puts this file's code inside some site-packages or tool
# cache directory that differs per install method and per machine — a plain
# `pip install sshand`, a `uvx sshand` run, and a from-source editable install
# all land in different directories. If the default followed __file__, each
# of those would silently keep its own separate hosts.yaml, so a host added
# under one would be invisible to the others even though "it's the same
# package". Anchoring on the user's home directory instead gives every
# install method the same answer for "where's my inventory" by default.
# ---------------------------------------------------------------------------

DEFAULT_HOSTS_FILE = Path(
    os.environ.get("SSH_MCP_HOSTS_FILE", str(Path.home() / ".sshand" / "hosts.yaml"))
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class KeyAuth(BaseModel):
    """Authentication via a private-key file."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    type: Literal["key"] = "key"
    key_path: str = Field(
        ...,
        description=(
            "Absolute or ~-relative path to the private key file "
            "(e.g., '~/.ssh/id_rsa', '/home/user/.ssh/deploy_key')."
        ),
    )
    passphrase: str | None = Field(
        default=None,
        description="Optional passphrase to decrypt the private key.",
    )

    @field_validator("key_path")
    @classmethod
    def expand_path(cls, v: str) -> str:
        expanded = Path(v).expanduser()
        # Validate that the key file exists; give a helpful error on Windows if it doesn't.
        if not expanded.exists():
            # Build a helpful error message specific to the user's platform
            msg = f"SSH key file not found: {expanded}"
            if expanded.drive and expanded.drive[0].isalpha():  # Windows path
                msg += (
                    f"\n\nOn Windows, SSH keys are typically in "
                    f"{Path.home() / '.ssh'}.\n"
                    f"Check that the file exists and the path is correct."
                )
            raise ValueError(msg)
        return str(expanded)


class PasswordAuth(BaseModel):
    """Authentication via username + password."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    type: Literal["password"] = "password"
    password: str = Field(..., description="SSH password for the user.")


class AgentAuth(BaseModel):
    """Authentication via the local ssh-agent."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent"] = "agent"


AuthConfig = KeyAuth | PasswordAuth | AgentAuth


class HostEntry(BaseModel):
    """A single SSH host in the inventory."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    hostname: str = Field(
        ...,
        description="IP address or fully-qualified domain name of the host.",
    )
    port: int = Field(default=22, ge=1, le=65535, description="SSH port (default 22).")
    username: str = Field(
        ...,
        description="SSH username (e.g., 'ubuntu', 'ec2-user', 'root').",
    )
    auth: AuthConfig = Field(
        ...,
        description="Authentication config.  Use type='key', 'password', or 'agent'.",
    )
    description: str | None = Field(
        default=None, description="Human-readable note about this host."
    )

    @field_validator("hostname")
    @classmethod
    def hostname_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("hostname must not be empty")
        return v


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------


def _load_raw(hosts_file: Path) -> dict[str, Any]:
    """Return the raw YAML dict, creating an empty one if the file is absent."""
    if not hosts_file.exists():
        return {"hosts": {}}
    with hosts_file.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "hosts" not in data:
        data["hosts"] = {}
    return data


def _save_raw(data: dict[str, Any], hosts_file: Path) -> None:
    hosts_file.parent.mkdir(parents=True, exist_ok=True)
    with hosts_file.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=True)


def list_hosts(hosts_file: Path = DEFAULT_HOSTS_FILE) -> dict[str, HostEntry]:
    """
    Return all hosts from the inventory as a dict of {alias: HostEntry}.

    Returns an empty dict if the inventory file does not exist yet.
    """
    data = _load_raw(hosts_file)
    result: dict[str, HostEntry] = {}
    for alias, raw in data["hosts"].items():
        try:
            result[alias] = HostEntry.model_validate(raw)
        except Exception as exc:
            # Skip malformed entries but don't crash
            result[alias] = exc  # type: ignore[assignment]
    return result


def get_host(alias: str, hosts_file: Path = DEFAULT_HOSTS_FILE) -> HostEntry:
    """
    Retrieve a single host by alias.

    Raises KeyError if not found, ValueError if the entry is malformed.
    """
    data = _load_raw(hosts_file)
    if alias not in data["hosts"]:
        raise KeyError(f"Host '{alias}' not found in inventory.")
    return HostEntry.model_validate(data["hosts"][alias])


def add_host(
    alias: str,
    entry: HostEntry,
    overwrite: bool = False,
    hosts_file: Path = DEFAULT_HOSTS_FILE,
) -> None:
    """
    Add (or replace) a host in the inventory.

    Raises ValueError if the alias already exists and overwrite=False.
    """
    data = _load_raw(hosts_file)
    if alias in data["hosts"] and not overwrite:
        raise ValueError(
            f"Host '{alias}' already exists.  Pass overwrite=True to replace it."
        )
    data["hosts"][alias] = entry.model_dump()
    _save_raw(data, hosts_file)


def remove_host(alias: str, hosts_file: Path = DEFAULT_HOSTS_FILE) -> None:
    """
    Remove a host from the inventory.

    Raises KeyError if the alias does not exist.
    """
    data = _load_raw(hosts_file)
    if alias not in data["hosts"]:
        raise KeyError(f"Host '{alias}' not found in inventory.")
    del data["hosts"][alias]
    _save_raw(data, hosts_file)


def ensure_hosts_file(hosts_file: Path = DEFAULT_HOSTS_FILE) -> Path:
    """
    Create an empty inventory file (and its parent directory) if one doesn't
    exist yet at `hosts_file`. Safe to call repeatedly.

    Without this, `~/.sshand/hosts.yaml` only appears the first time a host
    is added — confusing if you go looking for it right after install/setup
    and find nothing there yet. Call this once from each real entry point
    (server.py's main(), manage.py's run()) rather than at import time, so
    importing host_config for tests never touches the real filesystem.
    """
    if not hosts_file.exists():
        _save_raw({"hosts": {}}, hosts_file)
    return hosts_file

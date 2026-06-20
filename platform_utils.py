#!/usr/bin/env python3
"""
platform_utils.py -- Windows-specific SSH agent helpers.

On macOS/Linux the ssh-agent is managed by the OS or the user's shell
profile and just works.  On Windows it is an optional service that ships
with the built-in OpenSSH client but is disabled by default.

This module lets setup_wizard.py and ssh_client.py:
  - Detect whether the current platform is Windows
  - Check whether the OpenSSH Authentication Agent service is running
  - Attempt to enable + start it (requires Administrator privileges)
  - Surface clear, actionable instructions when it cannot be auto-fixed
"""

from __future__ import annotations

import subprocess
import sys
from enum import Enum, auto
from typing import Tuple


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS: bool = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Service status
# ---------------------------------------------------------------------------

class AgentStatus(Enum):
    NOT_WINDOWS   = auto()   # macOS / Linux -- no check needed
    RUNNING       = auto()   # service is active and ready
    STOPPED       = auto()   # service exists but is not running
    DISABLED      = auto()   # service start type is set to Disabled
    NOT_INSTALLED = auto()   # OpenSSH not installed at all
    UNKNOWN       = auto()   # could not determine (non-admin, etc.)


# PowerShell snippet shown to users who need to fix the service manually
WINDOWS_FIX_INSTRUCTIONS = """\
  Run the following in PowerShell as Administrator:

    Set-Service ssh-agent -StartupType Automatic
    Start-Service ssh-agent
    ssh-add               # optionally load your key into the agent

  To open an elevated PowerShell:
    Press Win+X  ->  "Windows PowerShell (Admin)"  or  "Terminal (Admin)"
"""


def get_agent_status() -> AgentStatus:
    """
    Query the Windows OpenSSH Authentication Agent service state.

    Returns AgentStatus.NOT_WINDOWS on non-Windows platforms so callers
    can use this unconditionally without a platform guard.
    """
    if not IS_WINDOWS:
        return AgentStatus.NOT_WINDOWS

    try:
        result = subprocess.run(
            ["sc", "query", "ssh-agent"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.upper()

        if result.returncode != 0:
            # Service not found
            if "DOES NOT EXIST" in output or "1060" in result.stdout:
                return AgentStatus.NOT_INSTALLED
            return AgentStatus.UNKNOWN

        if "RUNNING" in output:
            return AgentStatus.RUNNING

        # Check start type for DISABLED
        config_result = subprocess.run(
            ["sc", "qc", "ssh-agent"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "DISABLED" in config_result.stdout.upper():
            return AgentStatus.DISABLED

        return AgentStatus.STOPPED

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return AgentStatus.UNKNOWN


def is_windows_admin() -> bool:
    """Return True if the current process has Administrator privileges on Windows."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def start_agent_service() -> Tuple[bool, str]:
    """
    Attempt to set the ssh-agent service to Automatic and start it.

    Must be called with Administrator privileges.  Returns (success, message).
    """
    if not IS_WINDOWS:
        return False, "Not running on Windows."

    try:
        subprocess.run(
            ["sc", "config", "ssh-agent", "start=auto"],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["net", "start", "ssh-agent"],
            check=True, capture_output=True, timeout=10,
        )
        # Verify it actually started
        if get_agent_status() == AgentStatus.RUNNING:
            return True, "OpenSSH Authentication Agent service started successfully."
        return False, "Service start command ran but the service is not RUNNING."
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        return False, f"sc/net command failed: {stderr.strip() or exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def agent_status_message(status: AgentStatus) -> str:
    """
    Return a human-readable, actionable description of the given AgentStatus.
    Suitable for printing in the wizard or as an MCP error message.
    """
    if status == AgentStatus.NOT_WINDOWS:
        return ""   # nothing to report on mac/linux

    if status == AgentStatus.RUNNING:
        return "OpenSSH Authentication Agent is running. Agent auth will work."

    if status == AgentStatus.STOPPED:
        return (
            "OpenSSH Authentication Agent service exists but is not running.\n"
            + WINDOWS_FIX_INSTRUCTIONS
        )

    if status == AgentStatus.DISABLED:
        return (
            "OpenSSH Authentication Agent service is disabled.\n"
            + WINDOWS_FIX_INSTRUCTIONS
        )

    if status == AgentStatus.NOT_INSTALLED:
        return (
            "OpenSSH does not appear to be installed on this Windows machine.\n\n"
            "  Install it via Settings -> Apps -> Optional Features -> OpenSSH Client\n"
            "  or in PowerShell (Admin):\n\n"
            "    Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0\n\n"
            "  Then run:\n"
            "    Set-Service ssh-agent -StartupType Automatic\n"
            "    Start-Service ssh-agent\n"
        )

    # UNKNOWN
    return (
        "Could not determine the state of the OpenSSH Authentication Agent service.\n"
        + WINDOWS_FIX_INSTRUCTIONS
    )

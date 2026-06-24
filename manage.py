#!/usr/bin/env python3
"""
manage.py — Interactive terminal UI for SSHand.

A clean, uncluttered interface built on `rich` (output) and `questionary`
(prompts), with a single warm yellow→amber accent palette.

Run via:
    sshand manage        (host manager menu)
    python manage.py     (host manager menu)
    python manage.py setup  (first-run setup wizard)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    import questionary
    from questionary import Choice, Style
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich import box
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    sys.stderr.write(
        f"\nThe SSHand TUI needs 'rich' and 'questionary' (missing: "
        f"{getattr(exc, 'name', '?')}).\n"
        f"Install the project deps:  pip install -e .\n\n"
    )
    sys.exit(1)


console = Console()

# ─── Palette ─────────────────────────────────────────────────────────────────
# One warm yellow→amber gradient, plus a single accent and two neutral roles.

_GRAD = ["#FFE08A", "#FFC93C", "#F5A623", "#E0820C"]  # light yellow → deep amber
ACCENT = "#F5A623"   # primary amber — prompts, rules, table headers
MUTED = "#8A8A8A"    # secondary grey — hints, descriptions
OK = "#C9A227"       # success, kept within the warm family
ERR = "#C45B4C"      # errors — the one deliberately different hue

# Big block wordmark (ANSI Shadow). Pure box-drawing chars, no brackets.
_WORDMARK = [
    "███████╗███████╗██╗  ██╗ █████╗ ███╗   ██╗██████╗ ",
    "██╔════╝██╔════╝██║  ██║██╔══██╗████╗  ██║██╔══██╗",
    "███████╗███████╗███████║███████║██╔██╗ ██║██║  ██║",
    "╚════██║╚════██║██╔══██║██╔══██║██║╚██╗██║██║  ██║",
    "███████║███████║██║  ██║██║  ██║██║ ╚████║██████╔╝",
    "╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝ ",
]


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _grad_color_at(f: float) -> str:
    """Hex colour at fraction f (0..1) along the gradient."""
    stops = [_hex(c) for c in _GRAD]
    seg = max(0.0, min(1.0, f)) * (len(stops) - 1)
    lo = min(int(seg), len(stops) - 2)
    t = seg - lo
    r = round(stops[lo][0] + (stops[lo + 1][0] - stops[lo][0]) * t)
    g = round(stops[lo][1] + (stops[lo + 1][1] - stops[lo][1]) * t)
    b = round(stops[lo][2] + (stops[lo + 1][2] - stops[lo][2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient(text: str, bold: bool = True) -> Text:
    """Spread the gradient horizontally across the characters of `text`."""
    out = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        out.append(ch, style=("bold " if bold else "") + _grad_color_at(i / n))
    return out


# Questionary theme — every interactive element uses the accent, nothing else.
_QSTYLE = Style(
    [
        ("qmark", f"fg:{ACCENT} bold"),
        ("question", "bold"),
        ("answer", f"fg:{ACCENT} bold"),
        ("pointer", f"fg:{ACCENT} bold"),
        ("highlighted", f"fg:{ACCENT} bold"),
        ("selected", f"fg:{ACCENT}"),
        ("instruction", f"fg:{MUTED}"),
        ("text", ""),
        ("disabled", f"fg:{MUTED} italic"),
    ]
)


# ─── Small helpers ───────────────────────────────────────────────────────────


def _hosts_file() -> Path:
    # Must resolve the same way host_config.py's own default does (and thus
    # the same way ssh_client.py's get_host() calls resolve it internally).
    # A different fallback here would mean "Add a host" and "Test a host"
    # silently talk to two different hosts.yaml files.
    import host_config as hc

    return hc.DEFAULT_HOSTS_FILE


def _abort() -> None:
    console.print(f"\n[{MUTED}]Aborted.[/]")
    sys.exit(0)


def _banner() -> None:
    """Grand gradient wordmark (vertical gradient across the block letters)."""
    console.print()
    n = len(_WORDMARK) - 1
    for i, line in enumerate(_WORDMARK):
        console.print("  " + line, style="bold " + _grad_color_at(i / n),
                      markup=False, highlight=False)
    console.print(f"  [{MUTED}]give your AI agent SSH access[/]")
    console.print()


def _rule(label: str) -> None:
    console.rule(f"[{ACCENT}]{label}[/]", style=ACCENT, characters="─")


def _ok(msg: str) -> None:
    console.print(f"  [{OK}]✓[/] {msg}")


def _err(msg: str) -> None:
    console.print(f"  [{ERR}]✗[/] {msg}")


def _pause() -> None:
    """Let the user read output before the screen is cleared/redrawn."""
    try:
        questionary.press_any_key_to_continue(
            "  Press any key to continue…", style=_QSTYLE
        ).ask()
    except Exception:
        try:
            input("  Press Enter to continue… ")
        except (EOFError, KeyboardInterrupt):
            pass


def _status_line(ok: bool, alias: str, msg: str) -> str:
    icon = f"[{OK}]✓[/]" if ok else f"[{ERR}]✗[/]"
    first = msg.splitlines()[0][:70] if msg else ""
    return f"  {icon} [bold]{alias}[/] — {first}"


def _ask_text(message: str, default: str = "", required: bool = False) -> str:
    validate = (lambda v: True if v.strip() else "This field is required.") if required else None
    ans = questionary.text(message, default=default, validate=validate, style=_QSTYLE).ask()
    if ans is None:
        _abort()
    return ans.strip()


def _ask_int(message: str, default: int, lo: int = 1, hi: int = 65535) -> int:
    def _v(v: str):
        v = v.strip()
        if not v.isdigit():
            return "Enter a whole number."
        if not (lo <= int(v) <= hi):
            return f"Enter a number between {lo} and {hi}."
        return True

    ans = questionary.text(message, default=str(default), validate=_v, style=_QSTYLE).ask()
    if ans is None:
        _abort()
    return int(ans.strip())


# ─── Connection test ─────────────────────────────────────────────────────────


def _test_connection_sync(alias: str) -> tuple[bool, str]:
    import asyncio

    try:
        import ssh_client as sc

        return asyncio.run(sc.test_connection(alias))
    except Exception as exc:  # pragma: no cover - network dependent
        return False, str(exc)


def _test_host_flow(alias: str) -> tuple[bool, str]:
    with console.status(f"[{ACCENT}]Connecting to {alias}…[/]", spinner="dots"):
        ok, msg = _test_connection_sync(alias)
    if ok:
        _ok(msg)
    else:
        _err(msg)
        console.print(
            f"    [{MUTED}]Check hostname/port/username, key permissions (600), "
            f"and that the port is reachable.[/]"
        )
    return ok, msg


# ─── Host table ──────────────────────────────────────────────────────────────


def _render_hosts_table(hosts: dict) -> None:
    if not hosts:
        console.print(f"  [{MUTED}]No hosts yet. Choose “Add a host” to create one.[/]")
        return

    table = Table(box=box.SIMPLE, header_style=f"{ACCENT} bold", pad_edge=False, expand=False)
    table.add_column("Alias", style="bold")
    table.add_column("Address")
    table.add_column("User")
    table.add_column("Auth", style=MUTED)
    table.add_column("Description", style=MUTED)

    for alias, entry in sorted(hosts.items()):
        if isinstance(entry, Exception):
            detail = str(entry).splitlines()[0][:60]
            table.add_row(alias, f"[{ERR}]invalid[/]", "—", "—", f"[{ERR}]{detail}[/]")
            continue
        table.add_row(
            alias,
            f"{entry.hostname}:{entry.port}",
            entry.username,
            entry.auth.type,
            entry.description or "",
        )
    console.print(table)


# ─── Auth + add-host flow ────────────────────────────────────────────────────


def _prompt_auth():
    import host_config as hc

    method = questionary.select(
        "Authentication method",
        choices=[
            Choice("SSH key file   (recommended)", value="key"),
            Choice("Password       (avoid on internet-facing hosts)", value="password"),
            Choice("SSH agent      (forward from local ssh-agent)", value="agent"),
        ],
        style=_QSTYLE,
    ).ask()
    if method is None:
        _abort()

    if method == "key":
        key_path = _ask_text("Private key path", default="~/.ssh/id_rsa", required=True)
        passphrase = questionary.password(
            "Key passphrase (blank if none)", style=_QSTYLE
        ).ask()
        if passphrase is None:
            _abort()
        return hc.KeyAuth(type="key", key_path=key_path, passphrase=passphrase or None)

    if method == "password":
        pw = ""
        while not pw:
            pw = questionary.password("SSH password", style=_QSTYLE).ask()
            if pw is None:
                _abort()
            if not pw:
                console.print(f"  [{ERR}]Password cannot be empty.[/]")
        return hc.PasswordAuth(type="password", password=pw)

    # Best-effort: on Windows with agent auth, offer to start the
    # OpenSSH Authentication Agent service (no-op elsewhere).
    try:
        import setup_wizard as sw
        sw._check_windows_agent()
    except Exception:
        pass
    return hc.AgentAuth(type="agent")


def _add_host_flow(hosts_file: Path) -> Optional[str]:
    import host_config as hc

    existing = hc.list_hosts(hosts_file)

    alias = _ask_text("Alias  (short nickname, e.g. 'webserver')", required=True)
    hostname = _ask_text("Hostname or IP address", required=True)
    port = _ask_int("SSH port", 22)
    username = _ask_text("Username", default="ubuntu", required=True)

    try:
        auth = _prompt_auth()
    except Exception as exc:
        _err(str(exc))
        return None

    description = _ask_text("Description (optional)")

    try:
        entry = hc.HostEntry(
            hostname=hostname, port=port, username=username,
            auth=auth, description=description or None,
        )
    except Exception as exc:
        _err(f"Could not build host entry: {exc}")
        return None

    overwrite = False
    if alias in existing:
        overwrite = questionary.confirm(
            f"A host named '{alias}' already exists. Overwrite it?",
            default=False, style=_QSTYLE,
        ).ask()
        if not overwrite:
            console.print(f"  [{MUTED}]Kept the existing entry.[/]")
            return None

    try:
        hc.add_host(alias, entry, overwrite=overwrite, hosts_file=hosts_file)
    except Exception as exc:
        _err(str(exc))
        return None

    _ok(f"Saved [bold]{alias}[/] to [{MUTED}]{hosts_file}[/]")
    return alias


# ─── Client config snippets ──────────────────────────────────────────────────


def _snippet_hermes() -> str:
    import setup_wizard as sw
    return f"""\
  Hermes Agent reads ~/.hermes/config.yaml under the mcp_servers key.

  Add (uvx — zero-venv):

    mcp_servers:
      ssh:
        command: "uvx"
        args: ["sshand"]

  Installed from source instead? Use:
        command: "python"
        args: ["{sw._server_path()}"]

  No env var needed either way — hosts are stored at {sw._hosts_note()}.

  Then start or reload Hermes:
    hermes chat        # fresh start
    /reload-mcp        # inside a running session
"""


def _snippet_openclaw() -> str:
    import setup_wizard as sw
    return f"""\
  OpenClaw connects through the MCPorter CLI. Install it first:

    npm install -g mcporter

  Register SSHand (uvx — zero-venv):

    mcporter config add ssh --command uvx --args sshand

  Installed from source instead?

    mcporter config add ssh --command python --args {sw._server_path()}

  No env var needed either way — hosts are stored at {sw._hosts_note()}.

  Confirm MCPorter sees it:
    mcporter list ssh --schema
"""


def _show_client_snippets() -> None:
    import setup_wizard as sw
    import host_config as hc

    # The snippet builders embed ANSI colour codes and literal [ ] (JSON
    # arrays). Force their colour off and print without rich markup so nothing
    # is mis-parsed — we apply our own muted style instead.
    sw._NO_COLOR = True

    snippet_map = {
        "Claude Desktop": sw._snippet_claude_desktop,
        "Cursor": sw._snippet_cursor,
        "VS Code (GitHub Copilot Chat)": sw._snippet_vscode,
        "OpenAI (Agents SDK / ChatGPT Desktop)": sw._snippet_openai,
        "Hermes Agent": _snippet_hermes,
        "OpenClaw (via MCPorter)": _snippet_openclaw,
        "Other (HTTP server)": sw._snippet_http,
    }

    # Show which hosts the agent will be able to reach.
    hosts = hc.list_hosts(_hosts_file())
    if hosts:
        names = ", ".join(sorted(k for k, v in hosts.items() if not isinstance(v, Exception)))
        console.print(f"  [{MUTED}]Hosts this agent will reach:[/] [bold]{names}[/]")
    else:
        console.print(f"  [{MUTED}]No hosts configured yet — add one first.[/]")
    console.print()

    # Single-select (arrow + enter), consistent with the rest of the menu, so
    # there's no space-to-toggle confusion. "All" prints every snippet.
    choice = questionary.select(
        "Show config for which client?",
        choices=[
            *snippet_map.keys(),
            Choice("All of them", value="__all__"),
            Choice("← back", value=None),
        ],
        style=_QSTYLE,
    ).ask()
    if choice is None:
        return

    names = list(snippet_map) if choice == "__all__" else [choice]
    for name in names:
        console.print()
        console.print(f"  [{ACCENT} bold]{name}[/]")
        console.print(
            snippet_map[name]().strip(),
            markup=False, highlight=False, style=MUTED,
        )


# ─── Setup wizard ────────────────────────────────────────────────────────────


def run_setup() -> None:
    hosts_file = _hosts_file()
    console.clear()
    _banner()
    console.print(f"  [{MUTED}]Add a host, test it, then print client config.[/]")
    console.print()

    _rule("1 / 3 · Add a host")
    alias = _add_host_flow(hosts_file)
    if not alias:
        console.print(f"\n[{MUTED}]No host added. Exiting.[/]")
        return

    console.print()
    _rule("2 / 3 · Test connection")
    ok, _ = _test_host_flow(alias)

    console.print()
    _rule("3 / 3 · Configure your AI client(s)")
    _show_client_snippets()

    console.print()
    console.print(_gradient("  All done — SSHand is ready."))
    if ok:
        console.print(
            f'  [{MUTED}]Try asking your agent:[/] '
            f'[{ACCENT}]"What can you tell me about {alias}?"[/]'
        )
    console.print()


# ─── Host manager ────────────────────────────────────────────────────────────


def _pick_host(hosts_file: Path, action: str) -> Optional[str]:
    import host_config as hc

    hosts = hc.list_hosts(hosts_file)
    if not hosts:
        console.print(f"  [{MUTED}]No hosts to choose from.[/]")
        return None
    return questionary.select(
        f"Select a host to {action}",
        choices=[*sorted(hosts.keys()), Choice("← back", value=None)],
        style=_QSTYLE,
    ).ask()


def run_manager() -> None:
    import host_config as hc

    hosts_file = _hosts_file()
    status: Optional[str] = None

    while True:
        # Clear + redraw each cycle so the screen updates in place rather than
        # scrolling. The last action's result is shown as a status line.
        console.clear()
        _banner()
        _render_hosts_table(hc.list_hosts(hosts_file))
        console.print()
        if status:
            console.print(status)
            console.print()
            status = None

        action = questionary.select(
            "What would you like to do?",
            choices=[
                Choice("List hosts", value="list"),
                Choice("Add a host", value="add"),
                Choice("Test a host", value="test"),
                Choice("Remove a host", value="remove"),
                Choice("Client config snippets", value="config"),
                Choice("Quit", value="quit"),
            ],
            style=_QSTYLE,
        ).ask()

        if action in (None, "quit"):
            console.print(f"\n[{MUTED}]Bye.[/]")
            return

        if action == "list":
            continue  # the table is already current at the top of the loop

        console.print()

        if action == "add":
            alias = _add_host_flow(hosts_file)
            if alias:
                if questionary.confirm(
                    f"Test the connection to '{alias}' now?", default=True, style=_QSTYLE
                ).ask():
                    ok, msg = _test_host_flow(alias)
                    _pause()
                    status = _status_line(ok, alias, msg)
                else:
                    status = f"  [{OK}]✓[/] Added [bold]{alias}[/]"

        elif action == "test":
            alias = _pick_host(hosts_file, "test")
            if alias:
                ok, msg = _test_host_flow(alias)
                _pause()
                status = _status_line(ok, alias, msg)

        elif action == "remove":
            alias = _pick_host(hosts_file, "remove")
            if alias and questionary.confirm(
                f"Permanently remove '{alias}'?", default=False, style=_QSTYLE
            ).ask():
                try:
                    hc.remove_host(alias, hosts_file=hosts_file)
                    status = f"  [{OK}]✓[/] Removed [bold]{alias}[/]"
                except Exception as exc:
                    status = f"  [{ERR}]✗[/] {exc}"

        elif action == "config":
            _show_client_snippets()
            _pause()


# ─── Entry point ─────────────────────────────────────────────────────────────


def run(mode: str = "menu") -> None:
    """mode: 'setup' for the wizard, 'menu' for the host manager."""
    import host_config as hc

    hc.ensure_hosts_file(_hosts_file())
    try:
        run_setup() if mode == "setup" else run_manager()
    except KeyboardInterrupt:
        _abort()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "menu"
    run("setup" if arg == "setup" else "menu")

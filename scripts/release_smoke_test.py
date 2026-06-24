#!/usr/bin/env python3
"""
release_smoke_test.py — verify SSHand behaves correctly when installed
*exactly* the way a real `pip install sshand` user would get it.

Why this exists: running from inside the repo with the dev venv active, or
`pip install -e .` (editable), both keep CWD == repo dir and keep sys.path
pointed at the source tree. Several past bugs ("works in my venv, not via
pip install") only showed up once the package was actually built into a
wheel and installed somewhere else, then run from somewhere else. This
script reproduces that scenario for real:

    1. Build a real sdist + wheel from the current source (python -m build).
    2. Create a brand-new, throwaway virtualenv — NOT the dev venv.
    3. pip install the wheel into it — NOT `pip install -e .`.
    4. cd to a neutral directory with no relation to this repo.
    5. Run the installed `sshand` console script and import the installed
       modules directly, confirming they behave correctly with zero
       leftover context from the source tree (no shared CWD, no shared
       sys.path, no shared venv).

Run this before every `twine upload`.

Usage:
    pip install build          # once, if you don't already have it
    python scripts/release_smoke_test.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kw) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kw)


def venv_bin(venv_dir: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def main() -> int:
    try:
        import build  # noqa: F401
    except ImportError:
        print("Missing the 'build' package. Run: pip install build")
        return 1

    with tempfile.TemporaryDirectory(prefix="sshand_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        venv_dir = tmp / "venv"
        neutral_dir = tmp / "neutral"
        neutral_dir.mkdir()

        print("== 1. Building sdist + wheel from current source ==")
        dist_dir = REPO_ROOT / "dist"
        # Don't pre-clean dist/ — rmtree-ing a stale dist folder has been
        # flaky on some setups (locked files, permissions). Instead, just
        # build and pick whichever wheel comes out newest.
        run([sys.executable, "-m", "build"], cwd=REPO_ROOT)
        wheels = sorted(dist_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)
        if not wheels:
            print("No wheel was produced — build failed.")
            return 1
        wheel = wheels[-1]
        print(f"Built: {wheel.name}")

        print("\n== 2. Creating a brand-new virtualenv (not the dev venv) ==")
        venv.create(venv_dir, with_pip=True)
        pip = venv_bin(venv_dir, "pip")
        python = venv_bin(venv_dir, "python")
        sshand_cmd = venv_bin(venv_dir, "sshand")

        print("\n== 3. Installing the wheel (not `pip install -e .`) ==")
        run([str(pip), "install", "--quiet", str(wheel)])

        print("\n== 4. Verifying from a neutral directory, unrelated to the repo ==")
        check_script = (
            "import host_config as hc\n"
            "print('host_config loaded from:', hc.__file__)\n"
            f"assert {str(REPO_ROOT)!r} not in hc.__file__, "
            "'installed module is reading from the repo, not the wheel!'\n"
            "print('DEFAULT_HOSTS_FILE:', hc.DEFAULT_HOSTS_FILE)\n"
            "hc.ensure_hosts_file()\n"
            "print('exists after ensure_hosts_file():', hc.DEFAULT_HOSTS_FILE.exists())\n"
            "assert hc.DEFAULT_HOSTS_FILE.exists()\n"
        )
        run([str(python), "-c", check_script], cwd=neutral_dir)

        print("\n== 5. Running the installed CLI (--help) ==")
        run([str(sshand_cmd), "--help"], cwd=neutral_dir)

        print(
            "\nAll checks passed. This build behaves correctly when installed "
            "and run exactly like a real `pip install sshand` user would "
            "experience it — fresh venv, real wheel, neutral working directory."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Provenance (spec R8.10, R12.2). Shared with the Jetson controller.

Collects the git SHA and dirty flag, the OS and architecture, and the Python,
numpy (and, if loaded, torch) versions. Used by ``ctl.py`` to build the
controller metadata that travels in HELLO_ACK (R8.10), and by run logging for
``meta.json`` (R12.2).

Standard library + numpy only, Python 3.12 features only (R1.3). ``git`` is
optional: it is found with :func:`shutil.which`, called with an argument list
(never ``shell=True``), and its absence yields ``unknown`` rather than a
traceback (R2.2).
"""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

# Resolve git from the directory of the running code, not the process cwd, so
# the recorded SHA is the checkout that is actually running (M3). git searches
# upward from here to the enclosing .git.
_PKG_DIR = str(Path(__file__).resolve().parent)


def _run_git(args: list[str], cwd: str | None) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        res = subprocess.run(
            [git, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def git_info(cwd: str | None = None) -> dict[str, Any]:
    """``{"sha": <hex> | "unknown", "dirty": <bool> | None}`` (R8.10).

    Defaults to the package directory so the SHA reflects the running code
    regardless of the process working directory (M3).
    """
    if cwd is None:
        cwd = _PKG_DIR
    out = _run_git(["rev-parse", "HEAD"], cwd)
    if out is None:
        return {"sha": "unknown", "dirty": None}
    status = _run_git(["status", "--porcelain"], cwd)
    dirty = None if status is None else bool(status.strip())
    return {"sha": out.strip(), "dirty": dirty}


def _torch_version() -> str | None:
    torch = sys.modules.get("torch")  # never import it; only report if loaded
    return getattr(torch, "__version__", None) if torch is not None else None


def controller_metadata(
    name: str,
    params: dict[str, Any] | None = None,
    *,
    fault: Any = None,
    stage_log: str | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """The controller metadata object for HELLO_ACK (R8.10).

    ``fault`` and ``stage_log`` are ``null`` until T22 / T23. The object is the
    same for every episode of a connection.
    """
    g = git_info(cwd)
    meta: dict[str, Any] = {
        "name": name,
        "params": dict(params or {}),
        "fault": fault,
        "stage_log": stage_log,
        "git_sha": g["sha"],
        "git_dirty": g["dirty"],
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": _torch_version(),
    }
    return meta


def package_version(name: str) -> str | None:
    """Installed version of a package, or None if it is not installed.

    Uses importlib.metadata, so it does not import the package (matplotlib need
    not be importable on the Jetson)."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def host_metadata(cwd: str | None = None) -> dict[str, Any]:
    """Simulation-host provenance for ``meta.json`` (R12.2)."""
    g = git_info(cwd)
    return {
        "git_sha": g["sha"],
        "git_dirty": g["dirty"],
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "matplotlib": package_version("matplotlib"),
    }

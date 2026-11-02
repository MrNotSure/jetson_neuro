"""Host adapter — the one place that knows about the operating system (R2.1).

Nothing else in the package branches on the OS. This module provides, for
macOS (the core build):

* keep-awake during realtime runs, via ``caffeinate -i -w <pid>``;
* the matplotlib viewer backend (``macosx``), honouring an ``MPLBACKEND``
  override;
* the per-user config directory;
* ``which`` and a small "run an external tool" helper (R2.2): tools are found
  with :func:`shutil.which`, called with argument lists (never ``shell=True``),
  and a missing tool gives a clear message rather than a traceback.

OS detection is injectable (``Host(os_name=...)``) so tests can simulate
another platform. The Linux paths arrive with T21 and the config directory is
used by T11; the structure here lets T21 add Linux by editing only this module.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Iterator, Sequence


class UnsupportedHostError(RuntimeError):
    """The current OS has no support in this build (clear, not a traceback)."""


class ToolNotFoundError(FileNotFoundError):
    """A required external tool was not found on PATH."""


def current_os() -> str:
    """Normalised OS name: ``macos``, ``linux`` or the lowercased system name."""
    return {"Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower()
    )


# Only macOS is implemented in the core build. T21 adds "linux".
_SUPPORTED: frozenset[str] = frozenset({"macos"})


class Host:
    def __init__(self, os_name: str | None = None) -> None:
        self.os_name = os_name or current_os()

    # -- support gate ------------------------------------------------------ #
    def check_supported(self) -> None:
        """Raise a clear error before a run starts on an unsupported OS."""
        if self.os_name in _SUPPORTED:
            return
        if self.os_name == "linux":
            raise UnsupportedHostError(
                "Linux support is an optional task (T21) and is not built yet. "
                "Use macOS for now."
            )
        raise UnsupportedHostError(
            f"unsupported OS {self.os_name!r}: only macOS is supported in the "
            "core build (Linux is optional, T21)."
        )

    # -- external tools ---------------------------------------------------- #
    @staticmethod
    def which(tool: str) -> str | None:
        return shutil.which(tool)

    def run_tool(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run an external tool by argument list (never ``shell=True``).

        Raises :class:`ToolNotFoundError` with a clear message if the tool is
        not on PATH.
        """
        if not args:
            raise ValueError("run_tool: empty argument list")
        exe = self.which(args[0])
        if exe is None:
            raise ToolNotFoundError(f"required tool {args[0]!r} not found on PATH")
        return subprocess.run(
            [exe, *args[1:]],
            timeout=timeout,
            check=check,
            capture_output=True,
            text=True,
        )

    # -- keep-awake -------------------------------------------------------- #
    @contextlib.contextmanager
    def keep_awake(self) -> Iterator[subprocess.Popen[bytes] | None]:
        """Keep the machine awake for the duration of a realtime run (R2.1).

        macOS: a ``caffeinate -i -w <pid>`` child tied to this process. If
        ``caffeinate`` is missing, warn and continue (R2.1). Ends with the
        context.
        """
        if self.os_name == "macos":
            exe = self.which("caffeinate")
            if exe is None:
                warnings.warn(
                    "caffeinate not found; the realtime run continues without "
                    "keep-awake (timing may suffer under App Nap).",
                    stacklevel=2,
                )
                yield None
                return
            proc = subprocess.Popen([exe, "-i", "-w", str(os.getpid())])
            try:
                yield proc
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return
        # Linux keep-awake (systemd-inhibit) arrives with T21.
        self.check_supported()
        yield None  # pragma: no cover - unreachable once check_supported raises

    # -- viewer backend ---------------------------------------------------- #
    def viewer_backend(self, env: dict[str, str] | None = None) -> str | None:
        """The matplotlib backend to use, or None if no viewer is available.

        ``MPLBACKEND`` overrides the choice on any OS (R2.1). macOS uses the
        native ``macosx`` backend. The Linux TkAgg/display logic arrives with
        T21.
        """
        environ = os.environ if env is None else env
        override = environ.get("MPLBACKEND")
        if override:
            return override
        if self.os_name == "macos":
            return "macosx"
        # Linux display detection / TkAgg is T21; other OSes have no viewer.
        return None

    # -- config directory -------------------------------------------------- #
    def config_dir(self, env: dict[str, str] | None = None) -> Path:
        """``$XDG_CONFIG_HOME/jn_sim``, default ``~/.config/jn_sim`` (R2.1)."""
        environ = os.environ if env is None else env
        base = environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "jn_sim"

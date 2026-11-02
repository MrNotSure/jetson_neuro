"""T3: host adapter — OS detection, support gate, keep-awake, backend."""

from __future__ import annotations

import pytest

from jn_sim import host
from jn_sim.host import Host, ToolNotFoundError, UnsupportedHostError


def test_os_detection_overridable() -> None:
    # Default detection works on this machine...
    assert Host().os_name == host.current_os()
    # ...and can be overridden so tests can simulate another platform.
    assert Host(os_name="linux").os_name == "linux"
    assert Host(os_name="freebsd").os_name == "freebsd"


def test_macos_is_supported() -> None:
    Host(os_name="macos").check_supported()  # does not raise


def test_unsupported_os_reports_clearly() -> None:
    with pytest.raises(UnsupportedHostError) as linux:
        Host(os_name="linux").check_supported()
    assert "T21" in str(linux.value)

    with pytest.raises(UnsupportedHostError) as other:
        Host(os_name="freebsd").check_supported()
    assert "freebsd" in str(other.value)


def test_mplbackend_override_wins() -> None:
    h = Host(os_name="macos")
    assert h.viewer_backend(env={}) == "macosx"
    assert h.viewer_backend(env={"MPLBACKEND": "Agg"}) == "Agg"
    # The override wins even on an OS that otherwise has no viewer.
    assert Host(os_name="freebsd").viewer_backend(env={"MPLBACKEND": "Agg"}) == "Agg"
    assert Host(os_name="freebsd").viewer_backend(env={}) is None


def test_missing_caffeinate_warns_not_fails(monkeypatch) -> None:
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    h = Host(os_name="macos")
    with pytest.warns(UserWarning, match="caffeinate"):
        with h.keep_awake() as proc:
            assert proc is None  # no-op, run continues


@pytest.mark.skipif(host.current_os() != "macos", reason="caffeinate is macOS-only")
def test_keep_awake_spawns_and_cleans_up() -> None:
    h = Host(os_name="macos")
    if h.which("caffeinate") is None:  # pragma: no cover - present on macOS
        pytest.skip("caffeinate not installed")
    with h.keep_awake() as proc:
        assert proc is not None
        assert proc.poll() is None  # running inside the context
    assert proc.poll() is not None  # terminated on exit


def test_run_tool_missing_raises() -> None:
    with pytest.raises(ToolNotFoundError):
        Host().run_tool(["jn_definitely_not_a_tool_xyz", "--version"])


def test_run_tool_runs_existing() -> None:
    if Host().which("true") is None:  # pragma: no cover
        pytest.skip("'true' not available")
    result = Host().run_tool(["true"], timeout=5)
    assert result.returncode == 0


def test_config_dir_respects_xdg() -> None:
    h = Host(os_name="macos")
    assert h.config_dir(env={"XDG_CONFIG_HOME": "/tmp/xdg"}).as_posix() == "/tmp/xdg/jn_sim"
    # default falls under the home directory's .config
    assert h.config_dir(env={}).name == "jn_sim"

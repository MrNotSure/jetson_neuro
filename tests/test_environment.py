"""T1: the package imports, the dependency split is correct, and the pinned
versions match the lock file.

Guards R1.1 by inspecting the installed metadata (numpy is the only
unconditional runtime dependency; matplotlib is the ``view`` extra and pytest
the ``dev`` extra) and by asserting the exact pins. The suite runs in the one
``.venv`` on Python 3.12 (R14.3), which is the Jetson's Python too, so this run
also covers the shared modules.
"""

from __future__ import annotations

import sys
from importlib.metadata import requires

from packaging.requirements import Requirement

import jn_sim


def test_interpreter_is_python_312() -> None:
    # One version everywhere (spec §2, R14.3): fail loudly on a wrong venv so it
    # cannot pass silently.
    assert sys.version_info[:2] == (3, 12), (
        f"tests must run on Python 3.12, not {sys.version_info.major}."
        f"{sys.version_info.minor}"
    )


def test_package_version() -> None:
    assert jn_sim.__version__ == "0.1.0"


def test_dependency_split() -> None:
    """numpy is the only unconditional requirement; matplotlib and pytest are
    gated behind the ``view`` and ``dev`` extras (R1.1)."""
    reqs = [Requirement(r) for r in requires("jn_sim")]
    by_name = {r.name: r for r in reqs}

    unconditional = [r for r in reqs if r.marker is None]
    assert [r.name for r in unconditional] == ["numpy"]
    assert str(unconditional[0].specifier) == "==2.5.4"

    mpl = by_name["matplotlib"]
    assert mpl.marker is not None, "matplotlib must be gated behind an extra"
    assert mpl.marker.evaluate({"extra": "view"})
    assert not mpl.marker.evaluate({"extra": ""})

    pt = by_name["pytest"]
    assert pt.marker is not None, "pytest must be gated behind an extra"
    assert pt.marker.evaluate({"extra": "dev"})
    assert not pt.marker.evaluate({"extra": ""})


def test_numpy_pinned() -> None:
    import numpy

    assert numpy.__version__ == "2.5.4"


def test_matplotlib_pinned() -> None:
    import matplotlib

    assert matplotlib.__version__ == "3.11.2"


def test_pytest_pinned() -> None:
    import pytest

    assert pytest.__version__ == "9.1.1"

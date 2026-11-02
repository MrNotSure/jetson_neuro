"""Random streams (spec R2.5, R8.12).

One integer seed drives all randomness. Each stream has its own generator,
``Generator(PCG64(SeedSequence(seed, spawn_key=KEY)))``, with a fixed key:

    ON thresholds   (0,)       whole run
    OFF thresholds  (1,)       whole run
    trajectory      (2, e)     episode e
    shot noise      (3, e)     episode e
    controller      (4, e)     episode e; only ctl_seed is derived from it

PCG64 is named explicitly rather than using ``default_rng`` (whose bit
generator may change between numpy versions). A new stream must take a new key
so that adding one never shifts the existing streams. Draws depend only on the
seed, the episode and the period index — never on wall-clock time, the gimbal
or the controller's commands (R2.5, R7.4).

Simulator-side only; the controller receives ``ctl_seed`` in HELLO (R8.12) and
never sees the run seed (R8.4).
"""

from __future__ import annotations

import numpy as np


def _generator(seed: int, spawn_key: tuple[int, ...]) -> np.random.Generator:
    ss = np.random.SeedSequence(seed, spawn_key=spawn_key)
    return np.random.Generator(np.random.PCG64(ss))


def on_threshold_rng(seed: int) -> np.random.Generator:
    return _generator(seed, (0,))


def off_threshold_rng(seed: int) -> np.random.Generator:
    return _generator(seed, (1,))


def trajectory_rng(seed: int, episode: int) -> np.random.Generator:
    return _generator(seed, (2, episode))


def noise_rng(seed: int, episode: int) -> np.random.Generator:
    return _generator(seed, (3, episode))


def controller_seed(seed: int, episode: int) -> int:
    """The u64 ``ctl_seed`` sent in HELLO (R8.12)."""
    ss = np.random.SeedSequence(seed, spawn_key=(4, episode))
    return int(ss.generate_state(1, np.uint64)[0])

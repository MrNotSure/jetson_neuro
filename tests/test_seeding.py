"""R2.5 / R8.12: independent, reproducible random streams with fixed keys."""

from __future__ import annotations

import numpy as np

from jn_sim import seeding


def test_streams_reproducible() -> None:
    a = seeding.trajectory_rng(0, 0).standard_normal(100)
    b = seeding.trajectory_rng(0, 0).standard_normal(100)
    assert np.array_equal(a, b)


def test_streams_independent_across_keys() -> None:
    # Different streams of the same run draw differently.
    on = seeding.on_threshold_rng(0).standard_normal(100)
    off = seeding.off_threshold_rng(0).standard_normal(100)
    traj = seeding.trajectory_rng(0, 0).standard_normal(100)
    noise = seeding.noise_rng(0, 0).standard_normal(100)
    streams = [on, off, traj, noise]
    for i in range(len(streams)):
        for j in range(i + 1, len(streams)):
            assert not np.array_equal(streams[i], streams[j])


def test_episode_key_shifts_trajectory_and_noise() -> None:
    assert not np.array_equal(
        seeding.trajectory_rng(0, 0).standard_normal(50),
        seeding.trajectory_rng(0, 1).standard_normal(50),
    )
    assert not np.array_equal(
        seeding.noise_rng(0, 0).standard_normal(50),
        seeding.noise_rng(0, 1).standard_normal(50),
    )


def test_controller_seed_matches_spec_formula() -> None:
    for episode in (0, 1, 5):
        expected = int(
            np.random.SeedSequence(0, spawn_key=(4, episode)).generate_state(
                1, np.uint64
            )[0]
        )
        assert seeding.controller_seed(0, episode) == expected


def test_uses_explicit_pcg64() -> None:
    gen = seeding.trajectory_rng(0, 0)
    assert isinstance(gen.bit_generator, np.random.PCG64)


def test_stream_spawn_keys_pinned() -> None:
    # Pin the exact SeedSequence spawn_key per stream (R2.5, M8).
    seed = 20261023

    def gen(key):
        return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=key)))

    assert np.array_equal(seeding.on_threshold_rng(seed).random(16), gen((0,)).random(16))
    assert np.array_equal(seeding.off_threshold_rng(seed).random(16), gen((1,)).random(16))
    for e in (0, 3):
        assert np.array_equal(seeding.trajectory_rng(seed, e).random(16), gen((2, e)).random(16))
        assert np.array_equal(seeding.noise_rng(seed, e).random(16), gen((3, e)).random(16))
    for e in (0, 3):
        expected = int(
            np.random.SeedSequence(seed, spawn_key=(4, e)).generate_state(1, np.uint64)[0]
        )
        assert seeding.controller_seed(seed, e) == expected

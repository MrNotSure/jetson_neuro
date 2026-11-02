"""T2: configuration — round trip, validation, intrinsics, scenarios."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from jn_sim.config import (
    Config,
    ConfigError,
    load_scenario,
    resolve_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"
V1_SCENARIOS = {
    "track-static-v1": "static",
    "track-sine-v1": "sine",
    "track-step-v1": "step",
    "track-random-v1": "random",
}


def test_dict_roundtrip() -> None:
    cfg = Config()
    assert Config.from_dict(cfg.to_dict()).to_dict() == cfg.to_dict()


def test_json_roundtrip(tmp_path: Path) -> None:
    cfg = Config()
    cfg.target.trajectory = "step"
    cfg.run.seed = 7
    path = tmp_path / "cfg.json"
    cfg.save_json(path)
    loaded = Config.load_json(path)
    assert loaded.to_dict() == cfg.to_dict()


def test_intrinsics_match_spec() -> None:
    intr = Config().intrinsics()
    # R3.1: fx = fy ~= 277.1, principal point (159.5, 119.5).
    assert intr.fx == pytest.approx(277.128, abs=0.01)
    assert intr.fy == intr.fx
    assert intr.cx == pytest.approx(159.5)
    assert intr.cy == pytest.approx(119.5)
    # cross-check the defining relation
    half = math.radians(60.0) / 2.0
    assert intr.fx == pytest.approx((320 / 2.0) / math.tan(half))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: setattr(c.camera, "width", 0),
        lambda c: setattr(c.camera, "hfov_deg", 0.0),
        lambda c: setattr(c.camera, "hfov_deg", 180.0),
        lambda c: setattr(c.scene, "background", "textured"),
        lambda c: setattr(c.target, "radius_deg", -1.0),
        lambda c: setattr(c.target, "trajectory", "spiral"),
        lambda c: setattr(c.plant, "omega_n", 0.0),
        lambda c: setattr(c.plant, "rate_limit", -1.0),
        lambda c: setattr(c.target, "sine_az_amp_deg", 120.0),  # > pan limit
        lambda c: setattr(c.target, "sine_el_amp_deg", 60.0),  # > tilt limit
        lambda c: setattr(c.events, "threshold_min", 0.0),
        lambda c: setattr(c.events, "noise_rate_hz", -0.1),
        lambda c: setattr(c.loop, "period_s", 0.0),
        lambda c: setattr(c.link, "port", 0),
        lambda c: setattr(c.run, "episodes", 0),
        lambda c: setattr(c.run, "success_in_fov", 1.5),
    ],
)
def test_bad_values_raise(mutate) -> None:
    cfg = Config()
    mutate(cfg)
    with pytest.raises(ConfigError) as exc:
        cfg.validate()
    assert str(exc.value)  # a non-empty, descriptive message


def test_override_type_conversion() -> None:
    cfg = Config()
    applied = cfg.apply_overrides(
        [
            "camera.width=640",
            "plant.zeta=0.5",
            "run.save_events=true",
            "target.trajectory=step",
        ]
    )
    assert cfg.camera.width == 640 and isinstance(cfg.camera.width, int)
    assert cfg.plant.zeta == 0.5 and isinstance(cfg.plant.zeta, float)
    assert cfg.run.save_events is True
    assert cfg.target.trajectory == "step"
    assert applied == [
        "camera.width=640",
        "plant.zeta=0.5",
        "run.save_events=true",
        "target.trajectory=step",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "camera.width",  # no '='
        "camerawidth=1",  # no section.key split
        "camera.height.extra=1",  # too many dots
        "nope.width=1",  # unknown section
        "camera.nope=1",  # unknown key
        "camera.width=notanint",  # bad type
        "run.save_events=maybe",  # bad bool
    ],
)
def test_bad_overrides_raise(bad: str) -> None:
    with pytest.raises(ConfigError):
        Config().apply_overrides([bad])


def test_scene_section_and_background_key() -> None:
    # R4.1 / review S2: the background lives at scene.background.
    cfg = Config()
    assert cfg.scene.background == "uniform" and cfg.scene.i_bg == 0.25
    cfg.apply_overrides(["scene.i_bg=0.4"])
    assert cfg.scene.i_bg == 0.4
    assert "scene" in cfg.to_dict() and "background" not in cfg.to_dict()["target"]


def test_unknown_section_and_key_in_dict() -> None:
    with pytest.raises(ConfigError):
        Config.from_dict({"bogus": {}})
    data = Config().to_dict()
    data["camera"]["bogus"] = 1
    with pytest.raises(ConfigError):
        Config.from_dict(data)


def test_v1_scenarios_load() -> None:
    for name, traj in V1_SCENARIOS.items():
        cfg = load_scenario(name, SCENARIOS_DIR)
        assert cfg.target.trajectory == traj


def test_scenario_exact_without_overrides() -> None:
    res = resolve_config(scenario="track-sine-v1", scenarios_dir=SCENARIOS_DIR)
    assert res.scenario == "track-sine-v1"
    assert res.overrides == []
    assert res.scenario_exact is True


def test_scenario_with_overrides_lists_them() -> None:
    res = resolve_config(
        scenario="track-sine-v1",
        scenarios_dir=SCENARIOS_DIR,
        sets=["events.noise_rate_hz=5.0"],
        seed=5,
        episodes=3,
    )
    assert res.scenario_exact is False
    assert res.overrides == [
        "events.noise_rate_hz=5.0",
        "run.seed=5",
        "run.episodes=3",
    ]
    assert res.config.events.noise_rate_hz == 5.0
    assert res.config.run.seed == 5
    assert res.config.run.episodes == 3


def test_config_file_layers_on_scenario(tmp_path: Path) -> None:
    # --config overrides specific keys on top of the scenario, not replacing it
    # (M4). track-step-v1 differs from the defaults, so a replace would change
    # the trajectory and fail here.
    partial = {"run": {"seed": 3}}
    cfg_file = tmp_path / "over.json"
    cfg_file.write_text(json.dumps(partial), encoding="utf-8")

    res = resolve_config(
        scenario="track-step-v1", scenarios_dir=SCENARIOS_DIR, config_file=cfg_file
    )
    # scenario base retained...
    assert res.config.target.trajectory == "step"
    assert res.config.camera.width == 320
    # ...with only the file's keys overridden, each recorded as its own override
    assert res.config.run.seed == 3
    assert "run.seed=3 (config=over.json)" in res.overrides
    assert res.scenario_exact is False


def test_config_file_rejects_unknown_key(tmp_path: Path) -> None:
    cfg_file = tmp_path / "bad.json"
    cfg_file.write_text(json.dumps({"events": {"bogus": 1}}), encoding="utf-8")
    with pytest.raises(ConfigError):
        resolve_config(scenario="track-sine-v1", scenarios_dir=SCENARIOS_DIR, config_file=cfg_file)


def test_resolve_defaults_no_scenario() -> None:
    res = resolve_config()
    assert res.scenario is None
    assert res.overrides == []
    assert res.scenario_exact is False
    assert res.config.to_dict() == Config().to_dict()

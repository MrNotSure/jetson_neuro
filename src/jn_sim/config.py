"""Configuration for the simulator (spec T2).

One dataclass per section (camera, target, plant, events, loop, link, view,
run), with the defaults from the spec's §3 table. The module loads and saves
JSON, applies ``section.key=value`` overrides with type conversion, validates
values, derives the camera intrinsics (R3.1), and resolves scenarios (R12.4).

The run *mode* (lockstep/realtime) and the controller *endpoint* are runtime
choices, not config, so a scenario file (R12.4) fixes everything here and
nothing else.

Standard library only; portable per R2.2 (pathlib, utf-8, no OS branches).
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised for an invalid configuration value or override."""


# --------------------------------------------------------------------------- #
# Section dataclasses. Defaults come from the spec §3 "Defaults" table.
# --------------------------------------------------------------------------- #


@dataclass
class CameraConfig:
    width: int = 320  # DVXplorer Lite
    height: int = 240
    hfov_deg: float = 60.0  # horizontal FOV, lens-dependent (R3.1)


@dataclass
class SceneConfig:
    # The background layer (R4.1). Stage 1 implements only the uniform
    # background; the spec names this key `scene.background`.
    background: str = "uniform"
    i_bg: float = 0.25  # I_bg, linear intensity


@dataclass
class TargetConfig:
    # The target disc composited over the scene (R4.1).
    i_t: float = 1.0  # I_t
    radius_deg: float = 1.5  # target angular radius (~7 px)

    # Which trajectory (R4.2) and its parameters.
    trajectory: str = "sine"

    # sine (Lissajous): amplitude, frequency and phase per axis.
    sine_az_amp_deg: float = 15.0
    sine_az_freq_hz: float = 0.25
    sine_az_phase_deg: float = 0.0
    sine_el_amp_deg: float = 8.0
    sine_el_freq_hz: float = 0.35
    sine_el_phase_deg: float = 0.0

    # step: a jump every interval, at most step_max from the previous position,
    # within the given ranges.
    step_interval_s: float = 3.0
    step_max_deg: float = 20.0
    step_az_range_deg: float = 15.0
    step_el_range_deg: float = 8.0

    # smooth random: sum of n sinusoids per axis, frequencies in [f_min, f_max],
    # bounded by the amplitude.
    random_az_amp_deg: float = 15.0
    random_el_amp_deg: float = 8.0
    random_f_min_hz: float = 0.05
    random_f_max_hz: float = 0.5
    random_n_sines: int = 5


@dataclass
class PlantConfig:
    # Per-axis second-order position servo (R5.1).
    omega_n: float = 25.0  # rad/s, natural frequency
    zeta: float = 0.8  # damping ratio
    rate_limit: float = 6.0  # rad/s (~0.17 s per 60 deg)
    pan_limit_deg: float = 90.0  # +/- limit
    tilt_limit_deg: float = 45.0  # +/- limit
    dead_time_s: float = 0.010  # tau_d on the setpoint (R5.3)
    dt_phys_s: float = 0.001  # fixed integration step (R5.2)


@dataclass
class EventConfig:
    # Log-intensity DVS model (R6).
    threshold_median: float = 0.12  # ln(1.13), DVXplorer Lite datasheet (R6.2)
    threshold_sigma: float = 0.039
    threshold_min: float = 0.01  # clip floor (R6.2)
    refractory_s: float = 0.0005  # per-pixel refractory period (R6.3)
    noise_rate_hz: float = 0.1  # shot noise per pixel (R6.4)
    log_eps: float = 1e-3  # epsilon in L = ln(I + eps) (R6.1)
    max_px_substep: float = 1.0  # sub-step motion cap (R6.5)


@dataclass
class LoopConfig:
    period_s: float = 0.010  # control period T = 10 ms (R7.1)
    cmd_deadline_s: float = 0.005  # realtime CMD deadline (R7.3)
    cmd_timeout_s: float = 5.0  # lockstep CMD timeout (R7.2)
    max_consecutive_misses: int = 100  # silent-link abort, realtime (R7.6)


@dataclass
class LinkConfig:
    connect_timeout: float = 10.0  # startup connect retry window (R7.7); spec key link.connect_timeout
    port: int = 5555  # default controller port
    # ssh_* are used only by the optional SSH adapter (T11); inert until then.
    ssh_command: str = "ssh"
    ssh_options: list[str] = field(default_factory=list)
    ssh_ready_timeout_s: float = 15.0


@dataclass
class ViewConfig:
    max_fps: float = 20.0  # viewer refresh cap (R12.1)
    window_s: float = 10.0  # rolling plot window (R12.1)


@dataclass
class RunConfig:
    episode_length_s: float = 30.0  # episode length
    episodes: int = 1  # episodes per run
    seed: int = 0  # master seed (R2.5)
    warmup_s: float = 1.0  # warm-up before metrics (R12.2)
    success_in_fov: float = 0.95  # episode-success threshold (R12.2)
    save_events: bool = False  # write events.bin (R12.2)


# --------------------------------------------------------------------------- #
# Derived intrinsics (R3.1).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


_SECTIONS = (
    "camera",
    "scene",
    "target",
    "plant",
    "events",
    "loop",
    "link",
    "view",
    "run",
)


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    plant: PlantConfig = field(default_factory=PlantConfig)
    events: EventConfig = field(default_factory=EventConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    link: LinkConfig = field(default_factory=LinkConfig)
    view: ViewConfig = field(default_factory=ViewConfig)
    run: RunConfig = field(default_factory=RunConfig)

    # -- intrinsics -------------------------------------------------------- #
    def intrinsics(self) -> Intrinsics:
        """Pinhole intrinsics from width, height and horizontal FOV (R3.1).

        fx = fy = (width/2) / tan(hfov/2); principal point at the image centre,
        with the origin at the centre of the top-left pixel (R3.4).
        """
        w = self.camera.width
        h = self.camera.height
        half = math.radians(self.camera.hfov_deg) / 2.0
        fx = (w / 2.0) / math.tan(half)
        return Intrinsics(fx=fx, fy=fx, cx=(w - 1) / 2.0, cy=(h - 1) / 2.0)

    # -- serialisation ----------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {name: dataclasses.asdict(getattr(self, name)) for name in _SECTIONS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("config must be a JSON object")
        unknown = set(data) - set(_SECTIONS)
        if unknown:
            raise ConfigError(
                f"unknown config section(s): {', '.join(sorted(unknown))}"
            )
        kwargs: dict[str, Any] = {}
        for name in _SECTIONS:
            section_cls = _section_class(name)
            raw = dict(data.get(name, {}))
            if not isinstance(data.get(name, {}), dict):
                raise ConfigError(f"section {name!r} must be a JSON object")
            valid = {f.name for f in dataclasses.fields(section_cls)}
            bad = set(raw) - valid
            if bad:
                raise ConfigError(
                    f"unknown key(s) in section {name!r}: {', '.join(sorted(bad))}"
                )
            # Type-check each value against the field's type, so a wrong JSON
            # type is a clear ConfigError, not a TypeError later (m4).
            defaults = section_cls()
            for key, val in raw.items():
                raw[key] = _check_field_type(name, key, val, getattr(defaults, key))
            kwargs[name] = section_cls(**raw)
        return cls(**kwargs)

    def save_json(self, path: str | Path) -> None:
        p = Path(path)
        with p.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=False)
            fh.write("\n")

    @classmethod
    def load_json(cls, path: str | Path) -> "Config":
        p = Path(path)
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    # -- overrides --------------------------------------------------------- #
    def apply_overrides(self, sets: list[str]) -> list[str]:
        """Apply ``section.key=value`` strings, converting to the field type.

        Returns the normalised list of applied overrides, for recording in
        ``meta.json`` (R12.4).
        """
        applied: list[str] = []
        for item in sets:
            if "=" not in item:
                raise ConfigError(
                    f"override {item!r} is not of the form section.key=value"
                )
            dotted, _, raw = item.partition("=")
            dotted = dotted.strip()
            if dotted.count(".") != 1:
                raise ConfigError(
                    f"override key {dotted!r} must be exactly section.key"
                )
            section_name, key = dotted.split(".")
            if section_name not in _SECTIONS:
                raise ConfigError(f"unknown config section {section_name!r}")
            section = getattr(self, section_name)
            if not hasattr(section, key):
                raise ConfigError(
                    f"unknown key {key!r} in section {section_name!r}"
                )
            current = getattr(section, key)
            value = _convert(current, raw, dotted)
            setattr(section, key, value)
            applied.append(f"{section_name}.{key}={_fmt(value)}")
        return applied

    # -- validation -------------------------------------------------------- #
    def validate(self) -> "Config":
        c, sc, t, p, e = self.camera, self.scene, self.target, self.plant, self.events
        lp, lk, rn = self.loop, self.link, self.run

        def require(cond: bool, msg: str) -> None:
            if not cond:
                raise ConfigError(msg)

        # camera (width/height fit a u16 in the protocol, R8.2)
        require(1 <= c.width <= 65535 and 1 <= c.height <= 65535, "camera width/height must be in 1..65535")
        require(0.0 < c.hfov_deg < 180.0, "camera hfov_deg must be in (0, 180)")

        # scene
        require(sc.background == "uniform", f"background {sc.background!r} not supported (only 'uniform')")
        require(sc.i_bg >= 0.0, "scene i_bg must be >= 0")

        # target
        require(t.i_t >= 0.0, "target i_t must be >= 0")
        require(t.radius_deg > 0.0, "target radius_deg must be > 0")
        require(
            t.trajectory in ("static", "sine", "step", "random"),
            f"unknown trajectory {t.trajectory!r}",
        )

        # plant (rates must be finite, not just positive)
        require(math.isfinite(p.omega_n) and p.omega_n > 0.0, "plant omega_n must be finite and > 0")
        require(math.isfinite(p.zeta) and p.zeta > 0.0, "plant zeta must be finite and > 0")
        require(math.isfinite(p.rate_limit) and p.rate_limit > 0.0, "plant rate_limit must be finite and > 0")
        require(p.pan_limit_deg > 0.0 and p.tilt_limit_deg > 0.0, "plant angle limits must be > 0")
        require(p.dead_time_s >= 0.0, "plant dead_time_s must be >= 0")
        require(p.dt_phys_s > 0.0, "plant dt_phys_s must be > 0")

        # trajectory amplitudes: non-negative and within the gimbal angle limits
        require(0.0 <= t.sine_az_amp_deg <= p.pan_limit_deg, "sine az amplitude must be in [0, pan limit]")
        require(0.0 <= t.sine_el_amp_deg <= p.tilt_limit_deg, "sine el amplitude must be in [0, tilt limit]")
        require(0.0 <= t.step_az_range_deg <= p.pan_limit_deg, "step az range must be in [0, pan limit]")
        require(0.0 <= t.step_el_range_deg <= p.tilt_limit_deg, "step el range must be in [0, tilt limit]")
        require(t.step_interval_s > 0.0, "step_interval_s must be > 0")
        require(t.step_max_deg > 0.0, "step_max_deg must be > 0")
        require(0.0 <= t.random_az_amp_deg <= p.pan_limit_deg, "random az amplitude must be in [0, pan limit]")
        require(0.0 <= t.random_el_amp_deg <= p.tilt_limit_deg, "random el amplitude must be in [0, tilt limit]")
        require(0.0 < t.random_f_min_hz <= t.random_f_max_hz, "random frequencies must satisfy 0 < f_min <= f_max")
        require(t.random_n_sines >= 1, "random_n_sines must be >= 1")
        require(t.sine_az_freq_hz > 0.0 and t.sine_el_freq_hz > 0.0, "sine frequencies must be > 0")

        # events
        require(e.threshold_median > 0.0, "events threshold_median must be > 0")
        require(e.threshold_sigma >= 0.0, "events threshold_sigma must be >= 0")
        require(e.threshold_min > 0.0, "events threshold_min must be > 0")
        require(e.refractory_s >= 0.0, "events refractory_s must be >= 0")
        require(e.noise_rate_hz >= 0.0, "events noise_rate_hz must be >= 0")
        require(e.log_eps > 0.0, "events log_eps must be > 0")
        require(e.max_px_substep > 0.0, "events max_px_substep must be > 0")

        # loop
        require(lp.period_s > 0.0, "loop period_s must be > 0")
        require(lp.cmd_deadline_s > 0.0, "loop cmd_deadline_s must be > 0")
        require(lp.cmd_timeout_s > 0.0, "loop cmd_timeout_s must be > 0")
        require(lp.max_consecutive_misses >= 1, "loop max_consecutive_misses must be >= 1")

        # link
        require(lk.connect_timeout > 0.0, "link connect_timeout must be > 0")
        require(1 <= lk.port <= 65535, "link port must be in 1..65535")

        # run
        require(rn.episode_length_s > 0.0, "run episode_length_s must be > 0")
        require(rn.episodes >= 1, "run episodes must be >= 1")
        require(rn.seed >= 0, "run seed must be >= 0")
        require(rn.warmup_s >= 0.0, "run warmup_s must be >= 0")
        require(0.0 <= rn.success_in_fov <= 1.0, "run success_in_fov must be in [0, 1]")
        # episodes cap (R6.6): uint32 us timestamps overflow after ~71 min
        require(rn.episode_length_s <= 3600.0, "episodes are capped at 60 min (R6.6)")

        return self


# --------------------------------------------------------------------------- #
# Scenario resolution (R12.4).
# --------------------------------------------------------------------------- #


_FLAG_OVERRIDES = {
    # CLI flag -> the section.key it overrides, for uniform recording (R12.4)
    "trajectory": "target.trajectory",
    "seed": "run.seed",
    "duration": "run.episode_length_s",
    "episodes": "run.episodes",
}

# Scenarios ship in the checkout, so resolve them relative to it, not the
# process working directory (m9).
_DEFAULT_SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


@dataclass
class ResolvedConfig:
    config: Config
    scenario: str | None  # scenario name, or None
    overrides: list[str]  # every override on top of the base, in order
    scenario_exact: bool  # True only for a scenario run with no overrides


def resolve_config(
    *,
    scenario: str | None = None,
    scenarios_dir: str | Path | None = None,
    config_file: str | Path | None = None,
    sets: list[str] | None = None,
    trajectory: str | None = None,
    seed: int | None = None,
    duration: float | None = None,
    episodes: int | None = None,
) -> ResolvedConfig:
    """Build the run config from a scenario base plus overrides (R12.4).

    Precedence: scenario (or defaults) < ``--config`` file < ``--set`` <
    the specific flags. Every override is recorded, so ``meta.json`` can list
    them and ``summary.json`` can set ``scenario_exact``.
    """
    sets = list(sets or [])
    overrides: list[str] = []

    # Base: the scenario (or defaults), as a dict we can layer onto.
    if scenario is not None:
        base = load_scenario(scenario, scenarios_dir).to_dict()
    else:
        base = Config().to_dict()

    # --config is an override layered on top of the scenario, not a
    # replacement (R12.4; M4). The file may be partial.
    if config_file is not None:
        with Path(config_file).open("r", encoding="utf-8") as fh:
            file_data = json.load(fh)
        if not isinstance(file_data, dict):
            raise ConfigError("--config file must be a JSON object")
        _deep_merge(base, file_data)
        # Record each key the file sets as its own override (M4), e.g.
        # "run.seed=3 (config=over.json)".
        fname = Path(config_file).name
        for section, kv in file_data.items():
            if isinstance(kv, dict):
                for key, val in kv.items():
                    overrides.append(f"{section}.{key}={_fmt(val)} (config={fname})")
            else:
                overrides.append(f"{section}={_fmt(kv)} (config={fname})")

    cfg = Config.from_dict(base)

    if sets:
        overrides.extend(cfg.apply_overrides(sets))

    flag_sets: list[str] = []
    if trajectory is not None:
        flag_sets.append(f"{_FLAG_OVERRIDES['trajectory']}={trajectory}")
    if seed is not None:
        flag_sets.append(f"{_FLAG_OVERRIDES['seed']}={seed}")
    if duration is not None:
        flag_sets.append(f"{_FLAG_OVERRIDES['duration']}={duration}")
    if episodes is not None:
        flag_sets.append(f"{_FLAG_OVERRIDES['episodes']}={episodes}")
    if flag_sets:
        overrides.extend(cfg.apply_overrides(flag_sets))

    cfg.validate()
    scenario_exact = scenario is not None and not overrides
    return ResolvedConfig(
        config=cfg,
        scenario=scenario,
        overrides=overrides,
        scenario_exact=scenario_exact,
    )


def load_scenario(name: str, scenarios_dir: str | Path | None = None) -> Config:
    base = _DEFAULT_SCENARIOS_DIR if scenarios_dir is None else Path(scenarios_dir)
    path = base / f"{name}.json"
    if not path.is_file():
        raise ConfigError(f"scenario {name!r} not found at {path}")
    return Config.load_json(path).validate()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _check_field_type(section: str, key: str, val: Any, current: Any) -> Any:
    """Check ``val`` against the field's type, coercing int->float (m4)."""
    if isinstance(current, bool):
        if not isinstance(val, bool):
            raise ConfigError(f"{section}.{key}: expected a boolean, got {type(val).__name__}")
        return val
    if isinstance(current, int):  # bool handled above
        if isinstance(val, bool) or not isinstance(val, int):
            raise ConfigError(f"{section}.{key}: expected an integer, got {type(val).__name__}")
        return val
    if isinstance(current, float):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ConfigError(f"{section}.{key}: expected a number, got {type(val).__name__}")
        return float(val)
    if isinstance(current, str):
        if not isinstance(val, str):
            raise ConfigError(f"{section}.{key}: expected a string, got {type(val).__name__}")
        return val
    if isinstance(current, list):
        if not isinstance(val, list):
            raise ConfigError(f"{section}.{key}: expected a list, got {type(val).__name__}")
        return val
    return val


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Merge ``override`` into ``base`` in place (nested dicts merged key-wise).

    Used to layer a (possibly partial) ``--config`` file onto the scenario base
    (R12.4). Unknown sections/keys survive the merge and are rejected later by
    :meth:`Config.from_dict`.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _section_class(name: str) -> type:
    return {
        "camera": CameraConfig,
        "scene": SceneConfig,
        "target": TargetConfig,
        "plant": PlantConfig,
        "events": EventConfig,
        "loop": LoopConfig,
        "link": LinkConfig,
        "view": ViewConfig,
        "run": RunConfig,
    }[name]


def _convert(current: Any, raw: str, dotted: str) -> Any:
    """Convert a string override to the type of the current value."""
    if isinstance(current, bool):
        low = raw.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise ConfigError(f"override {dotted}: expected a boolean, got {raw!r}")
    if isinstance(current, int):  # bool already handled above
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"override {dotted}: expected an integer, got {raw!r}") from exc
    if isinstance(current, float):
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"override {dotted}: expected a number, got {raw!r}") from exc
    if isinstance(current, list):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"override {dotted}: expected a JSON array, got {raw!r}") from exc
        if not isinstance(value, list):
            raise ConfigError(f"override {dotted}: expected a JSON array, got {raw!r}")
        return value
    # str (and anything else) passes through verbatim
    return raw


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return json.dumps(value)
    return str(value)

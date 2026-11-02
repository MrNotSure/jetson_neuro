"""Simulation loop and pacing (spec T12, R7).

Each episode resets the plant, trajectory, event-model reference and noise
stream (R2.5, R8.3) -- the sensor thresholds persist -- then runs the HELLO
handshake and the per-period loop. Per period (R7.1): advance the plant over
[kT, (k+1)T); subdivide so the target moves at most max_px between rendered
sub-steps (R6.5); render and generate events over the region of interest (R6.7)
and add shot noise; send OBS_k and wait for CMD_k through the Link; apply the
command through the plant's single validation call (R5.4); log the row.

Lockstep (R7.2) runs as fast as possible; realtime (R7.3) sends OBS on an
absolute monotonic schedule. A past-episode CMD, a malformed message or a
closed connection aborts (R7.6, S1); Ctrl-C ends the run cleanly (R7.5); exit
status follows R7.8.

Standard library + numpy; the simulator side (not run on the Jetson).
"""

from __future__ import annotations

import contextlib
import math
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import camera, protocol, seeding
from .config import Config
from .events import EventModel, combine
from .link import LinkConnectError
from .plant import Plant
from .render import Renderer
from .target import make_trajectory

_EXIT = {"completed": 0, "aborted": 1, "interrupted": 130}
_MAX_SUBSTEPS = 4096  # cap for fast step moves (R13.3); realtime may not keep up


@dataclass
class RunResult:
    status: str
    reason: str | None
    exit_code: int
    episodes: int
    run_dir: Any = None


class _Abort(Exception):
    """Internal: unwind the loop on a run-ending condition (R7.6)."""


_SPIN_MARGIN_NS = 2_000_000  # busy-spin the last ~2 ms to absorb time.sleep jitter


def _sleep_until_ns(target_ns: int) -> None:
    """Sleep then spin until the monotonic time ``target_ns`` (R7.3, m7).

    Sleep until ``_SPIN_MARGIN_NS`` before the target, then busy-wait, so that
    OS sleep oversleep does not push the send late on an otherwise idle host.
    Deadlines use ``monotonic_ns`` only (R2.2).
    """
    while True:
        remaining = target_ns - time.monotonic_ns()
        if remaining <= 0:
            return
        if remaining > _SPIN_MARGIN_NS:
            time.sleep((remaining - _SPIN_MARGIN_NS) / 1e9)


def _union_box(r: Renderer, pose0, pose1):
    b0 = r.roi_box(*pose0)
    b1 = r.roi_box(*pose1)
    if b0 is None:
        return b1
    if b1 is None:
        return b0
    return (min(b0[0], b1[0]), max(b0[1], b1[1]), min(b0[2], b1[2]), max(b0[3], b1[3]))


class Simulator:
    def __init__(self, cfg: Config, seed: int) -> None:
        self.cfg = cfg
        self.seed = seed
        self.intr = cfg.intrinsics()
        self.width = cfg.camera.width
        self.height = cfg.camera.height
        self.renderer = Renderer(cfg)
        self.events = EventModel(cfg, seed)
        self.plant = Plant(cfg.plant)
        self.period_s = cfg.loop.period_s
        self.dt = cfg.plant.dt_phys_s
        self.n_phys = max(1, round(self.period_s / self.dt))
        self.period_us = int(round(self.period_s * 1e6))
        # Pacing deadlines use monotonic_ns only (R2.2, m7).
        self.period_ns = int(round(self.period_s * 1e9))
        self.cmd_deadline_ns = int(round(cfg.loop.cmd_deadline_s * 1e9))
        self.cmd_timeout_ns = int(round(cfg.loop.cmd_timeout_s * 1e9))
        self.max_px = cfg.events.max_px_substep
        self._abort_reason: str | None = None
        self._run_start_ns: int | None = None
        self._n_logged = 0
        self._total_misses = 0  # cumulative over the run, for the viewer (m9)
        self._interrupted = False  # set by the SIGINT handler (R7.5, m2)

    # -- one control period ------------------------------------------------ #
    def _period(self, k: int, traj, noise_rng):
        cfg, intr = self.cfg, self.intr
        period_s = self.period_s
        kT = k * period_s
        start_pan, start_tilt = self.plant.pose
        angles, rates = self.plant.advance(self.n_phys)

        t_grid = kT + self.dt * np.arange(self.n_phys + 1)
        pan_grid = np.concatenate([[start_pan], angles[:, 0]])
        tilt_grid = np.concatenate([[start_tilt], angles[:, 1]])
        az_grid, el_grid = traj.az_el(t_grid)

        # Adaptive sub-steps from the target's projected pixel path (R6.5).
        u, v, _ = camera.project_azel(az_grid, el_grid, pan_grid, tilt_grid, intr)
        path_px = float(np.nansum(np.hypot(np.diff(u), np.diff(v))))
        uniform = self.renderer.bg.uniform
        if not uniform:
            # A textured background moves with the gimbal, so the whole frame
            # can alias; fold the gimbal's angular travel (× fx) into the
            # sub-step count, not just the target's path (R6.5, M3).
            gimbal_px = float(
                np.sum(np.hypot(np.diff(pan_grid), np.diff(tilt_grid)))
            ) * intr.fx
            path_px = max(path_px, gimbal_px)
        n_sub = int(min(_MAX_SUBSTEPS, max(1, math.ceil(path_px / self.max_px))))

        t_sub = kT + (period_s / n_sub) * np.arange(n_sub + 1)
        pan_sub = np.interp(t_sub, t_grid, pan_grid)
        tilt_sub = np.interp(t_sub, t_grid, tilt_grid)
        az_sub, el_sub = traj.az_el(t_sub)

        batches = []
        for j in range(1, n_sub + 1):
            pose0 = (pan_sub[j - 1], tilt_sub[j - 1], az_sub[j - 1], el_sub[j - 1])
            pose1 = (pan_sub[j], tilt_sub[j], az_sub[j], el_sub[j])
            t0, t1 = float(t_sub[j - 1]), float(t_sub[j])
            if uniform:
                # ROI path (R6.7): only the pixels the target can cover change.
                box = _union_box(self.renderer, pose0, pose1)
                if box is None:
                    continue  # target off-sensor at both ends: no scene events
                prev = self.renderer.render_region(*pose0, box)
                cur = self.renderer.render_region(*pose1, box)
                batches.append(self.events.update_region(prev, cur, box, t0, t1))
            else:
                # Full-frame path (R6.7): the whole frame can change with a
                # non-uniform background.
                prev = self.renderer.render_full(*pose0)
                cur = self.renderer.render_full(*pose1)
                batches.append(self.events.update(prev, cur, t0, t1))
        batches.append(self.events.noise(kT, (k + 1) * period_s, noise_rng))
        batch = combine(batches)

        # End-of-period state at (k+1)T.
        end_pan, end_tilt = self.plant.pose
        end_az, end_el = float(az_grid[-1]), float(el_grid[-1])
        eu, ev, front = camera.project_azel(end_az, end_el, end_pan, end_tilt, intr)
        in_fov = bool(camera.in_fov(end_az, end_el, end_pan, end_tilt, intr, self.width, self.height))
        err_px = (
            float(np.hypot(float(eu) - intr.cx, float(ev) - intr.cy)) if bool(front) else float("nan")
        )
        pstate = {
            "pan": end_pan,
            "tilt": end_tilt,
            "pan_rate": float(rates[-1, 0]),
            "tilt_rate": float(rates[-1, 1]),
            "pan_sp": float(self.plant.active_sp[0]),
            "tilt_sp": float(self.plant.active_sp[1]),
            "target_az": end_az,
            "target_el": end_el,
            "target_u": float(eu) if bool(front) else float("nan"),
            "target_v": float(ev) if bool(front) else float("nan"),
            "err_px": err_px,
            "in_fov": int(in_fov),
            "n_events": int(batch.size),
            "n_on": int(np.count_nonzero(batch["p"] == 1)),
            "n_off": int(np.count_nonzero(batch["p"] == 0)),
        }
        return batch, pstate

    # -- the run ----------------------------------------------------------- #
    def run(
        self,
        mode: str,
        link,
        *,
        episodes: int,
        duration_s: float,
        host,
        logger,
        viewer=None,
    ) -> RunResult:
        cfg = self.cfg
        n_periods = max(1, round(duration_s / self.period_s))
        status, reason = "completed", None
        started = False
        episode = 0
        pending_exc: BaseException | None = None

        # Ctrl-C sets a flag so the current period finishes before shutdown
        # (R7.5); the loop checks it at each period/episode boundary. Only the
        # main thread can install a handler, so fall back to the plain
        # KeyboardInterrupt path elsewhere (m2).
        self._interrupted = False
        prev_sigint = None
        installed = False
        try:
            prev_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._on_sigint)
            installed = True
        except (ValueError, OSError, RuntimeError):
            installed = False

        keep_awake = host.keep_awake() if mode == "realtime" else contextlib.nullcontext()
        try:
            with keep_awake:
                for episode in range(episodes):
                    if self._interrupted:
                        raise KeyboardInterrupt
                    ctl_seed = seeding.controller_seed(self.seed, episode)
                    hello = protocol.Hello(
                        episode, self.width, self.height, self.period_us,
                        self.intr.fx, self.intr.fy, self.intr.cx, self.intr.cy,
                        0.0, 0.0, ctl_seed,
                    )
                    name = link.open(hello)  # may raise LinkConnectError / ProtocolError
                    if not started:
                        logger.start(link.controller_meta, cfg.target.trajectory, name)
                        started = True
                    logger.set_ctl_seed(episode, ctl_seed)
                    self._run_episode(episode, mode, link, n_periods, logger, viewer)
                    link.send_bye(episode)
        except _Abort:
            status, reason = "aborted", self._abort_reason
        except LinkConnectError as exc:
            # Could not connect at startup (R7.7): no run directory is created.
            # A mid-run reset is a plain OSError, caught below as a lost
            # connection, not misreported as a connect failure (m6).
            status, reason = "aborted", f"could not connect: {exc}"
        except (protocol.ProtocolError, OSError) as exc:
            status, reason = "aborted", f"connection lost: {exc}"
        except KeyboardInterrupt:
            status, reason = "interrupted", "Ctrl-C (R7.5)"
            with contextlib.suppress(Exception):
                link.send_bye(episode)
        except Exception as exc:  # noqa: BLE001 - R7.8: finalise, then propagate
            status, reason = "aborted", f"unexpected error: {exc!r}"
            pending_exc = exc
        finally:
            if installed:
                with contextlib.suppress(Exception):
                    signal.signal(signal.SIGINT, prev_sigint)
            link.close()
            if started:
                if self._run_start_ns is not None:
                    elapsed = (time.monotonic_ns() - self._run_start_ns) / 1e9
                    logger.set_achieved_hz(self._n_logged / elapsed if elapsed > 0 else float("nan"))
                logger.finalize(status, reason)

        if pending_exc is not None:
            # The logs are finalised as "aborted"; let the error surface (R7.8).
            raise pending_exc

        return RunResult(
            status=status,
            reason=reason,
            exit_code=_EXIT.get(status, 1),
            episodes=episode + 1 if started else 0,
            run_dir=getattr(logger, "run_dir", None) if started else None,
        )

    def _on_sigint(self, signum, frame) -> None:
        """SIGINT handler: request a clean stop at the next period boundary."""
        self._interrupted = True

    def _run_episode(self, episode, mode, link, n_periods, logger, viewer) -> None:
        cfg = self.cfg
        self.plant.reset(0.0, 0.0)
        traj = make_trajectory(
            cfg.target, seeding.trajectory_rng(self.seed, episode), n_periods * self.period_s
        )
        noise_rng = seeding.noise_rng(self.seed, episode)
        init = self.renderer.render_full(0.0, 0.0, *traj.az_el(0.0))
        self.events.reset_episode(init)

        t0_ns = time.monotonic_ns()
        if self._run_start_ns is None:
            self._run_start_ns = t0_ns
        consecutive_misses = 0
        last_missed = False
        for k in range(n_periods):
            if self._interrupted:
                # The previous period finished and was logged; stop here (R7.5).
                raise KeyboardInterrupt
            t_compute = time.monotonic_ns()
            batch, pstate = self._period(k, traj, noise_rng)
            obs = protocol.Obs(episode, k, k * self.period_us, (k + 1) * self.period_us, batch)
            try:
                # Encoding the OBS is simulator compute, so it is inside sim_us
                # (R12.2, m4). It also applies the 16 MiB cap (R8.8).
                obs_bytes = protocol.encode_message(obs)
            except protocol.ProtocolError as exc:
                self._abort_reason = f"OBS batch exceeds the 16 MiB cap (R8.8): {exc}"
                raise _Abort from exc
            sim_us = (time.monotonic_ns() - t_compute) // 1000

            if mode == "realtime":
                scheduled_ns = t0_ns + (k + 1) * self.period_ns
                _sleep_until_ns(scheduled_ns)
                send_ns = time.monotonic_ns()
                send_lateness_us = (send_ns - scheduled_ns) / 1000.0
                deadline = (send_ns + self.cmd_deadline_ns) / 1e9
            else:
                send_lateness_us = float("nan")
                deadline = (time.monotonic_ns() + self.cmd_timeout_ns) / 1e9

            t_rtt = time.monotonic_ns()
            try:
                cmd = link.exchange(obs, deadline, obs_bytes=obs_bytes)
            except (protocol.ProtocolError, OSError) as exc:
                self._abort_reason = f"connection lost: {exc}"
                raise _Abort from exc
            rtt_us = (time.monotonic_ns() - t_rtt) / 1000.0

            if cmd is None:
                if mode == "lockstep":
                    self._abort_reason = "CMD timeout (lockstep, R7.6)"
                    raise _Abort
                consecutive_misses += 1
                self._total_misses += 1
                last_missed = k == n_periods - 1
                if consecutive_misses >= cfg.loop.max_consecutive_misses:
                    self._abort_reason = (
                        f"silent link: {consecutive_misses} consecutive misses (R7.6)"
                    )
                    raise _Abort
                row = self._row(episode, k, pstate, None, sim_us, float("nan"), send_lateness_us)
            else:
                consecutive_misses = 0
                last_missed = False
                _, cmd_invalid, cmd_clamped = self.plant.apply_command(cmd.pan, cmd.tilt)
                row = self._row(
                    episode, k, pstate, cmd, sim_us, rtt_us, send_lateness_us,
                    cmd_invalid=cmd_invalid, cmd_clamped=cmd_clamped,
                )
            logger.log_period(row, batch)
            self._n_logged += 1
            if viewer is not None:
                viewer.update(self._snapshot(k, pstate, batch, row))

        # R7.3: if the reply to this episode's last OBS missed its deadline,
        # wait for it and discard it before BYE, so it can't collide with the
        # next episode's handshake. A timeout here is a lost connection (R7.6).
        if mode == "realtime" and last_missed:
            deadline = (time.monotonic_ns() + self.cmd_timeout_ns) / 1e9
            try:
                ok = link.wait_for_late(episode, n_periods - 1, deadline)
            except (protocol.ProtocolError, OSError) as exc:
                self._abort_reason = f"connection lost: {exc}"
                raise _Abort from exc
            if not ok:
                self._abort_reason = (
                    f"late reply to episode {episode}'s last OBS never arrived "
                    "within the CMD timeout (R7.3/R7.6)"
                )
                raise _Abort

    def _row(self, episode, k, pstate, cmd, sim_us, rtt_us, send_lateness_us,
             cmd_invalid=False, cmd_clamped=False) -> dict:
        nan = float("nan")
        if cmd is None:
            cmd_pan = cmd_tilt = nan
            flags = 0
            ctl_rx = ctl_tx = 0
            ctl_us = nan
            rtt_us = nan
            miss = 1
        else:
            cmd_pan, cmd_tilt = cmd.pan, cmd.tilt
            flags = cmd.flags
            ctl_rx, ctl_tx = cmd.t_rx_ns, cmd.t_tx_ns
            ctl_us = (ctl_tx - ctl_rx) / 1000.0
            miss = 0
        link_us = (rtt_us - ctl_us) if (miss == 0) else nan
        row = {
            "episode": episode,
            "k": k,
            "t_us": (k + 1) * self.period_us,
            "cmd_pan": cmd_pan,
            "cmd_tilt": cmd_tilt,
            "cmd_invalid": int(cmd_invalid),
            "cmd_clamped": int(cmd_clamped),
            "ctl_flags": flags,
            "sim_us": int(sim_us),
            "ctl_us": ctl_us,
            "rtt_us": rtt_us,
            "link_us": link_us,
            "miss": miss,
            "ctl_rx_ns": ctl_rx,
            "ctl_tx_ns": ctl_tx,
            "send_lateness_us": send_lateness_us,
        }
        row.update(pstate)
        return row

    def _snapshot(self, k, pstate, batch, row) -> dict:
        return {
            "k": k,
            "sim_time": (k + 1) * self.period_s,
            "events": batch,
            "target_u": pstate["target_u"],
            "target_v": pstate["target_v"],
            "pan": pstate["pan"],
            "tilt": pstate["tilt"],
            "target_az": pstate["target_az"],
            "target_el": pstate["target_el"],
            "err_px": pstate["err_px"],
            "in_fov": pstate["in_fov"],
            "n_events": pstate["n_events"],
            "sim_us": row["sim_us"],
            "rtt_us": row["rtt_us"],
            "miss": row["miss"],
            "misses": self._total_misses,
            "width": self.width,
            "height": self.height,
            "cx": self.intr.cx,
            "cy": self.intr.cy,
        }

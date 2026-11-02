# Controller A evaluation and tuning, 1 Nov 2026

Summary files of the simulator runs behind `docs/ctl_a.md` §4–§7. Each folder
keeps the run folder's original name; `docs/ctl_a.md` cites them as
`runs/<name>`.

- `eval_*/eval.csv` and `eval.json`: one row per scenario and seed plus mean
  and worst rows, and the parameters and options of the evaluation
  (`scripts/eval_controllers.py`). The final tables use the `…_ce1bda2`
  folders: `r82_classical_ce1bda2_b` and `r82_centroid_ce1bda2` (§5),
  `r84_plant_*` (§6). `initial_defaults` is A before tuning.
- `tune_*/eval_*/`: the tuning grid of §4 (screens 1–3 and the confirmation).
  It ran an earlier `classical.py`, before the review fixes.
- `rt_classical_ce1bda2/*/`: `meta.json` and `summary.json` of the three 60 s
  realtime runs on the Mac (§7).

The per-period `periods.csv` files are not included. The `…_ce1bda2`
evaluations reproduce exactly in lockstep with this repo's code from their
scenario and seed (rerun `scripts/eval_controllers.py` with the seeds and
options in `eval.json`).

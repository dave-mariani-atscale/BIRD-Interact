#!/usr/bin/env python3
"""Estimate round-2 P1 / P2 / reward for a v12 database from its $0 ceiling sweeps.

No benchmark run is possible (no API credits), so the estimate is a calibration:
how much of a model's hand-written $0 ceiling the paid agent actually converted,
measured across the 16 v12 builds that recorded BOTH a full ceiling and a paid score.

  conversion = achieved_P1 / full_ceiling_P1     mean 0.81, sd 0.27, range 0.25-1.25

Achieved CAN exceed the ceiling - a ceiling sweep is a lower bound on the model,
not an upper bound on the agent (virtual_idol pass report, finding 5).

Per database we shrink that database's own historical conversion halfway to the
programme mean, because a single build is one noisy observation:

  ratio = clip(0.5 * own_ratio + 0.5 * 0.81, 0.35, 1.15)
  est_P1 = new_full_ceiling_P1 * ratio / tasks

The bare-name ceiling enters as a STEERING term. A fork the agent has to guess is
close to a coin flip, so tasks that pass at the full ceiling but NOT bare-named and
carry no ask are discounted; the round-2 rules exist to move tasks out of that set.

  est_P1 = (bare + ASK_CONV * (full - bare)) * ratio / tasks,  ASK_CONV = 0.7

ASK_CONV 0.7 is the programme's ask evidence, not a fitted constant: polar_equipment
4 of 4, cross_border 3 of 3 answered right, labor_certification's asks carrying the
build, against households where the asks were spent on the model's own forks.
It is the weakest number here - the report says so rather than hiding it.

Usage:
  scripts/v12_round2_estimate.py --db crypto_exchange --tasks 20 \
      --full-p1 16 --bare-p1 15 --full-p2 14 --bare-p2 13
"""
import argparse, json, sys

# db: (tasks, full_ceiling_P1, achieved_P1, achieved_P2, full_ceiling_P2, raw_reward)
HIST = {
 "solar_panel":            (20, 14, 17.0, 12.0, None, 0.525),
 "organ_transplant":       (19, 12,  3.0,  1.0, None, 0.0702),
 "insider_trading":        (21, 11,  7.5,  5.5, None, 0.2270),
 "polar_equipment":        (20, 14, 10.5,  5.5,    8, 0.070),
 "virtual_idol":           (19, None, 8.0,  2.0, None, 0.2526),
 "exchange_traded_funds":  (19, 16, 11.5,  7.0, None, 0.2947),
 "disaster_relief":        (12,  9,  5.0,  4.0, None, 0.1528),
 "fake_account":           (24, 18, 18.0, 15.0,   16, 0.2681),
 "planets_data":           (19, 16, 10.0,  6.5,   19, 0.4070),
 "mental_health":          (20,  4,  5.0,  5.0,    2, 0.1783),
 "crypto_exchange":        (20, 15, 13.0,  7.5,   10, 0.5717),
 "sports_events":          (20, 15, 12.5,  8.5,   13, 0.3633),
 "museum_artifact":        (20, None, 7.5,  3.5, None, 0.1367),
 "reverse_logistics":      (20, 18, 17.0, 15.5,   18, 0.5883),
 "cross_border":           (19, 13, 10.0,  7.0,   12, 0.1140),
 "hulushows":              (20, 13, 13.5, 11.5,   13, 0.4717),
 "households":             (21,  7,  2.5,  2.0,    9, 0.0698),
 "robot_fault_prediction": (10, None, None, None, None, 0.163),
 "archeology_scan":        (10, None, None, None, None, 0.113),
}
MEAN_CONV = 0.81
ASK_CONV  = 0.70

def ratio_for(db, phase2=False):
    h = HIST.get(db)
    if not h: return MEAN_CONV, "no history - programme mean"
    tasks, cp1, ap1, ap2, cp2, _ = h
    c, a = (cp2, ap2) if phase2 else (cp1, ap1)
    if not c or a is None: return MEAN_CONV, "no recorded ceiling - programme mean"
    own = a / c
    r = max(0.35, min(1.15, 0.5 * own + 0.5 * MEAN_CONV))
    return r, f"own {own:.2f} shrunk to {r:.2f}"

def est(db, tasks, full, bare, phase2=False):
    if full is None: return None, None, ""
    if bare is None: bare = full
    r, why = ratio_for(db, phase2)
    eff = bare + ASK_CONV * (full - bare)
    return (eff * r) / tasks, eff, why

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--tasks", type=int, required=True)
    p.add_argument("--full-p1", type=float); p.add_argument("--bare-p1", type=float)
    p.add_argument("--full-p2", type=float); p.add_argument("--bare-p2", type=float)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    p1, eff1, why1 = est(a.db, a.tasks, a.full_p1, a.bare_p1)
    p2, eff2, why2 = est(a.db, a.tasks, a.full_p2, a.bare_p2, phase2=True)
    if p1 is None:
        sys.exit("need --full-p1")
    if p2 is None: p2, eff2, why2 = 0.0, 0.0, "no P2 ceiling measured"
    reward = 0.7 * p1 + 0.3 * p2
    raw = HIST.get(a.db, (None,)*6)[5]
    out = dict(db=a.db, tasks=a.tasks, est_P1=round(p1, 4), est_P2=round(p2, 4),
               est_reward=round(reward, 4), raw=raw,
               lift_pp=(round((reward - raw) * 100, 1) if raw else None),
               effective_P1_tasks=round(eff1, 1), effective_P2_tasks=round(eff2, 1),
               p1_basis=why1, p2_basis=why2)
    if a.json:
        print(json.dumps(out))
    else:
        for k, v in out.items(): print(f"{k:22} {v}")

if __name__ == "__main__":
    main()

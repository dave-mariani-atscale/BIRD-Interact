#!/usr/bin/env python3
"""The four acceptance gates, run against DEPLOYED models rather than by hand.

    python scripts/acceptance_gates.py virtual_idol [sports_events ...]
    python scripts/acceptance_gates.py --all-new

`sml-cli validate` is layer 1 only. Every defect class the model-change log
records deployed clean and surfaced only through a live query, so these four
gates all talk to the deployed model through `run_query` and compare against a
second source of truth:

  1. EXACTNESS   - every sum/average/min/max/count metric queried through the
                   model, against the same aggregate computed directly on the
                   metric's own derived-dataset SQL in Postgres. The data is
                   synthetic, so a plausible number proves nothing; this is an
                   exact comparison against the warehouse.
  2. CONFORMANCE - per dimension, one measure-by-attribute query per fact that
                   dimension's relationships say it should reach. Empty or
                   erroring is a model bug.
  3. ATTRIBUTE-ONLY - every pair of dimensions projected together with NO
                   measure. Q-27: take the measure away and the planner has to
                   pick a path itself, and it can fail where the measured form
                   succeeds. BIRD questions ask for labels more often than
                   aggregates, so this is the shape that actually gets used.
  4. COVERAGE    - one query per question shape: group aggregate, filter then
                   measure, superlative/top-N, cross-fact, entity detail,
                   group-relative comparison.

Free: no LLM calls, no benchmark tokens. Reports per gate and exits non-zero on
any failure.
"""
from __future__ import annotations

import argparse
import importlib
import itertools
import json
import pathlib
import re
import sys
import time

ADK = pathlib.Path(__file__).resolve().parents[1]
MODELS = pathlib.Path(
    "/Users/davidmariani/workspace/atscale/bird-atscale-models")
sys.path.insert(0, str(ADK))

from shared.config import settings                      # noqa: E402
from shared.mcp_client import MCPClient, MCPEndpoint    # noqa: E402

import psycopg2                                         # noqa: E402

SCHEMA = "bird_atscale_models_catalog_main"

PG_AGG = {
    "sum": "sum", "average": "avg", "minimum": "min", "maximum": "max",
    "count non-null": "count", "count distinct": "count_distinct",
}

#: Relative tolerance for a float comparison. Exact for integers; a double sum
#: aggregated in a different order differs in the last bits, and AtScale returns
#: a rounded decimal for some averages.
REL_TOL = 5e-4

cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                            bearer_token=settings.semantic_layer_mcp_token))


def run(query):
    """One live query. Returns (rows, error)."""
    try:
        raw = str(cli.call_tool("run_query", {"query": query}))
    except Exception as e:                               # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    head = raw.split("\nqueryId:")[0].strip()
    if not head.startswith("["):
        return None, head[:200].replace("\n", " ")
    try:
        return json.loads(head), None
    except json.JSONDecodeError:
        return None, f"unparseable result: {head[:160]}"


def load_spec(db):
    gen = MODELS / db / "generator"
    for p in (str(MODELS / "utilities"), str(gen)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for mod in ("sql_defs", "spec_dims", "spec_metrics", "spec"):
        sys.modules.pop(mod, None)
    return importlib.import_module("spec")


def close(got, want):
    if got is None or want is None:
        return got is None and want is None
    try:
        g, w = float(got), float(want)
    except (TypeError, ValueError):
        return str(got) == str(want)
    if g == w:
        return True
    scale = max(abs(g), abs(w), 1.0)
    return abs(g - w) / scale <= REL_TOL


# --------------------------------------------------------------------------- #
def gate_exactness(spec, model, cur):
    """Every aggregate metric, model vs warehouse."""
    # A metric the spec deliberately hides is not queryable by name, and that is
    # the point of hiding it - a redundant twin kept for its description. Not a
    # defect, so it is not a gate failure.
    todo = [m for m in spec.METRICS
            if m["calculation_method"] in PG_AGG and not m.get("is_hidden")]
    want = {}
    for m in todo:
        ds, col = spec.DATASETS[m["dataset"]], m["column"]
        agg = PG_AGG[m["calculation_method"]]
        expr = (f'count(DISTINCT "{col}")' if agg == "count_distinct"
                else f'{agg}("{col}")')
        cur.execute(f"SELECT {expr} FROM ({ds}) t")
        want[m["unique_name"]] = cur.fetchone()[0]

    # Batch the model side: one query per 12 metrics, falling back to singles so
    # one bad metric cannot hide the other eleven.
    got, errs = {}, []
    names = list(want)
    for i in range(0, len(names), 12):
        chunk = names[i:i + 12]
        cols = ", ".join(f'"{n}"' for n in chunk)
        rows, err = run(f'SELECT {cols} FROM "{SCHEMA}"."{model}"')
        if err:
            for n in chunk:
                rows1, err1 = run(f'SELECT "{n}" FROM "{SCHEMA}"."{model}"')
                if err1:
                    errs.append((n, err1))
                else:
                    got[n] = rows1[0].get(n)
        else:
            got.update(rows[0])

    bad = []
    for n, w in want.items():
        if n in dict(errs):
            continue
        if not close(got.get(n), w):
            bad.append((n, got.get(n), w))
    return len(want), bad, errs


# --------------------------------------------------------------------------- #
def representative_attributes(spec):
    """One queryable attribute name per dimension.

    The key level of a profile dimension is hidden, so a query cannot project
    it; the first secondary attribute is what a question naming that entity
    actually selects.
    """
    out = {}
    for dim in spec.DIMENSIONS:
        for lvl in dim["levels"]:
            if not lvl.get("is_hidden"):
                out[dim["unique_name"]] = lvl["unique_name"]
                break
        else:
            secs = dim["levels"][0].get("secondaries") or []
            if secs:
                out[dim["unique_name"]] = secs[0][0]
    return out


def facts_by_dimension(spec):
    """{dimension: [datasets whose relationships reach it]} from the spec."""
    out = {}
    for r in spec.RELATIONSHIPS:
        out.setdefault(r["to"]["dimension"], set()).add(r["from"]["dataset"])
    return {k: sorted(v) for k, v in out.items()}


def metric_on(spec, dataset):
    for m in spec.METRICS:
        if m["dataset"] == dataset and m["calculation_method"] == "sum":
            return m["unique_name"]
    for m in spec.METRICS:
        if m["dataset"] == dataset:
            return m["unique_name"]
    return None


def gate_conformance(spec, model):
    attrs = representative_attributes(spec)
    reach = facts_by_dimension(spec)
    checked, bad = 0, []
    for dim, datasets in sorted(reach.items()):
        attr = attrs.get(dim)
        if not attr:
            bad.append((dim, "-", "no queryable attribute on this dimension"))
            continue
        for ds in datasets:
            met = metric_on(spec, ds)
            if not met:
                continue
            checked += 1
            rows, err = run(
                f'SELECT "{attr}", "{met}" FROM "{SCHEMA}"."{model}" '
                f'GROUP BY 1 LIMIT 5')
            if err:
                bad.append((dim, ds, err[:110]))
            elif not rows:
                bad.append((dim, ds, "returned no rows"))
    return checked, bad


def gate_attribute_only(spec, model):
    attrs = representative_attributes(spec)
    names = sorted(attrs)
    checked, bad = 0, []
    for a, b in itertools.combinations(names, 2):
        checked += 1
        rows, err = run(f'SELECT "{attrs[a]}", "{attrs[b]}" '
                        f'FROM "{SCHEMA}"."{model}" LIMIT 1')
        if err:
            bad.append((a, b, err[:110]))
    return checked, bad


SHAPES = [
    ("group aggregate",
     'SELECT "{attr}", "{met}" FROM {t} GROUP BY 1 ORDER BY 2 DESC LIMIT 5'),
    ("filter then measure",
     'SELECT "{met}" FROM {t} WHERE "{attr}" IS NOT NULL'),
    ("superlative top-N",
     'SELECT "{attr}", "{met}" FROM {t} GROUP BY 1 ORDER BY 2 DESC LIMIT 1'),
    ("cross-fact",
     'SELECT "{attr}", "{met}", "{met2}" FROM {t} GROUP BY 1 LIMIT 5'),
    ("entity detail",
     'SELECT "{attr}", "{attr2}" FROM {t} LIMIT 5'),
    ("group-relative comparison",
     'SELECT "{attr}", "{met}", "{calc}" FROM {t} GROUP BY 1 LIMIT 5'),
]


def gate_coverage(spec, model):
    attrs = representative_attributes(spec)
    names = sorted(attrs, key=lambda d: -len(
        [1 for r in spec.RELATIONSHIPS if r["to"]["dimension"] == d]))
    if len(names) < 2:
        return 0, [("setup", "-", "fewer than two dimensions")]
    reach = facts_by_dimension(spec)
    d1, d2 = names[0], names[1]
    ds1 = reach[d1]
    met = metric_on(spec, ds1[0])
    met2 = metric_on(spec, ds1[-1]) if len(ds1) > 1 else met
    calc = spec.CALCULATIONS[0]["unique_name"]
    t = f'"{SCHEMA}"."{model}"'
    checked, bad = 0, []
    for label, tmpl in SHAPES:
        q = tmpl.format(t=t, attr=attrs[d1], attr2=attrs[d2], met=met,
                        met2=met2, calc=calc)
        checked += 1
        rows, err = run(q)
        if err:
            bad.append((label, q[:90], err[:110]))
        elif not rows:
            bad.append((label, q[:90], "returned no rows"))
    return checked, bad


# --------------------------------------------------------------------------- #
NEW = ["insider_trading", "museum_artifact", "polar_equipment",
       "cold_chain_pharma_compliance", "disaster_relief", "hulushows",
       "mental_health", "planets_data", "reverse_logistics",
       "robot_fault_prediction", "sports_events", "virtual_idol"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="*")
    ap.add_argument("--all-new", action="store_true")
    ap.add_argument("--gates", default="1234",
                    help="which gates to run, e.g. 12")
    a = ap.parse_args()
    dbs = NEW if a.all_new else a.dbs
    if not dbs:
        ap.error("name at least one database, or pass --all-new")

    sys.path.insert(0, str(MODELS / "utilities"))
    from birdsml.pgtypes import PG                       # noqa: PLC0415

    overall = 0
    for db in dbs:
        spec = load_spec(db)
        model = spec.MODEL_NAME
        print(f"\n{'=' * 72}\n{db}  ->  {model}\n{'=' * 72}")
        t0 = time.time()
        conn = psycopg2.connect(**PG(spec.DATABASE))
        conn.set_session(readonly=True)
        cur = conn.cursor()

        if "1" in a.gates:
            n, bad, errs = gate_exactness(spec, model, cur)
            for name, got, want in bad:
                print(f"  MISMATCH {name}: model {got!r}, warehouse {want!r}")
            for name, err in errs:
                print(f"  ERROR    {name}: {err}")
            ok = not bad and not errs
            overall |= 0 if ok else 1
            print(f"  gate 1 exactness    : {'PASS' if ok else 'FAIL'} "
                  f"- {n - len(bad) - len(errs)}/{n} metrics exact")

        if "2" in a.gates:
            n, bad = gate_conformance(spec, model)
            for dim, ds, why in bad:
                print(f"  FAIL {dim} x {ds}: {why}")
            overall |= 0 if not bad else 1
            print(f"  gate 2 conformance  : {'PASS' if not bad else 'FAIL'} "
                  f"- {n - len(bad)}/{n} dimension-fact pairs resolve")

        if "3" in a.gates:
            n, bad = gate_attribute_only(spec, model)
            for x, y, why in bad:
                print(f"  FAIL {x} x {y}: {why}")
            overall |= 0 if not bad else 1
            print(f"  gate 3 attribute-only: {'PASS' if not bad else 'FAIL'} "
                  f"- {n - len(bad)}/{n} dimension pairs project")

        if "4" in a.gates:
            n, bad = gate_coverage(spec, model)
            for label, q, why in bad:
                print(f"  FAIL {label}: {why}\n       {q}")
            overall |= 0 if not bad else 1
            print(f"  gate 4 coverage     : {'PASS' if not bad else 'FAIL'} "
                  f"- {n - len(bad)}/{n} question shapes answer")

        cur.close()
        conn.close()
        print(f"  ({time.time() - t0:.0f}s)")
    print("\nACCEPTANCE " + ("PASS" if overall == 0 else "FAIL"))
    return overall


if __name__ == "__main__":
    sys.exit(main())

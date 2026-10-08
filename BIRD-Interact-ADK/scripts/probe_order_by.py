#!/usr/bin/env python3
"""Probe ORDER BY term resolution (ATSCALE-52089).

Every case below is valid Postgres against the deployed Households model. Run it
before and after an engine change: the three EXPECT_OK cases guard against
regression, and each EXPECT_FAIL case flipping to OK is one variant fixed.

    .venv-adk/bin/python scripts/probe_order_by.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import result_diff as rd                                          # noqa: E402

M = '"bird_atscale_models_catalog_main"."Households"'

CASES = [
    ("OK",   "bare projected column",
     f'SELECT "Region", "Resident Count" FROM {M} GROUP BY "Region" '
     f'ORDER BY "Resident Count" DESC LIMIT 3'),
    ("OK",   "bare alias",
     f'SELECT "Region", "Resident Count" AS rc FROM {M} GROUP BY "Region" '
     f'ORDER BY rc DESC LIMIT 3'),
    ("OK",   "ordinal position",
     f'SELECT "Region", "Resident Count" FROM {M} GROUP BY "Region" '
     f'ORDER BY 2 DESC LIMIT 3'),
    ("OK",   "subquery column, projected outside",
     f'SELECT t.zone FROM (SELECT "Zone" AS zone, "Resident Count" AS rc FROM {M} '
     f'GROUP BY "Zone") t ORDER BY t.zone LIMIT 3'),
    ("FAIL", "sort key not in the SELECT list",
     f'SELECT "Region", "Zone" FROM {M} GROUP BY "Region", "Zone" '
     f'ORDER BY "Resident Count" DESC LIMIT 3'),
    ("FAIL", "sort key projected but wrapped in ROUND/CAST",
     f'SELECT "Region", ROUND(CAST("Resident Count" AS numeric(18,2)), 1) AS rr FROM {M} '
     f'GROUP BY "Region" ORDER BY "Resident Count" DESC LIMIT 3'),
    ("FAIL", "expression over a projected alias",
     f'SELECT "Region", "Resident Count" AS rc FROM {M} GROUP BY "Region" '
     f'ORDER BY COALESCE(rc, -1) DESC LIMIT 3'),
    ("FAIL", "aggregate over a subquery column",
     f'SELECT t.region, SUM(t.rc) AS total FROM (SELECT "Region" AS region, '
     f'"Resident Count" AS rc FROM {M} GROUP BY "Region") t GROUP BY t.region '
     f'ORDER BY MIN(t.rc) DESC LIMIT 3'),
    ("FAIL", "subquery column dropped outside, used in ORDER BY",
     f'SELECT t.region, t.zone FROM (SELECT "Region" AS region, "Zone" AS zone, '
     f'"Resident Count" AS rc FROM {M} GROUP BY "Region", "Zone") t '
     f'ORDER BY t.rc DESC LIMIT 3'),
]


def main() -> int:
    mcp = rd.Mcp(); mcp.start()
    regressions = fixed = 0
    for expect, label, sql in CASES:
        rows, err = mcp.run_query(sql)
        got = "FAIL" if err else "OK"
        if expect == "OK" and got == "FAIL":
            mark, note = "REGRESSION", err.replace("engine error: ", "")[:70]
            regressions += 1
        elif expect == "FAIL" and got == "OK":
            mark, note = "FIXED", f"{len(rows)} rows"
            fixed += 1
        else:
            mark = "as expected"
            note = (err.replace("engine error: ", "")[:70] if err else f"{len(rows)} rows")
        print(f"  [{got:4}] {mark:12} {label:48} {note}")
    print(f"\n  {fixed} of 5 failing variants now work; {regressions} regressions")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())

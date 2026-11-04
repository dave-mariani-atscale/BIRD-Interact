#!/usr/bin/env python3
"""Create or update one Genie space per BIRD database, attaching ONLY that database's
Unity Catalog metric views (backend `dbx_genie_space`).

The spaces carry no text instructions, no example SQL, no join specs and no sample
questions: the metric views are the curated semantic model, exactly as the SML models
are for the AtScale arm, and the knowledge base already lives in their comments. A
space is matched by title ("BIRD <db> (metric views)") so the script is idempotent;
an existing space is PATCHed to exactly this definition.

Writes {db: space_id} into the `dbx_genie_space` block's domains in every backends file
given (default: the three in config/), and prints the map.

    python3 scripts/provision_genie_spaces.py [--db solar_panel ...] [--files config/x.yaml ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import settings  # noqa: E402
from shared.databricks_sql import DatabricksSQL  # noqa: E402

CATALOG = "bird_interact"
PARENT = "/Workspace/Users/dave@atscale.com/bird_genie_spaces"
DEFAULT_FILES = ["config/environment_backends.yaml", "config/environment_backends.no_gold_930.yaml",
                 "config/environment_backends.dbx_vs_0910.yaml"]


def title(db: str) -> str:
    return f"BIRD {db} (metric views)"


class _Retrying(httpx.Client):
    """The Genie API rate-limits space management (HTTP 429 RESOURCE_EXHAUSTED after
    about 20 rapid calls): back off and retry instead of failing half-way."""
    def request(self, *a, **kw):
        import time
        for i in range(8):
            r = super().request(*a, **kw)
            if r.status_code != 429:
                return r
            time.sleep(min(60, 5 * 2 ** i))
        return r


def client() -> httpx.Client:
    return _Retrying(base_url=settings.databricks_host.rstrip("/"), timeout=120, trust_env=False,
                     headers={"Authorization": f"Bearer {settings.databricks_token}"})


def metric_views() -> dict:
    r = DatabricksSQL().execute(
        f"SELECT table_schema, table_name FROM {CATALOG}.information_schema.tables "
        "WHERE table_type = 'METRIC_VIEW' ORDER BY 1, 2")
    if r.error:
        sys.exit(r.error)
    out: dict = {}
    for s, t in r.rows:
        out.setdefault(s, []).append(f"{CATALOG}.{s}.{t}")
    return out


def existing_spaces(c: httpx.Client) -> dict:
    out, token = {}, None
    while True:
        r = c.get("/api/2.0/genie/spaces", params={"page_size": 100, **({"page_token": token} if token else {})})
        r.raise_for_status()
        d = r.json()
        for s in d.get("spaces", []):
            out.setdefault(s["title"], s["space_id"])
        token = d.get("next_page_token")
        if not token:
            return out


def ensure_folder(c: httpx.Client) -> None:
    c.post("/api/2.0/workspace/mkdirs", json={"path": PARENT}).raise_for_status()


def serialized(views: list) -> str:
    return json.dumps({"version": 2, "data_sources": {"tables": [{"identifier": v} for v in sorted(views)]}})


def write_domains(files: list, spaces: dict) -> None:
    """Rewrite the `domains:` mapping of the dbx_genie_space block in place (text edit,
    so the rest of each file and its comments stay byte-identical)."""
    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        text = p.read_text()
        m = re.search(r"\n  dbx_genie_space:\n(?:.*\n)*?    domains:\n((?:      .*\n)*)", text)
        if not m:
            print(f"  {f}: no dbx_genie_space block, skipped")
            continue
        body = "".join(f"      {db}:\n        catalog: {CATALOG}\n        schema: {db}\n        objects: any\n"
                       f"        space_id: {sid}\n" for db, sid in sorted(spaces.items()))
        p.write_text(text[: m.start(1)] + body + text[m.end(1):])
        print(f"  {f}: {len(spaces)} domains written")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", nargs="*")
    ap.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    views = metric_views()
    dbs = a.db or sorted(views)
    c = client()
    have = existing_spaces(c)
    if not a.dry_run:
        ensure_folder(c)
    spaces = {}
    for db in dbs:
        body = {"title": title(db), "description": f"BIRD-Interact database {db}: its metric views only.",
                "warehouse_id": settings.databricks_warehouse_id, "serialized_space": serialized(views[db])}
        sid = have.get(title(db))
        if a.dry_run:
            print(f"  {db}: {'update' if sid else 'create'} with {len(views[db])} metric views")
            continue
        if sid:
            r = c.patch(f"/api/2.0/genie/spaces/{sid}", json=body)
        else:
            r = c.post("/api/2.0/genie/spaces", json={**body, "parent_path": PARENT})
        if r.status_code >= 400:
            sys.exit(f"{db}: HTTP {r.status_code}: {r.text[:400]}")
        sid = sid or r.json().get("space_id")
        # verify: the space holds exactly these views and nothing else
        g = c.get(f"/api/2.0/genie/spaces/{sid}", params={"include_serialized_space": "true"})
        g.raise_for_status()
        ss = json.loads(g.json().get("serialized_space") or "{}")
        got = sorted(t["identifier"] for t in ss.get("data_sources", {}).get("tables", []))
        extra = {k for k in ss if k not in ("version", "data_sources")} | \
                {k for k in ss.get("data_sources", {}) if k != "tables"}
        assert got == sorted(views[db]), f"{db}: space holds {got}"
        assert not extra or all(not ss.get(k) for k in extra), f"{db}: unexpected content {extra}"
        spaces[db] = sid
        print(f"  {db}: {sid} ({len(got)} metric views)")
    if spaces:
        write_domains(a.files, spaces)
        print(json.dumps(spaces, indent=1))


if __name__ == "__main__":
    main()

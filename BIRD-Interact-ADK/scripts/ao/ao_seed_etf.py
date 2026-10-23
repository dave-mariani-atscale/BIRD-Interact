"""Ingest the ETF warehouse into Auto Ontology with a seeded query log, then compile.

Usage (from the AO repo, whose .env points at the AO store and the warehouse):
  uv run python <ADK>/scripts/ao/ao_seed_etf.py <queries.csv> <brief dir>

AO's Postgres get_queries() reads pg_stat_activity, which holds nothing useful
here, so it is overridden to return the harvested CSV. Only the BIRD tables named
in brief/schema.txt are catalogued: the warehouse's public schema also holds
relations created by task solutions (e.g. closet_indexer_summary), which are
gold-derived, and an `aggregates` schema. Queries touching those are dropped.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd

from auto_ontology.env import load_env

load_env()  # before the imports below, some of which read the env at import

from auto_ontology.catalog import ingest_catalog  # noqa: E402
from auto_ontology.connectors.postgres import PostgresDatabase
from auto_ontology.dal.datasources import apply_metadata_batch
from auto_ontology.semantic.compile import run_semantic_compilation
from auto_ontology.utils import get_embed_params
from auto_ontology.utils.embedding import batch_embed
from auto_ontology.utils.embedding_rows import CatalogEmbeddingRowsOp
from auto_ontology.vdb import get_data_vdb
from auto_ontology.vdb.records import write_embedded_rows

SCHEMA = "public"
ALLOWED: set[str] = set()  # BIRD tables from brief/schema.txt, set in main()


class SeededPostgres(PostgresDatabase):
    def __init__(self, connection_string: str, queries_csv: str) -> None:
        super().__init__(connection_string)
        self._queries_csv = queries_csv

    def get_queries(self, hours: int = 24) -> pd.DataFrame:
        df = pd.read_csv(self._queries_csv, parse_dates=["end_time"])
        blocked = blocked_relations(self)
        keep = ~df.query_text.str.lower().apply(lambda q: any(re.search(rf"\b{t}\b", q) for t in blocked))
        logging.info("query log: %d kept, %d touch non-BIRD relations", keep.sum(), (~keep).sum())
        return df[keep][["end_time", "query_text"]]

    def get_tables(self) -> pd.DataFrame:
        return public_only(super().get_tables())

    def get_columns(self) -> pd.DataFrame:
        return public_only(super().get_columns())

    def get_views(self) -> pd.DataFrame:
        return public_only(super().get_views())

    def get_pks(self) -> pd.DataFrame:
        return public_only(super().get_pks())

    def get_fks(self) -> pd.DataFrame:
        return public_only(super().get_fks())


def public_only(df: pd.DataFrame) -> pd.DataFrame:
    if "table_schema" not in df.columns:
        return df
    keep = (df.table_schema == SCHEMA) & df.table_name.isin(ALLOWED)
    return df[keep].reset_index(drop=True)


def blocked_relations(connector: PostgresDatabase) -> set[str]:
    rels = PostgresDatabase.get_tables(connector)
    return set(rels[rels.table_schema == SCHEMA].table_name) - ALLOWED


def main(queries_csv: str, brief_dir: str) -> None:
    brief = Path(brief_dir)
    ALLOWED.update(re.findall(r'CREATE TABLE "?(\w+)', (brief / "schema.txt").read_text()))
    meanings_json = brief / "column_meaning_base.json"
    conn = os.environ["CONNECTION_STRINGS"].split(",")[0].strip()
    connector = SeededPostgres(conn, queries_csv)
    db = connector.database_name

    tables_df, columns_df = ingest_catalog(connector)
    logging.info("catalogued %d tables, %d columns", len(tables_df), len(columns_df))

    rows = []
    meanings = json.load(open(meanings_json)) if meanings_json.exists() else {}  # absent in DDL-only briefs
    for key, text in meanings.items():
        _, table, col = key.split("|")
        if not isinstance(text, str):  # JSON columns carry a per-field dict
            text = json.dumps(text)
        rows.append({"table_name": table, "column_name": col, "description": text})
    apply_metadata_batch(db, [], rows)
    logging.info("applied %d column descriptions", len(rows))

    embed_rows = CatalogEmbeddingRowsOp(database_name=db)((tables_df, columns_df))
    result = batch_embed(embed_rows, get_embed_params())
    vdb = get_data_vdb(database_name=db)
    if result is not None and not result.empty:
        logging.info("embedded %d catalog rows", write_embedded_rows(vdb, result))

    logging.info("compiled %d table visits", run_semantic_compilation(db))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main(sys.argv[1], sys.argv[2])

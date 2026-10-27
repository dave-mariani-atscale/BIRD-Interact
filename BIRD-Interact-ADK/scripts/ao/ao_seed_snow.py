"""Ingest one Snowflake schema into Auto Ontology with a seeded query log, then compile.

Usage (AO repo cwd, CONNECTION_STRINGS + POSTGRES_DATABASE in the process env):
  AODIS_SCHEMA=tpcds AODIS_CSV=<log.csv> .venv/bin/python ao_seed_snow.py

- database "atscale_tutorial_data" is lowercase: the URL carries it quoted (%22..%22) so
  Snowflake's USE DATABASE resolves it; the connector's database_name is then unquoted so
  SHOW ... IN DATABASE and AO's casefold connector match work.
- Only AODIS_SCHEMA is catalogued. get_queries() returns the CSV.
- Credit guard: any statement touching a table > BIG_ROWS rows is answered with an empty frame
  unless it is the bounded `SELECT * ... LIMIT 1000` sample (DISTINCT probes / FK sample-match
  probes on the big facts are skipped).
- The registry class is patched so get_connectors() (used by compile) returns this class too.
"""
import logging
import os
import re
import sys

import pandas as pd

from auto_ontology.env import load_env

load_env()

from auto_ontology.catalog import ingest_catalog  # noqa: E402
from auto_ontology.connectors import registry  # noqa: E402
from auto_ontology.connectors.snowflake import SnowflakeDatabase  # noqa: E402
from auto_ontology.semantic.compile import run_semantic_compilation  # noqa: E402
from auto_ontology.utils import get_embed_params  # noqa: E402
from auto_ontology.utils.embedding import batch_embed  # noqa: E402
from auto_ontology.utils.embedding_rows import CatalogEmbeddingRowsOp  # noqa: E402
from auto_ontology.vdb import get_data_vdb  # noqa: E402
from auto_ontology.vdb.records import write_embedded_rows  # noqa: E402

SCHEMA = os.environ["AODIS_SCHEMA"]
CSV = os.environ.get("AODIS_CSV", "")
BIG_ROWS = 10_000_000
BIG: set[str] = set()
SKIPPED = {"n": 0}


class SeededSnowflake(SnowflakeDatabase):
    def __init__(self, connection_string: str, schemas=None) -> None:
        super().__init__(connection_string)
        self._database_name = self._database_name.strip('"')

    def _only(self, df):
        if "table_schema" in df.columns:
            df = df[df.table_schema == SCHEMA].reset_index(drop=True)
        return df

    def get_tables(self): return self._only(super().get_tables())
    def get_columns(self): return self._only(super().get_columns())
    def get_views(self): return self._only(super().get_views())
    def get_pks(self): return self._only(super().get_pks())
    def get_fks(self):
        df = self._only(super().get_fks())
        if "referenced_schema" in df.columns:
            df = df[df.referenced_schema == SCHEMA]
        return df

    def get_queries(self, hours: int = 24) -> pd.DataFrame:
        df = pd.read_csv(CSV, parse_dates=["end_time"])
        logging.info("query log: %d rows from %s", len(df), CSV)
        return df[["end_time", "query_text"]]

    def execute(self, sql, parameters=None, *, timeout_s=None):
        low = sql.lower()
        if BIG and any(re.search(rf"\b{t}\b", low) for t in BIG) and not re.match(
            r"\s*select \* from .* limit 1000\s*$", low, re.S
        ):
            SKIPPED["n"] += 1
            return pd.DataFrame()
        return super().execute(sql, parameters, timeout_s=timeout_s)


registry.CONNECTOR_REGISTRY["snowflake"] = SeededSnowflake


def main() -> None:
    conn = os.environ["CONNECTION_STRINGS"].split(",")[0].strip()
    connector = SeededSnowflake(conn)
    db = connector.database_name
    rc = SnowflakeDatabase.execute(
        connector,
        f"SELECT table_name, row_count FROM \"{db}\".information_schema.tables WHERE table_schema='{SCHEMA}'",
    )
    BIG.update(str(r.TABLE_NAME).lower() for r in rc.itertuples() if (r.ROW_COUNT or 0) > BIG_ROWS)
    logging.info("big tables (probe-guarded): %s", sorted(BIG))

    tables_df, columns_df = ingest_catalog(connector)
    logging.info("catalogued %d tables, %d columns", len(tables_df), len(columns_df))
    embed_rows = CatalogEmbeddingRowsOp(database_name=db)((tables_df, columns_df))
    result = batch_embed(embed_rows, get_embed_params())
    vdb = get_data_vdb(database_name=db)
    if result is not None and not result.empty:
        logging.info("embedded %d catalog rows", write_embedded_rows(vdb, result))
    logging.info("compiled %d table visits", run_semantic_compilation(db))
    logging.info("guarded (skipped) statements on big tables: %d", SKIPPED["n"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()

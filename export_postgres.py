from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

try:
    from logging_config import get_logger
    from constants import (
        SCF_CSV_FILENAME, DOMAINS_CSV_FILENAME, ASSESSMENT_OBJECTIVES_CSV_FILENAME,
        RISK_CATALOG_CSV_FILENAME, THREAT_CATALOG_CSV_FILENAME,
        EVIDENCE_REQUEST_LIST_CSV_FILENAME, COLUMN_REGISTER_FILENAME
    )
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    SCF_CSV_FILENAME = "SCF.csv"
    DOMAINS_CSV_FILENAME = "SCF_Domains_Principles.csv"
    ASSESSMENT_OBJECTIVES_CSV_FILENAME = "Assessment_Objectives.csv"
    RISK_CATALOG_CSV_FILENAME = "Risk_Catalog.csv"
    THREAT_CATALOG_CSV_FILENAME = "Threat_Catalog.csv"
    EVIDENCE_REQUEST_LIST_CSV_FILENAME = "Evidence_Request_List.csv"
    COLUMN_REGISTER_FILENAME = "column_register.csv"

from export_sql import (
    split_controls_and_mappings, build_all_framework_mappings,
    build_scf_relationships, _load_entity_tables
)


def _pg_col_type(series: pd.Series) -> str:
    unique = set(str(v).lower() for v in series.dropna().unique())
    if unique.issubset({"true", "false", ""}):
        return "BOOLEAN"
    return "TEXT"


def _create_table(cur, table_name: str, df: pd.DataFrame) -> None:
    cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
    col_defs = []
    for col in df.columns:
        col_defs.append(f"    {col} {_pg_col_type(df[col])}")
    sql = f"CREATE TABLE {table_name} (\n" + ",\n".join(col_defs) + "\n);"
    cur.execute(sql)


def _insert_data(cur, table_name: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = ", ".join(df.columns)
    template = "(" + ", ".join(["%s"] * len(df.columns)) + ")"

    values = []
    for _, row in df.iterrows():
        row_vals = []
        for c in df.columns:
            v = row[c]
            if pd.isna(v):
                row_vals.append(None)
            elif str(v).lower() in ("true", "false"):
                row_vals.append(str(v).lower() == "true")
            else:
                row_vals.append(str(v))
        values.append(tuple(row_vals))

    sql = f"INSERT INTO {table_name} ({cols}) VALUES %s"
    execute_values(cur, sql, values, template=template, page_size=500)
    return len(values)


def export_to_postgres(dsn: str, clean_csv_dir: Path, scf_rel_dir: Path,
                       framework_rel_dir: Path, config_dir: Path,
                       selected_frameworks: Optional[list[str]] = None) -> None:
    logger.info("Connecting to Postgres...")

    try:
        conn = psycopg2.connect(dsn, sslmode="require")
    except psycopg2.OperationalError as e:
        raise RuntimeError(
            f"Could not connect to database. Check your credentials and try 'python main.py login <provider>'.\n"
            f"Error: {e}"
        )

    conn.autocommit = False
    cur = conn.cursor()

    try:
        df_core, df_full, fw_cols = split_controls_and_mappings(clean_csv_dir, config_dir)

        tables = {"scf_controls": df_core}
        tables.update(_load_entity_tables(clean_csv_dir))

        df_fw_mappings = build_all_framework_mappings(df_full, fw_cols, framework_rel_dir)
        tables["framework_mappings"] = df_fw_mappings

        df_scf_rels = build_scf_relationships(scf_rel_dir)
        tables["scf_relationships"] = df_scf_rels

        logger.info("Creating tables and loading data...")
        for table_name, df in tables.items():
            _create_table(cur, table_name, df)
            count = _insert_data(cur, table_name, df)
            logger.info(f"  {table_name}: {count} rows")

        conn.commit()
        logger.info("\nPostgres export complete. All data loaded successfully.")

    except Exception:
        conn.rollback()
        logger.error("Export failed. Transaction rolled back.")
        raise
    finally:
        cur.close()
        conn.close()

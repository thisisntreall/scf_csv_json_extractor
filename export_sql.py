import re
from pathlib import Path
from typing import Optional

import pandas as pd

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


def _sql_escape(value) -> str:
    if pd.isna(value) or value is None:
        return "NULL"
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _detect_boolean_col(series: pd.Series) -> bool:
    unique = set(str(v).lower() for v in series.dropna().unique())
    return unique.issubset({"true", "false", ""})


def _col_type(series: pd.Series) -> str:
    if _detect_boolean_col(series):
        return "BOOLEAN"
    return "TEXT"


def _build_create_table(table_name: str, df: pd.DataFrame) -> str:
    lines = [f"DROP TABLE IF EXISTS {table_name} CASCADE;"]
    lines.append(f"CREATE TABLE {table_name} (")
    col_defs = []
    for col in df.columns:
        col_defs.append(f"    {col} {_col_type(df[col])}")
    lines.append(",\n".join(col_defs))
    lines.append(");")
    return "\n".join(lines) + "\n"


def _build_inserts(table_name: str, df: pd.DataFrame) -> str:
    if df.empty:
        return f"-- No data for {table_name}\n"
    lines = []
    cols = ", ".join(df.columns)
    for _, row in df.iterrows():
        vals = ", ".join(_sql_escape(row[c]) for c in df.columns)
        lines.append(f"INSERT INTO {table_name} ({cols}) VALUES ({vals});")
    return "\n".join(lines) + "\n"


def _get_fw_snake_names(config_dir: Path) -> set[str]:
    reg = pd.read_csv(config_dir / COLUMN_REGISTER_FILENAME, encoding="utf-8")
    fw_raw_headers = set(reg[reg["label"] == "framework_relationship"]["raw_header"])
    fw_snake = set()
    for h in fw_raw_headers:
        h_clean = h.strip()
        if h_clean.endswith(" #"):
            h_clean = h_clean[:-2] + "_id"
        h_clean = h_clean.replace("+", " plus ")
        s = re.sub(r"[^a-z0-9]+", "_", h_clean.lower()).strip("_")
        fw_snake.add(s)
    return fw_snake


def split_controls_and_mappings(clean_csv_dir: Path, config_dir: Path):
    fw_snake = _get_fw_snake_names(config_dir)
    df = pd.read_csv(clean_csv_dir / SCF_CSV_FILENAME, dtype=str, encoding="utf-8")
    core_cols = [c for c in df.columns if c not in fw_snake]
    fw_cols = [c for c in df.columns if c in fw_snake]
    df_core = df[core_cols].copy()
    return df_core, df, fw_cols


def build_framework_mappings_from_controls(df_full: pd.DataFrame, fw_cols: list[str]) -> pd.DataFrame:
    rows = []
    for _, row in df_full.iterrows():
        scf_id = row.get("scf_id")
        if pd.isna(scf_id):
            continue
        for col in fw_cols:
            val = row[col]
            if pd.isna(val) or str(val).strip() == "":
                continue
            if str(val).lower() in ("true", "false"):
                if str(val).lower() == "true":
                    rows.append({"scf_id": scf_id, "framework": col, "control_ref": "x"})
                continue
            for ref in str(val).split("\n"):
                ref = ref.strip()
                if ref:
                    rows.append({"scf_id": scf_id, "framework": col, "control_ref": ref})
    return pd.DataFrame(rows, columns=["scf_id", "framework", "control_ref"])


def build_scf_relationships(scf_rel_dir: Path) -> pd.DataFrame:
    rows = []
    for csv_file in sorted(scf_rel_dir.glob("*.csv")):
        rel_type = csv_file.stem.replace("scf_to_", "")
        df = pd.read_csv(csv_file, dtype=str, encoding="utf-8")
        if len(df.columns) < 2:
            continue
        id_col, val_col = df.columns[0], df.columns[1]
        for _, row in df.iterrows():
            if pd.notna(row[id_col]) and pd.notna(row[val_col]):
                rows.append({"scf_id": row[id_col], "relationship_type": rel_type, "related_id": str(row[val_col])})
    return pd.DataFrame(rows, columns=["scf_id", "relationship_type", "related_id"])


def build_all_framework_mappings(df_full: pd.DataFrame, fw_cols: list[str], framework_rel_dir: Path) -> pd.DataFrame:
    df_fw = build_framework_mappings_from_controls(df_full, fw_cols)
    for csv_file in sorted(framework_rel_dir.glob("*.csv")):
        fw_name = csv_file.stem.replace("scf_to_", "")
        df = pd.read_csv(csv_file, dtype=str, encoding="utf-8")
        if len(df.columns) >= 2:
            id_col, val_col = df.columns[0], df.columns[1]
            new_rows = []
            for _, row in df.iterrows():
                if pd.notna(row[id_col]) and pd.notna(row[val_col]):
                    new_rows.append({"scf_id": row[id_col], "framework": fw_name, "control_ref": str(row[val_col])})
            if new_rows:
                df_fw = pd.concat([df_fw, pd.DataFrame(new_rows)], ignore_index=True)
    return df_fw.drop_duplicates()


def _load_entity_tables(clean_csv_dir: Path) -> dict[str, pd.DataFrame]:
    tables = {}
    entity_files = {
        "scf_domains": DOMAINS_CSV_FILENAME,
        "assessment_objectives": ASSESSMENT_OBJECTIVES_CSV_FILENAME,
        "risk_catalog": RISK_CATALOG_CSV_FILENAME,
        "threat_catalog": THREAT_CATALOG_CSV_FILENAME,
        "evidence_requests": EVIDENCE_REQUEST_LIST_CSV_FILENAME,
    }
    for table_name, filename in entity_files.items():
        path = clean_csv_dir / filename
        if path.exists():
            tables[table_name] = pd.read_csv(path, dtype=str, encoding="utf-8")
        else:
            logger.warning(f"  Skipping {table_name}: {filename} not found")
    return tables


def export_to_sql(clean_csv_dir: Path, scf_rel_dir: Path, framework_rel_dir: Path,
                  config_dir: Path, output_dir: Path,
                  selected_frameworks: Optional[list[str]] = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Generating SQL export...")

    df_core, df_full, fw_cols = split_controls_and_mappings(clean_csv_dir, config_dir)

    tables = {"scf_controls": df_core}
    tables.update(_load_entity_tables(clean_csv_dir))

    df_fw_mappings = build_all_framework_mappings(df_full, fw_cols, framework_rel_dir)
    tables["framework_mappings"] = df_fw_mappings

    df_scf_rels = build_scf_relationships(scf_rel_dir)
    tables["scf_relationships"] = df_scf_rels

    schema_parts = []
    for table_name, df in tables.items():
        schema_parts.append(_build_create_table(table_name, df))
    schema_sql = "\n".join(schema_parts)
    (output_dir / "01_schema.sql").write_text(schema_sql, encoding="utf-8")
    logger.info("  Written 01_schema.sql")

    all_sql = [schema_sql, ""]
    file_num = 2
    for table_name, df in tables.items():
        insert_sql = _build_inserts(table_name, df)
        filename = f"{file_num:02d}_{table_name}.sql"
        (output_dir / filename).write_text(insert_sql, encoding="utf-8")
        logger.info(f"  Written {filename} ({len(df)} rows)")
        all_sql.append(insert_sql)
        file_num += 1

    combined = "\n".join(all_sql)
    (output_dir / f"{file_num:02d}_all.sql").write_text(combined, encoding="utf-8")
    logger.info(f"  Written {file_num:02d}_all.sql (combined)")
    logger.info(f"\nSQL export complete. Files saved to '{output_dir}'")

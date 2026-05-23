# SQL & Postgres Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `sql`, `supabase`, and `neon` export formats to the SCF pipeline so users can generate SQL files or push data directly to a managed Postgres database.

**Architecture:** Three new modules — `auth_manager.py` (interactive login + credential storage for Supabase/Neon), `export_sql.py` (generates .sql files from cleaned CSVs and relationships), and `export_postgres.py` (connects to Postgres and loads data). The cleaned CSVs and relationship files are the input; the column register determines which columns are core vs framework mappings. All three modules are called from `run_pipeline()` in `main.py`.

**Tech Stack:** `psycopg2-binary` (Postgres driver), `python-dotenv` (.env loading), existing `pandas` for CSV reading.

---

### Task 1: Add dependencies and constants

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements.lock` (regenerated)
- Modify: `constants.py`
- Modify: `.gitignore`
- Modify: `.env.example`

- [ ] **Step 1: Add new dependencies to requirements.txt**

```
requests
tqdm
pyinstaller
packaging
altgraph
setuptools
pandas
openpyxl
psycopg2-binary
python-dotenv
```

- [ ] **Step 2: Regenerate lock file and sync**

Run: `uv pip compile requirements.txt -o requirements.lock && uv pip sync requirements.lock`

- [ ] **Step 3: Add constants to constants.py**

Add at the end of `constants.py`:

```python
# --- SQL/Postgres Export Configuration ---
DIR_SQL_OUTPUT = "sql_output"

# Core attribute columns to include in scf_controls table (everything else is a framework mapping)
# This list is derived from the column register labels at build time, not hardcoded here.

# --- Auth Configuration ---
ENV_SUPABASE_URL = "SUPABASE_URL"
ENV_SUPABASE_KEY = "SUPABASE_SERVICE_KEY"
ENV_NEON_DATABASE_URL = "NEON_DATABASE_URL"
```

- [ ] **Step 4: Add sql_output/ to .gitignore**

Add `sql_output/` to the "Generated data directories" section.

- [ ] **Step 5: Update .env.example**

Replace contents with:

```
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# Neon
NEON_DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt constants.py .gitignore .env.example
git commit -m "feat: add dependencies and constants for SQL/Postgres export"
```

---

### Task 2: Create auth_manager.py

**Files:**
- Create: `auth_manager.py`

This module handles interactive login for Supabase and Neon, reads/writes credentials to `.env`.

- [ ] **Step 1: Create auth_manager.py**

```python
import getpass
import re
from pathlib import Path

try:
    from logging_config import get_logger
    from constants import ENV_SUPABASE_URL, ENV_SUPABASE_KEY, ENV_NEON_DATABASE_URL
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    ENV_SUPABASE_URL = "SUPABASE_URL"
    ENV_SUPABASE_KEY = "SUPABASE_SERVICE_KEY"
    ENV_NEON_DATABASE_URL = "NEON_DATABASE_URL"

ENV_FILE = Path(__file__).parent.resolve() / ".env"


def _read_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    lines = []
    for key, value in env.items():
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    logger.info(f"Credentials saved to {ENV_FILE}")


def login_supabase() -> None:
    env = _read_env()
    print("\n--- Supabase Login ---")
    print("You can find these in your Supabase project: Settings > API\n")
    url = input("Project URL (e.g. https://xxx.supabase.co): ").strip()
    key = getpass.getpass("Service Role Key: ").strip()

    if not url or not key:
        print("Error: Both URL and key are required.")
        return

    env[ENV_SUPABASE_URL] = url
    env[ENV_SUPABASE_KEY] = key
    _write_env(env)
    print("Supabase credentials saved. You can now use --format supabase")


def login_neon() -> None:
    env = _read_env()
    print("\n--- Neon Login ---")
    print("You can find your connection string in the Neon console dashboard.\n")
    conn_str = getpass.getpass("Connection string (postgresql://...): ").strip()

    if not conn_str:
        print("Error: Connection string is required.")
        return

    if not conn_str.startswith("postgresql://") and not conn_str.startswith("postgres://"):
        print("Error: Connection string must start with postgresql:// or postgres://")
        return

    env[ENV_NEON_DATABASE_URL] = conn_str
    _write_env(env)
    print("Neon credentials saved. You can now use --format neon")


def get_supabase_dsn() -> str | None:
    env = _read_env()
    url = env.get(ENV_SUPABASE_URL)
    key = env.get(ENV_SUPABASE_KEY)
    if not url or not key:
        return None
    # Supabase Postgres is at db.<project-ref>.supabase.co:5432
    # Extract project ref from URL
    match = re.match(r"https://([^.]+)\.supabase\.co", url)
    if not match:
        logger.error(f"Could not parse Supabase URL: {url}")
        return None
    project_ref = match.group(1)
    return f"postgresql://postgres.{project_ref}:{key}@aws-0-us-east-1.pooler.supabase.com:6543/postgres"


def get_neon_dsn() -> str | None:
    env = _read_env()
    return env.get(ENV_NEON_DATABASE_URL)
```

- [ ] **Step 2: Commit**

```bash
git add auth_manager.py
git commit -m "feat: add auth_manager for Supabase/Neon login"
```

---

### Task 3: Create export_sql.py

**Files:**
- Create: `export_sql.py`

Generates `.sql` files from cleaned CSVs and relationship files. Reads the column register to split `scf_controls` core columns from framework mapping columns.

- [ ] **Step 1: Create export_sql.py**

```python
import csv
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


def _sql_escape(value: str) -> str:
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
        col_type = _col_type(df[col])
        col_defs.append(f"    {col} {col_type}")
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


def _get_core_columns(clean_csv_dir: Path, config_dir: Path) -> list[str]:
    from clean_csv import to_snake_case
    reg = pd.read_csv(config_dir / COLUMN_REGISTER_FILENAME, encoding="utf-8")
    fw_raw = set(reg[reg["label"] == "framework_relationship"]["raw_header"])
    remove_raw = set(reg[reg["label"] == "remove"]["raw_header"])
    exclude_raw = fw_raw | remove_raw

    all_cols = list(pd.read_csv(clean_csv_dir / SCF_CSV_FILENAME, nrows=0, encoding="utf-8").columns)
    return all_cols  # already snake_case after cleaning


def _split_controls_and_mappings(clean_csv_dir: Path, config_dir: Path):
    from clean_csv import to_snake_case

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

    df = pd.read_csv(clean_csv_dir / SCF_CSV_FILENAME, dtype=str, encoding="utf-8")
    core_cols = [c for c in df.columns if c not in fw_snake]
    fw_cols = [c for c in df.columns if c in fw_snake]

    df_core = df[core_cols].copy()
    return df_core, df, fw_cols


def _build_framework_mappings(df_full: pd.DataFrame, fw_cols: list[str]) -> pd.DataFrame:
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


def _build_scf_relationships(scf_rel_dir: Path) -> pd.DataFrame:
    rows = []
    for csv_file in sorted(scf_rel_dir.glob("*.csv")):
        rel_type = csv_file.stem.replace("scf_to_", "")
        df = pd.read_csv(csv_file, dtype=str, encoding="utf-8")
        if len(df.columns) < 2:
            continue
        id_col = df.columns[0]
        val_col = df.columns[1]
        for _, row in df.iterrows():
            scf_id = row[id_col]
            related = row[val_col]
            if pd.notna(scf_id) and pd.notna(related):
                rows.append({"scf_id": scf_id, "relationship_type": rel_type, "related_id": str(related)})
    return pd.DataFrame(rows, columns=["scf_id", "relationship_type", "related_id"])


def export_to_sql(clean_csv_dir: Path, scf_rel_dir: Path, framework_rel_dir: Path,
                  config_dir: Path, output_dir: Path,
                  selected_frameworks: Optional[list[str]] = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Generating SQL export...")

    # Split controls into core attributes and framework mappings
    df_core, df_full, fw_cols = _split_controls_and_mappings(clean_csv_dir, config_dir)

    # Load other entity tables
    tables = {"scf_controls": df_core}

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

    # Build junction tables
    df_fw_mappings = _build_framework_mappings(df_full, fw_cols)
    tables["framework_mappings"] = df_fw_mappings

    df_scf_rels = _build_scf_relationships(scf_rel_dir)
    tables["scf_relationships"] = df_scf_rels

    # Also include framework relationship files from the relationship dir
    for csv_file in sorted(framework_rel_dir.glob("*.csv")):
        fw_name = csv_file.stem.replace("scf_to_", "")
        df = pd.read_csv(csv_file, dtype=str, encoding="utf-8")
        if len(df.columns) >= 2:
            id_col, val_col = df.columns[0], df.columns[1]
            for _, row in df.iterrows():
                if pd.notna(row[id_col]) and pd.notna(row[val_col]):
                    df_fw_mappings = pd.concat([df_fw_mappings, pd.DataFrame([{
                        "scf_id": row[id_col], "framework": fw_name, "control_ref": str(row[val_col])
                    }])], ignore_index=True)
    # Deduplicate
    df_fw_mappings = df_fw_mappings.drop_duplicates()
    tables["framework_mappings"] = df_fw_mappings

    # Write schema file
    schema_parts = []
    for table_name, df in tables.items():
        schema_parts.append(_build_create_table(table_name, df))
    schema_sql = "\n".join(schema_parts)
    (output_dir / "01_schema.sql").write_text(schema_sql, encoding="utf-8")
    logger.info("  Written 01_schema.sql")

    # Write individual insert files
    all_sql = [schema_sql, ""]
    file_num = 2
    for table_name, df in tables.items():
        insert_sql = _build_inserts(table_name, df)
        filename = f"{file_num:02d}_{table_name}.sql"
        (output_dir / filename).write_text(insert_sql, encoding="utf-8")
        logger.info(f"  Written {filename} ({len(df)} rows)")
        all_sql.append(insert_sql)
        file_num += 1

    # Write combined file
    combined = "\n".join(all_sql)
    (output_dir / f"{file_num:02d}_all.sql").write_text(combined, encoding="utf-8")
    logger.info(f"  Written {file_num:02d}_all.sql (combined)")

    logger.info(f"\nSQL export complete. Files saved to '{output_dir}'")
```

- [ ] **Step 2: Commit**

```bash
git add export_sql.py
git commit -m "feat: add SQL file export for SCF data"
```

---

### Task 4: Create export_postgres.py

**Files:**
- Create: `export_postgres.py`

Shared Postgres push logic. Takes a DSN, creates tables, bulk inserts data. Used by both Supabase and Neon formats.

- [ ] **Step 1: Create export_postgres.py**

```python
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

from export_sql import _split_controls_and_mappings, _build_framework_mappings, _build_scf_relationships


def _pg_col_type(series: pd.Series) -> str:
    unique = set(str(v).lower() for v in series.dropna().unique())
    if unique.issubset({"true", "false", ""}):
        return "BOOLEAN"
    return "TEXT"


def _create_table(cur, table_name: str, df: pd.DataFrame) -> None:
    cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
    col_defs = []
    for col in df.columns:
        col_type = _pg_col_type(df[col])
        col_defs.append(f"    {col} {col_type}")
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
        # Build data
        df_core, df_full, fw_cols = _split_controls_and_mappings(clean_csv_dir, config_dir)

        tables = {"scf_controls": df_core}

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

        # Build junction tables from relationship dirs
        df_fw_mappings = _build_framework_mappings(df_full, fw_cols)
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
                    df_fw_mappings = pd.concat([df_fw_mappings, pd.DataFrame(new_rows)], ignore_index=True)
        df_fw_mappings = df_fw_mappings.drop_duplicates()
        tables["framework_mappings"] = df_fw_mappings

        df_scf_rels = _build_scf_relationships(scf_rel_dir)
        tables["scf_relationships"] = df_scf_rels

        # Create tables and insert data
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
```

- [ ] **Step 2: Commit**

```bash
git add export_postgres.py
git commit -m "feat: add Postgres direct push export"
```

---

### Task 5: Integrate into main.py

**Files:**
- Modify: `main.py`

Add `login` subcommand, extend `--format` choices, call new exporters in `run_pipeline()`.

- [ ] **Step 1: Add imports at top of main.py**

After the existing `from export_mongodb import create_mongodb_structure` line, add:

```python
from export_sql import export_to_sql
from export_postgres import export_to_postgres
from auth_manager import login_supabase, login_neon, get_supabase_dsn, get_neon_dsn
```

- [ ] **Step 2: Add SQL/Postgres export to run_pipeline()**

After the JSON export block (after line 237 `logger.info(f"MongoDB-optimized file created: {mongodb_file}")`), add:

```python
    # Export to SQL if requested
    if output_format == "sql":
        sql_dir = output_dir / DIR_SQL_OUTPUT
        logger.info("\nExporting data to SQL format...")
        export_to_sql(clean_csv_dir, scf_rel_dir, framework_rel_dir, config_dir, sql_dir,
                      selected_frameworks=selected_frameworks)

    # Export to Supabase if requested
    if output_format == "supabase":
        dsn = get_supabase_dsn()
        if not dsn:
            logger.info("No Supabase credentials found. Starting login...")
            login_supabase()
            dsn = get_supabase_dsn()
        if dsn:
            logger.info("\nExporting data to Supabase...")
            export_to_postgres(dsn, clean_csv_dir, scf_rel_dir, framework_rel_dir, config_dir,
                              selected_frameworks=selected_frameworks)
        else:
            logger.error("Could not get Supabase connection. Skipping database export.")

    # Export to Neon if requested
    if output_format == "neon":
        dsn = get_neon_dsn()
        if not dsn:
            logger.info("No Neon credentials found. Starting login...")
            login_neon()
            dsn = get_neon_dsn()
        if dsn:
            logger.info("\nExporting data to Neon...")
            export_to_postgres(dsn, clean_csv_dir, scf_rel_dir, framework_rel_dir, config_dir,
                              selected_frameworks=selected_frameworks)
        else:
            logger.error("Could not get Neon connection. Skipping database export.")
```

- [ ] **Step 3: Add DIR_SQL_OUTPUT to imports in main.py**

In the `from constants import (...)` block, add `DIR_SQL_OUTPUT` to the list.

- [ ] **Step 4: Add sql_output dir to do_clean()**

In the `dirs_to_remove` list inside `do_clean()`, add:

```python
PROJECT_ROOT / DIR_SQL_OUTPUT,
```

- [ ] **Step 5: Extend --format choices**

Change the `parser_run.add_argument("-f", "--format", ...)` call:

```python
    parser_run.add_argument(
        "-f", "--format",
        choices=["csv", "json", "both", "sql", "supabase", "neon"],
        default="csv",
        help="Output format: 'csv' (default), 'json', 'both', 'sql', 'supabase', or 'neon'."
    )
```

- [ ] **Step 6: Add login subcommand**

After the `update-register` subparser block, add:

```python
    # 'login' command
    parser_login = subparsers.add_parser("login", help="Authenticate with a database provider (supabase or neon).")
    parser_login.add_argument(
        "provider",
        choices=["supabase", "neon"],
        help="The database provider to authenticate with."
    )
```

- [ ] **Step 7: Add login handler to the command dispatch**

After the `elif args.command == "update-register":` block, add:

```python
    elif args.command == "login":
        if args.provider == "supabase":
            login_supabase()
        elif args.provider == "neon":
            login_neon()
```

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat: integrate SQL/Supabase/Neon export formats into pipeline"
```

---

### Task 6: Test SQL export end-to-end

**Files:** None (testing only)

- [ ] **Step 1: Clean previous output and run SQL export**

```bash
rm -rf sql_output/
.venv/bin/python main.py run --format sql
```

Expected: Pipeline completes, `sql_output/` directory created with numbered .sql files.

- [ ] **Step 2: Verify SQL files were generated**

```bash
ls -la sql_output/
```

Expected: `01_schema.sql`, `02_scf_controls.sql`, etc., plus a combined `_all.sql` file.

- [ ] **Step 3: Verify schema SQL is valid**

```bash
head -30 sql_output/01_schema.sql
```

Expected: Valid `DROP TABLE IF EXISTS` and `CREATE TABLE` statements with correct column names.

- [ ] **Step 4: Verify insert SQL is valid**

```bash
head -5 sql_output/02_scf_controls.sql
```

Expected: Valid `INSERT INTO scf_controls (...)` statements with properly escaped values.

- [ ] **Step 5: Verify framework_mappings table**

```bash
head -10 sql_output/*framework_mappings*
```

Expected: `INSERT INTO framework_mappings (scf_id, framework, control_ref)` with actual framework data.

- [ ] **Step 6: Check row counts**

```bash
wc -l sql_output/*.sql
```

Expected: Substantial row counts — scf_controls should have ~1468 inserts, framework_mappings should be large (tens of thousands).

---

### Task 7: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update format choices in CLI docs**

In the "Command-Line Interface" section, after the `--format both` example, add:

```markdown
*   **Run with SQL file output:**

    ```bash
    python main.py run --format sql
    ```

    Generates `.sql` files (schema + inserts) in the `sql_output/` directory, ready to run against any Postgres database.

*   **Push directly to Supabase:**

    ```bash
    python main.py login supabase
    python main.py run --format supabase
    ```

*   **Push directly to Neon:**

    ```bash
    python main.py login neon
    python main.py run --format neon
    ```
```

- [ ] **Step 2: Add sql_output/ to Output Structure**

In the output directory tree, add:

```
├── sql_output/            # SQL export files (when SQL format selected)
│   ├── 01_schema.sql      # CREATE TABLE statements
│   ├── 02_scf_controls.sql
│   ├── ...
│   └── XX_all.sql         # Combined schema + all inserts
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add SQL/Supabase/Neon export documentation"
```

---

### Task 8: Final validation

- [ ] **Step 1: Run the full pipeline with each format to verify no regressions**

```bash
rm -rf csv_cleaned/ scf_relationships/ framework_relationships/ json_output/ sql_output/
.venv/bin/python main.py run --format both
.venv/bin/python main.py run --format sql
```

Expected: Both complete without errors.

- [ ] **Step 2: Verify login --help works**

```bash
.venv/bin/python main.py login --help
```

Expected: Shows `supabase` and `neon` as provider choices.

- [ ] **Step 3: Verify clean removes sql_output**

```bash
.venv/bin/python main.py clean
ls sql_output/ 2>&1
```

Expected: `sql_output/` directory removed.

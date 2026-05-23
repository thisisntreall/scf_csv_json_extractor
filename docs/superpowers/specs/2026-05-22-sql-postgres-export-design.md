# SQL & Postgres Export for SCF Extractor

## Summary

Add three new export formats to the SCF pipeline: `sql` (generates .sql files), `supabase` (direct push), and `neon` (direct push). Both Supabase and Neon are Postgres, so the core logic is shared — only the auth flow differs.

## New Export Formats

| Format | Flag | What it does |
|--------|------|-------------|
| SQL files | `--format sql` | Generates `.sql` files with CREATE TABLE + INSERT statements |
| Supabase | `--format supabase` | Authenticates and pushes data directly to a Supabase project |
| Neon | `--format neon` | Authenticates and pushes data directly to a Neon database |

Existing formats (`csv`, `json`, `both`) are unchanged. The `both` flag continues to mean CSV + JSON. The new formats can be combined: `--format sql`, `--format supabase`, `--format neon`. Each is independent.

## Database Schema

Eight normalized tables. The many-to-many relationship CSVs (249 framework files + 4 SCF entity files) are consolidated into two junction tables with a `relationship_type` column instead of 253 separate tables.

### Tables

```sql
-- Core entity tables
scf_controls          -- Main controls (from SCF.csv cleaned)
scf_domains           -- Domain/principle definitions (from SCF_Domains_Principles.csv)
assessment_objectives -- Assessment objective mappings (from Assessment_Objectives.csv)
risk_catalog          -- Risk definitions (from Risk_Catalog.csv)
threat_catalog        -- Threat definitions (from Threat_Catalog.csv)
evidence_requests     -- Evidence request list (from Evidence_Request_List.csv)

-- Junction tables (many-to-many)
scf_relationships     -- SCF entity relationships (control->domain, control->threat, etc.)
framework_mappings    -- Framework relationships (control->NIST, control->ISO, etc.)
```

### Junction Table Design

**scf_relationships:**
```
scf_id TEXT NOT NULL
relationship_type TEXT NOT NULL  -- e.g. 'domain', 'evidence_request', 'risk_threat_summary', 'control_threat_summary'
related_id TEXT NOT NULL
PRIMARY KEY (scf_id, relationship_type, related_id)
```

**framework_mappings:**
```
scf_id TEXT NOT NULL
framework TEXT NOT NULL          -- e.g. 'nist_800_53_r5', 'iso_27001_2022'
control_ref TEXT NOT NULL        -- The framework's control reference
PRIMARY KEY (scf_id, framework, control_ref)
```

### Core Table Columns

Each core table mirrors its cleaned CSV columns directly. All columns are TEXT except boolean columns (which are already converted to True/False by the cleaning step) — those become BOOLEAN.

The `scf_controls` table has ~30 core attribute columns. The 200+ framework columns are NOT included in this table — they're normalized into `framework_mappings` instead.

## Authentication

### Login Commands

```bash
python main.py login supabase    # Interactive: prompts for project URL + service role key
python main.py login neon        # Interactive: prompts for connection string
```

Credentials are saved to `.env` in the project root:
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
NEON_DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
```

`.env` is already in `.gitignore`.

### Connection Flow

When `--format supabase` or `--format neon` is used:
1. Load credentials from `.env`
2. If not found, run the interactive login flow
3. Connect via `psycopg2`
4. Create tables (DROP IF EXISTS + CREATE)
5. Bulk insert data using `executemany` with parameterized queries
6. Report row counts

## New Files

| File | Purpose |
|------|---------|
| `export_sql.py` | Generates .sql files from cleaned CSVs and relationship files |
| `export_postgres.py` | Shared Postgres push logic (schema creation, data loading) |
| `auth_manager.py` | Login flows for Supabase and Neon, .env read/write |

## Modified Files

| File | Change |
|------|--------|
| `main.py` | Add `login` subcommand, add `sql`/`supabase`/`neon` to `--format` choices, call new exporters in `run_pipeline()` |
| `constants.py` | Add `DIR_SQL_OUTPUT`, new file name constants |
| `requirements.txt` | Add `psycopg2-binary`, `python-dotenv` |
| `README.md` | Document new formats and login commands |

## SQL File Output

When `--format sql` is used, generates files in `sql_output/`:

```
sql_output/
├── 01_schema.sql           -- All CREATE TABLE statements
├── 02_scf_controls.sql     -- INSERT statements for controls
├── 03_scf_domains.sql      -- INSERT statements for domains
├── 04_assessment_objectives.sql
├── 05_risk_catalog.sql
├── 06_threat_catalog.sql
├── 07_evidence_requests.sql
├── 08_scf_relationships.sql
├── 09_framework_mappings.sql
└── 10_all.sql              -- Combined file (schema + all inserts)
```

## SCF Controls Table Strategy

The cleaned SCF.csv has ~260 columns, most of which are framework mapping columns. For the SQL/Postgres export:

- **Core attribute columns** (~30) go into `scf_controls`: scf_id, scf_domain, scf_control, description, control question, weighting, PPTDF, SCRM, SCR-CMM levels, SCF CORE flags, etc.
- **Framework mapping columns** (~230) are normalized into `framework_mappings` junction table by reading the column register to identify which columns are labeled `framework_relationship`
- This avoids a 260-column table and makes querying by framework natural: `SELECT * FROM framework_mappings WHERE framework = 'nist_800_53_r5'`

## Error Handling

- Connection failures: clear error message with suggestion to re-run `login`
- Table creation: uses DROP IF EXISTS + CREATE (fresh load each run, not incremental)
- Data loading: transaction-wrapped, rolls back on failure
- Missing credentials: automatically triggers interactive login flow

## Dependencies

- `psycopg2-binary` — Postgres driver (works with both Supabase and Neon)
- `python-dotenv` — Load .env credentials

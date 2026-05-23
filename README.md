# Secure Controls Framework (SCF) Data Pipeline

A data pipeline for processing the [Secure Controls Framework (SCF)](https://github.com/securecontrolsframework/securecontrolsframework). Downloads the latest SCF data directly from the source and exports to CSV, JSON, SQL, Supabase, or Neon.

Originally created by [dwilbourn-git](https://github.com/dwilbourn-git/scf_csv_json_extractor). This fork adds SQL/Postgres export and auto-adapts to SCF schema changes.

## Key Features

*   **Always Current:** Automatically detects and registers new SCF columns and frameworks — no manual config updates needed.
*   **Multiple Export Formats:** CSV, JSON, SQL files, or direct push to Supabase/Neon Postgres.
*   **Relationship Mapping:** Generates many-to-many relationship tables between controls and 249+ frameworks (NIST, ISO, PCI DSS, GovRAMP, OWASP, etc.).
*   **Normalized SQL Schema:** 8-table normalized schema with junction tables for framework mappings and SCF relationships.
*   **Graphical User Interface (GUI):** Tkinter application for selecting output directories, frameworks, and formats.
*   **Clean CSV Output:** Normalized, database-ready files with standardized snake_case column names.
*   **Modern Tooling:** Uses `uv` for fast and reproducible dependency management.

## Getting Started

### Prerequisites

*   Python 3.10+
*   `uv` (Python package installer and manager)

### Setup

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/thisisntreall/scf_csv_json_extractor.git
    cd scf_csv_json_extractor
    ```

2.  **Create a virtual environment:**

    ```bash
    uv venv
    ```

3.  **Install dependencies:**

    ```bash
    uv pip sync requirements.lock
    ```

    Or to regenerate the lock file from requirements.txt:

    ```bash
    uv pip compile requirements.txt -o requirements.lock
    uv pip sync requirements.lock
    ```

## Usage

### Running the GUI Application

To run the GUI application, execute the `app.py` script:

```bash
python app.py
```

The GUI will allow you to:
1. Select an output directory for the cleaned data files
2. Choose output format: CSV, JSON, or both
3. Select specific frameworks or export all 258 frameworks
4. Run the full pipeline with a single click
5. View progress and status messages

### Command-Line Interface (CLI)

The project can also be controlled via the command line using the `main.py` script:

*   **Run the full data pipeline:**

    ```bash
    python main.py run
    ```

    This will:
    - Download the latest SCF Excel file from GitHub
    - Split the workbook into individual CSV files
    - Clean and normalize the data
    - Generate relationship mapping files

*   **Run with JSON output:**

    ```bash
    python main.py run --format json
    ```

    Or export both CSV and JSON:

    ```bash
    python main.py run --format both
    ```

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

*   **Check SCF version:**

    ```bash
    python main.py version
    ```

*   **Validate data integrity:**

    ```bash
    python main.py validate
    ```

    This checks for broken foreign key relationships.

*   **Clean up generated files:**

    ```bash
    python main.py clean
    ```

*   **For a full list of commands:**

    ```bash
    python main.py --help
    ```

### Building the Windows Executable

To build a standalone Windows executable:

```bash
python build.py
```

The executable will be created in the `dist` directory as `Dewis SCF Extractor.exe`.

## Output Structure

When the pipeline runs, it creates the following directory structure:

```
output_directory/
├── scf_full/              # Downloaded Excel file and metadata
├── csv/                   # Raw CSV files split from Excel
├── csv_cleaned/           # Cleaned and normalized CSV files
├── scf_relationships/     # SCF-to-entity relationship mappings
├── framework_relationships/ # Framework-to-control relationship mappings
├── json_output/           # JSON export files (when JSON format selected)
│   ├── scf_mongodb.json   # MongoDB-optimized denormalized structure
│   └── *.json             # Individual entity JSON files
└── sql_output/            # SQL export files (when SQL format selected)
    ├── 01_schema.sql      # CREATE TABLE statements
    ├── 02-09_*.sql        # INSERT statements per table
    └── 10_all.sql         # Combined schema + all inserts
```

### Main Data Files

- **SCF.csv**: Main controls file with all intrinsic control attributes
- **SCF_Domains_Principles.csv**: Domain and principle definitions
- **Assessment_Objectives.csv**: Assessment objective mappings
- **Risk_Catalog.csv**: Risk definitions
- **Threat_Catalog.csv**: Threat definitions

### Relationship Files

Relationship files use a two-column format for easy database import:
- SCF relationships: Link controls to SCF entities (domains, risks, threats, etc.)
- Framework relationships: Link controls to external frameworks (NIST, ISO, etc.)

### MongoDB JSON Structure

The `scf_mongodb.json` file provides a denormalized, MongoDB-optimized structure where:
- Each control is a complete document with embedded relationships
- Domains, assessment objectives, threats, risks, and evidence requests are embedded directly
- Framework mappings are included as sub-documents
- **Blank fields are omitted** to reduce document size and follow MongoDB best practices
- Ready for direct import with `mongoimport` or MongoDB drivers

Example structure:
```json
{
  "_id": "GOV-01",
  "control_id": "GOV-01",
  "title": "Statutory, Regulatory & Contractual Compliance",
  "domain": {
    "identifier": "GOV",
    "name": "Governance, Risk Management & Compliance"
  },
  "assessment_objectives": [...],
  "threats": [...],
  "framework_mappings": {
    "nist_800_53_rev5": ["PM-1"],
    "iso_iec_27001_2022": ["5.1"]
  }
}
```
### SQL Schema

The SQL export normalizes the data into 8 tables:

| Table | Description |
|-------|-------------|
| `scf_controls` | Core control attributes (ID, domain, description, PPTDF, SCR-CMM, etc.) |
| `scf_domains` | Domain and principle definitions |
| `assessment_objectives` | Assessment objective mappings |
| `risk_catalog` | Risk definitions |
| `threat_catalog` | Threat definitions |
| `evidence_requests` | Evidence request list |
| `framework_mappings` | Junction table: control-to-framework mappings (67K+ rows) |
| `scf_relationships` | Junction table: control-to-entity relationships (75K+ rows) |

### Credits

All credit for the Secure Controls Framework, its content and its relationship mappings goes to the SCF team: https://github.com/securecontrolsframework

Original extractor tool by [dwilbourn-git](https://github.com/dwilbourn-git/scf_csv_json_extractor).
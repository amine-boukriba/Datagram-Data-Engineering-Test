# Tunisianet Data Pipeline

A data pipeline that scrapes product listings from [tunisianet.com.tn](https://www.tunisianet.com.tn), loads them into PostgreSQL, and transforms them with dbt.

## How it works

```
tunisianet.com.tn
       │
       ▼
  scraping.py          ← scrapes product pages (name, price, brand, …)
       │  saves JSON to data/
       ▼
  load_to_db.py        ← upserts JSON files into PostgreSQL (raw_data table)
       │
       ▼
  dbt (tunisianet_dbt) ← transforms raw data through three layers
       │
       ├── staging/stg_raw_data   (deduplicate, latest row per product)
       ├── core/product           (incremental SCD: tracks created / updated)
       ├── core/price             (price history)
       └── analytics/             (aggregations & rankings)
```

The scraper rotates User-Agent headers and adds random delays between pages and categories to be respectful of the target site. A retry mechanism with exponential back-off handles transient failures.

`load_to_db.py` tracks every imported file in an `import_log` table so re-running it never double-counts data. Pass `--force <file>` to re-import a specific file.

---

## Requirements

- Python 3.10+
- Docker & Docker Compose
- dbt Core (`pip install dbt-postgres`)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/amine-boukriba/Datagram-Data-Engineering-Test.git
cd Datagram-Data-Engineering-Test
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install requests beautifulsoup4 fake-useragent psycopg2-binary python-dotenv
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your database credentials:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
```

### 5. Start PostgreSQL with Docker

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```

### 6. Set up dbt

It is recommended to create a dedicated virtual environment for dbt to avoid dependency conflicts with the scraper packages.

```bash
cd dbt/tunisianet_dbt

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install dbt-postgres
dbt deps
```

Configure `~/.dbt/profiles.yml` to point to your database (see [dbt docs](https://docs.getdbt.com/docs/core/connect-data-platform/postgres-setup)).

---

## Usage

### Step 1 — Scrape products

```bash
python scraping.py
```

This creates a timestamped JSON file in `data/` (e.g. `data/products_20260526_174000.json`).

To scrape additional categories, open `scraping.py` and uncomment the desired entries in the `CATEGORIES` list.

### Step 2 — Load into PostgreSQL

```bash
# Load all new files in data/ (already-imported files are skipped automatically)
python load_to_db.py
```

### Step 3 — Run dbt transformations

```bash
cd dbt/tunisianet_dbt
dbt run
dbt test
```

---

## Project structure

```
.
├── scraping.py               # Web scraper
├── load_to_db.py             # JSON → PostgreSQL loader
├── .env.example              # Environment variable template
├── docker-compose.example.yml
├── data/                     # Scraped JSON files (git-ignored)
└── dbt/
    └── tunisianet_dbt/
        ├── models/
        │   ├── staging/      # stg_raw_data — deduplication
        │   ├── core/         # product, price — incrementally updated
        │   └── analytics/    # aggregations & rankings
        ├── dbt_project.yml
        └── packages.yml
```

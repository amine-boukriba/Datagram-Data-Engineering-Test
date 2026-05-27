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
       ├── core/price             (price history with discount)
       ├── core/ranking           (rank history, current and historical max)
       └── analytics/             (brand-level aggregations)
```

The scraper rotates User-Agent headers and adds random delays between pages and categories to be respectful of the target site. A retry mechanism with exponential back-off handles transient failures.

`load_to_db.py` tracks every imported file in an `import_log` table so re-running it never double-counts data. Pass `--force <file>` to re-import a specific file.

---

## Quick start — Docker (recommended)

The entire pipeline runs in containers. You only need Docker Desktop installed.

```bash
git clone https://github.com/amine-boukriba/Datagram-Data-Engineering-Test.git
cd Datagram-Data-Engineering-Test

# Copy and fill in credentials
cp .env.example .env

# Build images and run the full pipeline
docker compose build
docker compose up
```

`docker compose up` executes the four services in sequence:

| Service | What it does |
|---|---|
| `postgres` | Starts the database, waits until healthy |
| `scraper` | Runs `scraping.py`, writes JSON to a shared volume |
| `loader` | Runs `load_to_db.py`, upserts JSON into `raw_data` |
| `dbt` | Runs `dbt run && dbt test` against the loaded data |

To run the pipeline again (e.g. next day):

```bash
docker compose up scraper loader dbt
```

---

## Inspecting the data

Once the pipeline has run, open a `psql` shell inside the postgres container (use the credentials from your `.env`):

```bash
docker compose exec postgres psql -U <DB_USER> -d <DB_NAME>
```

### Top brands by average price

```sql
SELECT brand, average_price, median_rank
FROM analytics
ORDER BY average_price DESC
LIMIT 10;
```

### Products with the biggest current discount

```sql
SELECT p.name, p.brand, pr.price, pr.price_old, pr.discount
FROM product p
JOIN price pr ON p.id = pr.product_id
WHERE pr.discount > 0
ORDER BY pr.discount DESC
LIMIT 10;
```

### Most recently discovered products

```sql
SELECT id, name, brand, created
FROM product
ORDER BY created DESC
LIMIT 10;
```

### Best-ranked products per brand

```sql
SELECT p.brand, p.name, r.rank, r.max_rank
FROM product p
JOIN ranking r ON p.id = r.product_id
WHERE r.rank <= 10
ORDER BY p.brand, r.rank;
```

Exit `psql` with `\q`.

---

## Manual setup (local)

Use this path if you prefer to run the scripts directly without Docker. PostgreSQL still runs in a container — only the Python scripts and dbt run on your host.

**Requirements:** Python 3.10+, Docker (for PostgreSQL).

### Setup

**1. Clone the repository**

```bash
git clone https://github.com/amine-boukriba/Datagram-Data-Engineering-Test.git
cd Datagram-Data-Engineering-Test
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

**3. Install Python dependencies**

```bash
pip install -r requirements.txt
pip install dbt-postgres
```

**4. Configure environment variables**

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

**5. Start PostgreSQL**

```bash
docker compose up postgres -d
```

**6. Install dbt packages**

```bash
cd dbt/tunisianet_dbt
dbt deps
```

`profiles.yml` is already included in the project and reads from your `.env` — no manual profile configuration needed.

### Running the pipeline

**1. Scrape products**

```bash
python scraping.py
```

This creates a timestamped JSON file in `data/` (e.g. `data/products_20260526_174000.json`).

To scrape additional categories, open `scraping.py` and uncomment the desired entries in the `CATEGORIES` list.

**2. Load into PostgreSQL**

```bash
python load_to_db.py
```

Already-imported files are skipped automatically (tracked in `import_log`). Pass `--force <file>` to re-import.

**3. Run dbt transformations**

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
├── requirements.txt          # Python dependencies
├── Dockerfile                # Image for scraper + loader
├── Dockerfile.dbt            # Image for dbt
├── docker-compose.yml        # Full pipeline orchestration
├── .env.example              # Environment variable template
├── data/                     # Scraped JSON files (git-ignored)
└── dbt/
    └── tunisianet_dbt/
        ├── profiles.yml      # DB connection config (reads from .env)
        ├── dbt_project.yml
        ├── packages.yml
        └── models/
            ├── staging/      # stg_raw_data — deduplication
            ├── core/         # product, price, ranking — incrementally updated
            └── analytics/    # brand aggregations & rankings
```

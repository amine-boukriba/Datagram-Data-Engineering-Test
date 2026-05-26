"""
Load scraped Tunisianet JSON data into PostgreSQL
==================================================
- Creates the `products` table (if not exists) and upserts all products.
- Tracks every loaded file in an `import_log` table so already-imported
  files are automatically skipped on subsequent runs.

Requirements:
    pip install psycopg2-binary python-dotenv

Usage:
    # Auto-discover all products_*.json in data/ directory (skips already loaded):
    python load_to_db.py

    # Explicit files (already-loaded ones are still skipped):
    python load_to_db.py data/products_20250525_120000.json data/products_20250526_090000.json

    # Force re-import a specific file even if already loaded:
    python load_to_db.py --force data/products_20250525_120000.json
"""

import glob
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB config  (all values come from .env)
# ---------------------------------------------------------------------------

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     int(os.getenv("DB_PORT")),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

DATA_DIR = Path("data")

# Glob pattern used when no files are passed on the command line
DEFAULT_PATTERN = str(DATA_DIR / "products_*.json")

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

SETUP_SQL = """
-- Products table
CREATE TABLE IF NOT EXISTS raw_data (
    pk              SERIAL PRIMARY KEY,
    id              INTEGER,
    name            TEXT,
    price           NUMERIC(12, 2),
    old_price       NUMERIC(12, 2),
    brand           TEXT,
    category        TEXT,
    rank            INTEGER,
    image_url       TEXT,
    product_url     TEXT,
    scraped_at      TIMESTAMP
);

-- Import log table — one row per successfully loaded file
CREATE TABLE IF NOT EXISTS import_log (
    id              SERIAL PRIMARY KEY,
    filename        TEXT        NOT NULL UNIQUE,
    file_size       BIGINT,
    products_loaded INTEGER,
    scraped_at      TIMESTAMP,
    imported_at     TIMESTAMP   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_log_filename ON import_log (filename);
"""

INSERT_SQL = """
INSERT INTO raw_data (
    id, name, price, old_price, brand, category,
    rank, image_url, product_url, scraped_at
)
VALUES %s;
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_scraped_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    log.warning("Could not parse scraped_at value: %r", value)
    return None


def product_to_row(p: dict) -> tuple:
    product_id = str(p["id"]) if p.get("id") else None
    category   = p.get("category") or "Unknown"
    if not product_id:
        product_id = f"name:{(p.get('name') or 'unknown').lower().replace(' ', '_')}"
    return (
        product_id,
        p.get("name"),
        p.get("price"),
        p.get("old_price"),
        p.get("brand"),
        category,
        p.get("rank"),
        p.get("image_url"),
        p.get("product_url"),
        parse_scraped_at(p.get("scraped_at")),
    )

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------------------------------------------------------
# Import log checks
# ---------------------------------------------------------------------------

def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SETUP_SQL)
    conn.commit()
    log.info("Schema ready (raw_data + import_log).")


def already_imported(conn, filename: str) -> bool:
    """Return True if a file with this name was already loaded."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM import_log WHERE filename = %s LIMIT 1;",
            (filename,)
        )
        return cur.fetchone() is not None


def record_import(conn, filename: str, file_size: int,
                  products_loaded: int, scraped_at: Optional[datetime]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_log (filename, file_size, products_loaded, scraped_at)
            VALUES (%s, %s, %s, %s);
            """,
            (filename, file_size, products_loaded, scraped_at)
        )
    conn.commit()

# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_file(conn, path: Path, force: bool = False) -> int:
    """
    Load a single JSON file into the DB.
    Skips if already imported (unless force=True).
    Returns number of products loaded (0 if skipped).
    """
    file_size = path.stat().st_size

    if not force and already_imported(conn, path.name):
        log.info("  SKIP  %s — already in import_log.", path.name)
        return 0

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    categories = data.get("categories", {})
    if not categories:
        log.warning("  %s — no 'categories' key, skipping.", path.name)
        return 0

    rows = [product_to_row(p) for prods in categories.values() for p in prods]
    if not rows:
        log.warning("  %s — 0 products found, skipping.", path.name)
        return 0

    top_scraped_at = parse_scraped_at(data.get("scraped_at"))

    # If forcing, remove the old import_log entry so it can be re-inserted cleanly
    if force:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM import_log WHERE filename = %s;", (path.name,))

    with conn.cursor() as cur:
        execute_values(cur, INSERT_SQL, rows, page_size=200)
    conn.commit()

    record_import(conn, path.name, file_size, len(rows), top_scraped_at)
    log.info("  ✓  %s — %d products inserted.", path.name, len(rows))
    return len(rows)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    if force:
        args = [a for a in args if a != "--force"]

    # If no files given, auto-discover products_*.json in data/ directory
    if not args:
        if not DATA_DIR.exists():
            log.warning("Data directory '%s' does not exist. Run the scraper first.", DATA_DIR)
            sys.exit(0)
        discovered = sorted(glob.glob(DEFAULT_PATTERN))
        if not discovered:
            log.warning("No files matching '%s' found. Run the scraper first.", DEFAULT_PATTERN)
            sys.exit(0)
        log.info("Auto-discovered %d file(s) in '%s'.", len(discovered), DATA_DIR)
        paths = [Path(f) for f in discovered]
    else:
        paths = [Path(a) for a in args]

    log.info("Connecting to PostgreSQL at %s:%s/%s …",
             DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["dbname"])
    try:
        conn = get_connection()
    except psycopg2.Error as exc:
        log.error("Cannot connect to database: %s", exc)
        sys.exit(1)

    try:
        ensure_schema(conn)

        total_loaded  = 0
        total_skipped = 0
        total_missing = 0

        for path in paths:
            if not path.exists():
                log.error("  NOT FOUND  %s", path)
                total_missing += 1
                continue
            try:
                n = load_file(conn, path, force=force)
                if n == 0:
                    total_skipped += 1
                else:
                    total_loaded += n
            except (psycopg2.Error, json.JSONDecodeError) as exc:
                log.error("  ERROR  %s — %s", path.name, exc)
                conn.rollback()

    finally:
        conn.close()

    log.info(
        "━━━  Done. %d products loaded | %d file(s) skipped (already imported) | %d missing.",
        total_loaded, total_skipped, total_missing,
    )


if __name__ == "__main__":
    main()
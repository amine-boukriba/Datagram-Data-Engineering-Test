"""
Scraper for tunisianet.com.tn - Multiple Categories
============================================================
Categories scraped:
  667-ecran-pc-tunisie
  515-tablette
  373-pc-de-bureau

Requirements:
    pip install requests beautifulsoup4 fake-useragent

Usage:
    python tunisianet_scraper.py

Output:
    data/products_<timestamp>.json  — all products grouped by category
"""

import re
import json
import time
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://www.tunisianet.com.tn"

DATA_DIR = Path("data")

CATEGORIES = [
    {"slug": "667-ecran-pc-tunisie", "label": "Ecran PC"},
    # {"slug": "515-tablette", "label": "Tablette"},
    # {"slug": "373-pc-de-bureau", "label": "PC de Bureau"},
]

# To scrape additional categories, uncomment lines above or add new entries to CATEGORIES.

# Delay ranges (seconds) — randomised for each pause
PAGE_DELAY   = (5, 10)    # between pages within a category
CAT_DELAY    = (10, 20)   # between categories

# Retry config
MAX_RETRIES  = 4
RETRY_BACKOFF = [3, 6, 12, 24]  # seconds to wait before each retry attempt

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
# HTTP helpers
# ---------------------------------------------------------------------------

_ua = UserAgent()


def _random_desktop_ua() -> str:
    """Return a random desktop (non-mobile) User-Agent string."""
    for _ in range(20):
        ua = _ua.random
        if not re.search(r"(iPhone|iPad|Android|Mobile|webOS|BlackBerry)", ua, re.I):
            return ua
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _build_headers() -> dict:
    """Build a fresh set of request headers with a rotated User-Agent."""
    return {
        "User-Agent": _random_desktop_ua(),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": random.choice([
            "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "en-US,en;q=0.9,fr;q=0.8",
            "ar-TN,ar;q=0.9,fr;q=0.8,en;q=0.7",
        ]),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": random.choice(["max-age=0", "no-cache"]),
        "DNT": str(random.randint(0, 1)),
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": random.choice(["none", "same-origin"]),
    }


def get_soup(url: str) -> BeautifulSoup:
    """
    Fetch *url* and return a BeautifulSoup object.
    Rotates headers on every call and retries on failure with exponential back-off.
    """
    session = requests.Session()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            session.headers.update(_build_headers())
            log.debug("GET %s  (attempt %d)", url, attempt)
            resp = session.get(url, timeout=25)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else "?"
            log.warning("HTTP %s on %s (attempt %d/%d)", status, url, attempt, MAX_RETRIES)
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                raise

        except requests.exceptions.ConnectionError as exc:
            log.warning("Connection error on %s (attempt %d/%d): %s", url, attempt, MAX_RETRIES, exc)

        except requests.exceptions.Timeout:
            log.warning("Timeout on %s (attempt %d/%d)", url, attempt, MAX_RETRIES)

        except requests.exceptions.RequestException as exc:
            log.warning("Request error on %s (attempt %d/%d): %s", url, attempt, MAX_RETRIES, exc)

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF[attempt - 1] + random.uniform(0, 2)
            log.info("Retrying in %.1f s …", wait)
            time.sleep(wait)

    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts.")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def get_all_page_urls(category_url: str, soup: BeautifulSoup) -> list[str]:
    """Return every page URL for a category (page 1 included)."""
    urls = [category_url]
    nav = soup.find("nav", class_="pagination")
    if not nav:
        return urls

    max_page = 1
    for a in nav.find_all("a", class_="js-search-link"):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))

    for p in range(2, max_page + 1):
        urls.append(f"{category_url}?page={p}")

    return urls


# ---------------------------------------------------------------------------
# Price parser
# ---------------------------------------------------------------------------

def parse_price(text: Optional[str]) -> Optional[float]:
    """
    Parse Tunisian price strings.
    '155,000 DT'   → 155.0
    '1 299,000 DT' → 1299.0
    """
    if not text:
        return None
    clean = (
        text.replace("DT", "")
            .replace("\xa0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .strip()
            .replace(",", ".")
    )
    try:
        return round(float(clean), 2)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Product parser
# ---------------------------------------------------------------------------

def parse_product(article: BeautifulSoup, rank: int, category_label: str) -> dict:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    product_id = article.get("data-id-product")

    name = None
    product_url = None
    title_tag = article.find("h2", class_="product-title")
    if title_tag:
        name = title_tag.get_text(strip=True)
        a = title_tag.find("a")
        if a:
            href = a.get("href", "")
            product_url = href if href.startswith("http") else BASE_URL + href

    image_url = None
    img_tag = article.find("img", class_="img-responsive")
    if img_tag:
        src = img_tag.get("data-full-size-image-url") or img_tag.get("src", "")
        image_url = src if src.startswith("http") else BASE_URL + src

    brand = None
    brand_img = article.find("img", class_="manufacturer-logo")
    if brand_img:
        brand = brand_img.get("alt")

    price = old_price = None
    price_block = article.find("div", class_="product-price-and-shipping")
    if price_block:
        current_tag = price_block.find("span", class_="price")
        if current_tag:
            price = parse_price(current_tag.get_text(strip=True))
        old_tag = price_block.find("span", class_="regular-price")
        if old_tag:
            old_price = parse_price(old_tag.get_text(strip=True))

    return {
        "id":           product_id,
        "name":         name,
        "price":        price,
        "old_price":    old_price,
        "brand":        brand,
        "category":     category_label,
        "rank":         rank,
        "image_url":    image_url,
        "product_url":  product_url,
        "scraped_at":   now_str,
    }


# ---------------------------------------------------------------------------
# Category scraper
# ---------------------------------------------------------------------------

def scrape_category(slug: str, label: str) -> list[dict]:
    category_url = f"{BASE_URL}/{slug}"
    log.info("━━━  Category: %s  (%s)", label, category_url)

    try:
        first_soup = get_soup(category_url)
    except RuntimeError as exc:
        log.error("Skipping category '%s': %s", label, exc)
        return []

    page_urls = get_all_page_urls(category_url, first_soup)
    log.info("  Pages detected: %d", len(page_urls))

    products: list[dict] = []
    rank = 1

    for i, url in enumerate(page_urls):
        page_soup = first_soup if i == 0 else None

        if page_soup is None:
            delay = random.uniform(*PAGE_DELAY)
            log.info("  Waiting %.1f s before page %d …", delay, i + 1)
            time.sleep(delay)
            try:
                page_soup = get_soup(url)
            except RuntimeError as exc:
                log.error("  Skipping page %d of '%s': %s", i + 1, label, exc)
                continue

        product_list = (
            page_soup.find("div", class_=lambda c: c and "product-thumbs" in c)
            or page_soup.find("div", id="js-product-list")
        )

        if not product_list:
            log.warning("  Product list not found on page %d", i + 1)
            continue

        items = product_list.find_all("div", class_="item-product")
        log.info("  Page %d: %d products", i + 1, len(items))

        for item in items:
            article = item.find("article", class_="product-miniature")
            if article:
                products.append(parse_product(article, rank, label))
                rank += 1

    log.info("  ✓  %d products scraped for '%s'", len(products), label)
    return products


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, list[dict]] = {}
    total = 0

    for idx, cat in enumerate(CATEGORIES):
        if idx > 0:
            delay = random.uniform(*CAT_DELAY)
            log.info("Waiting %.1f s before next category …", delay)
            time.sleep(delay)

        products = scrape_category(cat["slug"], cat["label"])
        all_results[cat["label"]] = products
        total += len(products)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = DATA_DIR / f"products_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scraped_at": datetime.now().isoformat(),
                "total_products": total,
                "categories": all_results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    log.info("━━━  Done. %d total products saved → %s", total, output_file)

    # Preview first product from each category
    print("\n── Preview (first product per category) ──")
    for label, prods in all_results.items():
        if prods:
            print(f"\n[{label}]")
            print(json.dumps(prods[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
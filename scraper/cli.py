"""
Entry point. Shows the category list, takes the user's choice
(category + number of products), and runs the collection.

Usage:
  python -m scraper.cli                      -> interactive mode
  python -m scraper.cli --category 1 --n 5   -> non-interactive (for tests)
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from .fetcher import fetch, logger, BlockDetected
from .parser import parse_search_results, parse_next_page_url, parse_product_page
from .storage import ProductWriter, get_output_path

BASE_DIR = Path(__file__).resolve().parent.parent
SEARCH_URL_TEMPLATE = "https://www.amazon.com/s?k={query}"


def load_existing_asins(path: Path) -> set[str]:
    """Reads ASINs already present in today's CSV (for dedup when resuming a run)."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row["asin"] for row in csv.DictReader(f) if row.get("asin")}


def load_categories() -> list[dict]:
    with open(BASE_DIR / "config" / "categories.json", encoding="utf-8") as f:
        return json.load(f)["categories"]


def print_menu(categories: list[dict]):
    print("\nChoose a category to collect data from:")
    for c in categories:
        print(f"  {c['id']}. {c['name']}")
    print("  0. Other - type your own search keyword/category")


def make_custom_category(keyword: str) -> dict:
    """Builds an ad-hoc category from a free-typed keyword (not in categories.json)."""
    keyword = keyword.strip()
    return {"id": 0, "name": keyword.title(), "search_query": keyword}


def choose_category_interactive(categories: list[dict]) -> dict:
    print_menu(categories)
    while True:
        raw = input("Category number (or 0 for a custom keyword): ").strip()
        if raw == "0":
            keyword = input("Enter a search keyword/category: ").strip()
            if keyword:
                return make_custom_category(keyword)
            print("Keyword cannot be empty, please try again.")
            continue
        for c in categories:
            if str(c["id"]) == raw:
                return c
        print("Invalid number, please try again.")


def choose_quantity_interactive() -> int:
    while True:
        raw = input("How many products to collect?: ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive number.")


def collect_products(category: dict, quantity: int, writer: ProductWriter, seen_asins: set[str]) -> tuple[int, str | None]:
    """
    Collects up to `quantity` NEW products from the category (skipping ASINs
    already in seen_asins) and writes each one to `writer` immediately
    (flushed after every row, so progress is never lost even if the process
    is interrupted). Returns (how_many_new_collected, stop_reason).
    """
    new_count = 0
    url = SEARCH_URL_TEMPLATE.format(query=category["search_query"].replace(" ", "+"))
    stop_reason = None
    consecutive_empty_pages = 0
    MAX_EMPTY_PAGE_RETRIES = 2  # Amazon sometimes serves a page with different markup (not CAPTCHA) - retry

    while new_count < quantity and url:
        try:
            html = fetch(url)
        except BlockDetected as exc:
            stop_reason = f"Blocked while fetching the search results page: {exc}"
            break
        except Exception as exc:
            logger.error(f"Failed to fetch the search results page: {exc}")
            break

        cards = parse_search_results(html)

        if not cards:
            consecutive_empty_pages += 1
            logger.warning(
                f"Search results page contained no recognized product cards (attempt {consecutive_empty_pages}). "
                f"No block signals present (no CAPTCHA/503) - likely a transient markup anomaly. url={url}"
            )
            if consecutive_empty_pages > MAX_EMPTY_PAGE_RETRIES:
                stop_reason = (
                    "Several consecutive pages returned no recognized products "
                    "(no clear CAPTCHA/ban signals, but no cards either) - stopping as a precaution."
                )
                break
            continue  # the same url will be re-fetched (a new session/delay may yield a different response)

        consecutive_empty_pages = 0

        for card in cards:
            if new_count >= quantity:
                break

            asin = card.get("asin")
            if asin in seen_asins:
                continue  # already collected in a previous run - skip

            try:
                product_html = fetch(card["url"])
            except BlockDetected as exc:
                stop_reason = f"Blocked while fetching a product page: {exc}"
                break
            except Exception as exc:
                logger.warning(f"Skipping product {asin}: {exc}")
                continue

            try:
                details = parse_product_page(product_html)
            except Exception as exc:
                logger.warning(f"Failed to parse product {asin}: {exc}")
                continue

            merged = {
                "title": details.get("title") or card.get("title"),
                "price": details.get("price") or card.get("price"),
                "rating": details.get("rating") or card.get("rating"),
                "review_count": details.get("review_count") or card.get("review_count"),
                "asin": asin,
                "url": card.get("url"),
                "availability": details.get("availability"),
                "category": category["name"],
                "scraped_at": datetime.now().isoformat(timespec="seconds"),
            }
            writer.write(merged)  # written to disk immediately
            seen_asins.add(asin)
            new_count += 1
            print(f"  [{new_count}/{quantity}] {asin} | {merged['title'][:60]}")

        if stop_reason:
            break

        if new_count < quantity:
            url = parse_next_page_url(html)
        else:
            url = None

    return new_count, stop_reason


def main():
    parser_args = argparse.ArgumentParser()
    parser_args.add_argument("--category", type=int, default=None)
    parser_args.add_argument("--keyword", type=str, default=None, help="Custom search keyword, bypasses the fixed category list")
    parser_args.add_argument("--n", type=int, default=None)
    args = parser_args.parse_args()

    categories = load_categories()

    if args.keyword is not None:
        category = make_custom_category(args.keyword)
    elif args.category is not None:
        category = next((c for c in categories if c["id"] == args.category), None)
        if category is None:
            print(f"Category with id={args.category} not found.")
            sys.exit(1)
    else:
        category = choose_category_interactive(categories)

    quantity = args.n if args.n is not None else choose_quantity_interactive()

    out_path = get_output_path()
    seen_asins = load_existing_asins(out_path)
    if seen_asins:
        print(f"The file already has {len(seen_asins)} products - resuming collection, duplicates will be skipped.")

    print(f"\nCollecting {quantity} new products from category '{category['name']}'...\n")

    with ProductWriter(out_path) as writer:
        new_count, stop_reason = collect_products(category, quantity, writer, seen_asins)

    print(f"\nNew products collected: {new_count} of {quantity} (total in file: {len(seen_asins)})")
    print(f"Saved to: {out_path}")

    if stop_reason:
        print(f"\n⚠️  STOPPED DUE TO BLOCK SIGNALS: {stop_reason}")
        print("No attempt was made to bypass the protection. Try again later or reduce the volume/frequency.")


if __name__ == "__main__":
    main()

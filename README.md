# Amazon Product Scraper

A Python command-line tool that collects Amazon search results by category or keyword and saves them to CSV. It is built to run unattended and to stop politely: progress is never lost, re-runs skip what is already collected, and the scraper backs off instead of fighting anti-bot protection.

## Features

- **43 ready-made categories** (`config/categories.json`) or any custom keyword
- **Interactive or scripted runs:** pick a category from a menu, or pass `--category` / `--keyword` and `--n`
- **Incremental CSV output:** every product is written as soon as it is parsed, so Ctrl+C never loses data
- **Resume and dedup:** re-running the same category on the same day skips ASINs already collected
- **Polite by design:** random delays, retries with backoff, one request at a time, rotating User-Agent
- **Stops on block signals:** CAPTCHA pages, 429/503 responses or repeated unrecognized pages end the run cleanly
- **Config, not code:** CSS selectors, delays and limits live in JSON files, so markup changes need no code edits

## Output

`output/products_{date}.csv` with the columns:

| Column | Example |
| --- | --- |
| title | Wireless Earbuds, Bluetooth 5.3 Headphones… |
| price | 24.99 |
| rating | 4.4 |
| review_count | 12873 |
| asin | B0XXXXXXXX |
| url | https://www.amazon.com/dp/B0XXXXXXXX |

## Tech

Python 3.10+ · requests · BeautifulSoup4 · csv · argparse


## Install
```
cd amazon_scraper
pip install -r requirements.txt
```
Requires Python 3.10+ (uses `X | None` type hints).

## Run
```
python -m scraper.cli                       # interactive mode (pick category + quantity from a list)
python -m scraper.cli --category 1 --n 20   # non-interactive mode (no prompts)
python -m scraper.cli --keyword "wireless earbuds" --n 20   # custom search keyword instead of a fixed category
```
Category numbers are listed in `config/categories.json`.

Rows are written to the CSV immediately after each product (incrementally), so:
- the script can be safely interrupted (Ctrl+C) - progress is never lost;
- re-running with the same `--category` on the same day resumes collection and skips already-collected ASINs (dedup) instead of starting over;
- for large volumes, run several smaller batches (`--n 10`, `--n 10`, ...) - they accumulate into the same `output/products_{date}.csv`.

## Structure
- `scraper/` - logic (fetch, parse, save)
- `config/` - `categories.json` (category list), `selectors.json` (CSS selectors), `settings.json` (delays, User-Agent, limits)
- `output/` - `products_{date}.csv`
- `logs/` - `scraper.log`

## If the script stops with "STOPPED DUE TO BLOCK SIGNALS"
This means CAPTCHA, 503/429, or several consecutive unrecognized search results pages. The script deliberately does NOT try to bypass the protection. What to do:
- wait a while and try again (with the same `--category` - dedup won't repeat what's already collected);
- reduce the volume per run;
- check `config/selectors.json` in case Amazon changed its markup.

## Known limitation (not a scraper bug)
If run from an IP outside the US, Amazon may show prices in a different currency and mark some products as unavailable for shipping to that region (`availability: "Not available for current shipping region"`). Accurate USD pricing requires a US proxy/VPN.

## Category links
The exact search URL used for each category is listed in `category_search_urls.csv`. Note that Amazon personalizes/rotates search result rankings between requests, so re-fetching the same URL can return a different product order or set - this is expected Amazon behavior, not a scraper bug.

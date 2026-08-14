"""
HTML parsing using selectors from config/selectors.json.
Selectors are NOT hardcoded here - only field-extraction logic lives here.
"""
import re
from bs4 import BeautifulSoup

from .fetcher import SELECTORS


def _text_or_none(el):
    return el.get_text(strip=True) if el else None


def parse_search_results(html: str) -> list[dict]:
    """
    Returns a list of product cards from the search results page:
    asin, title, price, rating, review_count, url.
    """
    soup = BeautifulSoup(html, "html.parser")
    sel = SELECTORS["search_page"]
    cards = soup.select(sel["result_card"])

    items = []
    for card in cards:
        asin = card.get("data-asin")
        if not asin:
            continue  # ad/sponsored blocks without an ASIN - skip

        title_el = card.select_one(sel["title"])
        title = _text_or_none(title_el)

        link = None
        if title_el:
            parent_a = title_el.find_parent("a")
            if parent_a:
                link = parent_a.get("href")

        price_el = card.select_one(sel["price_offscreen"])
        price = _text_or_none(price_el)

        rating_el = card.select_one(sel["rating_alt_text"])
        rating_text = _text_or_none(rating_el)
        rating = None
        if rating_text:
            match = re.search(r"[\d.]+", rating_text)
            rating = match.group() if match else None

        review_el = card.select_one(sel["review_count"])
        review_count = _text_or_none(review_el)

        if not title or not link:
            continue  # a card without a title/link is not useful

        items.append(
            {
                "asin": asin,
                "title": title,
                "price": price,
                "rating": rating,
                "review_count": review_count,
                "url": f"https://www.amazon.com{link}" if link.startswith("/") else link,
            }
        )
    return items


def parse_next_page_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    sel = SELECTORS["search_page"]
    next_link = soup.select_one(sel["next_page_link"])
    if not next_link:
        return None
    href = next_link.get("href")
    if not href:
        return None
    return f"https://www.amazon.com{href}" if href.startswith("/") else href


def _strip_savings_suffix(text: str) -> str:
    """'EUR 31.18 with 22 percent savings' -> 'EUR 31.18'"""
    return re.split(r"\s+with\s+", text, flags=re.IGNORECASE)[0].strip()


def _extract_price(soup: BeautifulSoup, sel: dict) -> str | None:
    """
    Looks for the price ONLY inside the buybox/corePrice containers (so it
    doesn't accidentally pick up a price from the "customers also viewed"
    carousel). If the main .a-offscreen is empty (happens with reinvent-style
    markup), reconstructs the price from the visible
    a-price-symbol/a-price-whole/a-price-fraction spans.
    """
    container = None
    for cand in sel["price_container_candidates"]:
        container = soup.select_one(cand)
        if container:
            break
    if container is None:
        return None

    off = container.select_one(sel["price_offscreen"])
    if off and off.get_text(strip=True):
        return _strip_savings_suffix(off.get_text(strip=True))

    acc = container.select_one(sel["price_accessibility_label"])
    if acc and acc.get_text(strip=True):
        # the accessibility text sometimes contains "... with 22 percent savings" - keep only the price
        return _strip_savings_suffix(acc.get_text(strip=True))

    whole = container.select_one(sel["price_whole"])
    if whole:
        symbol = container.select_one(sel["price_symbol"])
        fraction = container.select_one(sel["price_fraction"])
        whole_txt = whole.get_text(strip=True).rstrip(".")
        symbol_txt = symbol.get_text(strip=True) if symbol else ""
        fraction_txt = fraction.get_text(strip=True) if fraction else ""
        if whole_txt:
            price = f"{symbol_txt}{whole_txt}"
            if fraction_txt:
                price += f".{fraction_txt}"
            return price.strip()

    return None


def parse_product_page(html: str) -> dict:
    """
    Returns additional fields from the product page: title, price, rating,
    review_count, availability. Used to refine the data collected from the
    search results page (mainly availability, which isn't present there).

    If Amazon shows a shipping-restriction message
    ("cannot be shipped to your selected delivery location"), there is no
    price or availability on the page (this is not a parsing error), so we
    explicitly mark this with a dedicated status instead of falling back to
    an unrelated price.
    """
    soup = BeautifulSoup(html, "html.parser")
    sel = SELECTORS["product_page"]

    title = _text_or_none(soup.select_one(sel["title"]))

    shipping_restricted = sel["shipping_restricted_marker"] in html

    rating_text = _text_or_none(soup.select_one(sel["rating_alt_text"]))
    rating = None
    if rating_text:
        match = re.search(r"[\d.]+", rating_text)
        rating = match.group() if match else None

    review_count = _text_or_none(soup.select_one(sel["review_count"]))

    if shipping_restricted:
        price = None
        availability = "Not available for current shipping region"
    else:
        price = _extract_price(soup, sel)
        availability = _text_or_none(soup.select_one(sel["availability"]))
        if not availability:
            out_of_stock = soup.select_one(sel["out_of_stock_container"])
            availability = "Out of stock" if out_of_stock else "Unknown"

    return {
        "title": title,
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "availability": availability,
    }

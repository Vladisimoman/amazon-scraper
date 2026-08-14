"""
HTTP request layer: randomized delays, User-Agent rotation, retry with
backoff, logging, block-signal detection (CAPTCHA / 503 / 429).
"""
import json
import logging
import random
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

with open(CONFIG_DIR / "settings.json", encoding="utf-8") as f:
    SETTINGS = json.load(f)

with open(CONFIG_DIR / "selectors.json", encoding="utf-8") as f:
    SELECTORS = json.load(f)

logger = logging.getLogger("amazon_scraper")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(LOG_DIR / "scraper.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stream_handler)


class BlockDetected(Exception):
    """Raised when the scraper encounters block signals (CAPTCHA/ban)."""


def _random_delay():
    delay = random.uniform(
        SETTINGS["delay_seconds_min"], SETTINGS["delay_seconds_max"]
    )
    time.sleep(delay)
    return delay


def _random_user_agent():
    return random.choice(SETTINGS["user_agents"])


def _looks_like_block(status_code: int, text: str) -> str | None:
    """Returns a description of the block reason, or None if everything is fine."""
    if status_code in SELECTORS["block_signals"]["block_status_codes"]:
        return f"HTTP {status_code}"
    for marker in SELECTORS["block_signals"]["captcha_text_markers"]:
        if marker in text:
            return f"CAPTCHA marker found in response text: '{marker}'"
    return None


def fetch(url: str) -> str:
    """
    Performs a GET request with retry (max max_retries, exponential backoff),
    a randomized delay before each request, and User-Agent rotation.
    Raises BlockDetected if block signals are found - no attempt is made to
    bypass the protection.
    """
    max_retries = SETTINGS["max_retries"]
    last_exc = None

    for attempt in range(1, max_retries + 1):
        delay = _random_delay()
        ua = _random_user_agent()
        headers = {
            "User-Agent": ua,
            "Accept-Language": SETTINGS["accept_language"],
        }
        start = time.time()
        try:
            resp = requests.get(
                url, headers=headers, timeout=SETTINGS["request_timeout_seconds"]
            )
            elapsed = round(time.time() - start, 2)
            logger.info(
                f"GET {url} | status={resp.status_code} | delay={delay:.1f}s | "
                f"time={elapsed}s | attempt={attempt}"
            )

            block_reason = _looks_like_block(resp.status_code, resp.text)
            if block_reason:
                logger.warning(f"Block signal detected: {block_reason} | url={url}")
                raise BlockDetected(block_reason)

            resp.raise_for_status()
            return resp.text

        except BlockDetected:
            raise  # do not retry and do not attempt to bypass the block

        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                f"Request error (attempt {attempt}/{max_retries}): {exc} | url={url}"
            )
            if attempt < max_retries:
                backoff = SETTINGS["retry_backoff_base_seconds"] ** attempt
                time.sleep(backoff)

    logger.error(f"Failed to fetch page after {max_retries} attempts: {url}")
    raise last_exc if last_exc else RuntimeError(f"Fetch failed: {url}")

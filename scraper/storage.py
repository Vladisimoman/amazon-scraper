"""
Incremental writing of collected products into output/products_{date}.csv.
Writes a row immediately after each product is processed, so progress is
never lost on a crash or a block-triggered stop.
"""
import csv
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

FIELDNAMES = [
    "title",
    "price",
    "rating",
    "review_count",
    "asin",
    "url",
    "availability",
    "category",
    "scraped_at",
]


def get_output_path() -> Path:
    return OUTPUT_DIR / f"products_{date.today().isoformat()}.csv"


class ProductWriter:
    """Context manager: opens the CSV, appends rows, and always closes the file."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_output_path()
        self._file = None
        self._writer = None

    def __enter__(self):
        is_new = not self.path.exists()
        self._file = open(self.path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        if is_new:
            self._writer.writeheader()
        return self

    def write(self, row: dict):
        clean_row = {k: row.get(k, "") for k in FIELDNAMES}
        self._writer.writerow(clean_row)
        self._file.flush()  # write to disk immediately - never lose progress

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()

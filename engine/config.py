"""Central configuration for the Address Matching Engine."""
import os
import json
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
EXCEL_PATH = BASE_DIR / "egypt_governorates.xlsx"
OUTPUT_PATH = BASE_DIR / "orders_output.xlsx"
DATA_DIR = BASE_DIR / "data"
LOOKUP_CACHE = DATA_DIR / "lookup_cache.json"
AREAS_LEARNED = DATA_DIR / "areas_learned.json"
RESOLVED_LOG = DATA_DIR / "resolved_by_rule.log"
WIDE_NAMES_CONFIG = BASE_DIR / "config_wide_names.json"

# ── Fuzzy Matching Thresholds ──────────────────────────────
FUZZY_HIGH = 90   # auto-confirm, high confidence
FUZZY_LOW = 75    # auto-confirm, log for periodic review
# below FUZZY_LOW = match failure, needs_review

# ── Book Matching Thresholds (stricter than address) ────────
FUZZY_BOOK_HIGH = 90   # auto-confirm book name
FUZZY_BOOK_LOW = 75    # auto-confirm + log for periodic review
# below FUZZY_BOOK_LOW = match failure, needs_review

# ── Geocoding (disabled until API key provided) ────────────
GEOCODING_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# ── Wide Names Config Loader ───────────────────────────────
def load_wide_names() -> dict:
    """Load the wide_names config from JSON file."""
    if not WIDE_NAMES_CONFIG.exists():
        return {"enabled": True, "wide_names": [], "excluded_cases": []}
    with open(WIDE_NAMES_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

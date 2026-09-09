"""Gradual areas learning — builds the areas table from confirmed orders.

Each time an area→city→governorate link is confirmed (manually or via
Geocoding API), it's added here. Over time, more addresses resolve locally
without needing the API.
"""
import json
from pathlib import Path
from typing import Optional

from engine.normalizer import normalize_lookup_key

_AREAS_PATH = Path(__file__).resolve().parent.parent / "data" / "areas_learned.json"


def load_areas(path: Path | None = None) -> dict:
    """Load the learned areas table."""
    p = path or _AREAS_PATH
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {normalize_lookup_key(k): v for k, v in data.items()}


def save_areas(areas: dict, path: Path | None = None):
    """Persist the learned areas table."""
    p = path or _AREAS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(areas, f, ensure_ascii=False, indent=2)


def add_area(
    governorate_id: str,
    city_id: str,
    area_name: str,
    source: str = "manual",
    confidence: str = "high",
    path: Path | None = None,
):
    """Add or update an area entry after confirmation.

    Args:
        governorate_id: e.g. "01" for Cairo
        city_id: e.g. "01-035" for القاهرة الجديدة
        area_name: Original Arabic name (e.g. "التجمع الأول")
        source: "manual" / "geocoding_api" / "order_correction"
        confidence: "high" / "medium" / "low"
    """
    areas = load_areas(path)
    key = normalize_lookup_key(area_name)
    areas[key] = {
        "area_name": area_name,
        "governorate_id": governorate_id,
        "city_id": city_id,
        "source": source,
        "confidence": confidence,
    }
    save_areas(areas, path)
    return key


def find_parent_city(
    area_name: str,
    governorate_id: str,
    areas: dict | None = None,
) -> Optional[dict]:
    """Find the parent city for a known area name.

    Returns dict with city_id and area info, or None.
    """
    if areas is None:
        areas = load_areas()
    key = normalize_lookup_key(area_name)
    entry = areas.get(key)
    if entry and entry.get("governorate_id") == governorate_id:
        return entry
    return None


def list_areas(governorate_id: str | None = None) -> list[dict]:
    """List all learned areas, optionally filtered by governorate."""
    areas = load_areas()
    result = []
    for key, info in areas.items():
        if governorate_id and info.get("governorate_id") != governorate_id:
            continue
        result.append({"key": key, **info})
    return result

"""Google Maps Geocoding API fallback.

Used ONLY when local matching fails (no exact/fuzzy match in lookup tables)
and the governorate is at least confirmed. The API suggestion is treated as
a needs_review candidate — not auto-confirmed in this first phase.

Query format: "{area_text}, {governorate_name}, مصر"
"""
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional

from engine.config import GEOCODING_API_KEY

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode_query(area_text: str, governorate_name: str) -> Optional[dict]:
    """Query Google Maps Geocoding API for an area name.

    Args:
        area_text: The unmatched area/city text from the address.
        governorate_name: Confirmed governorate name (used as context).

    Returns:
        dict with lat, lng, formatted_address, components — or None on failure.
    """
    if not GEOCODING_API_KEY:
        logger.warning("Geocoding API key not set — skipping API fallback")
        return None

    query = f"{area_text}, {governorate_name}, مصر"
    params = urllib.parse.urlencode({
        "address": query,
        "key": GEOCODING_API_KEY,
        "language": "ar",
        "components": "country:EG",
    })
    url = f"{_GEOCODE_URL}?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AddressEngine/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("Geocoding API request failed: %s", e)
        return None

    if data.get("status") != "OK" or not data.get("results"):
        logger.info("Geocoding API returned status: %s", data.get("status"))
        return None

    result = data["results"][0]
    components = {}
    for comp in result.get("address_components", []):
        for t in comp["types"]:
            components[t] = comp["long_name"]

    return {
        "lat": result["geometry"]["location"]["lat"],
        "lng": result["geometry"]["location"]["lng"],
        "formatted_address": result.get("formatted_address", ""),
        "components": components,
        "source": "geocoding_api",
    }


def format_suggestion(geocode_result: dict, area_text: str) -> str:
    """Format a geocoding result as a review-ready suggestion string."""
    addr = geocode_result.get("formatted_address", "")
    comps = geocode_result.get("components", {})
    city = comps.get("locality", comps.get("sublocality", ""))
    area = comps.get("sublocality_level_1", comps.get("neighborhood", ""))
    return (
        f"Geocoding suggestion for \"{area_text}\":\n"
        f"  Address: {addr}\n"
        f"  City: {city}\n"
        f"  Area: {area}\n"
        f"  Coordinates: {geocode_result['lat']}, {geocode_result['lng']}"
    )

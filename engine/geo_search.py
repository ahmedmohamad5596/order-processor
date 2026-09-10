"""Geographic entity search for the edit UI autocomplete.

Searches the full Egyptian geography (governorates, cities, and the areas
layer: neighborhoods/areas, compounds, villages and major roads) built from
egypt_governorates.xlsx + learned areas. Independent of any UI option list:
the candidate universe is the complete lookup, never a filtered subset.

Each result carries its entity type — roads are typed `road`, never `area`.
Matching is progressive: exact → prefix → contains → fuzzy, all against
normalized Arabic (hamza/ta-marbuta neutral, Persian variants, digit forms).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from engine.lookup_builder import build_lookup
from engine.normalizer import normalize_digits, normalize_for_search

_TYPE_ORDER = {
    "governorate": 0,
    "city": 1,
    "area": 2,
    "compound": 3,
    "village": 4,
    "road": 5,
}
_SCORE_EXACT = 100.0
_SCORE_PREFIX = 98.0
_SCORE_CONTAINS = 90.0
_MIN_SCORE = 78.0
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 25


def _score(query: str, raw_texts: list[str]) -> float:
    """Best match score of query against candidate raw texts (0..100)."""
    best = 0.0
    for raw in raw_texts:
        cand = normalize_for_search(raw)
        if not cand:
            continue
        if cand == query:
            return _SCORE_EXACT
        if query == "":
            continue
        if cand.startswith(query):
            best = max(best, _SCORE_PREFIX)
        elif query in cand:
            best = max(best, _SCORE_CONTAINS)
        if len(query) >= 3:
            best = max(best, fuzz.token_sort_ratio(query, cand), fuzz.token_ratio(query, cand))
    return round(best, 1)


def _gov_name(area: dict, gov_by_id: dict[str, dict]) -> str:
    name = (area.get("governorate") or "").strip()
    if name:
        return name
    gid = area.get("governorate_id")
    if gid:
        info = gov_by_id.get(str(gid))
        if info:
            return info["name_ar"]
    return ""


def _city_name(area: dict, city_by_id: dict[str, dict]) -> str:
    name = (area.get("city") or area.get("city_name") or "").strip()
    if name:
        return name
    cid = area.get("city_id")
    if cid:
        info = city_by_id.get(str(cid))
        if info:
            return info["name_ar"]
    return ""


def _collect(lookup: dict, types: set[str]) -> list[tuple[str, dict, str]]:
    """Yield (entity_type, entity_dict, key) tuples for the requested types."""
    collected: list[tuple[str, dict, str]] = []
    govs = lookup.get("governorates") or {}
    cities = lookup.get("cities") or {}
    areas = lookup.get("areas") or {}
    if "governorate" in types:
        collected.extend(("governorate", info, key) for key, info in govs.items())
    if "city" in types:
        collected.extend(("city", info, key) for key, info in cities.items())
    for key, info in areas.items():
        etype = info.get("entity_type") or "area"
        if etype in types:
            collected.append((etype, info, key))
    return collected


def search_geo(
    q: str,
    types: str = "",
    lookup: dict | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Search geographic entities and return ranked candidates.

    Args:
        q: raw query string
        types: comma-separated entity types to search (empty = governorate,city,area)
        lookup: optional prebuilt lookup (avoids re-building when already loaded)
        limit: max results (clamped to _MAX_LIMIT)

    Returns:
        List of {id, name, type, governorate, city, parent, aliases, score}
        sorted by score desc, then type order, then name.
    """
    query = normalize_digits(normalize_for_search(q))
    if not query:
        return []

    wanted = {t.strip() for t in types.split(",") if t.strip()}
    if not wanted:
        wanted = {"governorate", "city", "area", "road", "compound", "village"}
    wanted = wanted & {"governorate", "city", "area", "road", "compound", "village"}
    if not wanted:
        return []

    lookup = lookup or build_lookup()
    n = min(limit if limit and limit >= 1 else _DEFAULT_LIMIT, _MAX_LIMIT)

    gov_by_id: dict[str, dict] = {}
    for info in (lookup.get("governorates") or {}).values():
        gov_by_id[info["id"]] = info
    city_by_id: dict[str, dict] = {}
    for info in (lookup.get("cities") or {}).values():
        city_by_id[info["id"]] = info

    results: list[dict] = []
    for etype, info, key in _collect(lookup, wanted):
        if etype == "governorate":
            texts = [info["name_ar"], *info.get("aliases", [])]
        elif etype == "city":
            texts = [info["name_ar"], *info.get("aliases", [])]
        else:
            texts = [info.get("area_name") or key]
        score = _score(query, texts)
        if score < _MIN_SCORE:
            continue

        if etype == "governorate":
            parent = ""
            city = ""
            gname = info["name_ar"]
        elif etype == "city":
            gname = info.get("gov_name") or ""
            parent = gname
            city = info["name_ar"]
        else:
            gname = _gov_name(info, gov_by_id)
            city = _city_name(info, city_by_id)
            parent = f"{city}، {gname}".strip(" ،")

        results.append({
            "id": str(info.get("id") or key),
            "name": info.get("name_ar") or info.get("area_name") or key,
            "type": etype,
            "governorate": gname,
            "city": city,
            "parent": parent,
            "aliases": info.get("aliases", []),
            "score": score,
        })

    results.sort(key=lambda r: (-r["score"], _TYPE_ORDER.get(r["type"], 9), r["name"]))
    return results[:n]
"""Build the lookup table from egypt_governorates.xlsx.

Reads Excel sheets once, normalizes all keys, and caches to JSON.
Rebuilds only when the Excel file modification time changes.
"""
import json
import os
import re
from pathlib import Path
from typing import Any

import openpyxl

from engine.normalizer import normalize_lookup_key, strip_prefix

_EXCEL_PATH = Path(__file__).resolve().parent.parent / "egypt_governorates.xlsx"
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "lookup_cache.json"
_AREAS_PATH = Path(__file__).resolve().parent.parent / "data" / "areas_learned.json"


def _load_excel(path: Path) -> openpyxl.Workbook:
    return openpyxl.load_workbook(path, read_only=True, data_only=True)


def _build_governorates(wb: openpyxl.Workbook) -> dict[str, dict]:
    """Build governorates dict from 'نظرة عامة' + 'الأسماء البديلة'.

    Returns: {normalized_name: {id, name_ar, aliases: [str]}}
    """
    gov_map: dict[str, dict] = {}

    # ── From نظرة عامة: governorate ID + official name ─────
    ws = wb["نظرة عامة"]
    for row in ws.iter_rows(min_row=4, values_only=True):
        seq, name_ar, capital, admin_type, count = row
        if not name_ar or not isinstance(seq, int):
            continue
        gid = str(seq).zfill(2)
        norm = normalize_lookup_key(name_ar)
        gov_map[norm] = {"id": gid, "name_ar": name_ar, "aliases": []}

    # ── From الأسماء البديلة: aliases ──────────────────────
    ws2 = wb["الأسماء البديلة"]
    for row in ws2.iter_rows(min_row=5, values_only=True):
        gid_official, name_ar, name_en, aliases_str, type_, notes = row
        if not gid_official or not name_ar:
            continue
        gid = str(gid_official).strip()
        norm = normalize_lookup_key(name_ar)
        if norm in gov_map:
            if aliases_str and aliases_str != "—":
                # Handle both Arabic comma (،) and regular comma (,)
                aliases = [a.strip() for a in aliases_str.replace(",", "،").split("،") if a.strip()]
                gov_map[norm]["aliases"].extend(aliases)

    return gov_map


def _city_aliases(city_name: str) -> list[str]:
    """Generate normalized alias keys for a city.

    Handles the common Egyptian mismatch between official names and how
    customers actually write them:
      - drop "(مدينة 6 أكتوبر)"-style parentheticals → "أكتوبر"
      - reorder "مدينه 6 اکتوبر" → "6 اکتوبر" and → "اكتوبر"
    Returns normalized alias keys (original name excluded; caller adds it).
    """
    name = city_name.strip()
    aliases: set[str] = set()

    # Strip حي/مركز/قسم prefix then drop parenthetical parts
    bare = re.sub(r"^حي\s+|^مركز\s+|^قسم\s+", "", name)
    no_paren = re.sub(r"\([^)]*\)", "", bare).strip()
    if no_paren and no_paren != bare:
        aliases.add(normalize_lookup_key(no_paren))

    # Work on the normalized form so "مدينة" and "مدينه" are interchangeable.
    # ة → ه via normalizer, so "مدينة نصر" and "قسم أكتوبر (مدينة 6 أكتوبر)"
    # match the "مدينه" patterns below.
    norm_bare = normalize_lookup_key(bare)
    no_paren_norm = re.sub(r"\([^)]*\)", "", norm_bare).strip()
    if no_paren_norm and no_paren_norm != norm_bare:
        aliases.add(no_paren_norm)

    # "مدينه 6 اکتوبر" → "6 اکتوبر" and → "اكتوبر"
    m = re.search(r"مدينه\s+([٠-٩0-9]+)\s+(.+)$", no_paren_norm)
    if m:
        num, rest = m.group(1), m.group(2)
        aliases.add(f"{num} {rest}")
        aliases.add(rest)

    # "شرق مدينه نصر" etc → "نصر" and → "مدينه نصر"
    m2 = re.search(r"مدينه\s+(.+)$", no_paren_norm)
    if m2 and m2.group(1) != no_paren_norm:
        aliases.add(m2.group(1))
        aliases.add(f"مدينه {m2.group(1)}")

    no_prefix = re.sub(r"^مدينه\s+", "", no_paren_norm).strip()
    if no_prefix and no_prefix != no_paren_norm:
        aliases.add(no_prefix)

    aliases.discard("")
    return sorted(aliases)


def _build_cities(wb: openpyxl.Workbook) -> tuple[dict[str, dict], dict[str, str], dict[str, list[str]]]:
    """Build cities dict from 'التسلسل الهرمي'.

    Returns: (cities, city_to_gov, ambiguous_cities)
      - cities: {normalized_name: {id, governorate_id, gov_name, aliases}}
      - city_to_gov: {normalized_city_name: governorate_id} (reverse lookup)
        Only names that belong to exactly ONE governorate are registered here.
      - ambiguous_cities: {normalized_name: [governorate_ids]} — names that
        exist in multiple governorates (e.g. فيصل: الجيزة + السويس). They are
        excluded from city_to_gov so the resolver flags them instead of
        silently picking one governorate.
    """
    cities: dict[str, dict] = {}
    city_to_gov: dict[str, str] = {}
    govs_per_name: dict[str, set[str]] = {}
    ambiguous_cities: dict[str, list[str]] = {}
    ws = wb["التسلسل الهرمي"]

    for row in ws.iter_rows(min_row=5, values_only=True):
        (
            gov_id_int, gov_name, gov_id_pad, city_id,
            sub_num, city_name, parent_id, level, admin_type, confidence
        ) = row

        if not city_name or level != "مركز/قسم/مدينة":
            continue
        if not city_id:
            continue

        bare_name = strip_prefix(str(city_name))
        norm = normalize_lookup_key(str(city_name))
        gov_id = str(gov_id_pad).strip() if gov_id_pad else str(gov_id_int).strip().zfill(2)
        aliases = [a for a in _city_aliases(str(city_name)) if a != norm]
        cities[norm] = {
            "id": str(city_id).strip(),
            "governorate_id": gov_id,
            "gov_name": str(gov_name),
            "name_ar": bare_name,
            "aliases": aliases,
        }
        # Track every governorate a name appears under (name itself + aliases)
        govs_per_name.setdefault(norm, set()).add(gov_id)
        for alias in aliases:
            govs_per_name.setdefault(alias, set()).add(gov_id)

    # Only names with exactly one governorate go into the reverse lookup;
    # multi-governorate names (فيصل…) are recorded as ambiguous instead.
    for name, gov_ids in govs_per_name.items():
        if len(gov_ids) == 1:
            city_to_gov[name] = next(iter(gov_ids))
        else:
            ambiguous_cities[name] = sorted(gov_ids)

    return cities, city_to_gov, ambiguous_cities


def _build_areas() -> dict[str, dict]:
    """Load areas from areas_learned.json (built gradually from orders)."""
    if not _AREAS_PATH.exists():
        return {}
    with open(_AREAS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Re-normalize keys
    return {normalize_lookup_key(k): v for k, v in data.items()}


def _cache_valid(cache_path: Path, excel_path: Path) -> bool:
    """Check if cache is newer than the Excel file and the learned-areas file."""
    if not cache_path.exists():
        return False
    cache_mtime = cache_path.stat().st_mtime
    excel_mtime = excel_path.stat().st_mtime
    ref_mtime = excel_mtime
    if _AREAS_PATH.exists():
        ref_mtime = max(ref_mtime, _AREAS_PATH.stat().st_mtime)
    return cache_mtime >= ref_mtime


def build_lookup(excel_path: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Build or load the lookup table.

    Returns: {
        "governorates": {norm_name: {id, name_ar, aliases}},
        "cities": {norm_name: {id, governorate_id, gov_name}},
        "areas": {norm_name: {city_id, area_name, ...}},
    }
    """
    excel = excel_path or _EXCEL_PATH

    if not force and _cache_valid(_CACHE_PATH, excel):
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    wb = _load_excel(excel)
    gov_map = _build_governorates(wb)
    cities, city_to_gov, ambiguous_cities = _build_cities(wb)
    areas = _build_areas()
    wb.close()

    lookup = {
        "governorates": gov_map,
        "cities": cities,
        "areas": areas,
        "city_to_gov": city_to_gov,  # reverse lookup: city_name -> governorate_id
        "ambiguous_cities": ambiguous_cities,  # name -> [gov ids] (multi-gov cities)
    }

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, indent=2)

    return lookup

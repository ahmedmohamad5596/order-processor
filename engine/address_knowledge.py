"""Structured address knowledge from human-confirmed saves (fix2 §10).

No per-address rules and no "if contains X -> return Y" patches. Every clean
save records two kinds of knowledge:

  - verified mappings: normalized raw address -> resolved entity ids (counted),
    the evidence trail a later pipeline stage (evidence scoring) can reuse.
  - alias votes: the typed spelling of a city/area -> the canonical entity id it
    resolved to. The lookup builder promotes spellings that reach a vote
    threshold, so search, autocomplete, canonicalization and the resolver all
    learn from human corrections without hardcoded special cases.

A spelling that resolves to several different entities past the threshold stays
ambiguous and is never promoted (shared names like "فيصل" are skipped).
"""
import json
from pathlib import Path
from typing import Any

from engine.normalizer import normalize_lookup_key

_KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "data" / "address_knowledge.json"
ALIAS_VOTE_THRESHOLD = 2


def _default() -> dict:
    return {"verified_mappings": {}, "city_alias_votes": {}, "area_alias_votes": {}}


def load_knowledge() -> dict:
    """Load the knowledge file (empty structure when absent)."""
    if not _KNOWLEDGE_PATH.exists():
        return _default()
    try:
        data = json.loads(_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default()
    return {**_default(), **data}


def save_knowledge(data: dict) -> None:
    """Persist the knowledge file."""
    _KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KNOWLEDGE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_name_for_id(lookup: dict, group: str, entity_id: str) -> str:
    """Official name of the city/area an id resolves to."""
    for info in (lookup.get(group) or {}).values():
        if str(info.get("id")) == str(entity_id):
            return str(info.get("name_ar") or info.get("area_name") or "")
    return ""


def record_address_save(entry: dict) -> dict:
    """Record one human-confirmed address save.

    Args:
        entry: the saved address — {raw, normalized, governorate, city, area,
            street, governorate_id, city_id, area_id, needs_review}

    Returns:
        The updated knowledge dict (also persisted to disk).
    """
    import datetime

    from engine.lookup_builder import build_lookup

    kbase = load_knowledge()

    # ── Verified mapping (full address) ─────────────────────
    normalized = str(entry.get("normalized") or "").strip() or normalize_lookup_key(
        " ".join(x for x in [
            entry.get("governorate"), entry.get("city"),
            entry.get("area"), entry.get("street")] if x))
    if normalized:
        m = kbase["verified_mappings"].setdefault(
            normalized,
            {"count": 0, "governorate_id": None, "city_id": None, "area_id": None,
             "last_saved_at": None})
        m["count"] += 1
        for field in ("governorate_id", "city_id", "area_id"):
            if entry.get(field):
                m[field] = entry[field]
        m["last_saved_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if entry.get("needs_review"):
        save_knowledge(kbase)
        return kbase

    lookup = build_lookup()

    # ── Alias votes: typed spelling -> canonical id ─────────
    city = str(entry.get("city") or "").strip()
    city_id = entry.get("city_id")
    if city and city_id:
        canon = _canonical_name_for_id(lookup, "cities", city_id)
        typed_norm = normalize_lookup_key(city)
        if canon and typed_norm != normalize_lookup_key(canon):
            votes = kbase["city_alias_votes"].setdefault(typed_norm, {})
            votes[str(city_id)] = votes.get(str(city_id), 0) + 1

    area = str(entry.get("area") or "").strip()
    area_id = entry.get("area_id")
    if area and area_id:
        canon = _canonical_name_for_id(lookup, "areas", area_id)
        typed_norm = normalize_lookup_key(area)
        if canon and typed_norm != normalize_lookup_key(canon):
            votes = kbase["area_alias_votes"].setdefault(typed_norm, {})
            votes[str(area_id)] = votes.get(str(area_id), 0) + 1

    save_knowledge(kbase)
    return kbase


def learned_aliases() -> dict:
    """Aliases promoted past the vote threshold: {group: {typed_norm: id}}.

    group is 'cities' or 'areas'. A typed spelling whose top target is tied
    with another target (shared name) is skipped to avoid mis-assignment.
    """
    kbase = load_knowledge()
    out: dict[str, dict[str, str]] = {"cities": {}, "areas": {}}
    for group, votes_blob in (
        ("cities", kbase["city_alias_votes"]),
        ("areas", kbase["area_alias_votes"]),
    ):
        for typed_norm, targets in votes_blob.items():
            contenders = {tid: n for tid, n in targets.items()
                          if n >= ALIAS_VOTE_THRESHOLD}
            if not contenders or typed_norm in ("", " "):
                continue
            top_id, top_n = max(contenders.items(), key=lambda kv: kv[1])
            others = [n for tid, n in contenders.items() if tid != top_id]
            if others and max(others) >= top_n:
                continue
            out[group][typed_norm] = top_id
    return out
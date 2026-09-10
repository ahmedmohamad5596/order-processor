"""Assembly of a saved address record (fix2 §9 + §10) — one testable unit.

The Edit-Order save path must not depend on whatever the UI showed: a manually
typed governorate/city/area value is always kept, canonicalized against the
FULL geographic reference (names AND learned aliases) when possible, and the
record stores raw + normalized text, resolved ids, the operator's manual
values and how resolution happened.

The server route delegates here (via the geo bridge) so the exact bytes stored
are unit-testable without a database.
"""
from engine.normalizer import normalize_input, normalize_lookup_key, normalize_digits


def _match_key(name: str) -> str:
    """Normalize a name for equality: digits unified, hamzas/ة/prefixes folded
    exactly like the matcher (so '٦ أكتوبر' equals alias '6 اکتوبر')."""
    return normalize_lookup_key(normalize_digits(str(name or "")))


def _matches_any(text: str, texts: list[str]) -> bool:
    """True when the text equals a reference name/alias, including fused
    digit-word forms ('6اكتوبر') — same token variants the matcher uses."""
    keys = {_match_key(t) for t in texts}
    if _match_key(text) in keys:
        return True
    from engine.matcher import _token_variants
    return any(_match_key(v) in keys for v in _token_variants(text))


def canonicalize_city(city: str, gov: str, lookup: dict) -> dict:
    """Canonicalize an operator-entered city (+ optional governorate).

    Faithful port of the old edit-time cityReferenceErrors logic: canonical
    city/governorate by matching the FULL reference, plus conflict/ambiguity /
    not-found flags. Does not consult any UI option list.
    """
    from engine.matcher import match_address

    city = str(city or "").strip()
    gov = str(gov or "").strip()
    if not city:
        return {"matched": False, "error": "city is required"}

    text = city if not gov else f"{city} ، {gov}"
    res = match_address(text, lookup)
    gs = getattr(res.governorate_status, "value", str(res.governorate_status))
    cs = getattr(res.city_status, "value", str(res.city_status))
    matched = cs == "confirmed" and bool(res.city)
    resolved_city = res.city
    resolved_gov = res.governorate
    conflict = bool(resolved_gov) and bool(gov) and \
        normalize_input(resolved_gov) != normalize_input(gov)
    reason = res.review_reason or ""
    amb = ("ambiguous" in reason.lower()) or ("needs manual selection" in reason.lower())
    return {
        "matched": matched,
        "city": resolved_city,
        "governorate": resolved_gov,
        "gov_status": gs,
        "city_status": cs,
        "conflict": conflict,
        "ambiguous": amb,
        "not_found": bool(not matched and not amb),
        "review_reason": reason,
    }


def resolve_address(gov: str, city: str, area: str, lookup: dict) -> dict:
    """Resolve canonical entity ids for a saved (operator-entered) address.

    Ids come from the full reference by name + learned alias — never from the
    client and never from a UI option list.
    """
    gov = str(gov or "").strip()
    city = str(city or "").strip()
    area = str(area or "").strip()

    gid = ""
    for ginfo in lookup["governorates"].values():
        if _match_key(ginfo["name_ar"]) == _match_key(gov):
            gid = ginfo["id"]
            break

    cid = ""
    for cinfo in lookup["cities"].values():
        texts = [cinfo["name_ar"], *cinfo.get("aliases", [])]
        if _matches_any(city, texts):
            if not gid or cinfo.get("governorate_id") == gid:
                cid = cinfo["id"]
                break

    aid = ""
    for ainfo in lookup["areas"].values():
        texts = [str(ainfo.get("area_name") or ""), *ainfo.get("aliases", [])]
        if _matches_any(area, texts):
            if (not cid or ainfo.get("city_id") == cid or not ainfo.get("city_id")) and \
               (not gid or ainfo.get("governorate_id") == gid or not ainfo.get("governorate_id")):
                aid = ainfo["id"]
                break

    return {
        "governorate_id": gid or None,
        "city_id": cid or None,
        "area_id": aid or None,
        "normalized": normalize_input(" ".join(x for x in (gov, city, area) if x)),
    }


def assemble_saved_address(
    previous: dict | None,
    updates: dict | None,
    lookup: dict,
    raw_text: str = "",
) -> tuple[dict, list[str]]:
    """Merge + validate + enrich a saved address (returns record, city_errors).

    Free text is always preserved: a manually typed city/area that is not in
    the reference is still stored (with a review flag), never replaced by the
    closest reference value.
    """
    previous = previous or {}
    a = {**previous, **(updates or {})}
    city = str(a.get("city") or "").strip()
    gov = str(a.get("governorate") or "").strip()
    city_errors: list[str] = []

    # The operator's values as typed — kept verbatim (free text is never
    # destroyed; resolution only adds ids alongside them).
    manual_governorate = str(a.get("governorate") or "")
    manual_city = str(a.get("city") or "")
    manual_area = str(a.get("area") or "")

    if city:
        ref = canonicalize_city(city, gov, lookup)
        r = ref
        if r.get("matched"):
            a["city"] = r["city"]
            a["governorate"] = r["governorate"]
            if r.get("conflict"):
                city_errors.append(
                    f'city: "{r["city"]}" belongs to {r["governorate"]} per the city '
                    f'reference but the governorate field says "{gov}" — verify'
                )
        elif r.get("ambiguous"):
            city_errors.append(
                f'city: "{city}" is ambiguous in the city reference — pick from the city list'
            )
        else:
            city_errors.append(
                f'city: "{city}" not found in the city reference — pick from the city '
                f"list or correct the spelling"
            )
    elif gov:
        official = any(g["name_ar"] == gov for g in lookup["governorates"].values())
        if not official:
            city_errors.append(
                f'governorate: "{gov}" is not an official governorate — '
                f"pick an official governorate or set the arrival city"
            )

    if city_errors:
        a["needs_review"] = True
        a["review_reason"] = "؛ ".join(city_errors)
    elif a.get("city"):
        a["needs_review"] = False
        a["review_reason"] = ""
        a["governorate_status"] = "confirmed"
        a["city_status"] = "confirmed"
        if not a.get("area"):
            a["area"] = a["city"]

    rid = resolve_address(
        str(a.get("governorate") or ""),
        str(a.get("city") or ""),
        str(a.get("area") or ""),
        lookup,
    )
    a["governorate_id"] = rid["governorate_id"] or None
    a["city_id"] = rid["city_id"] or None
    a["area_id"] = rid["area_id"] or None
    a["normalized"] = rid["normalized"] or ""
    a["raw"] = (a.get("raw") or previous.get("raw") or str(raw_text or "") or "") or ""
    a["manual_governorate"] = manual_governorate
    a["manual_city"] = manual_city
    a["manual_area"] = manual_area
    a["resolution_status"] = (
        "needs_review" if city_errors
        else ("human_confirmed" if a.get("city") and a["city_id"]
              else ("manual" if a.get("city") else "needs_review"))
    )
    a["resolution_confidence"] = a.get("confidence_scores") or {}
    a["resolution_evidence"] = a.get("matched_via") or {}

    return a, city_errors


def record_save_knowledge(address: dict, city_errors: list[str]) -> tuple[bool, str | None]:
    """Record a clean human save as structured knowledge (fix2 §10).

    Only runs when the save itself produced no city errors; a failure to record
    never fails the save. Returns (recorded, error_or_None).
    """
    try:
        if city_errors or not address.get("city"):
            return True, None
        from engine.address_knowledge import record_address_save
        record_address_save({
            "raw": str(address.get("raw") or ""),
            "normalized": str(address.get("normalized") or ""),
            "governorate": str(address.get("governorate") or ""),
            "city": str(address.get("city") or ""),
            "area": str(address.get("area") or ""),
            "street": str(address.get("street") or ""),
            "governorate_id": address.get("governorate_id") or None,
            "city_id": address.get("city_id") or None,
            "area_id": address.get("area_id") or None,
            "needs_review": False,
        })
        return True, None
    except Exception as exc:
        return False, str(exc)
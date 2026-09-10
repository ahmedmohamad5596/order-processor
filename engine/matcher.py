"""Main address matching engine.

Matches raw Arabic address text against the lookup table.
Uses normalize_lookup_key / normalize_input for consistent normalization.

Matching order (mandatory):
  1. Governorate
  2. City (narrowed by governorate)
  3. Area (from areas table or needs_review)
  4. Assembly per Section 4 rules
"""
import logging
import re
from typing import Any

from rapidfuzz import fuzz

from engine.config import (
    AREA_ENTITY_TYPES,
    EVIDENCE_MARGIN,
    FUZZY_HIGH,
    FUZZY_LOW,
)
from engine.normalizer import normalize_input, normalize_lookup_key
from engine.models import AddressResult, MatchCandidate, MatchType, FieldStatus
from engine.ambiguity import detect_and_resolve

logger = logging.getLogger(__name__)

# Common separators in Egyptian addresses
_SEPARATORS = ["،", ",", "/", "-", "–", "—"]
# Additional separators for unformatted addresses (used as fallback)
_EXTRA_SEPARATORS = [".", " "]

# Area-level specificity for evidence scoring: when an address names several
# real entities ("التجمع الخامس كمبوند ريتاج"), the most specific one is the
# area-level entity it denotes — a compound/village inside a district.
_AREA_SPECIFICITY = {
    "compound": 3, "village": 3, "community": 3,
    "district": 2, "neighborhood": 2, "area": 1,
}


def _split_tokens(text: str) -> list[str]:
    """Split address text into candidate tokens."""
    original = text
    
    # Strip common prefixes
    for prefix in ("محافظة", "مدينة", "مديريه", "مديرية"):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
    
    # First, normalize common separators
    for sep in _SEPARATORS:
        text = text.replace(sep, "،")
    parts = [p.strip() for p in text.split("،") if p.strip()]

    # If no meaningful split, try splitting on space for long tokens
    if len(parts) <= 1 or (len(parts) == 1 and len(parts[0]) > 20):
        words = text.split()
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            # Boundary keywords that start a new chunk
            if word in ("شارع", "محافظة", "مدينة", "حي", "منطقة", "الرقم",
                        "عمارة", "شقه", "دور", "مدخل", "كمبوند", "مجمع") and current:
                chunks.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            chunks.append(" ".join(current))
        if chunks:
            parts = chunks
    
    # If still one long token with dots, split on dots
    if len(parts) == 1 and "." in parts[0]:
        dot_parts = [p.strip() for p in parts[0].split(".") if p.strip()]
        if len(dot_parts) > 1:
            parts = dot_parts
    
    # Final: split any remaining long token (>=12 chars) on space
    # But preserve known multi-word city names
    _KNOWN_MULTI_WORD_CITIES = {
        "شرق مدينة نصر", "غرب مدينة نصر", "مدينة نصر",
        "السادس من أكتوبر", "october city",
    }
    final_parts = []
    for part in parts:
        if len(part) >= 12 and " " in part and part not in _KNOWN_MULTI_WORD_CITIES:
            sub = [p.strip() for p in part.split(" ") if p.strip()]
            final_parts.extend(sub)
        else:
            final_parts.append(part)

    return final_parts if final_parts else [original.strip()]


def _fuzzy_score(input_text: str, candidate: str) -> float:
    """Compute fuzzy match score between input and a candidate name."""
    return fuzz.token_sort_ratio(input_text, candidate)


def _decisive_scores(scores: list[float]) -> bool:
    """True when the top candidate wins by more than the evidence margin.

    Evidence scoring (fix2 §6): scores like 82 vs 81 do NOT mean the top
    candidate resolved — the field is ambiguous because the margin is too
    small, and a false positive is worse than no result.
    """
    if len(scores) <= 1:
        return True
    return (scores[0] - scores[1]) > EVIDENCE_MARGIN


def _reverse_from_city(
    tokens: list[str],
    city_to_gov: dict,
    id_to_gov: dict,
    ambiguous_cities: dict,
) -> tuple[MatchCandidate | None, str | None]:
    """Infer a governorate from a token that is a known city.

    This is the "parent/child geographic validation" layer. A raw token that
    exactly identifies a known city determines its parent governorate. It runs
    BEFORE any fuzzy governorate comparison:
      - "المنصورة" is a city ⇒ its governorate is الدقهلية (exact, 100)
        fuzzy-matching the city token against "المنوفية" at 75% is forbidden.
      - "6اكتوبر" ⇒ city alias "اكتوبر" ⇒ الجيزة.
      - A city name that exists in multiple governorates (e.g. فيصل) returns
        (None, review_reason) — the caller must flag it instead of guessing.

    Returns (candidate, review_reason). Only one is non-None.
    """
    # Consecutive token pairs cover multi-word cities: "شرق" + "مدينة نصر",
    # "مدينه" + "نصر". Single tokens cover the rest.
    cand_texts = list(tokens)
    for i in range(len(tokens) - 1):
        pair = f"{tokens[i]} {tokens[i + 1]}"
        if " " not in tokens[i] and " " not in tokens[i + 1]:
            cand_texts.append(pair)

    for text in cand_texts:
        for variant in _token_variants(text):
            norm = normalize_lookup_key(variant)
            if norm in ambiguous_cities:
                govs = ", ".join(str(g) for g in ambiguous_cities[norm])
                return None, (
                    f"City '{variant}' exists in multiple governorates "
                    f"({govs}) — needs manual selection"
                )

    for text in cand_texts:
        for variant in _token_variants(text):
            norm = normalize_lookup_key(variant)
            gid = city_to_gov.get(norm)
            if gid and gid in id_to_gov:
                return MatchCandidate(
                    name=id_to_gov[gid]["name_ar"],
                    id=gid,
                    score=100.0,
                    match_type=MatchType.REVERSE_CITY_TO_GOV,
                ), None

    return None, None


def _find_governorate_fuzzy(
    tokens: list[str], gov_lookup: dict, city_to_gov: dict
) -> tuple[MatchCandidate | None, str | None]:
    """Fuzzy governorate match — the LAST resolution layer only.

    Runs only after exact governorate AND reverse city→governorate layers
    failed. City tokens are excluded so a known city name (المنصورة) can never
    be fuzzy-matched against a governorate (المنوفية).

    Evidence-based (fix2 §6): when the top two governorates score within
    EVIDENCE_MARGIN, the field is ambiguous — no value is forced.
    Returns (candidate, review_reason); only one is non-None.
    """
    city_known = set(city_to_gov.keys())
    per_gov: dict[str, MatchCandidate] = {}

    for norm_name, info in gov_lookup.items():
        top: MatchCandidate | None = None
        for token in tokens:
            norm_input = normalize_input(token)
            if norm_input in city_known:
                continue
            score = _fuzzy_score(norm_input, norm_name)
            if score >= FUZZY_LOW:
                cand = MatchCandidate(
                    name=info["name_ar"],
                    id=info["id"],
                    score=score,
                    match_type=MatchType.FUZZY,
                )
                if top is None or cand.score > top.score:
                    top = cand
        if top is not None:
            per_gov[norm_name] = top

    if not per_gov:
        return None, None

    ranked = sorted(per_gov.values(), key=lambda c: c.score, reverse=True)
    if not _decisive_scores([c.score for c in ranked]):
        names = ", ".join(c.name for c in ranked[:2])
        return None, (
            f"Governorate ambiguous: '{names}' evidence too close — "
            f"needs manual selection"
        )
    return ranked[0], None


def _find_governorate(
    tokens: list[str],
    full_text: str,
    gov_lookup: dict,
    city_to_gov: dict | None = None,
    id_to_gov: dict | None = None,
    ambiguous_cities: dict | None = None,
) -> tuple[MatchCandidate | None, str | None]:
    """Find the best governorate match — layered, entity-type aware.

    Mandated resolution order:
      1. Exact canonical governorate name
      2. Exact normalized governorate name
      3. Governorate alias
      4. Contextual (leading-word) match: "قنا الشئون شارع..." → قنا
      5. Parent/child validation: token is a known city → its governorate
      6. (Map / geocoder verification — not available offline)
      7. Fuzzy governorate match — LAST LAYER ONLY

    A city/area/street token is never fuzzy-compared against governorate
    names as the primary method: the exact and reverse (parent/child) layers
    above always determine such a token's governorate first.

    Returns (candidate, review_reason). Only one is non-None. review_reason is
    set for ambiguous city names that exist in multiple governorates.
    """
    city_to_gov = city_to_gov or {}
    ambiguous_cities = ambiguous_cities or {}

    # Flatten all tokens + full text for the exact/governorate-name searches
    search_texts = list(set(tokens + [full_text]))
    best: MatchCandidate | None = None

    # ── Layers 1-3: exact canonical / normalized / alias ──
    for norm_name, info in gov_lookup.items():
        for text in search_texts:
            norm_input = normalize_input(text)

            if norm_input == norm_name:
                cand = MatchCandidate(
                    name=info["name_ar"],
                    id=info["id"],
                    score=100.0,
                    match_type=MatchType.EXACT,
                )
                if best is None or cand.score > best.score:
                    best = cand
                continue

            for alias in info.get("aliases", []):
                if norm_input == normalize_lookup_key(alias):
                    cand = MatchCandidate(
                        name=info["name_ar"],
                        id=info["id"],
                        score=100.0,
                        match_type=MatchType.EXACT,
                    )
                    if best is None or cand.score > best.score:
                        best = cand
                    break

    if best and best.score == 100.0:
        return best, None

    # ── Layer 4: contextual leading-word match ──
    # "قنا الشئون شارع..." → governorate قنا
    if best is None:
        for norm_name, info in gov_lookup.items():
            for text in search_texts:
                norm_input = normalize_input(text)
                if len(norm_input) <= 20 and norm_input.startswith(norm_name + " "):
                    cand = MatchCandidate(
                        name=info["name_ar"],
                        id=info["id"],
                        score=95.0,
                        match_type=MatchType.FUZZY,
                    )
                    if best is None or cand.score > best.score:
                        best = cand

    if best is not None:
        return best, None

    # ── Layer 5: parent/child — reverse city→governorate ──
    id_to_gov = id_to_gov or {v["id"]: v for v in gov_lookup.values()}
    gov, review = _reverse_from_city(tokens, city_to_gov, id_to_gov, ambiguous_cities)
    if gov is not None or review is not None:
        return gov, review

    # ── Layer 7: fuzzy governorate — LAST LAYER ONLY ──
    return _find_governorate_fuzzy(tokens, gov_lookup, city_to_gov)


def _token_variants(token: str) -> list[str]:
    """Expand a token into matching variants.

    Egyptian addresses routinely fuse a number + Arabic word with no space:
      "6اكتوبر" → ["6اكتوبر", "6", "اكتوبر"]
      "مدينه6اكتوبر" → ["مدينه6اكتوبر", "6اكتوبر", "اكتوبر"]
    Each variant is normalized on use by the caller.
    """
    norm = token.strip()
    variants = [norm]
    # Leading digit fused to a word: "6اكتوبر"
    m = re.match(r"^([0-9٠-٩]+)([^\d]+)$", norm)
    if m:
        variants.append(m.group(1))
        variants.append(m.group(2))
    # Word fused to trailing-free digit already covered; try "مدينه6اكتوبر"
    m2 = re.match(r"^([^\d]+?)([0-9٠-٩]+)(.+)$", norm)
    if m2 and len(m2.group(1)) <= 4 and len(m2.group(3)) >= 2:
        inner = m2.group(2) + m2.group(3)
        variants.append(inner)
        variants.append(m2.group(3))
    # Dot-fused tokens act as separators in handwritten addresses:
    # "اسنا....شارع" → ["اسنا", "شارع"]
    if "." in norm:
        for seg in re.split(r"[.]+", norm):
            if seg:
                variants.append(seg)
    return variants


def _city_matches_token(token: str, norm_name: str, info: dict) -> bool:
    """Check if a token (or variant) exactly matches a city key or one of its aliases."""
    targets = {norm_name}
    for a in info.get("aliases", []):
        targets.add(normalize_lookup_key(a))
    for variant in _token_variants(token):
        if normalize_lookup_key(variant) in targets:
            return True
    return False


def _find_city(
    tokens: list[str],
    full_text: str,
    gov_id: str,
    city_lookup: dict,
) -> list[MatchCandidate]:
    """Find all city candidates within a governorate.

    Returns candidates with score >= FUZZY_LOW, sorted by score desc.
    """
    # Narrow scope: only cities in this governorate
    scoped = {
        k: v for k, v in city_lookup.items()
        if v.get("governorate_id") == gov_id
    }

    search_texts = list(set(tokens + [full_text]))
    candidates: list[MatchCandidate] = []
    seen_ids: set[str] = set()

    # Pass 1: exact match on individual tokens only (not full text)
    for norm_name, info in scoped.items():
        cid = info["id"]
        if cid in seen_ids:
            continue
        for token in tokens:
            if _city_matches_token(token, norm_name, info):
                candidates.append(MatchCandidate(
                    name=info["name_ar"],
                    id=cid,
                    score=100.0,
                    match_type=MatchType.EXACT,
                ))
                seen_ids.add(cid)
                break

    # Pass 2: fuzzy match on individual tokens (stricter threshold)
    FUZZY_CITY_MIN = 85  # Higher bar for fuzzy city matches to avoid false positives
    for norm_name, info in scoped.items():
        cid = info["id"]
        if cid in seen_ids:
            continue
        for token in tokens:
            norm_input = normalize_input(token)
            score = _fuzzy_score(norm_input, norm_name)
            if score >= FUZZY_CITY_MIN:
                candidates.append(MatchCandidate(
                    name=info["name_ar"],
                    id=cid,
                    score=score,
                    match_type=MatchType.FUZZY,
                ))
                seen_ids.add(cid)
                break

    # Pass 3: multi-token combinations (e.g., "شرق" + "مدينة نصر")
    for i in range(len(tokens) - 1):
        combined = tokens[i] + " " + tokens[i + 1]
        norm_combined = normalize_input(combined)
        for norm_name, info in scoped.items():
            cid = info["id"]
            if cid in seen_ids:
                continue
            if norm_combined == norm_name:
                candidates.append(MatchCandidate(
                    name=info["name_ar"],
                    id=cid,
                    score=100.0,
                    match_type=MatchType.EXACT,
                ))
                seen_ids.add(cid)
            else:
                score = _fuzzy_score(norm_combined, norm_name)
                if score >= FUZZY_CITY_MIN:
                    candidates.append(MatchCandidate(
                        name=info["name_ar"],
                        id=cid,
                        score=score,
                        match_type=MatchType.FUZZY,
                    ))
                    seen_ids.add(cid)

    # Pass 4: word-boundary substring match against the full text. The
    # tokenizer merges adjacent words into single tokens (e.g. "قنا الشئون"),
    # which otherwise hides a genuine شهر like "قنا" (a real city in the
    # reference, distinct from the governorate of the same name). Only accept
    # the official name or an alias at word boundaries to avoid partial-name
    # false positives (e.g. "قناطر" must not match the شهر "قنا").
    if full_text:
        norm_full = normalize_input(full_text)
        for norm_name, info in scoped.items():
            cid = info["id"]
            if cid in seen_ids:
                continue
            targets = {norm_name}
            for a in info.get("aliases", []):
                targets.add(normalize_input(a))
            for target in targets:
                if target and _boundary_contains(norm_full, target):
                    candidates.append(MatchCandidate(
                        name=info["name_ar"],
                        id=cid,
                        score=100.0,
                        match_type=MatchType.EXACT,
                    ))
                    seen_ids.add(cid)
                    break

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _boundary_contains(text: str, word: str) -> bool:
    """True if `word` occurs in `text` surrounded by word boundaries.

    Word chars are Arabic letters and digits only, so a match inside another
    literal token ("قناطر" containing "قنا") never counts.
    """
    pattern = r"(?<![0-9\u0600-\u06FF])" + re.escape(word) + r"(?![0-9\u0600-\u06FF])"
    return re.search(pattern, text) is not None


def _find_area(
    tokens: list[str],
    full_text: str,
    gov_id: str,
    city_id: str | None,
    area_lookup: dict,
) -> tuple[MatchCandidate | None, str | None]:
    """Find area match from the areas reference.

    Only area-level entity types can confirm an area (fix2 §7): a road or
    street (جسر السويس، شارع الهرم، ...) spans multiple neighborhoods and is
    never an area by itself. Confidence is evidence-based (fix2 §6): when the
    two best area candidates score within EVIDENCE_MARGIN, no area is forced.

    Returns (candidate, ambiguous_reason); only one is non-None.
    """
    if not area_lookup:
        return None, None

    search_texts = list(set(tokens + [full_text]))
    # Add consecutive-token pairs so multi-word areas ("جسر السويس",
    # "مدينة نصر") can match without an exact pre-merged token.
    if len(tokens) >= 2:
        search_texts += [
            tokens[i] + " " + tokens[i + 1]
            for i in range(len(tokens) - 1)
            if " " not in tokens[i] and " " not in tokens[i + 1]
        ]
        search_texts += [
            tokens[i] + " " + tokens[i + 1] + " " + tokens[i + 2]
            for i in range(len(tokens) - 2)
            if " " not in tokens[i + 1]
        ]
    search_texts = list(dict.fromkeys(search_texts))
    candidates: dict[str, MatchCandidate] = {}

    for norm_name, info in area_lookup.items():
        # Roads/streets span areas — they never confirm an area by themselves.
        if info.get("entity_type", "area") not in AREA_ENTITY_TYPES:
            continue
        # Filter by governorate (and city if known)
        if info.get("governorate_id") != gov_id:
            continue
        if city_id and info.get("city_id") != city_id:
            continue

        # The candidate carries the parent city id (areas store it as city_id).
        parent_city_id = info.get("city_id") or info.get("area_id")

        for text in search_texts:
            norm_input = normalize_input(text)
            if norm_input == norm_name:
                candidates[norm_name] = MatchCandidate(
                    name=info.get("area_name", norm_name),
                    id=parent_city_id,
                    score=100.0,
                    match_type=MatchType.EXACT,
                    source=info.get("entity_type", "area"),
                )
                break
            score = _fuzzy_score(norm_input, norm_name)
            if score >= FUZZY_HIGH:
                cand = MatchCandidate(
                    name=info.get("area_name", norm_name),
                    id=parent_city_id,
                    score=score,
                    match_type=MatchType.FUZZY,
                    source=info.get("entity_type", "area"),
                )
                if norm_name not in candidates or cand.score > candidates[norm_name].score:
                    candidates[norm_name] = cand

    if not candidates:
        return None, None

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)

    # Evidence: exact entities always beat fuzzy ones.
    exact = [c for c in ranked if c.score >= 100.0]
    pool = exact if exact else ranked

    # Evidence: at equal strength the most specific entity type wins — a
    # compound/village inside a district is the entity the address names
    # ("التجمع الخامس كمبوند ريتاج" → ريتاج, not التجمع الخامس).
    max_spec = max(_AREA_SPECIFICITY.get(c.source, 0) for c in pool)
    pool = [c for c in pool if _AREA_SPECIFICITY.get(c.source, 0) == max_spec]

    pool = sorted(pool, key=lambda c: c.score, reverse=True)
    if not _decisive_scores([c.score for c in pool]):
        names = ", ".join(c.name for c in pool[:2])
        return None, (
            f"Area ambiguous: '{names}' evidence too close — "
            f"select the area manually"
        )
    return pool[0], None


def _city_id_key(city_id: str, city_lookup: dict) -> str | None:
    """Find the city_lookup key (normalized name) for a numeric city id."""
    for norm_name, info in city_lookup.items():
        if info.get("id") == city_id:
            return norm_name
    return None


def _build_street(
    tokens: list[str],
    matched_parts: set[str],
) -> str:
    """Build street from remaining unmatched tokens."""
    remaining = [t for t in tokens if t not in matched_parts]
    if not remaining:
        return None
    # Join with a natural space, not ", " — the raw tokens are word-level
    # fragments and comma-splitting every word destroys the address.
    street = " ".join(remaining)
    return re.sub(r"\s+", " ", street).strip() or None


def match_address(
    raw_text: str,
    lookup: dict[str, Any],
    gov_hint: dict | None = None,
) -> AddressResult:
    """Match a raw Arabic address string against the lookup table.

    Main entry point for the matching engine. `gov_hint` supplies a
    governorate ({"id": ..., "name": ...}) that was already confirmed by an
    external step (e.g. an AI suggestion) when the literal text carries no
    governorate name — the city/area steps then run scoped to that hint.
    """
    result = AddressResult()
    tokens = _split_tokens(raw_text)
    matched_tokens: set[str] = set()

    gov_lookup = lookup.get("governorates", {})
    city_lookup = lookup.get("cities", {})
    area_lookup = lookup.get("areas", {})

    # ── Step 1: Governorate matching (entity-type aware) ────
    id_to_gov = {v["id"]: v for v in gov_lookup.values()}
    gov, gov_review = _find_governorate(
        tokens,
        raw_text,
        gov_lookup,
        city_to_gov=lookup.get("city_to_gov", {}),
        id_to_gov=id_to_gov,
        ambiguous_cities=lookup.get("ambiguous_cities", {}),
    )

    if gov is None and gov_hint and gov_hint.get("id") and gov_hint.get("name"):
        gov = MatchCandidate(
            name=gov_hint["name"],
            id=str(gov_hint["id"]),
            score=100.0,
            match_type=MatchType.EXACT,
        )
        gov_review = None

    if gov_review:
        result.flag_governorate_review(gov_review)
        result.street = _build_street(tokens, matched_tokens)
        return result

    if gov is None:
        result.fail("No governorate match found")
        return result

    if gov.score == 100.0:
        result.set_governorate(gov.name, gov.id, gov.match_type, 100.0)
    elif gov.score >= FUZZY_HIGH:
        result.set_governorate(gov.name, gov.id, MatchType.FUZZY, gov.score)
    else:
        # 75-89: confirm but log for review
        result.set_governorate(gov.name, gov.id, MatchType.FUZZY, gov.score)
        result.confidence_scores["governorate_note"] = (
            f"Fuzzy match {gov.score:.0f}% — log for periodic review"
        )

    gov_id = gov.id
    # Mark matched tokens
    gov_name_norm = normalize_input(gov.name)
    for t in tokens:
        if normalize_input(t) == gov_name_norm or gov_name_norm in normalize_input(t):
            matched_tokens.add(t)

    # ── Step 2: City matching ───────────────────────────────
    city_candidates = _find_city(tokens, raw_text, gov_id, city_lookup)

    if len(city_candidates) == 0:
        # No city token matched. The city must be a REAL district/sub-city —
        # never echo the governorate name back as the city ("city == gov" is
        # forbidden). Left unresolved for manual review.
        if "مدينه نصر" in normalize_input(raw_text) and gov_id == "01":
            result.flag_city_review(
                "City ambiguous: 'مدينة نصر' without شرق/غرب — needs manual selection"
            )
        else:
            result.flag_city_review(
                f"No city match found in governorate {result.governorate} (id={gov_id})"
            )
    elif len(city_candidates) == 1:
        c = city_candidates[0]
        if c.score >= FUZZY_HIGH:
            result.set_city(c.name, c.id, c.match_type, c.score)
        elif c.score >= FUZZY_LOW:
            result.set_city(c.name, c.id, c.match_type, c.score)
            result.confidence_scores["city_note"] = (
                f"Fuzzy match {c.score:.0f}% — log for periodic review"
            )
        # Mark matched tokens
        city_norm = normalize_input(c.name)
        for t in tokens:
            if normalize_input(t) == city_norm or city_norm in normalize_input(t):
                matched_tokens.add(t)
    else:
        # Multiple candidates — check for exact match first
        exact = [c for c in city_candidates if c.score == 100.0]
        if len(exact) == 1:
            # One exact match wins over any fuzzy candidates
            c = exact[0]
            result.set_city(c.name, c.id, c.match_type, c.score)
            city_norm = normalize_input(c.name)
            for t in tokens:
                if normalize_input(t) == city_norm or city_norm in normalize_input(t):
                    matched_tokens.add(t)
        else:
            # Multiple exact or fuzzy — filter out matches where the
            # city name is just the governorate name under a different prefix
            gov_norm = normalize_input(result.governorate)
            real_exact = [
                c for c in exact
                if gov_norm not in normalize_input(c.name)
            ]

            if len(real_exact) == 1:
                c = real_exact[0]
                result.set_city(c.name, c.id, c.match_type, c.score)
                city_norm = normalize_input(c.name)
                for t in tokens:
                    if normalize_input(t) == city_norm or city_norm in normalize_input(t):
                        matched_tokens.add(t)
            elif len(real_exact) > 1:
                detect_and_resolve(real_exact, result, raw_text)
                if result.city:
                    city_norm = normalize_input(result.city)
                    for t in tokens:
                        if normalize_input(t) == city_norm or city_norm in normalize_input(t):
                            matched_tokens.add(t)
            else:
                # No real exact matches — use all candidates for ambiguity
                detect_and_resolve(city_candidates, result, raw_text)
                if result.city:
                    city_norm = normalize_input(result.city)
                    for t in tokens:
                        if normalize_input(t) == city_norm or city_norm in normalize_input(t):
                            matched_tokens.add(t)

    # ── Step 3: Area matching ───────────────────────────────
    area, area_note = _find_area(
        tokens, raw_text, gov_id,
        result.city_id if result.city_status == FieldStatus.CONFIRMED else None,
        area_lookup,
    )
    if area_note:
        result.flag_area_review(area_note)
    elif area is not None:
        if area.score >= FUZZY_HIGH:
            result.set_area(area.name, area.match_type, area.score)
            area_norm = normalize_input(area.name)
            for t in tokens:
                if normalize_input(t) == area_norm or area_norm in normalize_input(t):
                    matched_tokens.add(t)
            # If city was not resolved but the learned area knows its parent
            # city, confirm the city from the area data.
            if result.city_status != FieldStatus.CONFIRMED and area.id:
                parent = city_lookup.get(_city_id_key(area.id, city_lookup))
                if parent:
                    result.set_city(
                        parent["name_ar"], parent["id"], MatchType.EXACT, 90.0
                    )
                    result.matched_via["city"] = "area_parent_city"
                    result.confidence_scores["city"] = 90.0
                    # Step 2 may have flagged the city for review — resolve it.
                    result.clear_review()
    else:
        # No area in lookup — leave as unknown (Section 4 rules apply in assembly)
        pass

    # ── Step 4: Assembly per Section 4 ─────────────────────
    _assemble(result, tokens, matched_tokens)

    return result


def _assemble(
    result: AddressResult,
    tokens: list[str],
    matched_tokens: set[str],
):
    """Apply Section 4 assembly rules after all matching is done."""
    # Rule 1: Gov + City + Area all confirmed → keep all, rest = street
    if (result.governorate_status == FieldStatus.CONFIRMED
            and result.city_status == FieldStatus.CONFIRMED
            and result.area_status == FieldStatus.CONFIRMED):
        result.street = _build_street(tokens, matched_tokens)
        return

    # Rule 2: Gov + City confirmed, no Area → city must NOT be repeated as
    # the area. Left for manual review instead.
    if (result.governorate_status == FieldStatus.CONFIRMED
            and result.city_status == FieldStatus.CONFIRMED
            and result.area_status != FieldStatus.CONFIRMED):
        if result.review_reason is None:
            # Keep a more specific area reason if already flagged (e.g. an
            # evidence-margin ambiguity) — Rule 2 is only the generic fallback.
            result.flag_area_review(
                f"Area not mentioned for city {result.city} — select the area manually"
            )
        result.street = _build_street(tokens, matched_tokens)
        return

    # Rule 3: Gov + Area confirmed, no City → try parent from areas, else needs_review
    if (result.governorate_status == FieldStatus.CONFIRMED
            and result.area_status == FieldStatus.CONFIRMED
            and result.city_status != FieldStatus.CONFIRMED):
        # Try to find parent city from area data
        # For now, flag for review (Geocoding API can help later)
        result.flag_city_review(
            f"Area '{result.area}' found but no matching city"
        )
        result.street = _build_street(tokens, matched_tokens)
        return

    # Rule 4: No governorate → already failed in _find_governorate
    # Rule 5: Anything remaining → street
    result.street = _build_street(tokens, matched_tokens)

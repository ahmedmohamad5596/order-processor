"""Ambiguity detection and resolution for city matching.

Handles the case where multiple city candidates match.
Implements the "narrow vs wide" rule:
  - If one candidate is a known wide-area name and another is more specific,
    the specific one becomes City, the wide one becomes context/alias.
  - Otherwise → needs_review.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from engine.config import load_wide_names, RESOLVED_LOG
from engine.models import MatchCandidate, AddressResult, MatchType, FieldStatus

logger = logging.getLogger(__name__)


def _load_wide_names_set() -> set[str]:
    """Load wide area names as a normalized set for fast lookup."""
    config = load_wide_names()
    if not config.get("enabled", True):
        return set()
    return {w["name"] for w in config.get("wide_names", [])}


def _is_excluded(name: str) -> bool:
    """Check if a specific name is excluded from the narrow-wide rule."""
    config = load_wide_names()
    excluded = config.get("excluded_cases", [])
    return name in excluded


def _log_resolution(input_text: str, narrow: str, wide: str):
    """Append a resolution entry to the log file."""
    RESOLVED_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = (
        f"{timestamp} | input: \"{input_text}\"\n"
        f"  City resolved by 'narrow vs wide' rule: "
        f"{narrow} over {wide} (confidence: medium)\n\n"
    )
    with open(RESOLVED_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info("Narrow-wide resolved: %s over %s", narrow, wide)


def detect_and_resolve(
    candidates: list[MatchCandidate],
    result: AddressResult,
    input_text: str = "",
) -> bool:
    """Detect ambiguity among city candidates and resolve if possible.

    Args:
        candidates: All city candidates with score >= 75 (sorted by score desc).
        result: AddressResult to update.
        input_text: Original input for logging.

    Returns:
        True if resolved (either by rule or needs_review), False if single candidate.
    """
    if len(candidates) <= 1:
        return False

    wide_names = _load_wide_names_set()
    if not wide_names:
        # Rule disabled or no wide names configured
        result.flag_city_review(
            f"Multiple city candidates, rule disabled: "
            f"{[c.name for c in candidates]}"
        )
        return True

    # Separate wide vs narrow candidates
    # Normalize names for comparison against wide_names set
    from engine.normalizer import normalize_lookup_key
    wide_candidates = [
        c for c in candidates
        if normalize_lookup_key(c.name) in wide_names and not _is_excluded(c.name)
    ]
    narrow_candidates = [
        c for c in candidates
        if normalize_lookup_key(c.name) not in wide_names or _is_excluded(c.name)
    ]

    # Resolution requires: exactly 1 narrow + at least 1 wide
    if len(narrow_candidates) == 1 and len(wide_candidates) >= 1:
        narrow = narrow_candidates[0]
        wide = wide_candidates[0]

        result.set_city(
            narrow.name,
            narrow.id,
            MatchType.NARROW_WIDE,
            narrow.score,
        )
        result.confidence_scores["city_note"] = (
            f"Resolved by narrow-wide rule: {narrow.name} over {wide.name}"
        )
        _log_resolution(input_text, narrow.name, wide.name)
        return True

    # Multiple narrow candidates or multiple wide — can't resolve
    result.flag_city_review(
        f"Multiple candidates, rule cannot resolve: "
        f"narrow={[c.name for c in narrow_candidates]}, "
        f"wide={[c.name for c in wide_candidates]}"
    )
    return True

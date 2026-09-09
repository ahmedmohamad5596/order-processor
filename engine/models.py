"""Data models for the Address Matching Engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    NARROW_WIDE = "narrow_wide_rule"
    GEOCODING = "geocoding"
    REVERSE_CITY_TO_GOV = "reverse_city_to_gov"
    NONE = "none"


class FieldStatus(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    UNKNOWN = "unknown"


@dataclass
class MatchCandidate:
    """A single candidate match found during lookup."""
    name: str
    id: Optional[str]
    governorate_id: Optional[str] = None
    score: float = 0.0
    match_type: MatchType = MatchType.NONE
    source: str = "official"

    @property
    def is_confirmed(self) -> bool:
        return self.score >= 90

    @property
    def is_low_confidence(self) -> bool:
        return 75 <= self.score < 90


@dataclass
class AddressResult:
    """Final result of address matching for one order."""
    governorate: Optional[str] = None
    governorate_id: Optional[str] = None
    governorate_status: FieldStatus = FieldStatus.UNKNOWN

    city: Optional[str] = None
    city_id: Optional[str] = None
    city_status: FieldStatus = FieldStatus.UNKNOWN

    area: Optional[str] = None
    area_status: FieldStatus = FieldStatus.UNKNOWN

    street: Optional[str] = None

    needs_review: bool = False
    review_reason: Optional[str] = None

    confidence_scores: dict = field(default_factory=dict)
    matched_via: dict = field(default_factory=dict)

    def set_governorate(self, name: str, gid: str, match_type: MatchType, score: float):
        self.governorate = name
        self.governorate_id = gid
        self.governorate_status = FieldStatus.CONFIRMED
        self.confidence_scores["governorate"] = score
        self.matched_via["governorate"] = match_type.value

    def set_city(self, name: str, cid: str, match_type: MatchType, score: float):
        self.city = name
        self.city_id = cid
        self.city_status = FieldStatus.CONFIRMED
        self.confidence_scores["city"] = score
        self.matched_via["city"] = match_type.value

    def set_area(self, name: str, match_type: MatchType, score: float):
        self.area = name
        self.area_status = FieldStatus.CONFIRMED
        self.confidence_scores["area"] = score
        self.matched_via["area"] = match_type.value

    def flag_governorate_review(self, reason: str):
        self.governorate_status = FieldStatus.NEEDS_REVIEW
        self.needs_review = True
        self.review_reason = reason

    def flag_city_review(self, reason: str):
        self.city_status = FieldStatus.NEEDS_REVIEW
        self.needs_review = True
        self.review_reason = reason

    def flag_area_review(self, reason: str):
        self.area_status = FieldStatus.NEEDS_REVIEW
        self.needs_review = True
        self.review_reason = reason

    def clear_review(self):
        """Clear a pending review flag (used when a later rule resolves the field)."""
        self.needs_review = False
        self.review_reason = None

    def fail(self, reason: str):
        self.needs_review = True
        self.review_reason = reason

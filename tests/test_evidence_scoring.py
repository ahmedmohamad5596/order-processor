"""Task 6: evidence-scoring engine (fix2 §5-7).

- Roads/streets are never auto-promoted to AREA just because they appear in
  the address (fix2 §7): a road spans multiple neighborhoods.
- A near tie between the top candidates means ambiguous, not "top wins"
  (fix2 §6): confidence must come from evidence, and false positives are
  worse than an unresolved field.
- Same input ⇒ same output, every time (fix2 §11, run 100x).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.lookup_builder import build_lookup
from engine.matcher import (
    _decisive_scores,
    _find_area,
    _find_governorate_fuzzy,
    _fuzzy_score,
    match_address,
)
from engine.models import FieldStatus

_LOOKUP = build_lookup()


def _match(text: str):
    return match_address(text, _LOOKUP)


class TestRoadIsNotAnArea:
    """fix2 §7 — long roads must not be treated as areas."""

    def test_geda_suez_road_not_area(self):
        r = _match("القاهرة، جسر السويس، شارع جمال عبد الناصر، جسر السويس")
        assert r.governorate == "القاهرة"
        assert r.governorate_status == FieldStatus.CONFIRMED
        assert r.area != "جسر السويس"
        assert r.area in (None, "")
        assert r.needs_review is True
        assert not (r.matched_via.get("area") or "")

    def test_haram_street_not_area(self):
        r = _match("الجيزة شارع الهرم شقة ٥")
        assert r.governorate == "الجيزة"
        assert r.area != "شارع الهرم"
        assert r.area not in ("شارع الهرم",)
        assert r.needs_review is True

    def test_compound_still_resolves_as_area(self):
        """Compounds are area-level entities — they must keep resolving."""
        r = _match("محافظة القاهرة التجمع الخامس كمبوند ريتاج عمارة ٦ شقة ٣٠١")
        assert r.area == "ريتاج"
        assert r.area_status == FieldStatus.CONFIRMED
        assert r.needs_review is False

    def test_real_area_still_resolves(self):
        r = _match("شارع سمير شحاته، الياسمين، التجمع الأول، القاهرة الجديدة، القاهرة")
        assert r.area == "التجمع الأول"
        assert r.area_status == FieldStatus.CONFIRMED


class TestEvidenceMargin:
    """fix2 §6 — a small margin between candidates means ambiguous."""

    def test_decisive_margin(self):
        assert _decisive_scores([95.0]) is True
        assert _decisive_scores([95.0, 60.0]) is True

    def test_near_tie_is_not_decisive(self):
        assert _decisive_scores([82.0, 81.0]) is False

    def test_exact_tie_is_not_decisive(self):
        assert _decisive_scores([90.0, 90.0]) is False

    def test_area_near_tie_returns_ambiguous(self, monkeypatch):
        """Two close area candidates → (None, reason) instead of a forced pick."""
        def faked_score(_a, name):
            return 93.0 if "متشابهة أ" in name else 91.0

        monkeypatch.setattr(
            "engine.matcher._fuzzy_score", faked_score
        )
        areas = {
            "المنطقة المتشابهة أ": {
                "id": "AR0001", "area_name": "المنطقة المتشابهة أ",
                "entity_type": "area", "governorate_id": "01",
            },
            "المنطقة المتشابهة ب": {
                "id": "AR0002", "area_name": "المنطقة المتشابهة ب",
                "entity_type": "area", "governorate_id": "01",
            },
        }
        cand, note = _find_area(["المنطقة"], "المنطقة المتشابهة", "01", None, areas)
        assert cand is None
        assert note and "ambiguous" in note

    def test_area_decisive_still_resolves(self, monkeypatch):
        def faked_score(_a, name):
            return 95.0 if "المتشابهة أ" in name else 60.0

        monkeypatch.setattr("engine.matcher._fuzzy_score", faked_score)
        areas = {
            "المنطقة المتشابهة أ": {
                "id": "AR0001", "area_name": "المنطقة المتشابهة أ",
                "entity_type": "area", "governorate_id": "01",
            },
        }
        cand, note = _find_area(["المنطقة"], "المنطقة المتشابهة", "01", None, areas)
        assert note is None
        assert cand is not None and cand.name == "المنطقة المتشابهة أ"

    def test_governorate_near_tie_is_ambiguous(self, monkeypatch):
        def faked_score(_a, name):
            if "المنوفية" in name:
                return 82.0
            if "الشرقية" in name:
                return 81.0
            return 0.0

        monkeypatch.setattr("engine.matcher._fuzzy_score", faked_score)
        govs = {
            "المنوفية": {"name_ar": "المنوفية", "id": "10"},
            "الشرقية": {"name_ar": "الشرقية", "id": "14"},
        }
        cand, note = _find_governorate_fuzzy(["س"], govs, {})
        assert cand is None
        assert note and "ambiguous" in note

    def test_governorate_decisive_resolves(self, monkeypatch):
        def faked_score(_a, name):
            if "الشرقية" in name:
                return 95.0
            return 0.0

        monkeypatch.setattr("engine.matcher._fuzzy_score", faked_score)
        govs = {
            "الشرقية": {"name_ar": "الشرقية", "id": "14"},
        }
        cand, note = _find_governorate_fuzzy(["س"], govs, {})
        assert note is None
        assert cand is not None and cand.name == "الشرقية"


class TestDeterminism:
    """fix2 §11 — same input, identical output, 100 runs."""

    ADDRESSES = [
        "القاهرة، جسر السويس، شارع جمال عبد الناصر، جسر السويس",
        "٩٣ فيلا. شارع سمير شحاته، الياسمين، التجمع الأول، القاهرة الجديدة، القاهرة",
        "22ش عاطف عيد الشهير بالزريبة، الطالبية، الهرم، الجيزة",
        "٦ اكتوبر الحي التاني مجاوره ٤ شارع رنا مول عماره ١٠٦٢ الدور الاول شقه ٢",
        "المنصورة الاتوبيس الجديد اول شارع شمال من ناحية اولاد رجب فوق مسجد الفاروق",
    ]

    def test_identical_output_100_runs(self):
        for text in self.ADDRESSES:
            first = _match(text)
            for _ in range(100):
                again = _match(text)
                assert (again.governorate, again.governorate_id,
                        again.city, again.city_id,
                        again.area, again.street,
                        again.needs_review, again.review_reason,
                        again.confidence_scores, again.matched_via) == (
                    first.governorate, first.governorate_id,
                    first.city, first.city_id,
                    first.area, first.street,
                    first.needs_review, first.review_reason,
                    first.confidence_scores, first.matched_via)


def test_fuzzy_score_identity_is_100():
    s = _fuzzy_score("المنطقة المتشابهة أ", "المنطقة المتشابهة أ")
    assert s == 100.0
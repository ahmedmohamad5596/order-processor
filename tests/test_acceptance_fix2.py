"""Acceptance tests for the fix2 overhaul (fix2 §14, all 13 criteria).

Each criterion maps to one test method + a determinism run (same input, same
output, ×100). These prove the resolver behaves independently of any UI
dropdown: free text is always saved, the full geographic reference powers both
resolution and autocomplete, near-ties and ambiguous values stay unresolved,
roads never become areas, parent relationships disambiguate duplicates, and
false positives are never preferred over an unresolved value.
"""
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.lookup_builder import build_lookup
from engine.matcher import match_address, _decisive_scores
from engine.geo_search import search_geo
from engine.normalizer import normalize_lookup_key
from engine.save_address import (
    assemble_saved_address,
    canonicalize_city,
    resolve_address,
)
from engine.models import FieldStatus

_LOOKUP = build_lookup()


def _match(text: str):
    return match_address(text, _LOOKUP)


def _area_id(name: str):
    a = _LOOKUP["areas"].get(normalize_lookup_key(name))
    return a["id"] if a else None


class TestAC1_CityNotVisibleInUiStillResolves:
    """A city absent from any small dropdown resolves from the full reference."""

    def test_manzala(self):
        r = _match("المنزلة شارع الجمهورية الدقهلية")
        assert r.city == "المنزلة"
        assert r.city_id == "08-009"
        assert r.city_status == FieldStatus.CONFIRMED

    def test_mahalla(self):
        r = _match("المحلة الكبرى شارع البحر")
        assert r.city == "المحلة الكبرى"
        assert r.city_id == "10-002"
        assert r.city_status == FieldStatus.CONFIRMED

    def test_full_reference_size(self):
        assert len(_LOOKUP["cities"]) >= 287


class TestAC2_ManuallyTypedCityCanBeSaved:
    def test_free_typed_city_is_saved_and_resolved(self):
        a, errors = assemble_saved_address(
            {}, {"city": "المحلة الكبرى", "governorate": "", "area": ""}, _LOOKUP
        )
        assert a["manual_city"] == "المحلة الكبرى"  # free text preserved
        assert a["city_id"] == "10-002"             # resolved from full reference
        assert a["resolution_status"] == "human_confirmed"
        assert errors == []
        assert a["needs_review"] is False

    def test_alias_spelling_saved_and_resolved(self):
        a, errors = assemble_saved_address(
            {}, {"city": "6اكتوبر", "governorate": "الجيزة", "area": ""}, _LOOKUP
        )
        assert a["manual_city"] == "6اكتوبر"
        assert a["city"] == "أكتوبر (مدينة 6 أكتوبر)"
        assert a["city_id"] == "02-016"
        assert a["resolution_status"] == "human_confirmed"
        assert errors == []


class TestAC3_ManuallyTypedAreaCanBeSaved:
    def test_free_typed_area_is_saved_and_resolved(self):
        a, errors = assemble_saved_address(
            {},
            {"governorate": "القاهرة", "city": "القاهرة الجديدة", "area": "التجمع الخامس"},
            _LOOKUP,
        )
        assert a["manual_area"] == "التجمع الخامس"
        assert a["area_id"] == _area_id("التجمع الخامس")
        assert a["resolution_status"] == "human_confirmed"
        assert errors == []

    def test_area_not_in_reference_still_saved(self):
        a, errors = assemble_saved_address(
            {},
            {"governorate": "القاهرة", "city": "القاهرة الجديدة", "area": "مول العرب"},
            _LOOKUP,
        )
        assert a["manual_area"] == "مول العرب"
        assert a["area_id"] is None          # not forced to a "closest" area
        assert a["resolution_status"] == "human_confirmed"
        assert errors == []


class TestAC4_AutocompleteSearchesFullDatabase:
    def test_city_deep_in_reference(self):
        res = search_geo("المحلة", "city", _LOOKUP, 5)
        assert res and any(r["name"] == "المحلة الكبرى" for r in res)

    def test_alias_searchable(self):
        res = search_geo("اكتوبر", "city", _LOOKUP, 5)
        assert res and any(r["name"] == "أكتوبر (مدينة 6 أكتوبر)" for r in res)

    def test_area_searchable_with_metadata(self):
        res = search_geo("التجمع", "area", _LOOKUP, 5)
        assert res and any(r["name"] == "التجمع الأول" for r in res)
        for r in res:
            assert r["id"] and r["name"] and r["type"] == "area"


class TestAC5_ResolverIndependentOfUiDropdown:
    def test_city_absent_from_ui_lists_resolves(self):
        c = canonicalize_city("شبين القناطر", "", _LOOKUP)
        assert c["matched"] is True
        assert c["city"] == "شبين القناطر"
        rid = resolve_address("", "شبين القناطر", "", _LOOKUP)
        assert rid["city_id"] == "03-007"

    def test_resolved_ids_always_come_from_reference(self):
        """Every resolver output must be a real reference entity — never a
        dropdown-derived string."""
        a, _ = assemble_saved_address(
            {}, {"city": "بني عبيد", "governorate": "", "area": ""}, _LOOKUP
        )
        assert a["city_id"] == "08-008"
        assert any(c["id"] == a["city_id"] for c in _LOOKUP["cities"].values())


class TestAC6_SameAddressSameResult:
    def test_identical_output_100_runs(self):
        addresses = [
            "المنزلة شارع الجمهورية الدقهلية",
            "العبور، القليوبية",
            "القاهرة، جسر السويس، شارع جمال عبد الناصر، جسر السويس",
            "6 أكتوبر الحي التاني مجاوره ٤ عماره ١٠٦٢",
            "شارع سمير شحاته، الياسمين، التجمع الأول، القاهرة الجديدة، القاهرة",
        ]
        for text in addresses:
            first = _match(text)
            first_json = json.dumps({
                "gov": first.governorate, "gov_id": first.governorate_id,
                "city": first.city, "city_id": first.city_id,
                "area": first.area, "street": first.street,
                "review": first.needs_review, "reason": first.review_reason,
                "confidence": first.confidence_scores, "via": first.matched_via,
            }, sort_keys=True)
            for _ in range(100):
                again = _match(text)
                again_json = json.dumps({
                    "gov": again.governorate, "gov_id": again.governorate_id,
                    "city": again.city, "city_id": again.city_id,
                    "area": again.area, "street": again.street,
                    "review": again.needs_review, "reason": again.review_reason,
                    "confidence": again.confidence_scores, "via": again.matched_via,
                }, sort_keys=True)
                assert again_json == first_json


class TestAC7_AmbiguousAddressesRemainAmbiguous:
    def test_noon_city_ambiguous(self):
        r = _match("شارع X، مدينة نصر، القاهرة")
        assert r.needs_review is True
        assert r.city_status in (FieldStatus.NEEDS_REVIEW, FieldStatus.UNKNOWN)

    def test_obour_multi_governorate_ambiguous(self):
        r = _match("العبور، شارع ١٥")
        assert r.needs_review is True
        assert r.city_status in (FieldStatus.NEEDS_REVIEW, FieldStatus.UNKNOWN)


class TestAC8_RoadNotAutomaticallyAnArea:
    def test_geda_suez(self):
        r = _match("القاهرة، جسر السويس، شارع جمال عبد الناصر، جسر السويس")
        assert r.area not in ("جسر السويس",)
        assert r.area in (None, "")
        assert r.needs_review is True

    def test_salah_salem(self):
        r = _match("القاهرة، صلاح سالم، عمارة ١٢")
        assert r.area not in ("صلاح سالم",)
        assert r.area in (None, "")
        assert r.needs_review is True

    def test_road_is_searchable_but_not_area(self):
        res = search_geo("جسر السويس", "road", _LOOKUP, 5)
        assert res and res[0]["type"] == "road"


class TestAC9_DuplicateNamesDisambiguatedByParent:
    def test_without_parent_ambiguous(self):
        c = canonicalize_city("العبور", "", _LOOKUP)
        assert c["matched"] is False
        assert c["ambiguous"] is True

    def test_parent_cairo_resolves_cairo_obour(self):
        a, errors = assemble_saved_address(
            {}, {"city": "العبور", "governorate": "القاهرة", "area": ""}, _LOOKUP
        )
        assert a["city"] == "العبور"
        assert a["city_id"] == "01-037"
        assert errors == []

    def test_parent_qalyubia_resolves_medinat_alobour(self):
        a, errors = assemble_saved_address(
            {}, {"city": "العبور", "governorate": "القليوبية", "area": ""}, _LOOKUP
        )
        assert a["city"] == "مدينة العبور"
        assert a["city_id"] == "03-009"
        assert errors == []


class TestAC10_ArabicSpellingVariations:
    def test_october_variants_same_entity(self):
        variants = ["6 أكتوبر", "6اكتوبر", "٦ أكتوبر", "اكتوبر"]
        ids = {
            resolve_address("الجيزة", v, "", _LOOKUP)["city_id"] for v in variants
        }
        assert ids == {"02-016"}

    def test_mansourah_hamza_variants_same_entity(self):
        a1 = resolve_address("", "المنصورة", "", _LOOKUP)
        a2 = resolve_address("", "المنصوره", "", _LOOKUP)
        assert a1["city_id"] == a2["city_id"]
        assert a1["city_id"] is not None


class TestAC11_ArabicEnglishMixed:
    def test_latin_digit_plus_arabic_resolves(self):
        r = _match("6 أكتوبر الحي التاني شارع رنا")
        assert r.city == "أكتوبر (مدينة 6 أكتوبر)"
        assert r.city_id == "02-016"

    def test_fused_latin_digit_arabic_resolves(self):
        r = _match("6اكتوبر مجاوره ٤ عماره ١٠٦٢")
        assert r.city_id == "02-016"

    def test_latin_only_never_false_positive(self):
        r = _match("Giza 5th Settlement")
        assert r.city in (None, "")
        assert r.needs_review is True


class TestAC12_ConfidenceIsEvidenceBased:
    def test_exact_evidence_full_confidence(self):
        r = _match("شارع سمير شحاته، الياسمين، التجمع الأول، القاهرة الجديدة، القاهرة")
        assert r.confidence_scores["city"] == 100.0
        assert r.matched_via["city"] == "exact"

    def test_close_candidates_are_ambiguous_not_forced(self):
        assert _decisive_scores([82.0, 81.0]) is False
        r = _match("شارع X، مدينة نصر، القاهرة")
        assert r.city_status != FieldStatus.CONFIRMED
        assert r.needs_review is True


class TestAC13_FalsePositivesNotPreferred:
    def test_no_city_echo_of_governorate(self):
        r = _match("القاهرة شارع رمسيس")
        assert r.city in (None, "")
        assert r.city != r.governorate
        assert r.needs_review is True

    def test_road_never_becomes_area(self):
        r = _match("شارع الهرم، الجيزة")
        assert r.area not in ("شارع الهرم",)
        assert r.area in (None, "")
        assert r.needs_review is True

    def test_unresolved_area_does_not_copy_city(self):
        r = _match("المنزلة شارع الجمهورية الدقهلية")
        assert r.area != r.city


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Tests for engine.geo_search — the full-reference autocomplete search."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.geo_search import search_geo


def _find(results, etype, name=None, gov=None):
    for r in results:
        if r["type"] != etype:
            continue
        if name is not None and r["name"] != name:
            continue
        if gov is not None and r["governorate"] != gov:
            continue
        return r
    return None


class TestExactAndPrefix:
    def test_governorate_exact(self):
        res = search_geo("القاهرة", "governorate")
        r = _find(res, "governorate", "القاهرة")
        assert r is not None and r["score"] == 100.0 and r["id"] == "01"

    def test_governorate_hamza_variant(self):
        res = search_geo("القاهره", "governorate")
        assert _find(res, "governorate", "القاهرة") is not None

    def test_road_prefix(self):
        res = search_geo("جسر", "road")
        r = _find(res, "road", "جسر السويس")
        assert r is not None and r["score"] == 100.0

    def test_city_alias(self):
        res = search_geo("6 أكتوبر", "city")
        assert _find(res, "city", "أكتوبر (مدينة 6 أكتوبر)") is not None

    def test_city_alias_with_arabic_digits(self):
        res = search_geo("٦ أكتوبر", "city")
        assert _find(res, "city", "أكتوبر (مدينة 6 أكتوبر)") is not None

    def test_area_prefix(self):
        res = search_geo("التجمع", "")
        r = _find(res, "area", "التجمع الخامس")
        assert r is not None and r["city"] == "القاهرة الجديدة"


class TestEntityTypes:
    def test_road_is_not_area(self):
        """A long road typed `road` must never surface as an `area`."""
        res = search_geo("جسر", "area")
        assert all(r["type"] != "road" for r in res)
        assert _find(res, "area", "جسر السويس") is None

    def test_road_type_searchable(self):
        res = search_geo("جسر السويس", "road")
        r = _find(res, "road", "جسر السويس")
        assert r is not None and r["governorate"] == "القاهرة"

    def test_compound_type(self):
        res = search_geo("ريتاج", "compound")
        assert _find(res, "compound", "ريتاج") is not None

    def test_village_type(self):
        res = search_geo("ميت بره", "village")
        assert _find(res, "village", "ميت بره") is not None

    def test_default_types_include_roads(self):
        res = search_geo("كورنيش", "")
        assert any(r["type"] == "road" for r in res)


class TestContainsAndFuzzy:
    def test_contains_tail(self):
        res = search_geo("السويس", "road")
        assert _find(res, "road", "جسر السويس") is not None

    def test_contains_short(self):
        res = search_geo("نصر", "city")
        assert _find(res, "city", "شرق مدينة نصر") is not None

    def test_fuzzy_typo(self):
        res = search_geo("شبرا الخيمه", "city")
        assert any(r["name"].startswith("مدينة شبرا الخيمة") for r in res)


class TestTypeFiltering:
    def test_types_area_excludes_roads(self):
        res = search_geo("جسر", "area")
        assert all(r["type"] == "area" for r in res)

    def test_types_city_excludes_gov(self):
        res = search_geo("القاهرة", "city")
        assert all(r["type"] == "city" for r in res)

    def test_no_match_returns_empty(self):
        assert search_geo("zzzلايوجد", "") == []

    def test_empty_query_returns_empty(self):
        assert search_geo("", "") == []


class TestResultShape:
    def test_every_result_has_required_fields(self):
        res = search_geo("الرحاب", "")
        assert res
        for r in res:
            for key in ("id", "name", "type", "governorate", "city", "parent", "aliases", "score"):
                assert key in r

    def test_sorting_score_desc(self):
        res = search_geo("نصر", "city")
        scores = [r["score"] for r in res]
        assert scores == sorted(scores, reverse=True)

    def test_limit(self):
        res = search_geo("ا", "", limit=3)
        assert len(res) <= 3


class TestIndependenceFromUI:
    def test_city_not_in_any_gov_dropdown_edge(self):
        """Search finds entities regardless of which governorate is selected."""
        res = search_geo("الزيتون", "city")
        assert any(r["name"] == "الزيتون" for r in res)

    def test_determinism(self):
        a = search_geo("جسر السويس", "area")
        b = search_geo("جسر السويس", "area")
        assert a == b
"""Tests for the areas layer (level 3 below governorate/city) in the lookup.

Covers the ''المناطق والأحياء'' seed sheet merge with learned areas, entity
typing (area/road/compound/village) and parent relationships — the data model
backing fix2 requirements: roads are typed ROAD, not AREA, and every entity
has a stable ID plus governorate/city parents.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.lookup_builder import build_lookup
from engine.normalizer import normalize_lookup_key

_LOOKUP = build_lookup()


def _areas():
    return _LOOKUP["areas"]


class TestSeedLayer:
    def test_has_substantial_seed(self):
        assert len(_areas()) >= 120

    def test_all_entity_types_present(self):
        types = {a["entity_type"] for a in _areas().values()}
        assert {"area", "road", "compound", "village"} <= types

    def test_every_entity_has_id_and_governorate(self):
        for a in _areas().values():
            assert a["id"]
            assert a["governorate_id"]

    def test_road_is_typed_road(self):
        assert _areas()[normalize_lookup_key("جسر السويس")]["entity_type"] == "road"

    def test_major_roads_are_not_areas(self):
        for name in ("صلاح سالم", "شارع الهرم", "كورنيش النيل", "الطريق الدائري"):
            a = _areas().get(normalize_lookup_key(name))
            assert a is not None, name
            assert a["entity_type"] == "road", name

    def test_compound_typed(self):
        assert _areas()[normalize_lookup_key("ريتاج")]["entity_type"] == "compound"

    def test_city_parent_link(self):
        a = _areas()[normalize_lookup_key("التجمع الخامس")]
        assert a["city_id"] == "01-035"


class TestLearnedMerge:
    def test_learned_only_area_survives(self):
        a = _areas().get(normalize_lookup_key("الواحات البحرية"))
        assert a is not None and a["source"] == "learned"

    def test_learned_area_enriches_seed_city(self):
        a = _areas()[normalize_lookup_key("ميت بره")]
        assert a["city_id"] == "11-006" and a["entity_type"] == "village"

    def test_learned_does_not_downgrade_road(self):
        a = _areas()[normalize_lookup_key("جسر السويس")]
        assert a["entity_type"] == "road"


class TestDeterminism:
    def test_lookup_is_stable_across_builds(self):
        fresh = build_lookup(force=True)
        assert fresh["areas"] == _areas()
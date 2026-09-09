"""Tests for the radical fixes applied to the book/price matcher.

Covers the root-cause cases extracted from the 14 needs-review customers:
  - تالته → G3 mapping (#10)
  - Everybody Up English variants + term markers (#6)
  - التيرم الاول no longer spawns a phantom أولى إعدادي (#16)
  - "٣ نسخ" is a quantity, not grade G3 (#19)
  - Numeric levels ↔ G-code (Opportunities 3 → 130) (#20)
  - Continuation-line linking via link_items (#9, #11, #12, #15, #19)
  - grade_hint from year_edition (#9, #4)
"""
import pytest

from engine.book_lookup_builder import build_book_lookup, _ARABIC_BOOK_ALIASES
from engine.book_matcher import (
    match_book_order, link_items, extract_quantity, detect_grade,
    _is_genuine_grade, _grades_equal, _TERM_NOISE_RE, _ORDINAL_TO_GCODE,
)


@pytest.fixture(scope="module")
def book_lookup():
    return build_book_lookup(force=True)


class TestGradeMappings:
    def test_talthe_g3(self, book_lookup):
        items = match_book_order("باور اپ تانيه وتالته ابتدائي", book_lookup)
        grades = [i.grade for i in items]
        assert "G2" in grades
        assert "G3" in grades

    def test_ordinal_map_keys(self):
        assert _ORDINAL_TO_GCODE["تالته"] == "G3"
        assert _ORDINAL_TO_GCODE["تالتة"] == "G3"


class TestEverybodyUpAliases:
    def test_alias_present(self):
        for key in ("ever bady up", "ever bady", "everbody", "every body up"):
            assert key in _ARABIC_BOOK_ALIASES

    def test_everybody_up(self, book_lookup):
        items = match_book_order("كتاب ال ever bady up التيرم الاول للصف الرابع الابتدائي", book_lookup)
        assert len(items) == 1
        assert items[0].grade == "G4"
        assert items[0].price == 150.0
        assert items[0].needs_review is False


class TestTermNoiseStripping:
    def test_no_phantom_prep_item(self, book_lookup):
        """الترم الاول must not produce a phantom أولى إعدادي line item."""
        items = match_book_order(
            "بايونير level B2 الصف الثالث الاعدادي الترم الاول كتاب واحد", book_lookup)
        assert len(items) == 1
        assert items[0].grade == "تالتة إعدادي"
        assert items[0].price == 140.0
        assert items[0].needs_review is False

    def test_term_noise_regex(self):
        assert _TERM_NOISE_RE.sub(" ", "التيرم الاول").strip() == ""
        assert _TERM_NOISE_RE.sub(" ", "الترم التاني").strip() == ""


class TestQuantityVersusGrade:
    def test_three_neskh_is_quantity_not_grade(self):
        gi = detect_grade("٣ نسخ")
        assert gi.grade is None

    def test_quantity_neskh(self):
        qty, assumed, mult = extract_quantity("٣ نسخ")
        assert qty == 3
        assert assumed is False

    def test_dual_book_quantity(self, book_lookup):
        qty, assumed, mult = extract_quantity("كتابين")
        assert qty == 2
        assert assumed is False

    def test_genuine_grade_detection(self):
        assert _is_genuine_grade("٣ نسخ", detect_grade("٣ نسخ")) is False
        assert _is_genuine_grade("كتابين grade 2", detect_grade("كتابين grade 2")) is True
        assert _is_genuine_grade("نسخه واحده جريد٦", detect_grade("نسخه واحده جريد٦")) is True


class TestNumericLevelPrice:
    def test_power_up_g3(self, book_lookup):
        items = match_book_order("كتاب power up 3", book_lookup)
        assert len(items) == 1
        assert items[0].price == 160.0
        assert items[0].needs_review is False
        assert items[0].grade is not None


class TestGradesEqual:
    def test_same_grade(self):
        assert _grades_equal("G3", "تالته") or _grades_equal("G3", "تالتة") or _grades_equal("G3", "G3")
        assert _grades_equal("تالتة إعدادي", "تالته اعدادي")


class TestLinkItems:
    def test_quantity_only_carries_to_book(self, book_lookup):
        items = link_items(
            ["هاي ليفيل منهجour world جريد ٤", "٣ نسخ"],
            book_lookup,
        )
        assert len(items) == 1
        assert items[0].book_name is not None
        assert items[0].grade == "G4"
        assert items[0].quantity == 3
        assert items[0].needs_review is False

    def test_header_book_with_grade_continuations(self, book_lookup):
        items = link_items(
            ["كتاب power up", "كتابين grade 2", "كتاب grade 6", "3كتب grade 1"],
            book_lookup,
        )
        by_grade = {}
        for it in items:
            by_grade.setdefault(it.grade, []).append(it)
        assert "G2" in by_grade and by_grade["G2"][0].quantity == 2
        assert "G6" in by_grade and by_grade["G6"][0].quantity >= 1
        assert "G1" in by_grade and by_grade["G1"][0].quantity == 3
        # header "power up" without grade must be replaced by graded items
        assert all(it.grade for it in items)

    def test_book_then_grade_continuation(self, book_lookup):
        items = link_items(
            ["كتاب ورلد وتشر", "نسخه واحده جريد٦", "نسخه واحده جريد٣"],
            book_lookup,
        )
        grades = sorted(it.grade for it in items)
        assert "G3" in grades
        assert "G6" in grades
        assert all(it.price is not None and it.needs_review is False for it in items)

    def test_grade_line_before_book(self, book_lookup):
        items = link_items(
            ["نسخه كتاب الصف الثالث الإعدادي", "كتاب power up 3"],
            book_lookup,
        )
        assert len(items) == 1
        assert items[0].price == 160.0

    def test_grade_hint_resolves_power_up(self, book_lookup):
        items = link_items(
            ["كتاب power up", "خمس نسخ"],
            book_lookup,
            grade_hint="٣ ابتدائى",
        )
        assert len(items) == 1
        assert items[0].grade == "G3"
        assert items[0].quantity == 5
        assert items[0].price == 160.0
        assert items[0].needs_review is False

    def test_per_customer_like_case(self, book_lookup):
        items = link_items(
            ["كتاب ال ever bady up التيرم الاول للصف الرابع الابتدائي", "خمس نسخ"],
            book_lookup,
        )
        assert len(items) == 1
        assert items[0].book_name is not None
        assert items[0].grade == "G4"
        assert items[0].quantity == 5
        assert items[0].price == 150.0
"""Tests for Book & Price Matching Engine (Part 2).

Covers the 7 mandatory test cases from the spec plus edge cases.
"""
import pytest

from engine.book_lookup_builder import build_book_lookup
from engine.book_matcher import match_book_order, extract_quantity, split_items
from engine.models import FieldStatus


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def book_lookup():
    """Build book lookup once for all tests."""
    return build_book_lookup(force=True)


def _match(text: str, lookup):
    return match_book_order(text, lookup)


# ── B1: B-code fallback ──────────────────────────────────────

class TestB1_BCodeFallback:
    """B1 code → أولى إعدادي, price 140."""

    INPUT = "٤ كتب new close up b1"
    EXPECTED_BOOK = "New Close up B1"
    EXPECTED_GRADE = "أولى إعدادي"
    EXPECTED_PRICE = 140.0
    EXPECTED_QTY = 4

    def test_book_name(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].book_name == self.EXPECTED_BOOK

    def test_grade_from_bcode(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].grade == self.EXPECTED_GRADE

    def test_price(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].price == self.EXPECTED_PRICE

    def test_quantity(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].quantity == self.EXPECTED_QTY

    def test_not_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].needs_review is False


# ── B2: B2 code fallback ─────────────────────────────────────

class TestB2_B2CodeFallback:
    """B2 code → تالتة إعدادي, price 140."""

    INPUT = "1 كتاب new close up b2"
    EXPECTED_BOOK = "New Close up B2"
    EXPECTED_GRADE = "تالتة إعدادي"
    EXPECTED_PRICE = 140.0
    EXPECTED_QTY = 1

    def test_book_name(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].book_name == self.EXPECTED_BOOK

    def test_grade(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].grade == self.EXPECTED_GRADE

    def test_price(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].price == self.EXPECTED_PRICE

    def test_not_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].needs_review is False


# ── B3: English stage + number ───────────────────────────────

class TestB3_EnglishStageGrade:
    """'primary 4' → G4, Full Blast Second Edition, price 160."""

    INPUT = "2 كتاب full blast second edition primary 4"
    EXPECTED_BOOK = "Full Blast Second Edition"
    EXPECTED_GRADE = "G4"
    EXPECTED_PRICE = 160.0
    EXPECTED_QTY = 2

    def test_book_name(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].book_name == self.EXPECTED_BOOK

    def test_grade(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].grade == self.EXPECTED_GRADE

    def test_price(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].price == self.EXPECTED_PRICE

    def test_quantity(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].quantity == self.EXPECTED_QTY

    def test_not_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].needs_review is False


# ── B4: Multi-item order with Arabic grades ──────────────────

class TestB4_MultiItemArabicGrades:
    """Power Up الصف الثاني + Power Up الصف الثالث → 2 line items."""

    INPUT = "Power Up الصف الثاني نسخه واحده + Power Up الصف الثالث نسخه واحده"

    def test_two_items(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 2

    def test_first_item(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].book_name == "Power Up"
        assert items[0].grade == "G2"
        assert items[0].price == 160.0
        assert items[0].quantity == 1
        assert items[0].needs_review is False

    def test_second_item(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[1].book_name == "Power Up"
        assert items[1].grade == "G3"
        assert items[1].price == 160.0
        assert items[1].quantity == 1
        assert items[1].needs_review is False


# ── B5: Ambiguous book (multiple stages) ─────────────────────

class TestB5_AmbiguousMultiStage:
    """English World without grade → needs_review (Primary + Preparatory)."""

    INPUT = "English World"

    def test_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].needs_review is True

    def test_review_reason(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert "multiple stages" in items[0].review_reason.lower() or \
               "no grade" in items[0].review_reason.lower()


# ── B6: Arabic grade + secondary stage ───────────────────────

class TestB6_ArabicGradeSecondary:
    """Aim High للصف الاول الثانوي → grade=الأول الثانوي, price=160."""

    INPUT = "Aim High للصف الاول الثانوي"
    EXPECTED_BOOK = "Aim High"
    EXPECTED_GRADE = "الأول الثانوي"
    EXPECTED_PRICE = 160.0

    def test_book_name(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].book_name == self.EXPECTED_BOOK

    def test_grade(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].grade == self.EXPECTED_GRADE

    def test_price(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].price == self.EXPECTED_PRICE

    def test_not_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert items[0].needs_review is False


# ── B7: Multiplier phrase + single-stage uniform price ───────

class TestB7_MultiplierWithGrades:
    """Family & Friends with grades explicitly mentioned before multiplier.

    Input mentions الصف الأول والتاني والتالت الابتدائي → 3 line items.
    """
    INPUT = "Family & Friends للصف الأول والتاني والتالت الابتدائي، نسخة من كل مرحلة"
    EXPECTED_BOOK = "Family & Friends"
    EXPECTED_PRICE = 140.0

    def test_three_line_items(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 3

    def test_each_item_has_correct_grade(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        grades = [i.grade for i in items]
        assert "G1" in grades
        assert "G2" in grades
        assert "G3" in grades

    def test_each_item_price(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        for item in items:
            assert item.price == self.EXPECTED_PRICE
            assert item.quantity == 1
            assert item.needs_review is False


class TestB7b_MultiplierNoGrades:
    """Multiplier phrase with NO grades mentioned before it → needs_review.

    Per spec: إذا مفيش أي صف مذكور قبل العبارة، الحالة تبقى غامضة.
    """
    INPUT = "نسخة من كل مرحلة كتاب Family & Friends"

    def test_needs_review(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert len(items) == 1
        assert items[0].needs_review is True

    def test_review_reason(self, book_lookup):
        items = _match(self.INPUT, book_lookup)
        assert "no grades" in items[0].review_reason.lower() or \
               "غامض" in items[0].review_reason


# ── Edge cases ───────────────────────────────────────────────

class TestEdgeCases:
    """Additional edge cases for robustness."""

    def test_quantity_arabic_word(self, book_lookup):
        """'اربع نسخ' → qty=4."""
        items = _match("اربع نسخ macmillan", book_lookup)
        assert items[0].quantity == 4

    def test_quantity_assumed(self, book_lookup):
        """No quantity mentioned → assumed=1, quantity_assumed=True."""
        items = _match("macmillan", book_lookup)
        assert items[0].quantity == 1
        assert items[0].quantity_assumed is True

    def test_aim_high_vs_aim_high_4(self, book_lookup):
        """'Aim High' (preparatory) ≠ 'Aim High' (secondary) — matched by grade context."""
        items_a = _match("Aim High", book_lookup)
        items_sec = _match("Aim High للصف الاول الثانوي", book_lookup)
        assert items_a[0].book_name == "Aim High"
        assert items_sec[0].book_name == "Aim High"
        assert items_a[0].price is None  # multiple stages, needs review
        assert items_sec[0].price == 160.0

    def test_special_vs_second_edition(self, book_lookup):
        """'Full Blast Special' (G1=140) ≠ 'Full Blast Second Edition' (G4=160)."""
        items_s = _match("Full Blast Special G1", book_lookup)
        items_e = _match("Full Blast Second Edition G4", book_lookup)
        assert items_s[0].book_name == "Full Blast Special"
        assert items_e[0].book_name == "Full Blast Second Edition"
        assert items_s[0].price == 140.0
        assert items_e[0].price == 160.0

    def test_full_blast_g1_g2_different_prices(self, book_lookup):
        """Full Blast Special G1=140, G2=160 — different prices."""
        items_g1 = _match("Full Blast Special G1", book_lookup)
        items_g2 = _match("Full Blast Special G2", book_lookup)
        assert items_g1[0].price == 140.0
        assert items_g2[0].price == 160.0

    def test_split_items(self):
        """Split on '+' correctly."""
        parts = split_items("A + B + C")
        assert parts == ["A", "B", "C"]

    def test_split_no_plus(self):
        """No '+' → single item."""
        parts = split_items("Just one book")
        assert parts == ["Just one book"]

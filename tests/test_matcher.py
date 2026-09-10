"""Tests for engine.matcher — the 5 mandatory test cases from the spec."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.lookup_builder import build_lookup
from engine.matcher import match_address
from engine.models import FieldStatus

# Shared lookup — built once for all tests in this module
_LOOKUP = build_lookup()


def _match(text: str):
    return match_address(text, _LOOKUP)


class TestCase1_ExactMatch:
    """تطابق حرفي مباشر — Cairo new cities."""

    INPUT = "٩٣ فيلا. شارع سمير شحاته، الياسمين، التجمع الأول، القاهرة الجديدة، القاهرة"
    EXPECTED_GOV = "القاهرة"
    EXPECTED_CITY = "القاهرة الجديدة"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_area_resolved_from_table(self):
        """المنطقة تُحسم من قاعدة المناطق الواقعية — لا تُقلَّد من المدينة ولا تُنسخ."""
        r = _match(self.INPUT)
        assert r.area == "التجمع الأول"
        assert r.area != r.city  # حقيقية، وليست نسخة اسم المدينة
        assert (r.matched_via.get("area") or "") == "exact"
        assert "fallback_area_eq_city" not in (r.matched_via.get("area") or "")

    def test_no_review_when_area_resolved(self):
        """منطقة محسومة فعلياً → لا مراجعة."""
        r = _match(self.INPUT)
        assert r.needs_review is False

    def test_needs_review_when_area_absent(self):
        """مدينة محسومة بلا منطقة معروفة → مراجعة (لا تُنسخ المدينة في المنطقة)."""
        r = _match("شارع سمير شحاته، القاهرة الجديدة، القاهرة")
        assert r.area in (None, "")
        assert r.area != r.city
        assert r.needs_review is True
        assert "area" in (r.review_reason or "").lower()


class TestCase2_GovernorateNameAsCity:
    """الهرم قسم قائم بذاته — اختبار مباشر لمشكلة تكرار اسم المحافظة."""

    INPUT = "22ش عاطف عيد الشهير بالزريبة، الطالبية، الهرم، الجيزة"
    EXPECTED_GOV = "الجيزة"
    EXPECTED_CITY = "الطالبية"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city(self):
        """الطالبية (narrow) تفوز على الهرم (wide) بالقاعدة."""
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_resolved_by_rule(self):
        r = _match(self.INPUT)
        assert r.matched_via.get("city") == "narrow_wide_rule"

    def test_area_resolved_from_reference(self):
        """الزريبة منطقة حقيقية للطالبية — تُحسم من قواعد المناطق (وليس نسخة المدينة)."""
        r = _match(self.INPUT)
        assert r.area == "الزريبة"
        assert r.area != r.city
        assert r.area_status == FieldStatus.CONFIRMED
        assert r.needs_review is False


class TestCase3_CityDirectMatch:
    """الزاوية الحمراء = city مباشرة في الخطوة 4."""

    INPUT = "٥٢ شارع بورسعيد، الزاوية الحمراء، القاهرة"
    EXPECTED_GOV = "القاهرة"
    EXPECTED_CITY = "الزاوية الحمراء"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV

    def test_city(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_street(self):
        r = _match(self.INPUT)
        assert "بورسعيد" in (r.street or "")

    def test_no_area_fabrication(self):
        """لا منطقة مذكورة → مراجعة بدل نسخ المدينة."""
        r = _match(self.INPUT)
        assert r.area in (None, "")
        assert r.area != r.city
        assert r.needs_review is True


class TestCase4_UnknownArea:
    """عنوان بمنطقة غير موجودة — يجب needs_review."""

    INPUT = "شارعunknown، منطقةغيرموجودة، القاهرة"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == "القاهرة"
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_needs_review(self):
        """المحافظة واضحة لكن المدينة/المنطقة غير موجودة."""
        r = _match(self.INPUT)
        assert r.needs_review is True

    def test_no_guessing(self):
        """لا قيمة تخمينية في city."""
        r = _match(self.INPUT)
        assert r.city_status in (FieldStatus.NEEDS_REVIEW, FieldStatus.UNKNOWN)


class TestCase5_AmbiguousCity:
    """مدينة نصر بدون ذكر شرق/غرب — needs_review."""

    INPUT = "شارع X، مدينة نصر، القاهرة"
    EXPECTED_GOV = "القاهرة"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV

    def test_needs_review(self):
        """تعارض شرق/غرب بدون سياق → needs_review."""
        r = _match(self.INPUT)
        assert r.needs_review is True

    def test_city_not_guessed(self):
        """لا اختيار عشوائي لأي نتيجة."""
        r = _match(self.INPUT)
        assert r.city_status in (FieldStatus.NEEDS_REVIEW, FieldStatus.UNKNOWN)


class TestCase6_GovernorateFuzzyLast_CityTakesPriority:
    """المنصورة مدينة وليست تخمين محافظة — نتيجة التطابق الضبابي السيء كان المنوفية (75%)."""

    INPUT = "المنصورة الاتوبيس الجديد اول شارع شمال من ناحية اولاد رجب فوق مسجد الفاروق"
    EXPECTED_GOV = "الدقهلية"
    EXPECTED_CITY = "المنصورة"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_governorate_via_reverse_city(self):
        """المحافظة تأتي من city_to_gov لا من fuzzy — السلوك المطلوب في spec."""
        r = _match(self.INPUT)
        assert r.matched_via["governorate"] == "reverse_city_to_gov"

    def test_missing_area_needs_review(self):
        """لا منطقة مذكورة → مراجعة (لا نسخ المدينة في المنطقة)."""
        r = _match(self.INPUT)
        assert r.area in (None, "")
        assert r.area != r.city
        assert r.needs_review is True


class TestCase7_GovernorateTokenWithCity_Fused:
    """'الغربية طنطا' ملتصقان معاً — الطنطا تقطع وتتحل."""

    INPUT = "الغربية طنطا شارع سليمان المامون"
    EXPECTED_GOV = "الغربية"
    EXPECTED_CITY = "طنطا"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_missing_area_needs_review(self):
        """لا منطقة مذكورة → مراجعة (لا نسخ المدينة في المنطقة)."""
        r = _match(self.INPUT)
        assert r.area in (None, "")
        assert r.area != r.city
        assert r.needs_review is True


class TestCase8_GovernorateHiddenInCity:
    """اكتوبر مدينة في الجيزة وليست محافظة — بعد نسخة الخطأ القديمة (=الأقصر)."""

    INPUT = "٦ اكتوبر الحي التاني مجاوره ٤ شارع رنا مول عماره ١٠٦٢ الدور الاول شقه ٢"
    EXPECTED_GOV = "الجيزة"
    EXPECTED_CITY = "أكتوبر (مدينة 6 أكتوبر)"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == self.EXPECTED_GOV
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_area_resolved_from_reference(self):
        """الحي الثاني منطقة حقيقية في 6 أكتوبر — تُحسم من قواعد المناطق."""
        r = _match(self.INPUT)
        assert r.area == "الحي الثاني"
        assert r.area != r.city
        assert r.area_status == FieldStatus.CONFIRMED
        assert r.needs_review is False


class TestCase5b_AmbiguousCityWithHint:
    """مدينة نصر مع تلميح — يتحل."""

    INPUT = "شارع X، شرق مدينة نصر، القاهرة"
    EXPECTED_CITY = "شرق مدينة نصر"

    def test_city_resolved(self):
        r = _match(self.INPUT)
        assert r.city == self.EXPECTED_CITY
        assert r.city_status == FieldStatus.CONFIRMED

    def test_no_area_fabrication(self):
        """لا منطقة مذكورة → مراجعة بدل نسخ المدينة."""
        r = _match(self.INPUT)
        assert r.area in (None, "")
        assert r.area != r.city
        assert r.needs_review is True


class TestCase9_NoGovernorateAsCity:
    """المدينة لا تُعاد كاسم المحافظة (capital_city_fallback محذوف)."""

    INPUT = "القاهرة شارع رمسيس"

    def test_governorate(self):
        r = _match(self.INPUT)
        assert r.governorate == "القاهرة"
        assert r.governorate_status == FieldStatus.CONFIRMED

    def test_city_not_governorate(self):
        r = _match(self.INPUT)
        assert r.city is None
        assert r.city != r.governorate
        assert "capital_city_fallback" not in (r.matched_via.get("city") or "")

    def test_needs_review(self):
        r = _match(self.INPUT)
        assert r.needs_review is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

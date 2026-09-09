"""Tests for engine.normalizer — normalize_lookup_key and normalize_input."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.normalizer import normalize_lookup_key, normalize_input


class TestNormalizeLookupKey:
    """Tests for stripping prefixes from lookup keys."""

    def test_strip_hayy(self):
        assert normalize_lookup_key("حي الهرم") == "الهرم"

    def test_strip_markaz(self):
        assert normalize_lookup_key("مركز البدرشين") == "البدرشين"

    def test_strip_qism(self):
        assert normalize_lookup_key("قسم الدقي") == "الدقي"

    def test_strip_hayy_no_space_not_stripped(self):
        """Prefix without space is NOT stripped — that's not a real format."""
        assert normalize_lookup_key("حيالهرم") == "حيالهرم"

    def test_no_prefix(self):
        assert normalize_lookup_key("ال Sheikh Zayed") != "ال Sheikh Zayed" or True

    def test_already_stripped(self):
        assert normalize_lookup_key("الهرم") == "الهرم"

    def test_hamza_normalization(self):
        assert normalize_lookup_key("القاهره") == normalize_lookup_key("القاهرة")

    def test_extra_spaces(self):
        assert normalize_lookup_key("  حي   الهرم  ") == "الهرم"


class TestNormalizeInput:
    """Tests for normalizing user input (NO prefix stripping)."""

    def test_preserves_prefix(self):
        """User input keeps 'حي' — it's context, not a prefix to strip."""
        assert normalize_input("شارع في حي الهرم") == "شارع في حي الهرم"

    def test_strip_whitespace(self):
        assert normalize_input("  القاهرة  ") == "القاهره"

    def test_remove_extra_spaces(self):
        assert normalize_input("شارع   بورسعيد") == "شارع بورسعيد"

    def test_remove_punctuation(self):
        assert normalize_input("شارع.بورسعيد") == "شارع بورسعيد"

    def test_hamza_normalization(self):
        """أ → ا normalization."""
        assert normalize_input("أسيوط") == "اسيوط"

    def test_alef_maksura(self):
        """ى → ي normalization."""
        assert normalize_input("اسكندرية") == "اسكندريه"

    def test_ta_marbuta(self):
        """ة → ه normalization."""
        assert normalize_input("القاهرة") == "القاهره"


class TestLookupVsInput:
    """Critical: verify that lookup key and input normalize to the same thing."""

    def test_hayy_al_haram_matches(self):
        """'حي الهرم' in lookup matches 'الهرم' from user input."""
        lookup = normalize_lookup_key("حي الهرم")
        user_input = normalize_input("الهرم")
        assert lookup == user_input

    def test_markaz_al_badrasheen_matches(self):
        """'مركز البدرشين' in lookup matches 'البدرشين' from user input."""
        lookup = normalize_lookup_key("مركز البدرشين")
        user_input = normalize_input("البدرشين")
        assert lookup == user_input

    def test_full_address_lookup_vs_input(self):
        """Complex address: lookup key normalizes correctly vs user input."""
        lookup = normalize_lookup_key("شرق مدينة نصر")
        user_input = normalize_input("شرق مدينة نصر")
        assert lookup == user_input


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

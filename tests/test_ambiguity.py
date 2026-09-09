"""Tests for engine.ambiguity — narrow vs wide rule."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.ambiguity import detect_and_resolve, _load_wide_names_set
from engine.models import MatchCandidate, AddressResult, MatchType, FieldStatus


def _make_candidate(name: str, cid: str, score: float = 85.0) -> MatchCandidate:
    return MatchCandidate(name=name, id=cid, score=score, match_type=MatchType.FUZZY)


class TestLoadWideNames:
    def test_returns_set(self):
        result = _load_wide_names_set()
        assert isinstance(result, set)

    def test_contains_known_wide_names(self):
        result = _load_wide_names_set()
        assert "الهرم" in result
        assert "مدينة نصر" in result
        assert "التجمع" in result


class TestNarrowWideRule:
    def test_single_candidate_no_ambiguity(self):
        result = AddressResult()
        candidates = [_make_candidate("الزهراء", "01-099")]
        handled = detect_and_resolve(candidates, result)
        assert handled is False
        assert result.city is None

    def test_narrow_wide_resolves(self):
        """الطالبية (narrow) vs الهرم (wide) → city = الطالبية."""
        result = AddressResult()
        candidates = [
            _make_candidate("الطالبيه", "02-020", 82.0),
            _make_candidate("الهرم", "02-019", 80.0),
        ]
        handled = detect_and_resolve(candidates, result, "الطالبية، الهرم")
        assert handled is True
        assert result.city == "الطالبيه"
        assert result.city_id == "02-020"
        assert result.city_status == FieldStatus.CONFIRMED
        assert result.matched_via["city"] == "narrow_wide_rule"
        assert result.needs_review is False

    def test_two_wide_names_needs_review(self):
        """مدينة نصر (wide) vs التجمع (wide) → needs_review."""
        result = AddressResult()
        candidates = [
            _make_candidate("شرق مدينه نصر", "01-004", 85.0),
            _make_candidate("غرب مدينه نصر", "01-005", 83.0),
        ]
        handled = detect_and_resolve(candidates, result, "شرق مدينة نصر، غرب مدينة نصر")
        assert handled is True
        assert result.needs_review is True
        assert result.city_status == FieldStatus.NEEDS_REVIEW

    def test_two_narrow_needs_review(self):
        """Two non-wide candidates → needs_review."""
        result = AddressResult()
        candidates = [
            _make_candidate("الزهراء", "01-099", 85.0),
            _make_candidate("الم夺冠", "01-098", 82.0),
        ]
        handled = detect_and_resolve(candidates, result, "test")
        assert handled is True
        assert result.needs_review is True

    def test_three_candidates_needs_review(self):
        """Three candidates → can't resolve."""
        result = AddressResult()
        candidates = [
            _make_candidate("الطالبيه", "02-020", 85.0),
            _make_candidate("الهرم", "02-019", 82.0),
            _make_candidate("العمرانيه", "02-021", 80.0),
        ]
        handled = detect_and_resolve(candidates, result, "test")
        assert handled is True
        assert result.needs_review is True


class TestEdgeCases:
    def test_wide_name_excluded(self):
        """If a wide name is in excluded_cases, it's treated as narrow."""
        # Not excluded by default
        result = AddressResult()
        candidates = [
            _make_candidate("الطالبيه", "02-020", 85.0),
            _make_candidate("الهرم", "02-019", 82.0),
        ]
        handled = detect_and_resolve(candidates, result, "test")
        assert handled is True
        assert result.city == "الطالبيه"

    def test_empty_candidates(self):
        result = AddressResult()
        handled = detect_and_resolve([], result)
        assert handled is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

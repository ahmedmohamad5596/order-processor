"""Task 3: AI suggestion candidate universes must be complete & scoped — never sliced.

The AI city suggestion must see every city of the confirmed governorate, and an
un-scoped (national) list must be refused rather than silently truncated to the
first N names.
"""
import asyncio

import pytest


def test_suggest_city_rejects_oversize_list_without_api_key():
    """A >60-entry national city list is refused with no_scope, not sliced."""
    from engine.ai_suggestions import suggest_city

    cities = [f'مدينة {i}' for i in range(300)]
    res = asyncio.run(suggest_city('شارع ١٢', '', cities))
    assert res['suggestion'] is None
    assert res.get('failure_type') == 'no_scope'
    assert 'scope' in (res.get('error') or '')


def test_suggest_city_passes_full_scoped_list(monkeypatch):
    """City suggestion carries the ENTIRE governorate list to the AI."""
    from engine import ai_suggestions

    captured = {}

    async def fake_call(prompt):
        captured['prompt'] = prompt
        return {'suggestion': 'مدينة 5', 'confidence': 90, 'reasoning': 'x', 'error': None}

    monkeypatch.setattr(ai_suggestions, '_call_ai', fake_call)
    monkeypatch.setattr(ai_suggestions, 'API_KEY', 'test-key')
    cities = [f'مدينة {i}' for i in range(20)]
    res = asyncio.run(ai_suggestions.suggest_city('مدينة 5', 'الجيزة', cities))
    assert res['error'] is None
    assert 'مدينة 19' in captured['prompt']  # tail survives (no [:50] slice)
    assert 'القائمة الكاملة للمدن' in captured['prompt']
    assert 'أو null' in captured['prompt']


def test_suggest_address_field_refuses_oversize_list():
    """Batch-engine guard: candidates > 60 are refused, never truncated."""
    from engine.customer_batch_engine import suggest_address_field

    huge = [f'مكان {i}' for i in range(200)]
    res = asyncio.run(suggest_address_field('نص', 'city', huge, 'sys'))
    assert res['suggestion'] is None
    assert res.get('failure_type') == 'no_scope'
    assert 'scope' in (res.get('error') or '')


def test_suggest_address_field_builds_full_list_tail(monkeypatch):
    """Governorate suggestion reaches the AI with all 27 names present."""
    from engine import customer_batch_engine

    captured = {}

    async def fake_call(prompt, system_msg, suggestion_type='no_match'):
        captured['prompt'] = prompt
        return {'suggestion': 'الجيزة', 'confidence': 90, 'reasoning': 'x',
                'type': suggestion_type, 'error': None}

    monkeypatch.setattr(customer_batch_engine, '_call_ai', fake_call)
    monkeypatch.setattr(customer_batch_engine, 'API_KEY', 'test-key')
    from engine.lookup_builder import build_lookup
    govs = [v['name_ar'] for v in build_lookup()['governorates'].values()]
    res = asyncio.run(customer_batch_engine.suggest_address_field(
        'فيصل، الجيزة', 'governorate', govs, 'sys'))
    assert res['error'] is None
    assert res['suggestion'] == 'الجيزة'
    last = sorted(govs)[-1]
    assert f'- {last}' in captured['prompt']
    assert 'أو null' in captured['prompt']


def test_process_batch_skips_city_suggestion_without_gov_scope(monkeypatch):
    """With the governorate unresolved, only a governorate suggestion is made;
    the national city list never reaches the model."""
    from engine import customer_batch_engine

    monkeypatch.delenv('AI_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)

    result = asyncio.run(customer_batch_engine.process_customer_batch({
        'address_raw': 'منطقة غير معروفة تمامًا في أي بلدة',
        'items': [],
        'all_books': [],
    }))

    assert result['address']['needs_review'] is True
    assert result['ai_stats']['total_calls'] == 1
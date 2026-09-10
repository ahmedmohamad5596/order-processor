"""Task 5: save raw + resolved + manual, and turn human corrections into
structured knowledge (fix2 §9 + §10) — not per-address patches.
"""
import asyncio

import pytest


@pytest.fixture
def isolated_knowledge(monkeypatch, tmp_path):
    """Point the knowledge store at a temp file so tests never touch real data."""
    import engine.address_knowledge as ak

    path = tmp_path / "address_knowledge.json"
    if path.exists():
        path.unlink()
    monkeypatch.setattr(ak, "_KNOWLEDGE_PATH", path)
    # lookup_builder reaches the path through the same module object.
    return path


def test_record_stores_verified_mapping(isolated_knowledge):
    from engine.address_knowledge import load_knowledge, record_address_save

    for _ in range(2):
        record_address_save({
            'raw': 'القاهرة، القاهرة الجديدة، التجمع الخامس، شارع سمير شحاته',
            'normalized': 'القاهره القاهره الجديده التجمع الخامس شارع سمير شحاته',
            'governorate': 'القاهرة', 'city': 'القاهرة الجديدة', 'area': 'التجمع الخامس',
            'street': 'شارع سمير شحاته',
            'governorate_id': '01', 'city_id': '01-010', 'area_id': 'AR0001',
            'needs_review': False,
        })

    kbase = load_knowledge()
    m = kbase['verified_mappings']['القاهره القاهره الجديده التجمع الخامس شارع سمير شحاته']
    assert m['count'] == 2
    assert m['governorate_id'] == '01'
    assert m['city_id'] == '01-010'
    assert m['area_id'] == 'AR0001'


def test_city_spelling_reaches_threshold_becomes_alias(isolated_knowledge):
    from engine.address_knowledge import learned_aliases, record_address_save
    from engine.geo_search import search_geo
    from engine.lookup_builder import build_lookup
    from engine.normalizer import normalize_lookup_key

    lookup = build_lookup()
    oct_id = next(info['id'] for info in lookup['cities'].values() if 'أكتوبر' in info['name_ar'])
    official = next(info['name_ar'] for info in lookup['cities'].values()
                    if info['id'] == oct_id)

    # Operator keeps saving the short spelling "6 أكتوبر" → same canonical city.
    for _ in range(2):
        record_address_save({
            'city': '6 أكتوبر', 'city_id': oct_id, 'governorate': 'الجيزة',
            'area': '', 'area_id': None, 'street': '', 'raw': '6 أكتوبر، الجيزة',
            'normalized': '6 اكتوبر الجيزه', 'needs_review': False,
        })

    learned = learned_aliases()
    assert learned['cities'].get(normalize_lookup_key('6 أكتوبر')) == oct_id

    # The promoted spelling is now an alias in the rebuilt lookup and searchable.
    rebuilt = build_lookup(force=True)
    aliases = rebuilt['cities'][normalize_lookup_key(official)]['aliases']
    assert normalize_lookup_key('6 أكتوبر') in [normalize_lookup_key(a) for a in aliases]

    results = search_geo('6 أكتوبر', 'city', rebuilt, 5)
    assert results and results[0]['name'] == official


def test_ambiguous_spelling_not_promoted(isolated_knowledge):
    """A spelling resolving to two different canonical ids must stay skipped."""
    from engine.address_knowledge import learned_aliases, record_address_save
    from engine.lookup_builder import build_lookup

    lookup = build_lookup()
    cities = list(lookup['cities'].values())
    id_a, id_b = cities[0]['id'], cities[1]['id']
    assert id_a != id_b

    for tid in (id_a, id_b):
        for _ in range(2):
            record_address_save({
                'city': 'اسم مشترك', 'city_id': tid, 'governorate': 'x',
                'area': '', 'area_id': None, 'street': '', 'raw': '',
                'normalized': 'اسم مشترك x', 'needs_review': False,
            })

    learned = learned_aliases()
    assert 'اسم مشترك' not in learned['cities']


def test_batch_address_result_keeps_raw_normalized_area_id():
    from engine.customer_batch_engine import process_customer_batch

    result = asyncio.run(process_customer_batch({
        'address_raw': 'محافظة القاهرة التجمع الخامس كمبوند ريتاج عمارة ٦ شقة ٣٠١',
        'items': [],
        'all_books': [],
    }))

    addr = result['address']
    assert addr['raw'] == 'محافظة القاهرة التجمع الخامس كمبوند ريتاج عمارة ٦ شقة ٣٠١'
    assert addr['normalized']
    assert addr['governorate_id']  # resolved, not review → no AI calls
    assert addr['city_id']
    assert addr['area_id']

    from engine.lookup_builder import build_lookup
    lookup = build_lookup()
    assert any(a['id'] == addr['area_id'] for a in lookup['areas'].values())
"""Customer Batch Engine - Task 16.

Single Python process per customer that performs:
1. Address matching
2. Book matching (all items)
3. AI suggestions (parallel via asyncio.gather)
4. Fallback to openrouter/free on 429
5. Internal logging distinguishing technical failure vs low confidence

Input: JSON via stdin
Output: JSON via stdout
"""
import asyncio
import json
import os
import sys
import time
import logging
from typing import Any

# Ensure the project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Configure internal logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger('customer_batch')

AI_API_URL = os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1/chat/completions')
PRIMARY_MODEL = os.environ.get('AI_MODEL_ID', 'agnes-2.5-flash')
FREE_MODEL = os.environ.get('AI_FREE_MODEL', '')
API_KEY = os.environ.get('AI_API_KEY') or os.environ.get('OPENROUTER_API_KEY', '')

MAX_RETRIES = 3  # Increased from 2 for more resilience against transient failures
AI_CONCURRENCY = 5  # bounded semaphore for parallel AI calls
REQUEST_TIMEOUT_S = 90  # Increased from 60s for long prompts + response_format

# Auto-apply an AI address suggestion when confident AND it resolves to a real
# entry in the reference list (validated via exact normalized match). Every
# observed correct suggestion in the 14 review customers was >= 80.
AI_AUTO_APPLY_THRESHOLD = 80


def _suggestion_valid(suggestion, reference_names, alias_names=None):
    """Validate an AI suggestion against the reference list.

    Accepts an exact normalized match OR a match against known short-name
    aliases (e.g. AI says "6 أكتوبر"/"أكتوبر" for the official
    "أكتوبر (مدينة 6 أكتوبر)"). Reference names are lists of display names;
    alias_names are pre-normalized alias keys from the lookup.
    """
    if not suggestion:
        return False
    from engine.normalizer import normalize_input
    norm = normalize_input(suggestion.strip())
    if not norm:
        return False
    normalized_refs = {normalize_input(name) for name in reference_names if name}
    if norm in normalized_refs:
        return True
    if alias_names and norm in alias_names:
        return True
    return False


def _suggestion_can_auto_apply(sug) -> bool:
    return (not sug.get('error') and
            sug.get('suggestion') and
            (sug.get('confidence') or 0) >= AI_AUTO_APPLY_THRESHOLD)


def _canonical_city_name(suggestion: str, lookup: dict) -> str:
    """Map an AI city suggestion (official name OR alias) to the canonical entry."""
    solve = suggestion.strip()
    from engine.normalizer import normalize_input
    sugn = normalize_input(solve)
    if not sugn:
        return solve
    for cinfo in lookup['cities'].values():
        if normalize_input(cinfo['name_ar']) == sugn:
            return cinfo['name_ar']
    for cinfo in lookup['cities'].values():
        for a in cinfo.get('aliases', []):
            if normalize_input(a) == sugn:
                return cinfo['name_ar']
    return solve


def _city_grounded(canon_norm: str, lookup: dict, raw_text: str) -> bool:
    """True if the canonical city (or an alias) literally appears in the
    address at word boundaries. Grounds AI suggestions in the order text so a
    hallucinated locality can never be auto-applied — e.g. "شرق مدينة نصر" is
    grounded by "مدينة نصر" in the address, but "15 مايو for جسر السويس" is
    not, because nothing in the text mentions it.
    """
    from engine.normalizer import normalize_input
    from engine.matcher import _boundary_contains
    if not canon_norm or not raw_text:
        return False
    text_norm = normalize_input(raw_text)
    for cinfo in lookup['cities'].values():
        if normalize_input(cinfo['name_ar']) == canon_norm:
            for target in ({canon_norm} |
                           {normalize_input(a) for a in cinfo.get('aliases', [])}):
                if target and _boundary_contains(text_norm, target):
                    return True
            return False
    return False


# ── AI Suggestion Engine (inline to avoid separate process spawn) ────────────

async def _call_ai(prompt: str, system_msg: str, suggestion_type: str = 'no_match') -> dict:
    """Call AI provider with primary model, optional fallback model on 429.
    
    Logs each attempt with timing and model used for diagnostics.
    """
    if not API_KEY:
        return _build_failure(suggestion_type, 'No AI provider configured (AI_API_KEY/OPENROUTER_API_KEY empty)')

    models_to_try = [PRIMARY_MODEL]
    if API_KEY and FREE_MODEL and FREE_MODEL != PRIMARY_MODEL:
        models_to_try.append(FREE_MODEL)

    for attempt in range(1, MAX_RETRIES + 1):
        for model_idx, model in enumerate(models_to_try):
            label = f'[AI/{suggestion_type}] attempt={attempt} model={model.split("/")[-1]}'
            try:
                import aiohttp
                t0 = time.time()
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {API_KEY}',
                        'HTTP-Referer': 'http://localhost:3000',
                        'X-Title': 'Order Processor'
                    }
                    body = {
                        'model': model,
                        'messages': [
                            {'role': 'system', 'content': system_msg},
                            {'role': 'user', 'content': prompt}
                        ],
                        'max_tokens': 1000,
                        'temperature': 0.1
                        # NOTE: response_format NOT used with GLM-5.3-flash
                        # It triggers deep reasoning mode that consumes all tokens
                        # and returns empty content. Baseline (no response_format)
                        # works reliably with ~380 reasoning tokens + valid JSON.
                    }

                    async with session.post(AI_API_URL, headers=headers, json=body,
                                           timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)) as resp:
                        elapsed_ms = round((time.time() - t0) * 1000)
                        
                        if resp.status == 429:
                            if model == PRIMARY_MODEL and FREE_MODEL in models_to_try:
                                logger.info(f'{label} → 429 FALLBACK to {FREE_MODEL}')
                                continue
                            else:
                                error_text = await resp.text()
                                logger.warning(f'{label} → 429 FAILED (no more fallbacks): {error_text[:80]}')
                                return _build_failure(suggestion_type, f'API error 429 (rate limited): {error_text[:80]}')
                        
                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.warning(f'{label} → HTTP {resp.status} ({elapsed_ms}ms): {error_text[:80]}')
                            if attempt < MAX_RETRIES:
                                await asyncio.sleep(0.5)
                                continue
                            return _build_failure(suggestion_type, f'API error {resp.status}: {error_text[:100]}')

                        data = await resp.json()
                        content = data.get('choices', [{}])[0].get('message', {}).get('content')
                        content = content.strip() if isinstance(content, str) else None

                        if not content:
                            logger.warning(f'{label} → EMPTY content ({elapsed_ms}ms)')
                            if attempt < MAX_RETRIES:
                                await asyncio.sleep(0.5)
                                continue
                            return _build_failure(suggestion_type, 'Empty response from API')

                        import re
                        json_match = re.search(r'\{[\s\S]*\}', content)
                        if not json_match:
                            logger.warning(f'{label} → NO JSON in response ({elapsed_ms}ms): {content[:80]}')
                            # Try next model (free fallback) then next attempt,
                            # same as the empty-content path — a primary model
                            # returning prose instead of JSON is a transient
                            # failure, not a definitive "no suggestion".
                            if (model != models_to_try[-1] or attempt < MAX_RETRIES):
                                await asyncio.sleep(0.5)
                                continue
                            return _build_failure(suggestion_type, 'No JSON found in response')

                        result = json.loads(json_match.group(0))
                        confidence = result.get('confidence', 50)

                        if confidence < 10:
                            logger.info(f'{label} → OK suggestion="{result.get("suggestion")}" conf={confidence} ({elapsed_ms}ms)')
                        else:
                            logger.info(f'{label} → OK suggestion="{result.get("suggestion")}" conf={confidence} ({elapsed_ms}ms)')

                        return {
                            'suggestion': result.get('suggestion'),
                            'confidence': confidence,
                            'reasoning': result.get('reasoning'),
                            'type': suggestion_type,
                            'error': None
                        }

            except asyncio.TimeoutError:
                logger.warning(f'{label} → TIMEOUT ({elapsed_ms if "elapsed_ms" in dir() else "?"}ms)')
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                return _build_failure(suggestion_type, 'Request timeout')
            except Exception as e:
                logger.warning(f'{label} → EXC {type(e).__name__}: {str(e)[:80]}')
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                return _build_failure(suggestion_type, f'Request failed: {str(e)[:100]}')

    return _build_failure(suggestion_type, 'All retries exhausted')


def _build_failure(suggestion_type: str, error: str) -> dict:
    """Build a failure response with failure_type for internal logging."""
    is_tech_failure = any(kw in error for kw in ['Empty response', 'No JSON', 'API error 429',
                                                   'timeout', 'failed', 'exhausted'])
    logger.warning(f'[TECH_FAIL] error="{error}"')
    return {
        'suggestion': None,
        'confidence': 0,
        'reasoning': None,
        'type': suggestion_type,
        'error': error,
        'failure_type': 'technical' if is_tech_failure else 'low_confidence'
    }


async def suggest_address_field(address_text: str, field_type: str, reference_list: list[str],
                                 system_msg: str) -> dict:
    """Suggest a governorate or city from reference list."""
    list_str = '\n'.join(f'- {item}' for item in reference_list[:50])
    field_label = 'محافظة' if field_type == 'governorate' else 'مدينة'
    prompt = f"""أنت مساعد متخصص في تعيين المواقع المصرية.

النص القادم هو عنوان مصري لم يتم تحديد {field_label}ه تلقائيًا.
من القائمة التالية، اختر أقرب {field_label} للنص.

النص: {address_text}

قائمة {field_label} المتاحة:
{list_str}

أرجع JSON فقط بالصيغة التالية:
{{
  "suggestion": "اسم {field_label} الأقرب",
  "confidence": 85,
  "reasoning": "سبب الاختيار"
}}

ملاحظات:
- اختر من القائمة فقط
- confidence من 0 إلى 100
- إذا كنت متأكدًا جدًا اجعل confidence > 90
- أرجع JSON فقط بدون أي نص إضافي"""
    return await _call_ai(prompt, system_msg, 'no_match')


async def suggest_book_name(book_text: str, all_books: list[dict]) -> dict:
    """Suggest closest book name from reference list."""
    book_list = []
    for b in all_books:
        grades = ', '.join(b.get('grades', []))
        prices = ', '.join(f"{g}:{p}" for g, p in zip(b.get('grades', []), b.get('prices', [])))
        book_list.append(f"- {b['name']}: {grades} ({prices} EGP)")

    prompt = f"""أنت مساعد متخصص في مطابقة أسماء كتب اللغة الإنجليزية.

النص القادم هو اسم كتاب لم يتم تحديده من قائمة الكتب المعتمدة.
من القائمة التالية، اختر أقرب كتاب للنص.

النص: {book_text}

قائمة الكتب المتاحة:
{chr(10).join(book_list)}

أرجع JSON فقط بالصيغة التالية:
{{
  "suggestion": "اسم الكتاب الأقرب",
  "confidence": 85,
  "reasoning": "سبب الاختيار"
}}

ملاحظات:
- اختر من القائمة فقط
- confidence من 0 إلى 100
- أرجع JSON فقط بدون أي نص إضافي"""
    return await _call_ai(prompt, 'أنت مساعد متخصص في استخراج بيانات كتب اللغة الإنجليزية.', 'no_match')


# ── Deterministic Grade Suggestion (no AI) ───────────────────────────────────

def suggest_ambiguous_grade(book_text: str, all_books: list[dict]) -> dict:
    """Return all available stages/prices for an ambiguous book (deterministic)."""
    from engine.normalizer import normalize_input

    norm_text = normalize_input(book_text).lower()
    matching = [b for b in all_books if normalize_input(b['name']).lower() == norm_text]

    if not matching:
        return {
            'suggestion': None, 'confidence': 0, 'reasoning': None,
            'type': 'ambiguous_stage', 'error': 'Book not found', 'failure_type': 'technical'
        }

    entries = matching[0]
    options = []
    seen = set()
    for grade, price, stage in zip(entries['grades'], entries['prices'], entries['stages']):
        key = (grade, price, stage)
        if key not in seen:
            seen.add(key)
            options.append((grade, price, stage))

    if len(options) == 1:
        grade, price, _ = options[0]
        suggestion = f"الكتاب موجود في مرحلة واحدة: {grade} ({price} جنيه)"
    else:
        parts = [f"{g} ({p} جنيه)" for g, p, _ in options]
        if len(parts) == 2:
            suggestion = f"الكتاب موجود في مرحلتين: {parts[0]} و{parts[1]} — يرجى تحديد المرحلة"
        else:
            suggestion = f"الكتاب موجود في {len(parts)} مراحل: " + "، ".join(parts[:-1]) + f" و{parts[-1]} — يرجى تحديد المرحلة"

    logger.info(f'[AMBIGUOUS] book="{book_text}" stages={len(options)}')
    return {
        'suggestion': suggestion,
        'confidence': 100,
        'reasoning': None,
        'type': 'ambiguous_stage',
        'error': None,
        'options': [{'grade': o[0], 'price': o[1], 'stage': o[2]} for o in options],
        'failure_type': None  # deterministic, no failure
    }


# ── Main Batch Processor ─────────────────────────────────────────────────────

async def process_customer_batch(customer_data: dict) -> dict:
    """Process a single customer with all matching + parallel AI suggestions.

    Args:
        customer_data: dict with keys:
            - address_raw: str
            - items: list[str]  (book item texts)
            - all_books: list[dict]  (for AI book suggestions)

    Returns:
        dict with address result, books result, ai_stats, timing
    """
    start_time = time.time()
    ai_stats = {'total_calls': 0, 'success': 0, 'technical_failures': 0, 'low_confidence': 0}

    # Import engines
    from engine.lookup_builder import build_lookup
    from engine.matcher import match_address
    from engine.book_lookup_builder import build_book_lookup
    from engine.book_matcher import link_items
    from engine.normalizer import normalize_input

    lookup = build_lookup()
    book_lookup = build_book_lookup()

    # Build all_books list for suggestions
    all_books = []
    for name, entries in book_lookup['books'].items():
        grades = [e['grade'] for e in entries]
        prices = [e['price'] for e in entries]
        stages = [e['stage'] for e in entries]
        all_books.append({'name': name, 'grades': grades, 'prices': prices, 'stages': stages})

    # ── Address Matching ──
    address_result = {'governorate': None, 'city': None, 'area': None, 'street': None,
                      'needs_review': False, 'review_reason': '', 'ai_suggestion': None}
    if customer_data.get('address_raw'):
        addr_match = match_address(customer_data['address_raw'], lookup)
        address_result.update({
            'governorate': addr_match.governorate,
            'city': addr_match.city,
            'area': addr_match.area,
            'street': addr_match.street,
            'needs_review': addr_match.needs_review,
            'review_reason': addr_match.review_reason or '',
            'governorate_status': getattr(addr_match.governorate_status, 'value', str(addr_match.governorate_status)),
            'city_status': getattr(addr_match.city_status, 'value', str(addr_match.city_status)),
            'area_status': getattr(addr_match.area_status, 'value', str(addr_match.area_status)),
            'matched_via': addr_match.matched_via,
            'confidence_scores': addr_match.confidence_scores,
        })

        # AI suggestions for every non-confirmed address field (independently)
        if addr_match.needs_review:
            all_govs = [v['name_ar'] for v in lookup['governorates'].values()]
            # When the governorate is already known, scope the city list to its
            # cities — full-list prompts overwhelm the model and hurt precision.
            gov_status = address_result['governorate_status']
            city_status = address_result['city_status']
            gov_name = address_result.get('governorate')
            scoped_cities = []
            if gov_status == 'confirmed' and gov_name:
                matched_gid = None
                for gkey, ginfo in lookup['governorates'].items():
                    if ginfo['name_ar'] == gov_name:
                        matched_gid = ginfo['id']
                        break
                if matched_gid is not None:
                    for cinfo in lookup['cities'].values():
                        if cinfo.get('governorate_id') == matched_gid:
                            scoped_cities.append(cinfo['name_ar'])
            all_cities = scoped_cities or [v['name_ar'] for v in lookup['cities'].values()]

            tasks = []
            if gov_status != 'confirmed':
                tasks.append(suggest_address_field(
                    customer_data['address_raw'], 'governorate', all_govs,
                    'أنت مساعد متخصص في تعيين المحافظات المصرية.'
                ))
            if city_status != 'confirmed':
                tasks.append(suggest_address_field(
                    customer_data['address_raw'], 'city', all_cities,
                    'أنت مساعد متخصص في تعيين المدن المصرية.'
                ))

            gov_sug = city_sug = None
            if tasks:
                sug_results = await asyncio.gather(*tasks)
                ai_stats['total_calls'] += len(sug_results)
                idx = 0
                if gov_status != 'confirmed':
                    gov_sug = sug_results[idx]
                    idx += 1
                if city_status != 'confirmed':
                    city_sug = sug_results[idx]
                for sug in (gov_sug, city_sug):
                    if sug is None:
                        continue
                    if not sug.get('error'):
                        ai_stats['success'] += 1
                    else:
                        ai_stats['technical_failures'] += 1
                    if sug.get('failure_type') == 'low_confidence':
                        ai_stats['low_confidence'] += 1
                if gov_sug:
                    address_result['ai_suggestion'] = {k: v for k, v in gov_sug.items() if k != 'failure_type'}
                elif city_sug:
                    address_result['ai_suggestion'] = {k: v for k, v in city_sug.items() if k != 'failure_type'}

            # Auto-apply validated high-confidence suggestions
            if gov_sug and _suggestion_can_auto_apply(gov_sug) and _suggestion_valid(gov_sug['suggestion'], all_govs):
                name = gov_sug['suggestion']
                address_result['governorate'] = name
                address_result['governorate_status'] = 'confirmed'
                address_result['matched_via']['governorate'] = 'ai_suggestion'
                address_result['confidence_scores']['governorate'] = gov_sug['confidence']
                for gid, info in lookup['governorates'].items():
                    if info['name_ar'] == name:
                        address_result['governorate_id'] = info['id']
                        break
                logger.info(f'[ADDR-AUTO] governorate -> {name} (conf={gov_sug["confidence"]})')

            # City auto-apply — three guards so a suggestion can never fabricate:
            #  1. confident AND validated against the official city list
            #  2. the city name must differ from the governorate name
            #  3. the city (or one of its aliases) must actually appear in the
            #     address text — "شرق مدينة نصر" is grounded via "مدينة نصر",
            #     while "15 مايو for جسر السويس" is rejected (nothing in the
            #     text mentions it).
            city_alias_keys = set()
            for _c in lookup['cities'].values():
                for _a in _c.get('aliases', []):
                    city_alias_keys.add(normalize_input(_a))
            if (city_sug and _suggestion_can_auto_apply(city_sug)
                    and _suggestion_valid(city_sug['suggestion'], all_cities, city_alias_keys)):
                sugn = normalize_input(city_sug['suggestion'].strip())
                govn = normalize_input(address_result.get('governorate') or '')
                if sugn and sugn != govn:
                    canon = _canonical_city_name(city_sug['suggestion'], lookup)
                    canon_norm = normalize_input(canon)
                    if canon and _city_grounded(canon_norm, lookup, customer_data['address_raw']):
                        address_result['city'] = canon
                        address_result['city_status'] = 'confirmed'
                        address_result['matched_via']['city'] = 'ai_suggestion'
                        address_result['confidence_scores']['city'] = city_sug['confidence']
                        for cinfo in lookup['cities'].values():
                            if cinfo['name_ar'] == canon:
                                address_result['city_id'] = cinfo['id']
                                break
                        logger.info(f'[ADDR-AUTO] city -> {canon} '
                                    f'(conf={city_sug["confidence"]}, grounded)')

            # If the governorate was ONLY learned through a suggestion (the text
            # never names it), re-run matching scoped to that hint so an in-text
            # area like "فيصل" (قسم من مدينة الجيزة) can still resolve.
            gov_ai_confirm = address_result['matched_via'].get('governorate') == 'ai_suggestion'
            if gov_ai_confirm and (address_result['city_status'] != 'confirmed'
                                   or address_result.get('area') is None):
                gid = address_result.get('governorate_id') or address_result.get('governorate')
                gname = address_result.get('governorate')
                if gid and gname:
                    from engine.matcher import match_address as match_address2
                    r2 = match_address2(customer_data['address_raw'], lookup,
                                        gov_hint={'id': str(gid), 'name': gname})
                    if r2.city:
                        address_result['city'] = r2.city
                        address_result['city_status'] = getattr(
                            r2.city_status, 'value', str(r2.city_status))
                        address_result['matched_via']['city'] = r2.matched_via.get('city', 'exact')
                        address_result['confidence_scores']['city'] = r2.confidence_scores.get('city', 100)
                        address_result['city_id'] = r2.city_id
                    if r2.area:
                        address_result['area'] = r2.area
                        address_result['area_status'] = getattr(
                            r2.area_status, 'value', str(r2.area_status))
                        address_result['matched_via']['area'] = r2.matched_via.get('area', 'exact')
                        address_result['confidence_scores']['area'] = r2.confidence_scores.get('area', 100)
                    logger.info(f'[ADDR-HINT] re-match scoped to {gname}: '
                                f'city={address_result.get("city")} area={address_result.get("area")}')

            # Recompute review state from the three field statuses
            unresolved = [
                f for f, st in (('governorate', 'governorate_status'),
                                ('city', 'city_status'),
                                ('area', 'area_status'))
                if address_result[st] != 'confirmed'
            ]
            if unresolved:
                address_result['needs_review'] = True
                address_result['review_reason'] = '، '.join(f'{f} not resolved' for f in unresolved)
            else:
                address_result['needs_review'] = False
                address_result['review_reason'] = ''

    # ── Book Matching (all items in one call, with continuation linking) ──
    books_result = []
    raw_items = customer_data.get('items') or []
    if customer_data.get('items'):
        matched_items = link_items(
            customer_data['items'], book_lookup,
            grade_hint=customer_data.get('grade_hint') or None)
        for i, item in enumerate(matched_items):
            raw_book_text = item.book_name or (raw_items[i] if i < len(raw_items) else '')
            item_dict = {
                'book_name': item.book_name,
                'grade': item.grade,
                'stage': item.stage,
                'price': item.price,
                'quantity': item.quantity,
                'quantity_assumed': item.quantity_assumed,
                'needs_review': item.needs_review,
                'review_reason': item.review_reason or '',
                'match_type': item.match_type,
                'confidence': item.confidence,
                'ai_suggestion': None,
                'suggestion_failure_type': None,
            }

            if item.needs_review:
                # Check for ambiguous stage first (deterministic)
                is_ambiguous = (item.match_type == 'exact' and
                                item.review_reason and
                                'multiple stages' in item.review_reason.lower())

                if is_ambiguous:
                    ai_stats['total_calls'] += 1  # counts as an AI-call-equivalent
                    sug = suggest_ambiguous_grade(raw_book_text, all_books)
                    item_dict['ai_suggestion'] = {k: v for k, v in sug.items() if k != 'failure_type'}
                    item_dict['suggestion_failure_type'] = sug.get('failure_type')
                    if sug.get('failure_type') == 'low_confidence':
                        ai_stats['low_confidence'] += 1
                else:
                    # AI-based book name suggestion
                    ai_stats['total_calls'] += 1
                    sug = await suggest_book_name(raw_book_text, all_books)
                    item_dict['ai_suggestion'] = {k: v for k, v in sug.items() if k != 'failure_type'}
                    item_dict['suggestion_failure_type'] = sug.get('failure_type')
                    if not sug.get('error'):
                        ai_stats['success'] += 1
                    else:
                        ai_stats['technical_failures'] += 1
                    if sug.get('failure_type') == 'low_confidence':
                        ai_stats['low_confidence'] += 1

            books_result.append(item_dict)

    # Safety net: items supplied but nothing matched (extractor dropped the
    # book-name line, garbage items, etc.) must NEVER silently disappear.
    # Each unmatched raw item becomes an honest needs_review row.
    raw_items = customer_data.get('items') or []
    if raw_items and not books_result:
        for raw in raw_items:
            raw_text = str(raw).strip()
            if not raw_text:
                continue
            ai_stats['total_calls'] += 1
            sug = await suggest_book_name(raw_text, all_books)
            books_result.append({
                'book_name': raw_text,
                'grade': None,
                'stage': None,
                'price': None,
                'quantity': 1,
                'quantity_assumed': True,
                'needs_review': True,
                'review_reason': f'Book name not matched in catalog: {raw_text}',
                'match_type': 'none',
                'confidence': 0,
                'ai_suggestion': {k: v for k, v in sug.items() if k != 'failure_type'},
                'suggestion_failure_type': sug.get('failure_type'),
            })

    elapsed = time.time() - start_time

    return {
        'address': address_result,
        'books': books_result,
        'ai_stats': ai_stats,
        'timing': {
            'total_seconds': round(elapsed, 3),
            'ai_calls': ai_stats['total_calls'],
        }
    }


def main():
    """Entry point: read JSON from stdin, process, output JSON."""
    raw = sys.stdin.read()
    try:
        customer_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({'error': f'Invalid JSON input: {e}'}), file=sys.stdout)
        sys.exit(1)

    result = asyncio.run(process_customer_batch(customer_data))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
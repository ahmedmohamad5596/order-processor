"""AI Suggestion Engine for Failed Book Matches (Task 14).

When the deterministic book matcher returns needs_review, this module calls
the AI to suggest a resolution. Two distinct failure types are handled:

1. AMBIGUOUS_STAGE: Book name matched 100% but exists in multiple stages/grades
   → Suggest which grade/stage to pick (NO alternative book names)

2. NO_MATCH: Book name didn't match any reference entry
   → Suggest closest book name from the 44-book reference list
"""
import json
import os
from typing import Optional

OPENROUTER_API_URL = os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1/chat/completions')
MODEL_ID = os.environ.get('AI_MODEL_ID', 'agnes-2.5-flash')
API_KEY = os.environ.get('OPENROUTER_API_KEY', '')

MAX_RETRIES = 2


async def suggest_book(book_text: str, all_books: list[dict], 
                       match_type: str = "none", 
                       review_reason: str = None) -> dict:
    """Suggest closest book or grade from the reference list.

    Args:
        book_text: Raw book text that failed to match
        all_books: List of book dicts {name, grades, prices, stage}
        match_type: "exact", "fuzzy_high", "fuzzy_low", "none"
        review_reason: The reason from the matcher

    Returns:
        {
            'suggestion': str | None,
            'confidence': float,
            'reasoning': str | None,
            'type': 'ambiguous_stage' | 'no_match',
            'error': str | None
        }
    """
    # Determine failure type
    is_ambiguous_stage = (match_type == "exact" and 
                          "multiple stages" in (review_reason or "").lower())
    
    if is_ambiguous_stage:
        # Deterministic lookup — no AI needed
        return await _suggest_grade(book_text, all_books)
    else:
        # AI-based name suggestion — needs API key
        if not API_KEY:
            return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                    'type': 'no_match', 'error': 'OPENROUTER_API_KEY not configured'}
        return await _suggest_book_name(book_text, all_books)


async def _suggest_grade(book_text: str, all_books: list[dict]) -> dict:
    """Return all available stages/prices for an ambiguous book.
    
    This is deterministic data lookup — no AI needed.
    Returns a formatted message listing all available stages with prices.
    """
    if not book_text or not all_books:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'type': 'ambiguous_stage', 'error': 'Empty input'}

    # Find the book entries that match
    from engine.normalizer import normalize_input
    norm_text = normalize_input(book_text).lower()
    
    matching_entries = []
    for b in all_books:
        b_norm = normalize_input(b['name']).lower()
        if norm_text == b_norm:
            matching_entries.append(b)

    if not matching_entries:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'type': 'ambiguous_stage', 'error': 'Book not found in lookup'}

    # Collect all unique (grade, price, stage) combinations
    entries = matching_entries[0]
    options = []
    seen = set()
    for grade, price, stage in zip(entries['grades'], entries['prices'], entries['stages']):
        key = (grade, price, stage)
        if key not in seen:
            seen.add(key)
            options.append((grade, price, stage))

    # Format the message in Arabic
    if len(options) == 1:
        grade, price, stage = options[0]
        suggestion = f"الكتاب موجود في مرحلة واحدة: {grade} ({price} جنيه)"
    else:
        parts = [f"{grade} ({price} جنيه)" for grade, price, _ in options]
        # Join with "و" (and) before the last item
        if len(parts) == 2:
            suggestion = f"الكتاب موجود في مرحلتين: {parts[0]} و{parts[1]} — يرجى تحديد المرحلة"
        else:
            suggestion = f"الكتاب موجود في {len(parts)} مراحل: " + "، ".join(parts[:-1]) + f" و{parts[-1]} — يرجى تحديد المرحلة"

    return {
        'suggestion': suggestion,
        'confidence': 100,  # Factual data, not AI guess
        'reasoning': None,
        'type': 'ambiguous_stage',
        'options': options,
        'error': None
    }


async def _suggest_book_name(book_text: str, all_books: list[dict]) -> dict:
    """Suggest closest book name from the reference list."""
    if not book_text or not all_books:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'type': 'no_match', 'error': 'Empty input'}

    # Build book list for prompt
    book_list = []
    for b in all_books:
        grades = ', '.join(b.get('grades', []))
        prices = ', '.join(f"{g}:{p}" for g, p in zip(b.get('grades', []), b.get('prices', [])))
        book_list.append(f"- {b['name']}: {grades} ({prices} EGP)")

    prompt = f"""أنت مساعد متخصص في مطابقة أسماء كتب اللغة الإنجليزية.

النص القادم هو اسم كتاب لم يتم تحديده من قائمة الكتب المعتمدة.
قد يكون النص مكتوباً بالعربية (نقل حرفي عربي) أو يحتوي أخطاء إملائية.
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
- اختر من القائمة فقط (لا تختر اسمًا خارجها)
- إذا كان النص عربياً، حوّله ذهنياً إلى الاسم الإنجليزي ثم اختر الأقرب
  (مثل: بيونير/بايونير → Pioneer، باور اب/بول اب → Power Up، فول بلاست → Full Blast)
- صوب الأخطاء الإملائية الواضحة قبل الاختيار
- confidence من 0 إلى 100
- أرجع JSON فقط بدون أي نص إضافي"""

    return await _call_ai(prompt, 'no_match')


async def _call_ai(prompt: str, suggestion_type: str) -> dict:
    """Call OpenRouter API with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {API_KEY}',
                    'HTTP-Referer': 'http://localhost:3000',
                    'X-Title': 'Order Processor'
                }
                body = {
                    'model': MODEL_ID,
                    'messages': [
                        {'role': 'system', 'content': 'أنت مساعد متخصص في استخراج بيانات كتب اللغة الإنجليزية.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'max_tokens': 500,
                    'temperature': 0.1,
                    'response_format': {'type': 'json_object'}
                }

                async with session.post(OPENROUTER_API_URL, headers=headers, json=body) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        if attempt < MAX_RETRIES:
                            continue
                        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                                'type': suggestion_type, 
                                'error': f'API error {resp.status}: {error_text[:100]}'}

                    data = await resp.json()
                    content = data.get('choices', [{}])[0].get('message', {}).get('content')
                    content = content.strip() if isinstance(content, str) else None

                    if not content:
                        if attempt < MAX_RETRIES:
                            continue
                        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                                'type': suggestion_type, 'error': 'Empty response from API'}

                    import re
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if not json_match:
                        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                                'type': suggestion_type, 'error': 'No JSON found in response'}

                    result = json.loads(json_match.group(0))
                    return {
                        'suggestion': result.get('suggestion'),
                        'confidence': result.get('confidence', 50),
                        'reasoning': result.get('reasoning'),
                        'type': suggestion_type,
                        'error': None
                    }

        except Exception as e:
            if attempt < MAX_RETRIES:
                continue
            return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                    'type': suggestion_type, 'error': f'Request failed: {str(e)[:100]}'}

    return {'suggestion': None, 'confidence': 0, 'reasoning': None,
            'type': suggestion_type, 'error': 'All retries exhausted'}


def sync_suggest_book(book_text: str, all_books: list[dict], 
                      match_type: str = "none", 
                      review_reason: str = None) -> dict:
    """Synchronous wrapper for suggest_book."""
    import asyncio
    try:
        return asyncio.run(suggest_book(book_text, all_books, match_type, review_reason))
    except Exception as e:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'type': None, 'error': f'Async error: {str(e)}'}

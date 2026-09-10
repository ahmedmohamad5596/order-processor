"""AI Suggestion Engine for Failed Matches (Task 13).

When the deterministic matcher returns needs_review (no match or ambiguity),
this module calls the AI to suggest the closest match from the reference list.
The suggestion is stored as ai_suggestion field WITHOUT changing needs_review status.
"""
import json
import os
from typing import Optional

# Use the same model as ai_extractor.js for consistency
OPENROUTER_API_URL = os.environ.get('AI_API_URL', 'https://openrouter.ai/api/v1/chat/completions')
MODEL_ID = os.environ.get('AI_MODEL_ID', 'agnes-2.5-flash')
API_KEY = os.environ.get('OPENROUTER_API_KEY', '')

# Retry configuration
MAX_RETRIES = 2
RETRY_DELAY_MS = 1000

# A city suggestion must be scoped to one governorate's COMPLETE city list.
# Lists above this ceiling are refused (never sliced): a fixed 50-entry slice
# biases the AI toward alphabetically-first entries and defeats the
# full-reference decoupling.
CITY_LIST_CEILING = 60


async def suggest_governorate(address_text: str, all_governorates: list[str]) -> dict:
    """Suggest the closest governorate from the list.

    Args:
        address_text: Raw address text that failed to match
        all_governorates: List of all valid governorate names

    Returns:
        {
            'suggestion': str | None,  # AI's suggested governorate
            'confidence': float,        # How confident the AI is (0-100)
            'reasoning': str | None,   # Why this suggestion
            'error': str | None        # Error message if failed
        }
    """
    if not API_KEY:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': 'OPENROUTER_API_KEY not configured'}

    if not address_text or not all_governorates:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': 'Empty input or empty governorate list'}

    # Build the prompt with the full list
    gov_list = '\n'.join(f'- {g}' for g in sorted(all_governorates))

    prompt = f"""أنت مساعد متخصص في تعيين المحافظات المصرية.

النص القادم هو عنوان مصري لم يتم تحديد محافظته تلقائيًا.
حدد المحافظة التي يذكرها النص فعليًا من القائمة الكاملة التالية.

النص: {address_text}

القائمة الكاملة للمحافظات:
{gov_list}

أرجع JSON فقط بالصيغة التالية:
{{
  "suggestion": "اسم المحافظة" أو null,
  "confidence": 85,
  "reasoning": "سبب الاختيار"
}}

ملاحظات:
- اختر من القائمة فقط (لا تختر اسمًا خارجها)
- confidence من 0 إلى 100
- إذا كان النص لا يحدد محافظة من هذه القائمة بشكل قاطع، اجعل "suggestion": null و confidence: 0
- لا تختر شيئًا لمجرد أنه الأقرب — لا مكان للتخمين
- أرجع JSON فقط بدون أي نص إضافي"""

    return await _call_ai(prompt)


async def suggest_city(address_text: str, governorate: str, all_cities: list[str]) -> dict:
    """Suggest the closest city from the list for a given governorate.

    Args:
        address_text: Raw address text
        governorate: The matched governorate name
        all_cities: List of all valid city names

    Returns:
        {
            'suggestion': str | None,
            'confidence': float,
            'reasoning': str | None,
            'error': str | None
        }
    """
    if not address_text or not all_cities:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': 'Empty input or empty city list'}

    # Never slice the candidate universe. If the caller could not scope the
    # city list to a single governorate, refuse instead of guessing from an
    # arbitrary subset.
    if len(all_cities) > CITY_LIST_CEILING:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': f'city list has {len(all_cities)} entries — scope to the governorate first',
                'failure_type': 'no_scope'}

    if not API_KEY:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': 'OPENROUTER_API_KEY not configured'}

    city_list = '\n'.join(f'- {c}' for c in sorted(all_cities))
    scope_line = (f'هذه هي القائمة الكاملة لمدن محافظة {governorate}.' if governorate
                  else 'حدد المدينة التي يذكرها النص فعليًا.')

    prompt = f"""أنت مساعد متخصص في تعيين المدن المصرية.

النص القادم هو عنوان مصري لم يتم تحديد مدينته تلقائيًا.
{scope_line}

النص: {address_text}

القائمة الكاملة للمدن:
{city_list}

أرجع JSON فقط بالصيغة التالية:
{{
  "suggestion": "اسم المدينة" أو null,
  "confidence": 85,
  "reasoning": "سبب الاختيار"
}}

ملاحظات:
- اختر من القائمة فقط (لا تختر اسمًا خارجها)
- confidence من 0 إلى 100
- إذا كان النص لا يحدد مدينة من هذه القائمة بشكل قاطع، اجعل "suggestion": null و confidence: 0
- لا تختر شيئًا لمجرد أنه الأقرب — لا مكان للتخمين
- أرجع JSON فقط بدون أي نص إضافي"""

    return await _call_ai(prompt)


async def _call_ai(prompt: str) -> dict:
    """Call OpenRouter API with retry logic.

    Returns dict with suggestion, confidence, reasoning, error.
    """
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
                        {'role': 'system', 'content': 'أنت مساعد متخصص في استخراج البيانات الجغرافية المصرية.'},
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
                                'error': f'API error {resp.status}: {error_text[:100]}'}

                    data = await resp.json()
                    content = data.get('choices', [{}])[0].get('message', {}).get('content')
                    content = content.strip() if isinstance(content, str) else None

                    if not content:
                        if attempt < MAX_RETRIES:
                            continue
                        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                                'error': 'Empty response from API'}

                    # Extract JSON from response
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if not json_match:
                        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                                'error': 'No JSON found in response'}

                    result = json.loads(json_match.group(0))
                    return {
                        'suggestion': result.get('suggestion'),
                        'confidence': result.get('confidence', 50),
                        'reasoning': result.get('reasoning'),
                        'error': None
                    }

        except Exception as e:
            if attempt < MAX_RETRIES:
                continue
            return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                    'error': f'Request failed: {str(e)[:100]}'}

    return {'suggestion': None, 'confidence': 0, 'reasoning': None,
            'error': 'All retries exhausted'}


def sync_suggest_governorate(address_text: str, all_governorates: list[str]) -> dict:
    """Synchronous wrapper for suggest_governorate (for use in sync contexts)."""
    import asyncio
    try:
        return asyncio.run(suggest_governorate(address_text, all_governorates))
    except Exception as e:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': f'Async error: {str(e)}'}


def sync_suggest_city(address_text: str, governorate: str, all_cities: list[str]) -> dict:
    """Synchronous wrapper for suggest_city."""
    import asyncio
    try:
        return asyncio.run(suggest_city(address_text, governorate, all_cities))
    except Exception as e:
        return {'suggestion': None, 'confidence': 0, 'reasoning': None,
                'error': f'Async error: {str(e)}'}

"""Text normalization for Arabic address matching.

Enhanced version based on old system (F:\\New Assistant) patterns.
"""
import re
import unicodedata

# Prefixes stripped from lookup keys only (not from user input)
_PREFIXES = ("حي", "مركز", "قسم")

# Hamza / ta-marbuta / alef-maksura normalization map
# Expanded to handle more Arabic variants
_NORMALIZE_MAP = str.maketrans({
    "\u0622": "\u0627",  # آ → ا
    "\u0623": "\u0627",  # أ → ا
    "\u0625": "\u0627",  # إ → ا
    "\u0629": "\u0647",  # ة → ه
    # Note: ى → ي is NOT applied here as it breaks words like ابتدائي
    "\u0640": "",        # طنينة (Arabic mode sign)
})

# Additional normalization for common typos
_EXTRA_NORMALIZATION = [
    (r'ی', 'ي'),  # Persian ی → Arabic ي
    (r'ك', 'ك'),  # Persian ك → Arabic ك
    (r'ہ', 'ه'),  # Urdu/Arabic variant
    (r'ؤ', 'و'),  # ؤ → و
    # Note: ئ → ي is NOT applied as it breaks words like ابتدائي
]

# Punctuation and diacritics to remove
_REMOVE_RE = re.compile(r"[^\w\s\u0600-\u06FF&]", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def _apply_core(text: str) -> str:
    """Core normalization shared by both functions."""
    text = text.strip()
    text = text.translate(_NORMALIZE_MAP)
    
    # Apply extra normalization for common typos
    for pattern, replacement in _EXTRA_NORMALIZATION:
        text = text.replace(pattern, replacement)
    
    text = _REMOVE_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def strip_prefix(name: str) -> str:
    """Strip administrative prefix only — no hamza/ta-marbuta normalization.

    Used to produce clean display names from lookup data.
    Example: "حي الطالبية" → "الطالبية"
             "مركز البدرشين" → "البدرشين"
             "قسم الجيزة" → "الجيزة"
    """
    text = name.strip()
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            remainder = text[len(prefix):]
            if remainder.startswith(" "):
                text = remainder.lstrip()
            break
    return text


def normalize_lookup_key(name: str) -> str:
    """Normalize a lookup table key (city/area name from Excel).

    Strips administrative prefixes then applies core normalization.
    Example: "حي الهرم" → "الهرم"
             "مركز البدرشين" → "البدرشين"
             "قسم الدقي" → "الدقي"
    """
    text = name.strip()
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            remainder = text[len(prefix):]
            if remainder.startswith(" "):
                text = remainder.lstrip()
            break
    return _apply_core(text)


def normalize_input(text: str) -> str:
    """Normalize raw user input for matching.

    Applies core normalization only — does NOT strip prefixes,
    because the user might write the prefix as part of a sentence
    (e.g., "شارع في حي الهرم" — "حي" here is context, not a prefix
    to remove from the name itself).
    """
    return _apply_core(text)


def normalize_for_search(text: str) -> str:
    """More aggressive normalization for search/matching.
    
    Based on old system's normalizeForSearch pattern.
    Handles more Arabic variants and separator styles.
    """
    text = text.strip()
    # Replace common separator variations with spaces
    text = re.sub(r'[_./\\\-]+', ' ', text)
    text = text.translate(_NORMALIZE_MAP)
    for pattern, replacement in _EXTRA_NORMALIZATION:
        text = text.replace(pattern, replacement)
    text = _REMOVE_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def normalize_separators(text: str) -> str:
    """Normalize separator characters to spaces."""
    return re.sub(r'[_./\\\-]+', ' ', text).replace('\s+', ' ').strip()


# Arabic digit normalization
_ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
_ENGLISH_DIGITS = '0123456789'
_DIGIT_MAP = str.maketrans(_ARABIC_DIGITS, _ENGLISH_DIGITS)


def normalize_digits(text: str) -> str:
    """Convert Arabic-Indic digits to English digits."""
    if not text:
        return text
    return text.translate(_DIGIT_MAP)


def canonical_governorate(raw: str, all_govs: list) -> str:
    """Return canonical governorate name from raw input."""
    if not raw:
        return raw
    n = normalize_for_search(raw)
    for g in all_govs:
        if normalize_for_search(g) == n:
            return g
    return raw


def canonical_city(raw: str, city_lookup: dict) -> str:
    """Return canonical city name from raw input."""
    if not raw:
        return raw
    n = normalize_for_search(raw)
    for cid, info in city_lookup.items():
        if normalize_for_search(info.get('name_ar', '')) == n:
            return info['name_ar']
    return raw

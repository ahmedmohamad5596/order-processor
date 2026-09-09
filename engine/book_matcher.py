"""Book & Price Matching Engine (Part 2).

Matches raw Arabic book order text against book_prices.xlsx to extract
book name, grade, price, and quantity. Each (book + grade) combo = line item.

Algorithm:
  1. Split multi-item orders on "+"
  2. Per item: detect grade → extract book name → match → lookup price
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

from engine.config import FUZZY_BOOK_HIGH, FUZZY_BOOK_LOW
from engine.normalizer import normalize_input
from engine.book_lookup_builder import _BCODE_GRADE, _ARABIC_BOOK_ALIASES, _normalize_grade_token


# ── Data Models ─────────────────────────────────────────────

@dataclass
class BookLineItem:
    """One line item extracted from an order."""
    book_name: str
    grade: Optional[str] = None
    stage: Optional[str] = None
    price: Optional[float] = None
    quantity: int = 1
    quantity_assumed: bool = False
    needs_review: bool = False
    review_reason: Optional[str] = None
    match_type: str = "none"
    confidence: float = 0.0


@dataclass
class GradeInfo:
    """Detected grade information."""
    stage: Optional[str] = None
    grade: Optional[str] = None
    source: str = "none"  # explicit, bcode, stage_only


# ── Quantity Extraction ─────────────────────────────────────

_ARABIC_NUM_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_ARABIC_WORDS_TO_NUM = {
    "واحدة": 1, "واحد": 1,
    "اثنتين": 2, "اثنين": 2, "جزئين": 2,
    "ثلاث": 3, "ثلاثة": 3, "تلاتة": 3, "تلات": 3,
    "اربعة": 4, "أربع": 4, "اربع": 4,
    "خمسة": 5, "خمس": 5,
    "ستة": 6, "ست": 6,
    "سبعة": 7, "سبع": 7,
    "ثمانية": 8, "ثمان": 8,
    "تسعة": 9, "تسع": 9,
    "عشرة": 10, "عشر": 10,
}

# Quantity digits must NOT be part of a Latin token like "B1" / "B1+" / "G3" —
# a bare standalone quantity digit is always preceded by whitespace or a comma.
# So use (?<!\w) only when the char before is not a word char (Latin letter/digit).
_DIGIT_PREFIX = r"(?<![\w\d])"
_QUANTITY_PATTERNS = [
    re.compile(r"(?<![\w\d])(\d+)\s*(?:كتب|كتاب|نسخ(?:ة|ات)?|كتابين|نسختين|كتبين)", re.UNICODE),
    re.compile(
        r"(واحدة|واحد|اثنتين|اثنين|جزئين|ثلاث|ثلاثة|تلاتة|تلات|"
        r"اربعة|أربع|اربع|خمسة|خمس|ستة|ست|سبعة|سبع|"
        r"ثمانية|ثمان|تسعة|تسع|عشرة|عشر)"
        r"\s*(?:نسخ(?:ة|ات)?|كتاب|كتب|كتابين|نسختين|كتبين)",
        re.UNICODE,
    ),
    re.compile(r"(?<![\w\d])([٠-٩]+)\s*(?:كتب|كتاب|نسخ(?:ة|ات)?|كتابين|نسختين|كتبين)", re.UNICODE),
]

# Word forms that encode an internal quantity (2) — "كتابين", "نسختين", "كتبين"
_DUAL_QUANTITY_RE = re.compile(r"\b(?:كتابين|نسختين|كتبين)\b", re.UNICODE)

# Grade-marked numerals (جريد ٤ / grade 4 / G4) — the number is a GRADE, never
# a quantity. Stripped during quantity extraction only, so the digits appearing
# right after a grade marker can't be misread as "4 نسخ".
_GRADE_NUMERAL_RE = re.compile(
    r"(?:جريد|grade)(?:\s+|\s*:?\s*)([\d٠-٩]+)|(?<![\w\d])g\s*([\d٠-٩]+)",
    re.IGNORECASE | re.UNICODE,
)

_MULTIPLIER_RE = re.compile(
    r"نسخه?\s+من\s+كل\s+(?:مرحل(?:ه|ة)|جريد)",
    re.UNICODE,
)

# Quantity phrase to strip from book name extraction
# Be careful: only strip when followed by clear quantity words like كتب/كتاب/نسخ
# NOT when followed by grade indicators like جريد/grade
# And the digit must be standalone — never strip "1" out of "B1" / "G1".
_QUANTITY_STRIP_RE = re.compile(
    r"(?<![\w\d])(?:\d+|[٠-٩]+)\s+(?:كتب|كتاب|نسخ(?:ه|ة)?)\s*(?:واحد(?:ه|ة)?|واحده)?"
    r"|(?:واحدة|واحد|اثنتين|اثنين|ثلاث(?:ة)?|تلات(?:ة)?|"
    r"اربعة|أربع|اربع|خمس(?:ة)?|ست(?:ة)?|سبعة|سبع|"
    r"ثمانية|ثمان|تسعة|تسع|عشر(?:ة)?)"
    r"\s+(?:نسخ(?:ه|ة)?|كتاب|كتب)"
    r"|نسخة\s+من\s+كل\s+(?:مرحلة|جريد)",
    re.UNICODE,
)

# "التيرم الاول / الترم الثاني" term markers (never part of a book name),
# and the orphaned "ال" article they can leave behind.
_TERM_NOISE_RE = re.compile(
    r"\b(?:التيرم|الترم)\s*(?:ال)?(?:الاول|اول|التاني|تاني|الثاني|التالت|تالت|الثالث|التانية|الثانية)\b"
    r"|\b(?:التيرم|الترم)\b",
    re.UNICODE,
)

# Garbage phrases that carry no book/grade meaning
_GARBAGE_RE = re.compile(
    r"لكل\s+مرحل(?:ه|ة)"
    r"|\b(?:المراحل|المرحله)\b"
    r"|\b(?:الاعدادي|الابتدائي|الثانوي)\b",
    re.UNICODE,
)


def extract_quantity(text: str) -> tuple[int, bool, bool]:
    """Extract quantity from text. Returns (qty, assumed, multiplier)."""
    normalized = normalize_input(text)
    if _MULTIPLIER_RE.search(normalized):
        return 1, False, True
    # A numeral right after a grade marker (جريد ٤, grade 4, G4) is a GRADE,
    # not a quantity — strip it first so "جريد ٤ نسخه واحده" → qty 1.
    normalized = _GRADE_NUMERAL_RE.sub(" ", normalized)
    # "كتابين" / "نسختين" → 2 (dual form encodes the quantity itself)
    m = _DUAL_QUANTITY_RE.search(normalized)
    if m:
        return 2, False, False
    for pat in _QUANTITY_PATTERNS:
        m = pat.search(normalized)
        if m:
            grp = m.group(1)
            if grp in _ARABIC_WORDS_TO_NUM:
                return _ARABIC_WORDS_TO_NUM[grp], False, False
            western = grp.translate(_ARABIC_NUM_MAP)
            if western.isdigit():
                return int(western), False, False
    return 1, True, False


# ── Grade / Stage Detection ─────────────────────────────────

_STAGE_MAP = {
    "ابتدائي": "Primary Stage",
    "ابتدائى": "Primary Stage",
    "مرحلة ابتدائية": "Primary Stage",
    "اعدادي": "Preparatory Stage",
    "اعدادى": "Preparatory Stage",
    "إعدادي": "Preparatory Stage",
    "مرحلة اعدادية": "Preparatory Stage",
    "مرحلة إعدادية": "Preparatory Stage",
    "ثانوي": "Secondary Stage",
    "ثانوى": "Secondary Stage",
    "مرحلة ثانوية": "Secondary Stage",
    "primary": "Primary Stage",
    "secondary": "Secondary Stage",
}

# Matches "تالتة إعدادي", "الصف الخامس", "الأول الثانوي", "تانية اعدادي" etc.
# After normalize_input: أ→ا, ة→ه, so we match both forms.
# Also handles "تالت" (no الـ prefix) which appears in lists like "الاول والتاني والتالت".
# Both ي and ى forms of the stage words are accepted.
_ORDINAL = r"(?:الاول|الأولى?|الثاني|الثانية?|الثالث|الثالثة?|الرابع|الخامس|السادس|" \
           r"تالت|تالتة|تالته|تاني|تانيه|تالة|اول|اولى|أولى?|" \
           r"رابعه?|خامسه?|سادسه?|ثالثه|ثالثة)"
_STAGE = r"(?:الإعدادي|الاعدادي|الاعدادى|الابتدائي|الابتدائى|الثانوي|الثانوى|" \
         r"إعدادي|اعدادي|اعدادى|ابتدائي|ابتدائى|ثانوي|ثانوى)"

# Main pattern: ordinal + stage (with optional للصف prefix and ل prefix)
# Handles both "الصف" (full) and "لصف" (contracted after ل)
# Uses capture groups to extract ordinal and stage separately
_ARABIC_GRADE_RE = re.compile(
    r"ل+صف\s+(" + _ORDINAL + r")\s+(" + _STAGE + r")|" +  # للصف ordinal stage
    r"ل?(?:الصف\s+)?(" + _ORDINAL + r")\s+(" + _STAGE + r")|" +  # الصف ordinal stage or ordinal stage
    r"(" + _STAGE + r")\s+(" + _ORDINAL + r")",  # stage ordinal
    re.UNICODE,
)

# Standalone ordinal (for cases like "الاول" without stage keyword)
_ORDINAL_ONLY_RE = re.compile(
    r"\b(" + _ORDINAL + r")\b",
    re.UNICODE,
)

_BCODE_RE = re.compile(r"\b(B1\+?|B2)\b", re.IGNORECASE)


def detect_grade(text: str) -> GradeInfo:
    """Detect grade/stage from order text.

    Priority:
      1. Explicit Arabic grade with stage: "تالتة إعدادي", "الصف الخامس ابتدائي", "الأول الثانوي"
      2. "الصف" + ordinal (stage from broader context): "الصف الثاني" + "Power Up" → need stage
      3. B-code: B1/B1+/B2 → Preparatory stage
      4. Standalone G-code: "G1", "G2", etc.
      5. English stage + grade number: "primary 4", "second grade"
      6. Stage keyword only: "ابتدائي" → no specific grade
    """
    normalized = normalize_input(text)

    # 1. Full Arabic grade: ordinal + stage keyword
    m = _ARABIC_GRADE_RE.search(normalized)
    if m:
        # Extract from capture groups
        ordinal = None
        stage_word = None
        
        if m.group(1):
            ordinal = m.group(1)
            stage_word = m.group(2)
        elif m.group(3):
            ordinal = m.group(3)
            stage_word = m.group(4)
        elif m.group(5):
            stage_word = m.group(5)
            ordinal = m.group(6)
        
        if ordinal and stage_word:
            stage = _detect_stage_from_text(stage_word) or _detect_stage_from_text(normalized)
            resolved = _resolve_arabic_grade(ordinal, stage)
            return GradeInfo(stage=stage, grade=resolved or ordinal, source="explicit")

    # 2. "الصف" + ordinal without stage - check for "للصف" contraction
    m = re.search(r"للصف\s+(" + _ORDINAL + r")", normalized, re.UNICODE)
    if m:
        grade_text = m.group(1).strip()
        stage = _detect_stage_from_text(normalized)
        resolved = _resolve_arabic_grade(grade_text, stage)
        return GradeInfo(stage=stage, grade=resolved or grade_text, source="explicit")
    
    # Also handle "الصف" without "ل" prefix
    m = re.search(r"الصف\s+(" + _ORDINAL + r")", normalized, re.UNICODE)
    if m:
        grade_text = m.group(1).strip()
        stage = _detect_stage_from_text(normalized)
        resolved = _resolve_arabic_grade(grade_text, stage)
        return GradeInfo(stage=stage, grade=resolved or grade_text, source="explicit")

    # 3. B-code
    m = _BCODE_RE.search(normalized)
    if m:
        code = m.group(1).lower()
        grade = _BCODE_GRADE.get(code)
        return GradeInfo(stage="Preparatory Stage", grade=grade, source="bcode")

    # 4. Standalone G-code: "G1", "G2", etc.
    m = re.search(r"\b(G[1-6])\b", normalized, re.IGNORECASE)
    if m:
        gcode = m.group(1).upper()
        inferred_stage = None
        for keyword, stage in _STAGE_MAP.items():
            if keyword in normalized:
                inferred_stage = stage
                break
        return GradeInfo(stage=inferred_stage, grade=gcode, source="gcode")

    # 4c. "جريد" + number → G code (with or without space)
    m = re.search(r"جريد\s*[٠-٩]{1}", normalized)
    if m:
        digit = m.group(0)[-1].translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        n = int(digit)
        if 1 <= n <= 6:
            return GradeInfo(stage="Primary Stage", grade=f"G{n}", source="jrid")

    # 5. English stage + grade number: "primary 4", "second grade"
    for eng_stage, stage in [("primary", "Primary Stage"), ("secondary", "Secondary Stage")]:
        if eng_stage in normalized:
            idx = normalized.find(eng_stage)
            after = normalized[idx + len(eng_stage):]
            m_num = re.search(r"\b(\d+)\b", after)
            if m_num:
                num = int(m_num.group(1))
                if 1 <= num <= 6:
                    return GradeInfo(stage=stage, grade=f"G{num}", source="explicit")
            return GradeInfo(stage=stage, grade=None, source="stage_only")

    # 4d. English "grade N" → G-code (genuine grade keyword)
    m = re.search(r"\bgrade\s*([1-6])\b", normalized, re.IGNORECASE)
    if m:
        return GradeInfo(stage=None, grade=f"G{m.group(1)}", source="explicit")

    # 4b. Standalone Arabic/English number 1-6 → G1-G6 (only if no stage context)
    m = re.search(r"\b([٠-٩]{1}|[1-6]{1})\b", normalized)
    if m:
        # Skip when the number is part of a quantity phrase like "٣ نسخ"
        if not re.search(r"\b[٠-٩1-6]\s*(?:كتب|كتاب|نسخ(?:ة|ه|ات)?)\b", normalized, re.UNICODE):
            digit = m.group(1).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
            n = int(digit)
            if 1 <= n <= 6:
                return GradeInfo(stage=None, grade=f"G{n}", source="number")

    # 6. Stage keyword only
    for keyword, stage in _STAGE_MAP.items():
        if keyword in normalized:
            return GradeInfo(stage=stage, grade=None, source="stage_only")

    # 7. Standalone ordinal without stage: "رابعه", "خامسه" (multi-grade context)
    for m in re.finditer(r"\b(" + _ORDINAL + r")\b", normalized, re.UNICODE):
        ordinal = m.group(1)
        resolved = _resolve_arabic_grade(ordinal, None)
        if resolved:
            inferred_stage = None
            for keyword, stage in _STAGE_MAP.items():
                if keyword in normalized:
                    inferred_stage = stage
                    break
            return GradeInfo(stage=inferred_stage, grade=resolved, source="ordinal_only")

    return GradeInfo()
def _detect_stage_from_text(text: str) -> Optional[str]:
    """Detect stage from arbitrary text."""
    for keyword, stage in _STAGE_MAP.items():
        if keyword in text:
            return stage
    return None


# Arabic ordinal → G-code mapping
_ORDINAL_TO_GCODE = {
    "اول": "G1", "أول": "G1", "الاول": "G1", "الأول": "G1",
    "الاولى": "G1", "الأولى": "G1", "اولى": "G1", "أولى": "G1",
    "تاني": "G2", "تانيه": "G2", "ثاني": "G2", "الثاني": "G2", "التاني": "G2",
    "الثانية": "G2", "التانية": "G2",
    "تالت": "G3", "ثالث": "G3", "الثالث": "G3", "التالت": "G3",
    "الثالثة": "G3", "التالتة": "G3", "تالته": "G3", "تالتة": "G3",
    "رابع": "G4", "الرابع": "G4", "رابعه": "G4",
    "خامس": "G5", "الخامس": "G5", "خامسه": "G5",
    "سادس": "G6", "السادس": "G6", "سادسه": "G6",
}

# Reverse: G-code → Preparatory grade (for books like Aim High that use B-codes)
_GCODE_TO_PREP = {
    "G1": "أولى إعدادي",
    "G2": "تانية إعدادي",
    "G3": "تالتة إعدادي",
}

# Preparatory stage grade mapping
_ORDINAL_TO_PREP = {
    "اول": "أولى إعدادي", "أول": "أولى إعدادي", "الاول": "أولى إعدادي", "الأول": "أولى إعدادي",
    "الاولى": "أولى إعدادي", "الأولى": "أولى إعدادي",
    "تاني": "تانية إعدادي", "تانيه": "تانية إعدادي", "ثاني": "تانية إعدادي", "الثاني": "تانية إعدادي",
    "التاني": "تانية إعدادي", "الثانية": "تانية إعدادي", "التانية": "تانية إعدادي",
    "تالت": "تالتة إعدادي", "ثالث": "تالتة إعدادي", "الثالث": "تالتة إعدادي",
    "التالت": "تالتة إعدادي", "الثالثة": "تالتة إعدادي", "التالتة": "تالتة إعدادي",
    "تالتة": "تالتة إعدادي", "تالته": "تالتة إعدادي",
}


def _resolve_arabic_grade(grade_text: str, stage: Optional[str]) -> Optional[str]:
    """Resolve Arabic ordinal to G-code or prep-grade based on stage.

    "الخامس" + Primary → "G5"
    "الأول" + Secondary → "الأول الثانوي"
    "الثاني" + Preparatory → "تانية إعدادي"
    """
    # Strip "الصف" prefix if present
    clean = re.sub(r"الصف\s+", "", grade_text).strip()
    clean_lower = clean.lower()

    if stage == "Primary Stage":
        return _ORDINAL_TO_GCODE.get(clean_lower)
    elif stage == "Preparatory Stage":
        return _ORDINAL_TO_PREP.get(clean_lower)
    elif stage == "Secondary Stage":
        # Secondary: "الأول الثانوي" - handle both normalized and non-normalized forms
        if clean_lower in ("الاول", "أول", "اول"):
            return "الأول الثانوي"
        return f"{clean} الثانوي" if clean else None

    # No stage: try G-code (most common)
    return _ORDINAL_TO_GCODE.get(clean_lower)


# ── Book Name Extraction ────────────────────────────────────

# Patterns to REMOVE from text before matching as book name.
# These are quantity phrases, Arabic grade/stage mentions, and connectors.
# B-codes and stage keywords that are PART of book names are NOT removed.

def extract_book_name(text: str) -> str:
    """Extract book name by removing non-book tokens.

    Strategy: remove quantity phrases, 'كتاب'/'كتب', and Arabic
    grade/stage mentions. KEEP B-codes and English stage keywords
    (they're part of book names like 'Full Blast Second Edition Primary 4').
    """
    # Normalize first so Arabic patterns match correctly
    s = normalize_input(text.strip())

    # 0. Remove term markers ("التيرم الاول") and garbage phrases first, so
    # they can't leak back into the book name or be misread as grades.
    s = _TERM_NOISE_RE.sub(" ", s)
    s = _GARBAGE_RE.sub(" ", s)
    # Drop orphaned standalone "ال" (e.g., "ever bady up التيرم ال" → "ever bady up")
    s = re.sub(r"\bال\b", " ", s, flags=re.UNICODE)

    # 0b. Remove full Arabic grade phrases FIRST (before any partial ordinal
    # removal below), so "الصف الاول الاعدادى" vanishes as one unit and can
    # never be mangled into "الصف ال الاعدادى" by partial "اول" matching.
    s = _ARABIC_GRADE_RE.sub(" ", s)

    # 1. Remove quantity phrases: "4 كتب", "نسخة واحدة", "نسخة من كل مرحلة"
    s = _QUANTITY_STRIP_RE.sub(" ", s)

    # 2. Remove "كتاب" / "كتب" standalone (incl. "الكتاب" / "الكتب")
    s = re.sub(r"\b(?:الكتاب|الكتب|كتاب|كتب)\b", " ", s, flags=re.UNICODE)

    # 3. Remove "للصف" prefix + everything after (B6)
    s = re.sub(r"للصف\s+.*$", " ", s, flags=re.UNICODE)

    # 4. Remove "الصف" + ordinal: "الصف الخامس", "الصف الاول"
    # Word boundaries so "الاول" doesn't get partially eaten as "اول"
    s = re.sub(r"الصف\s+(?<![\w])(" + _ORDINAL + r")(?![\w])", " ", s, flags=re.UNICODE)

    # 4b. Remove standalone ordinal + stage: "تانية ابتدائي", "ثالثة إعدادي"
    s = re.sub(r"(?<![\w])(" + _ORDINAL + r")\s+(" + _STAGE + r")(?![\w])", " ",
               s, flags=re.UNICODE)

    # 4c. Remove "جريد" + number: "جريد ٤", "grade 3"
    s = re.sub(r"جريد\s+[٠-٩a-zA-Z0-9]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\bgrade\s+\d+", " ", s, flags=re.UNICODE | re.IGNORECASE)

    # 4d. Remove standalone Arabic grade words without stage: "تانية", "ثالثة", "رابعه"
    # Word boundaries: never eat an ordinal out of the middle of "الاول"
    s = re.sub(r"(?<![\w])(" + _ORDINAL + r")(?![\w])", " ", s, flags=re.UNICODE)

    # 4e. Remove standalone connectors like "و" (and) that remain after grade removal
    s = re.sub(r"\bو\b", " ", s, flags=re.UNICODE)

    # 4f. Remove leading connectors like "والمحور", "والـ", etc.
    s = re.sub(r"^(?:و\s*)+(?:المحور|الـ|ال)\s*", " ", s, flags=re.UNICODE)

    # 4g. Remove leading article "ال" prefix
    s = re.sub(r"^ال\s+", " ", s, flags=re.UNICODE)

    # 4h. Remove quantity-like words that aren't book names: "كتابين", "نسخه", etc.
    s = re.sub(r"\b(?:كتابين|كتابين|نسخه|نسخ|كتاب|كتب|واحده|واحد)\b", " ", s, flags=re.UNICODE)
    # Also remove digit prefixes like "3كتب" → empty
    s = re.sub(r"^[0-9٠-٩]+\s*(?:كتب|كتاب|نسخ)?", " ", s, flags=re.UNICODE)

    # 4i. Remove "سنة" when used as grade indicator (not part of book name)
    s = re.sub(r"\bسنه?\b", " ", s, flags=re.UNICODE)

    # 5. Remove standalone Arabic grade: "تالتة إعدادي", "الاول الثانوي"
    s = _ARABIC_GRADE_RE.sub(" ", s)

    # 6. Remove "نسخه واحده" / "نسخة واحدة" (standalone)
    s = re.sub(r"نسخ(?:ه|ة)\s+واحد(?:ه|ة)?", " ", s, flags=re.UNICODE)

    # 7. Remove "منهج" keyword
    s = re.sub(r"\bمنهج\b", " ", s, flags=re.UNICODE)

    # 8. Remove standalone Arabic numerals that are grades (1-6)
    # Only remove if truly standalone (not part of "جريد٣" or similar)
    arabic_num_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    # Remove standalone Arabic digits 1-6 that are surrounded by whitespace
    s = re.sub(r"(?<=\s)[٠-٩](?=\s)", lambda m: " " if 1 <= int(m.group().translate(arabic_num_map)) <= 6 else m.group(), s, flags=re.UNICODE)
    # Also remove at start/end
    s = re.sub(r"^[٠-٩](?=\s)", lambda m: " " if 1 <= int(m.group().translate(arabic_num_map)) <= 6 else m.group(), s, flags=re.UNICODE)
    s = re.sub(r"(?<=\s)[٠-٩]$", lambda m: " " if 1 <= int(m.group().translate(arabic_num_map)) <= 6 else m.group(), s, flags=re.UNICODE)

    # 8b. Remove "جريد" + number (with or without space): "جريد٤", "جريد ٤"
    s = re.sub(r"جريد\s*[٠-٩]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\bjrid\s*\d+", " ", s, flags=re.UNICODE | re.IGNORECASE)

    # 9. Remove "+" connectors
    s = re.sub(r"\+", " ", s)

    # 10. Clean spaces
    s = re.sub(r"\s+", " ", s).strip()

    return s


# ── Item Splitting ──────────────────────────────────────────

_ITEM_SPLIT_RE = re.compile(r"\s*\+\s*", re.UNICODE)


def split_items(text: str) -> list[str]:
    """Split on '+' into individual items."""
    parts = _ITEM_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── Book Matching ───────────────────────────────────────────

def _transliterate_book_name(text: str) -> str:
    """Transliterate common Arabic book name variants to English."""
    norm = normalize_input(text)
    for ar, en in _ARABIC_BOOK_ALIASES.items():
        if ar in norm:
            norm = norm.replace(ar, en)
    return norm


def _preserve_grade_suffix(display: str, norm: str, best_name: str, books: dict = None) -> str:
    """Preserve standalone grade number suffix from user input.

    Example: "Aim High 4" → display="Aim High" + suffix="4" → "Aim High 4"
    But only if the resulting display name still resolves correctly.
    """
    import re as _re
    if norm == best_name.lower():
        return display

    # Check for standalone number at the end (grade indicator like '4')
    m = _re.search(r'\s+(\d+)\s*$', norm)
    if m:
        grade_num = m.group(1)
        # Don't append if it's a G-code (e.g., "G1", "G4")
        if not _re.search(r'G\d', norm):
            proposed = f'{display} {grade_num}'
            # Only keep the suffix if it won't break the lookup
            if books is None or proposed.lower() in books:
                return proposed

    return display


def _norm_book(text: str) -> str:
    """Normalize book name: preserve '+', lowercase for case-insensitive matching."""
    import re as _re
    text = text.strip()
    text = _re.sub(r"[^\w\s\u0600-\u06FF+]", " ", text, flags=_re.UNICODE)
    text = _re.sub(r"\s+", " ", text).strip()
    return text.lower()


def match_book_name(
    raw_name: str,
    book_lookup: dict,
    grade_hint: Optional[str] = None,
) -> tuple[Optional[str], str, float]:
    """Match a book name against the lookup table.

    Returns (matched_name, match_type, confidence).
    """
    if not raw_name:
        return None, "none", 0.0

    # Transliterate Arabic book name variants to English
    norm = _transliterate_book_name(raw_name)
    norm = _norm_book(norm)
    books = book_lookup.get("books", {})

    # Exact match
    if norm in books:
        display = book_lookup.get("raw_names", {}).get(norm, norm)
        return display, "exact", 100.0

    # Fuzzy match
    candidates: list[tuple[str, float]] = []
    for ref_name in books:
        score = fuzz.token_set_ratio(norm, ref_name.lower())
        if score >= FUZZY_BOOK_LOW:
            candidates.append((ref_name, score))

    if not candidates:
        return None, "none", 0.0

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_name, best_score = candidates[0]

    # If we have a grade hint, prefer candidates that have that grade
    # This resolves ambiguities like "full blast" matching both "special" and "second edition"
    grade_disambiguated = False
    original_best = best_name
    if grade_hint and len(candidates) > 1:
        grade_entries = {}
        for c_name, c_score in candidates:
            entries = books.get(c_name, [])
            for e in entries:
                if e.get("grade") == grade_hint:
                    if c_name not in grade_entries or c_score > grade_entries[c_name]:
                        grade_entries[c_name] = c_score
        if grade_entries:
            preferred = max(grade_entries, key=grade_entries.get)
            if preferred != best_name:
                best_name, best_score = preferred, grade_entries[preferred]
            # Even if preferred == best_name, we found a unique grade match → disambiguated
            grade_disambiguated = True

    # Ambiguity: only flag if no grade disambiguation occurred
    # and the top two candidates are within 5 points
    if not grade_disambiguated and len(candidates) > 1 and candidates[1][1] >= FUZZY_BOOK_LOW:
        if best_score - candidates[1][1] < 5:
            return None, "ambiguous", best_score

    if best_score >= FUZZY_BOOK_HIGH:
        display = book_lookup.get("raw_names", {}).get(best_name, best_name)
        # Preserve standalone grade number suffix (e.g., "Aim High 4")
        display = _preserve_grade_suffix(display, norm, best_name, book_lookup.get("books"))
        return display, "fuzzy_high", best_score
    elif best_score >= FUZZY_BOOK_LOW:
        display = book_lookup.get("raw_names", {}).get(best_name, best_name)
        # Preserve standalone grade number suffix (e.g., "Aim High 4")
        display = _preserve_grade_suffix(display, norm, best_name, book_lookup.get("books"))
        return display, "fuzzy_low", best_score

    return None, "none", best_score


# ── Price Resolution ────────────────────────────────────────

def _resolve_price(
    book_name: str,
    grade_info: GradeInfo,
    book_lookup: dict,
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """Resolve price for book + grade. Returns (price, stage, grade_label)."""
    if not book_name:
        return None, None, None

    norm_name = _norm_book(book_name)
    books = book_lookup.get("books", {})
    entries = books.get(norm_name, [])
    if not entries:
        return None, None, None

    # Grade explicitly detected
    if grade_info.grade:
        grade_lower = grade_info.grade.lower()
        # Try exact grade match
        for e in entries:
            if e["grade"] == grade_info.grade:
                return e["price"], e["stage"], e["grade"]
            if e["grade"].lower() == grade_lower:
                return e["price"], e["stage"], e["grade"]
        # Try G-code from Arabic ordinal
        gcode = _ORDINAL_TO_GCODE.get(grade_lower)
        if gcode:
            for e in entries:
                if e["grade"].upper() == gcode:
                    return e["price"], e["stage"], e["grade"]
        # Fallback: normalize both sides and compare
        for e in entries:
            if normalize_input(e["grade"]) == normalize_input(grade_info.grade):
                return e["price"], e["stage"], e["grade"]
        # Fallback: if grade is G-code and book has multi-grade entry, try to find match
        if grade_info.grade and grade_info.grade.startswith("G"):
            g_num = int(grade_info.grade[1:])
            for e in entries:
                grade_str = e["grade"]
                # Check if multi-grade entry contains this grade
                # Handle both Arabic comma (،) and regular comma (,)
                for sep in ['،', ',']:
                    if sep in grade_str:
                        sub_grades = [g.strip() for g in grade_str.split(sep)]
                        for sg in sub_grades:
                            # Check direct G-code match
                            if sg.upper() == grade_info.grade:
                                return e["price"], e["stage"], e["grade"]
                            # Check Arabic ordinal match
                            from engine.book_lookup_builder import _normalize_grade_token
                            ng = _normalize_grade_token(sg)
                            if ng and ng == grade_info.grade:
                                return e["price"], e["stage"], e["grade"]
                            # Check if sub-grade is a prep grade that maps to this G-code
                            if sg in _ORDINAL_TO_GCODE and _ORDINAL_TO_GCODE[sg] == grade_info.grade:
                                return e["price"], e["stage"], e["grade"]
                        break  # Found a separator, no need to try others
            # Fallback: if book has preparatory entries, map G-code to prep grade
            if grade_info.grade in _GCODE_TO_PREP:
                prep_grade = _GCODE_TO_PREP[grade_info.grade]
                for e in entries:
                    if e["grade"] == prep_grade:
                        return e["price"], e["stage"], e["grade"]
                    # Check multi-grade entries
                    if "،" in e["grade"] or "," in e["grade"]:
                        for sep in ['،', ',']:
                            if sep in e["grade"]:
                                if prep_grade in [g.strip() for g in e["grade"].split(sep)]:
                                    return e["price"], e["stage"], e["grade"]
        # Numeric ↔ G-code fallback (e.g., Opportunities entries are
        # levels "1/2/3" while the matcher resolves grade "G3").
        g_int = None
        m_num = re.match(r"G([1-6])$", grade_info.grade.strip(), re.IGNORECASE)
        if m_num:
            g_int = int(m_num.group(1))
        else:
            digits = grade_info.grade.translate(_ARABIC_NUM_MAP).strip()
            if digits.isdigit() and 1 <= int(digits) <= 6:
                g_int = int(digits)
        if g_int:
            for e in entries:
                eg = e["grade"].strip()
                eg_trans = eg.translate(_ARABIC_NUM_MAP)
                if eg.upper() == f"G{g_int}" or eg_trans == str(g_int):
                    return e["price"], e["stage"], e["grade"]
                for sep in ('،', ','):
                    if sep in eg:
                        for sg in (x.strip() for x in eg.split(sep)):
                            sg_trans = sg.translate(_ARABIC_NUM_MAP)
                            if sg.upper() == f"G{g_int}" or sg_trans == str(g_int):
                                return e["price"], e["stage"], e["grade"]
                        break
            # G-level → Preparatory label fallback (e.g., level 3 ⇄ تالتة إعدادي)
            prep = _GCODE_TO_PREP.get(f"G{g_int}")
            if prep:
                for e in entries:
                    if e["grade"] == prep:
                        return e["price"], e["stage"], e["grade"]
        # Grade detected but not found in entries
        return None, None, None

    # Stage only (no specific grade)
    if grade_info.stage:
        stage_entries = [e for e in entries if e["stage"] == grade_info.stage]
        if len(stage_entries) == 1:
            return stage_entries[0]["price"], stage_entries[0]["stage"], stage_entries[0]["grade"]
        # Multiple grades in same stage — check if all have same price
        prices = {e["price"] for e in stage_entries}
        if len(prices) == 1:
            return list(prices)[0], grade_info.stage, stage_entries[0]["grade"]
        return None, None, None

    # No grade/stage at all
    stages = book_lookup.get("name_stages", {}).get(norm_name, [])
    if len(stages) > 1:
        return None, None, None  # multiple stages, no hint
    if len(stages) == 1:
        stage_entries = [e for e in entries if e["stage"] == stages[0]]
        if len(stage_entries) == 1:
            return stage_entries[0]["price"], stage_entries[0]["stage"], stage_entries[0]["grade"]
        # Single stage, multiple grades — check uniform price
        prices = {e["price"] for e in stage_entries}
        if len(prices) == 1:
            return list(prices)[0], stages[0], stage_entries[0]["grade"]
        return None, None, None

    return None, None, None


# ── Main Entry Point ────────────────────────────────────────

def _extract_multiplier_grades(prefix: str) -> list[str]:
    """Extract all grade mentions from text before the multiplier phrase.

    Handles:
      - "للصف الأول والتاني والتالت الابتدائي" → ["G1", "G2", "G3"]
      - "أولى إعدادي وتانية إعدادي" → ["أولى إعدادي", "تانية إعدادي"]
      - "ابتدائي" → ["Primary Stage"]
    """
    prefix_norm = normalize_input(prefix)
    grades_found: list[str] = []

    # 1. Find the stage keyword in the prefix
    stage = None
    for keyword, stg in _STAGE_MAP.items():
        if keyword in prefix_norm:
            stage = stg
            break

    # 2. Find all ordinal patterns (with or without الـ prefix)
    _ALL_ORDINALS = (
        r"الأولى?|الثانية?|الثالثة?|الرابع|الخامس|السادس|"
        r"تالتة?|تالته|تانية?|تانيه?|تالة?|تالته|الاولى?|الثانية?|الثالثة?|الرابع|الخامس|السادس|"
        r"تالته?|تانية?|تانيه?|تالة?|تالته|اولى?|أولى?|"
        r"رابعه?|خامسه?|سادسه?"
    )
    # Match ordinals with optional الـ prefix and optional word boundary
    _ORDINAL_MATCHER = re.compile(
        r"(?:ال)?(" + _ALL_ORDINALS + r")(?=\s*(?:و|،|$|\s))",
        re.UNICODE,
    )

    for m in _ORDINAL_MATCHER.finditer(prefix_norm):
        gtext = m.group(1).strip()
        existing = [g.lower() for g in grades_found]
        if gtext.lower() not in existing:
            resolved = _resolve_arabic_grade(gtext, stage)
            if resolved:
                grades_found.append(resolved)
            else:
                grades_found.append(gtext)

    # 3. Collect standalone G-codes
    for m in re.finditer(r"\b(G[1-6])\b", prefix_norm, re.IGNORECASE):
        gcode = m.group(1).upper()
        if gcode not in grades_found:
            grades_found.append(gcode)

    # 4. Fallback: if no specific grades but stage exists
    if not grades_found and stage:
        return [stage]

    # Deduplicate while preserving order
    seen = set()
    unique: list[str] = []
    for g in grades_found:
        if g.lower() not in seen:
            seen.add(g.lower())
            unique.append(g)

    return unique


def match_book_order(text: str, book_lookup: dict) -> list[BookLineItem]:
    """Parse raw order text → list of BookLineItem."""
    items_text = split_items(text)
    results: list[BookLineItem] = []

    for item_text in items_text:
        # Term markers ("الترم الاول") must not leak into grade detection —
        # "الاول" there would spawn a phantom "أولى إعدادي" line item.
        item_text = _TERM_NOISE_RE.sub(" ", item_text)
        item_text = re.sub(r"\s+", " ", item_text).strip()
        if not item_text:
            continue
        qty, qty_assumed, is_multiplier = extract_quantity(item_text)

        if is_multiplier:
            # Multiplier case: "نسخة من كل مرحلة"
            # Split on the multiplier phrase to get the prefix (book + grades context)
            prefix_match = _MULTIPLIER_RE.search(normalize_input(item_text))
            if not prefix_match:
                results.append(BookLineItem(
                    book_name=None, quantity=1, needs_review=True,
                    review_reason="Multiplier phrase not found"))
                continue

            prefix = item_text[:prefix_match.start()].strip()
            suffix = item_text[prefix_match.end():].strip()

            # Detect book name from the full text (excluding quantity words)
            full_norm = normalize_input(item_text)
            book_candidates = []
            # Try to find book name in suffix (after multiplier phrase)
            if suffix:
                raw_suffix = extract_book_name(suffix)
                if raw_suffix:
                    book_candidates.append((raw_suffix, suffix))
            # Try prefix as book name hint
            raw_prefix = extract_book_name(prefix)
            if raw_prefix:
                book_candidates.append((raw_prefix, prefix))

            matched_name = None
            match_type = "none"
            confidence = 0.0
            for candidate, source in book_candidates:
                name, mt, conf = match_book_name(candidate, book_lookup)
                if name and conf > confidence:
                    matched_name = name
                    match_type = mt
                    confidence = conf

            # Detect grades from prefix
            grades = _extract_multiplier_grades(prefix)

            if not matched_name:
                results.append(BookLineItem(
                    book_name=suffix or prefix, quantity=1, needs_review=True,
                    review_reason="Book name not found in multiplier context"))
                continue

            if not grades:
                results.append(BookLineItem(
                    book_name=matched_name, quantity=1, needs_review=True,
                    review_reason="No grades mentioned before multiplier phrase"))
                continue

            # Create one line item per grade
            for grade_str in grades:
                gi = GradeInfo(stage=None, grade=grade_str, source="multiplier")
                price, stage, grade_label = _resolve_price(
                    matched_name, gi, book_lookup)
                needs_review, review_reason = _check_review(
                    matched_name, "", match_type, gi, price, book_lookup)
                results.append(BookLineItem(
                    book_name=matched_name,
                    grade=grade_label or grade_str,
                    stage=stage or gi.stage,
                    price=price,
                    quantity=1,
                    quantity_assumed=False,
                    needs_review=needs_review,
                    review_reason=review_reason,
                    match_type=match_type,
                    confidence=confidence,
                ))
            continue

        # Normal case (no multiplier)
        # Check for multi-grade pattern: "للصف الثاني والثالث" or "الصف الأول والتاني"
        grade_info = detect_grade(item_text)
        
        # If we detected a grade but the text contains "و" (and) with multiple grades,
        # try to expand into multiple line items
        if grade_info.grade and 'و' in normalize_input(item_text):
            # Try to extract multiple grades
            expanded_grades = _extract_multiplier_grades(item_text)
            if len(expanded_grades) > 1:
                # Re-match with each grade
                raw_name = extract_book_name(item_text)
                matched_name, match_type, confidence = match_book_name(raw_name, book_lookup)
                if matched_name:
                    for grade_str in expanded_grades:
                        gi = GradeInfo(stage=grade_info.stage, grade=grade_str, source="explicit")
                        price, stage, grade_label = _resolve_price(matched_name, gi, book_lookup)
                        needs_review, review_reason = _check_review(
                            matched_name, raw_name, match_type, gi, price, book_lookup
                        )
                        results.append(BookLineItem(
                            book_name=matched_name,
                            grade=grade_label or grade_str,
                            stage=stage or gi.stage,
                            price=price,
                            quantity=qty,
                            quantity_assumed=qty_assumed,
                            needs_review=needs_review,
                            review_reason=review_reason,
                            match_type=match_type,
                            confidence=confidence,
                        ))
                    continue

        raw_name = extract_book_name(item_text)
        matched_name, match_type, confidence = match_book_name(raw_name, book_lookup, grade_info.grade)

        price, stage, grade_label = None, None, None
        if matched_name:
            price, stage, grade_label = _resolve_price(matched_name, grade_info, book_lookup)

        needs_review, review_reason = _check_review(
            matched_name, raw_name, match_type, grade_info, price, book_lookup
        )

        item = BookLineItem(
            book_name=matched_name or raw_name,
            grade=grade_label or grade_info.grade,
            stage=stage or grade_info.stage,
            price=price,
            quantity=qty,
            quantity_assumed=qty_assumed,
            needs_review=needs_review,
            review_reason=review_reason,
            match_type=match_type,
            confidence=confidence,
        )
        results.append(item)

    return results


def _check_review(
    matched_name: Optional[str],
    raw_name: str,
    match_type: str,
    grade_info: GradeInfo,
    price: Optional[float],
    book_lookup: dict,
) -> tuple[bool, Optional[str]]:
    """Determine if item needs review and why."""
    if matched_name is None:
        reason = f"Book name not matched: '{raw_name}'" if raw_name else "Could not extract book name"
        return True, reason

    if match_type == "ambiguous":
        return True, f"Ambiguous book name match for '{raw_name}'"

    # If price was successfully resolved, no review needed
    if price is not None:
        return False, None

    if grade_info.grade is None and grade_info.source != "bcode":
        norm_name = _norm_book(matched_name)
        stages = book_lookup.get("name_stages", {}).get(norm_name, set())
        if len(stages) > 1:
            return True, f"Book '{matched_name}' in multiple stages, no grade specified"
        if len(stages) == 1:
            entries = book_lookup.get("books", {}).get(norm_name, [])
            stage_entries = [e for e in entries if e["stage"] == stages[0]]
            if len(stage_entries) > 1:
                return True, f"Book '{matched_name}' has multiple prices, no grade specified"
        if not stages:
            return True, f"No grade/stage specified for '{matched_name}'"

    if price is None:
        return True, f"Could not resolve price for '{matched_name}' (grade={grade_info.grade})"

    return False, None


# ── Continuation-Line Linking ───────────────────────────────

def _grades_equal(a: Optional[str], b: Optional[str]) -> bool:
    """Compare two grade labels under Arabic normalization."""
    if not a or not b:
        return False
    return normalize_input(a) == normalize_input(b)


def _is_genuine_grade(text: str, gi: GradeInfo) -> bool:
    """Whether a grade mention is real, vs a quantity numeral like '٣ نسخ'.

    A number that is only a quantity (comes from a books/نسخ phrase) must
    not spawn a new grade-based sub-item.
    """
    if gi.source in ("explicit", "bcode", "gcode", "jrid", "ordinal_only"):
        return True
    if gi.source == "stage_only":
        return False
    norm = normalize_input(text)
    return bool(re.search(r"grade|جريد|ابتدائي|اعدادي|ثانوي|للصف|الصف", norm, re.IGNORECASE))


def _apply_grade_to_item(item: BookLineItem, gi: GradeInfo, book_lookup: dict) -> None:
    """Set grade on an item and re-resolve its price."""
    if not item.book_name or not gi.grade:
        return
    price, stage, label = _resolve_price(item.book_name, gi, book_lookup)
    item.grade = label or gi.grade
    item.stage = stage or gi.stage or item.stage
    item.price = price
    if price is not None:
        item.needs_review = False
        item.review_reason = None
    else:
        item.needs_review = True
        item.review_reason = f"Could not resolve price for '{item.book_name}' (grade={gi.grade})"


def _add_grade_item(block: dict, gi: GradeInfo, qty: int, qty_assumed: bool, book_lookup: dict) -> None:
    """Append (or bump) a grade-specific sub-item for a book block."""
    for existing in block["items"]:
        if existing.grade and _grades_equal(existing.grade, gi.grade):
            existing.quantity = max(existing.quantity or 1, qty)
            return
    item = BookLineItem(
        book_name=block["name"], quantity=qty, quantity_assumed=qty_assumed,
        needs_review=True, review_reason="placeholder",
    )
    _apply_grade_to_item(item, gi, book_lookup)
    block["items"].append(item)
    block["has_continuation_grades"] = True


def _attach_quantity(block: dict, qty: int) -> None:
    """Fold a quantity-only continuation line into the block's last sub-item."""
    if not block["items"] or qty <= 1:
        return
    last = block["items"][-1]
    last.quantity = qty
    last.quantity_assumed = False


def link_items(items: list[str], book_lookup: dict, grade_hint: Optional[str] = None) -> list[BookLineItem]:
    """Match a customer's raw item lines, linking continuation lines.

    Continuation rules:
      - genuine grade-only line after a book → new sub-item for that book
        (or bumps quantity if the grade already exists)
      - quantity-only line after a book → folds into the last sub-item's qty
      - grade-only line BEFORE any book → saved, applied to the next book line
      - grade_hint (year_edition) → resolves an ungraded solo book item, e.g.
        "٤ كتب power up" + year_edition "٣ ابتدائى" → Power Up G3
    """
    blocks: list[dict] = []
    pending_grades: list[GradeInfo] = []

    for line in items:
        text = (line or "").strip()
        if not text:
            continue

        gi = detect_grade(text)
        qty, qty_assumed, is_multiplier = extract_quantity(text)
        genuine = _is_genuine_grade(text, gi)

        book_items = [b for b in match_book_order(text, book_lookup) if b.book_name]

        if book_items:
            base = book_items[0]
            if pending_grades and base.grade is None:
                _apply_grade_to_item(base, pending_grades.pop(0), book_lookup)
            blocks.append({
                "items": book_items,
                "name": base.book_name,
                "has_continuation_grades": False,
            })
            continue

        if not blocks:
            if genuine and gi.grade:
                pending_grades.append(gi)
            continue

        block = blocks[-1]

        if is_multiplier:
            continue

        if genuine and gi.grade:
            _add_grade_item(block, gi, qty, qty_assumed, book_lookup)
        elif not qty_assumed and qty > 1:
            _attach_quantity(block, qty)

    # grade_hint fallback for solo ungraded book items with no continuations
    if grade_hint:
        hint_grade = detect_grade(grade_hint)
        if hint_grade.grade:
            for block in blocks:
                if block["has_continuation_grades"] or len(block["items"]) != 1:
                    continue
                item = block["items"][0]
                if item.grade is None and item.book_name:
                    _apply_grade_to_item(item, hint_grade, book_lookup)

    results: list[BookLineItem] = []
    for block in blocks:
        # A book header that never named a grade is replaced by the graded
        # continuation sub-items (e.g., "power up" + lines for G2/G6/G1).
        if block["has_continuation_grades"] and not block["items"][0].grade:
            block["items"] = block["items"][1:]
        results.extend(block["items"])
    return results

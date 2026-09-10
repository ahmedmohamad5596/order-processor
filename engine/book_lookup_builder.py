"""Build book lookup from book_prices.xlsx.

Produces a lookup table mapping (normalized_book_name, grade) → price,
plus supporting structures for grade detection and stage resolution.
"""
import json
import re as _re
from pathlib import Path
from typing import Any
import openpyxl

from engine.config import EXCEL_PATH, DATA_DIR
from engine.normalizer import normalize_input

BOOK_EXCEL_PATH = EXCEL_PATH.parent / "book_prices.xlsx"
BOOK_CACHE_PATH = DATA_DIR / "book_lookup_cache.json"

# Arabic transliteration aliases for common book names
# Keys are normalized Arabic text → values are English equivalents.
# Order matters: most-specific (longest) keys first, since _transliterate_book_name
# replaces substrings in dict order.
_ARABIC_BOOK_ALIASES = {
    "بايونير": "pioneer",
    "بيونير": "pioneer",
    "بايو نير": "pioneer",
    "نيو كلوز اب": "new close up",
    "نيو كلوزاب": "new close up",
    "نيوكلوزاب": "new close up",
    "كلوزاب": "close up",
    "كلوز اب": "close up",
    "كلوس اب": "close up",
    "كلوساب": "close up",
    "اني وستريم": "upstream",
    "انيوستريم": "upstream",
    "انيستريم": "upstream",
    "استريم": "upstream",
    "اب ستريم": "upstream",
    "ابستريم": "upstream",
    "واب ستريم": "upstream",
    "وابستريم": "upstream",
    "اول ستريم": "upstream",
    "اولستريم": "upstream",
    "فوكس": "focus",
    "ايم هاي": "aim high",
    "ايمهاي": "aim high",
    "اتش هاي": "aim high",
    "اتشهاي": "aim high",
    "ايم هاى": "aim high",
    "وند رول": "wonderful world",
    "وندر فول": "wonderful world",
    "وندرول": "wonderful world",
    "وندرفول": "wonderful world",
    "ووندر فول": "wonderful world",
    "وندر وورلد": "wonderful world",
    "وارلد وندر": "wonderful world",
    "ماك ميلان": "macmillan",
    "ماكميلان": "macmillan",
    "اكسفورد ديسكفر": "oxford discover",
    "اكسفورد ديسكفري": "oxford discover",
    "اوكسفورد ديسكفر": "oxford discover",
    "اوكسفورد ديسكفري": "oxford discover",
    "اكسفورد": "oxford discover",
    "اوكسفورد": "oxford discover",
    "وكسفورد": "oxford discover",
    "وديسكفر": "oxford discover",
    "تيم تو جاذر": "team together",
    "تيم تو جادر": "team together",
    "تيم تو جذر": "team together",
    "تيم توگذر": "team together",
    "تيمتوگذر": "team together",
    "تيم توغذر": "team together",
    "تيم تو جاثر": "team together",
    "بور بوينت": "point point",
    "بوربوينت": "point point",
    "فور بلست": "full blast",
    "فوربلاست": "full blast",
    "فول بلست": "full blast",
    "فولبلاست": "full blast",
    "فل بلاست": "full blast",
    "فول بلاست": "full blast",
    "بول اب": "power up",
    "بولاپ": "power up",
    "باور اب": "power up",
    "باوراپ": "power up",
    "باور اپ": "power up",
    "باوراب": "power up",
    "بور اب": "power up",
    "بوراب": "power up",
    "بوار اب": "power up",
    "وورلد ووتشرز": "world watchers",
    "وورلد ووتشر": "world watchers",
    "ورلد ووتشرز": "world watchers",
    "ورلد ووتشر": "world watchers",
    "وورلد وتشر": "our world",
    "ورلد وتشر": "our world",
    "اور وورلد": "our world",
    "اورل وتشر": "our world",
    "ايڤر بادي اب": "everybody up",
    "ايفر بادي اب": "everybody up",
    "ايفربادياب": "everybody up",
    "ايڤر بادي": "everybody",
    "ايفر بادي": "everybody",
    "اور ديسكفري ايلاند": "our discovery island",
    "اور ديسكفر ايلاند": "our discovery island",
    "انجلش وورلد": "english world",
    "انجليزي وورلد": "english world",
    "انجلش ورلد": "english world",
    "انجليش ورلد": "english world",
    "انجلش": "english world",
    "توب سكور": "top score",
    "توب اسكور": "top score",
    "توبسكور": "top score",
    "توب سكوور": "top score",
    "تشالنج": "challenge",
    "شالنج": "challenge",
    "تشالينج": "challenge",
    "سوبر لاند": "superland",
    "سوپر لاند": "superland",
    "سوبرلاند": "superland",
    "فاميلي اند فرندز": "family friends",
    "فاملي اند فرندز": "family friends",
    "فاميلي اند فريندز": "family friends",
    "فاملي اند فریندز": "family friends",
    "فاميلي فريندز": "family friends",
    "سكند اديشن": "second edition",
    "سبشل": "special",
    "سبيال": "special",
    "هاي ليفيل": "our world",
    "هايڤيل": "our world",
    "ever bady up": "everybody",
    "every body up": "everybody",
    "everybody up": "everybody",
    "ever body up": "everybody",
    "everbody": "everybody",
    "everbady up": "everybody",
    "ever bady": "everybody",
    "واندر فول": "wonderful world",
    "واندرر فول": "wonderful world",
    "سوبر لاند": "superland",
    "المحور": "wonderful world",
    "محور": "wonderful world",
}

# Grade code mapping — B1/B1+/B2 in book names → explicit stage names
_GRADE_CODES = {
    "b1": "أولى إعدادي",
    "b1+": "تانية إعدادي",
    "b2": "تالتة إعدادي",
}

# Arabic grade patterns → normalized grade
_ARABIC_GRADE_MAP = {
    "اول": "G1", "أول": "G1", "الاول": "G1", "الأول": "G1", "الاولي": "G1", "الأولى": "G1",
    "تاني": "G2", "ثاني": "G2", "الثاني": "G2", "التاني": "G2", "الثانية": "G2", "التانية": "G2",
    "تالت": "G3", "ثالث": "G3", "الثالث": "G3", "التالت": "G3", "الثالثة": "G3", "التالتة": "G3",
    "تالته": "G3", "تالتة": "G3",
    "رابع": "G4", "الرابع": "G4",
    "خامس": "G5", "الخامس": "G5",
    "سادس": "G6", "السادس": "G6",
}

# B-code to grade within preparatory stage
_BCODE_GRADE = {
    "b1": "أولى إعدادي",
    "b1+": "تانية إعدادي",
    "b2": "تالتة إعدادي",
}


def _normalize_grade_token(token: str) -> str | None:
    """Normalize a grade token (e.g., 'الخامس', 'G5', '5') to 'G5' format."""
    t = token.strip().strip("،").strip()
    upper = t.upper()
    if upper.startswith("G") and len(upper) <= 3 and upper[1:].isdigit():
        return upper
    arabic_to_western = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    digit = t.translate(arabic_to_western)
    if digit.isdigit() and 1 <= int(digit) <= 6:
        return f"G{digit}"
    normalized = normalize_input(t)
    for pattern, gcode in _ARABIC_GRADE_MAP.items():
        if normalize_input(pattern) == normalized:
            return gcode
    return None


def _parse_grade_field(raw: str) -> list[str]:
    """Parse Excel Grade/Level field into list of individual grades.

    Examples:
        "G1 : G6" → ["G1", "G2", "G3", "G4", "G5", "G6"]
        "G4, G5" → ["G4", "G5"]
        "أولى إعدادي" → ["أولى إعدادي"]
        "أولى إعدادي، تانية إعدادي، تالتة إعدادي" → ["أولى إعدادي", "تانية إعدادي", "تالتة إعدادي"]
    """
    if not raw:
        return []
    s = str(raw).strip()
    if ":" in s:
        parts = [p.strip() for p in s.split(":")]
        if len(parts) == 2 and parts[0].upper().startswith("G") and parts[1].upper().startswith("G"):
            start = int(parts[0][1:])
            end = int(parts[1][1:])
            return [f"G{i}" for i in range(start, end + 1)]
    grades = []
    for part in s.split(","):
        part = part.strip()
        if part:
            grades.append(part)
    return grades


def _norm_book_key(title: str) -> str:
    """Normalize a book title for lookup key.

    Like normalize_input but preserves '+' (needed for B1/B1+ distinction).
    """
    text = title.strip()
    text = _re.sub(r"[^\w\s\u0600-\u06FF+]", " ", text, flags=_re.UNICODE)
    text = _re.sub(r"\s+", " ", text).strip()
    return text.lower()


def _build_book_lookup() -> dict[str, Any]:
    """Build full book lookup from Excel."""
    wb = openpyxl.load_workbook(str(BOOK_EXCEL_PATH), read_only=True)
    ws = wb[wb.sheetnames[0]]

    books: dict[str, list[dict]] = {}
    raw_names: dict[str, str] = {}

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if row_idx == 0:
            continue
        stage, title, grade_field, price = row
        if not title or not price:
            continue
        title = str(title).strip()
        stage = str(stage).strip() if stage else ""
        norm_name = _norm_book_key(title)
        raw_names[norm_name] = title

        if norm_name not in books:
            books[norm_name] = []

        grades = _parse_grade_field(grade_field)
        price_val = float(price) if price else 0.0

        for g in grades:
            books[norm_name].append({
                "grade": g,
                "price": price_val,
                "stage": stage,
            })

    wb.close()

    # Build Arabic-to-English alias map for book names
    alias_map: dict[str, str] = {}
    for ar_alias, en_target in _ARABIC_BOOK_ALIASES.items():
        for norm_name in books:
            if en_target in norm_name:
                alias_map[norm_name] = norm_name  # already English
                break
        else:
            alias_map[ar_alias] = en_target

    name_stages: dict[str, set[str]] = {}
    for norm_name, entries in books.items():
        name_stages[norm_name] = {e["stage"] for e in entries if e["stage"]}

    cache = {
        "books": books,
        "raw_names": raw_names,
        "name_stages": {k: list(v) for k, v in name_stages.items()},
        "total_entries": sum(len(v) for v in books.values()),
        "arabic_aliases": alias_map,
    }
    return cache


def _cache_valid() -> bool:
    """Check if cache is newer than the book prices Excel file."""
    if not BOOK_CACHE_PATH.exists():
        return False
    return BOOK_CACHE_PATH.stat().st_mtime >= BOOK_EXCEL_PATH.stat().st_mtime


def build_book_lookup(force: bool = False) -> dict[str, Any]:
    """Load or build the book lookup table.

    Returns dict with keys: books, raw_names, name_stages, total_entries.
    """
    if not force and _cache_valid():
        with open(BOOK_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = _build_book_lookup()
    with open(BOOK_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return cache

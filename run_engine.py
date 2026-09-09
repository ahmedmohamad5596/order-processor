"""Address Matching Engine — main entry point.

Reads orders from an input Excel file, matches addresses using the
lookup table, and writes results to orders_output.xlsx (confirmed)
and a needs_review list for manual inspection.
"""
import sys
from pathlib import Path

import openpyxl

from engine.config import EXCEL_PATH, OUTPUT_PATH
from engine.lookup_builder import build_lookup
from engine.matcher import match_address
from engine.models import FieldStatus

# Column indices in orders_output.xlsx (0-based)
COL_ORDER_CODE = 0
COL_RECEIVER = 1
COL_PHONE = 2
COL_PHONE2 = 3
COL_GOVERNORATE = 4
COL_CITY = 5
COL_AREA = 6
COL_STREET = 7
COL_ITEM_TYPE = 8
COL_ITEM_NAME = 9
COL_INSURANCE = 10
COL_EXPRESS = 11
COL_EX_DESC = 12
COL_COD_CURRENCY = 13
COL_COD_AMOUNT = 14
COL_FOD_AMOUNT = 15
COL_WEIGHT = 16
COL_PICKUP_NUM = 17
COL_PICKUP_INFO = 18
COL_REMARKS = 19
COL_RC = 20


def process_address_field(raw_address: str, lookup: dict) -> dict:
    """Run the matcher on a raw address and return a result dict."""
    result = match_address(raw_address, lookup)
    return {
        "governorate": result.governorate or "",
        "city": result.city or "",
        "area": result.area or "",
        "street": result.street or "",
        "needs_review": result.needs_review,
        "review_reason": result.review_reason or "",
        "confidence_scores": result.confidence_scores,
        "matched_via": result.matched_via,
    }


def run(input_path: str | Path | None = None):
    """Main execution: read orders, match, write results."""
    lookup = build_lookup(EXCEL_PATH)
    print(f"Lookup loaded: {len(lookup['governorates'])} gov, "
          f"{len(lookup['cities'])} cities, {len(lookup['areas'])} areas")

    src = Path(input_path) if input_path else OUTPUT_PATH
    if not src.exists():
        print(f"Input file not found: {src}")
        print("Creating sample output with test addresses...")
        _write_sample(lookup)
        return

    wb = openpyxl.load_workbook(src)
    ws = wb.active

    confirmed_rows = []
    review_rows = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue

        # Extract raw address from the street column or reconstruct
        raw_address = _extract_address(row)
        if not raw_address:
            continue

        result = process_address_field(raw_address, lookup)

        if result["needs_review"]:
            review_rows.append({
                "row": row_idx,
                "original": list(row),
                "result": result,
            })
        else:
            confirmed_rows.append({
                "row": row_idx,
                "original": list(row),
                "result": result,
            })

    wb.close()

    # Print summary
    total = len(confirmed_rows) + len(review_rows)
    print(f"\nProcessed: {total} orders")
    print(f"  Confirmed: {len(confirmed_rows)}")
    print(f"  Needs review: {len(review_rows)}")

    if review_rows:
        print("\n--- Needs Review ---")
        for r in review_rows[:10]:
            print(f"  Row {r['row']}: {r['result']['review_reason']}")

    return {"confirmed": confirmed_rows, "review": review_rows}


def _extract_address(row: tuple) -> str | None:
    """Extract the raw address text from an order row.

    Reconstructs from governorate + city + area + street columns.
    """
    parts = []
    for idx in [COL_GOVERNORATE, COL_CITY, COL_AREA, COL_STREET]:
        val = row[idx] if idx < len(row) else None
        if val:
            parts.append(str(val).strip())
    return "، ".join(parts) if parts else None


def _write_sample(lookup: dict):
    """Write a sample output file with the 5 test cases."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Headers
    headers = [
        "Order code", "*Recevier", "*Recevier's phonenumber",
        "Recevier's phonenumber2", "*Arrival governorate", "*Arrival city",
        "*Arrival area", "*Receiver street", "Item type", "Item name",
        "Insurance Value", "Express product", "EX/DR Description",
        "COD currency", "COD amount", "FOD  amount", "Goods weight",
        "Customer's pickup number", "Customer's pickup information",
        "Remarks", "RC",
    ]
    ws.append(headers)

    # Test cases
    test_cases = [
        ("T1", "عميل 1", "01012345678", None,
         "القاهرة", "القاهرة الجديدة", "التجمع الأول",
         "٩٣ فيلا. شارع سمير شحاته، الياسمين", "كتاب", "Full Blast 5", 150, "لا", "", "EGP", 250, 0, 1.5, None, None, None, None),
        ("T2", "عميل 2", "01098765432", None,
         "الجيزة", "الطالبية", "الهرم",
         "22ش عاطف عيد الشهير بالزريبة متفرع من كراتيه", "كتاب", "Upstream 3", 130, "لا", "", "EGP", 200, 0, 1.2, None, None, None, None),
        ("T3", "عميل 3", "01155512345", None,
         "القاهرة", "الزاوية الحمراء", "",
         "٥٢ شارع بورسعيد، برج مريم رقم ٢٤", "كتاب", "Close Up 2", 140, "لا", "", "EGP", 220, 0, 1.0, None, None, None, None),
        ("T4", "عميل 4", "01288876543", None,
         "القاهرة", "", "",
         "شارعunknown، منطقةغيرموجودة", "كتاب", "Pioneer 1", 160, "لا", "", "EGP", 280, 0, 1.3, None, None, None, None),
        ("T5", "عميل 5", "01033345678", None,
         "القاهرة", "مدينة نصر", "",
         "شارع X", "كتاب", "Macmillan 4", 110, "لا", "", "EGP", 180, 0, 0.9, None, None, None, None),
    ]

    for tc in test_cases:
        ws.append(list(tc))

    # Process each row
    for row_idx in range(2, ws.max_row + 1):
        row = tuple(cell.value for cell in ws[row_idx])
        raw = _extract_address(row)
        if not raw:
            continue

        result = process_address_field(raw, lookup)

        # Write matched fields
        ws.cell(row=row_idx, column=COL_GOVERNORATE + 1,
                value=result["governorate"])
        ws.cell(row=row_idx, column=COL_CITY + 1,
                value=result["city"])
        ws.cell(row=row_idx, column=COL_AREA + 1,
                value=result["area"])
        ws.cell(row=row_idx, column=COL_STREET + 1,
                value=result["street"])

        status = "REVIEW" if result["needs_review"] else "OK"
        reason = result["review_reason"] or ""
        ws.cell(row=row_idx, column=COL_RC + 1,
                value=f"{status}: {reason}" if reason else status)

    wb.save(OUTPUT_PATH)
    print(f"\nSample output written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    run(input_file)

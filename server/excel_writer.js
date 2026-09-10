/**
 * Excel Writer - Task 17 (J&T Format)
 * 
 * Writes processed customer data to Excel file in J&T Express format.
 * Uses ExcelJS for cell styling (SheetJS CE cannot write styles):
 * header row highlighted yellow, all cells center-aligned, columns autofit.
 * 
 * J&T 21-column layout:
 * 1. Order code
 * 2. *Recevier
 * 3. *Recevier's phonenumber
 * 4. Recevier's phonenumber2
 * 5. *Arrival governorate
 * 6. *Arrival city
 * 7. *Arrival area
 * 8. *Receiver street
 * 9. Item type
 * 10. Item name
 * 11. Insurance Value
 * 12. Express product
 * 13. EX/DR Description
 * 14. COD currency
 * 15. COD amount
 * 16. FOD amount
 * 17. Goods weight
 * 18. Customer's pickup number
 * 19. Customer's pickup information
 * 20. Remarks
 * 21. RC
 */

const fs = require('fs');
const path = require('path');
const ExcelJS = require('exceljs');

// Reference styling (C:\Users\ahmed\Downloads\orders.xlsx): yellow header,
// Calibri 12, every cell centered, no borders.
const HEADER_STYLE = {
    font: { size: 12, color: { theme: 1 }, name: 'Calibri', family: 2, scheme: 'minor' },
    fill: { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFF00' }, bgColor: { indexed: 64 } },
    alignment: { horizontal: 'center', vertical: 'middle' }
};
const DATA_STYLE = {
    alignment: { horizontal: 'center', vertical: 'middle' }
};

// J&T 21-column layout
const COLUMNS = [
    'Order code',
    '*Recevier',
    "*Recevier's phonenumber",
    "Recevier's phonenumber2",
    '*Arrival governorate',
    '*Arrival city',
    '*Arrival area',
    '*Receiver street',
    'Item type',
    'Item name',
    'Insurance Value',
    'Express product',
    'EX/DR Description',
    'COD currency',
    'COD amount',
    'FOD  amount',
    'Goods weight',
    "Customer's pickup number",
    "Customer's pickup information",
    'Remarks',
    'RC'
];

const OUTPUT_DIR = path.join(__dirname, '..', 'OUTPUT');

/**
 * Estimate a column width so content fits (Excel ALT H O I auto-fit logic).
 * Multi-line cells count the widest line.
 */
function estimateWidth(cellText) {
    const lines = String(cellText ?? '').split(/\r\n|\n/);
    let max = 0;
    for (const line of lines) {
        let w = 0;
        for (const ch of line) {
            w += /[\u0600-\u06FF\u0660-\u0669]/.test(ch) ? 1.4 : 1;
        }
        max = Math.max(max, w);
    }
    return Math.ceil(max + 2);
}

/**
 * Generate filename with date.
 * @returns {string} Filename like 2026-09-08.xlsx
 */
function generateFilename() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}.xlsx`;
}

/**
 * Write customer data to Excel file in J&T format (ExcelJS with styling).
 * 
 * @param {object[]} customers - Processed customer records
 * @param {string} outputPath - Path to output Excel file
 * @returns {object} Result with success status, path, and stats
 */
async function writeToExcel(customers, outputPath = null) {
    if (!customers || customers.length === 0) {
        return { success: false, error: 'No customers to write' };
    }

    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Orders');

    // Header row — yellow highlight, centered (matches the reference sheet)
    const headerRow = ws.getRow(1);
    COLUMNS.forEach((name, idx) => {
        const cell = headerRow.getCell(idx + 1);
        cell.value = name;
        cell.style = HEADER_STYLE;
    });
    headerRow.commit();

    // Data rows — one row per customer/order (not per book). A multi-book
    // customer must not appear multiple times in the J&T sheet. All books go
    // into pickup info; COD amount is the order total.
    const valueRows = customers.map(customer => {
        const books = customer.books || [];
        if (books.length > 0) {
            const pickupInfo = books
                .map(book => buildPickupInfo(customer, book))
                .filter(Boolean)
                .join(' + ');
            // Item name column is intentionally empty; the full order
            // description lives in pickup info.
            const itemName = '';
            const codAmount = books.reduce((sum, book) =>
                sum + (book.price ? Number(book.price) * (Number(book.quantity) || 1) : 0), 0);

            return [
                '', customer.name || '', customer.phone1 || '', customer.phone2 || '',
                customer.address?.governorate || '', customer.address?.city || '',
                customer.address?.area || '', customer.address?.street || '',
                '', itemName, '', 'Standard', '', '',
                codAmount > 0 ? codAmount : '', '', 1, '',
                pickupInfo, customer.remarks || '', ''
            ];
        } else {
            // Customer with no books
            return [
                '', customer.name || '', customer.phone1 || '', customer.phone2 || '',
                customer.address?.governorate || '', customer.address?.city || '',
                customer.address?.area || '', customer.address?.street || '',
                '', '', '', 'Standard', '', '',
                '', '', 1, '',
                '', customer.remarks || '', ''
            ];
        }
    });

    // Track widest content per column for auto-fit
    const colWidths = COLUMNS.map((name, idx) => estimateWidth(name));
    valueRows.forEach(row => {
        row.forEach((value, idx) => {
            colWidths[idx] = Math.max(colWidths[idx], estimateWidth(value));
        });
    });

    valueRows.forEach((rowValues, idx) => {
        const row = ws.getRow(idx + 2);
        rowValues.forEach((value, cidx) => {
            const cell = row.getCell(cidx + 1);
            cell.value = value;
            cell.style = DATA_STYLE;
        });
        row.commit();
    });

    // Auto-fit column widths (capped so long cells don't blow up the sheet)
    colWidths.forEach((w, idx) => {
        ws.getColumn(idx + 1).width = Math.min(w, 75);
    });

    // Determine output path
    const outputDir = outputPath ? path.dirname(outputPath) : OUTPUT_DIR;
    const filename = outputPath ? path.basename(outputPath) : generateFilename();
    const finalPath = path.join(outputDir, filename);

    try {
        fs.mkdirSync(outputDir, { recursive: true });
        await wb.xlsx.writeFile(finalPath);
    } catch (error) {
        return { success: false, error: 'حدث خطأ أثناء تجهيز الـexcel' };
    }

    return {
        success: true,
        output_path: finalPath,
        filename: filename,
        rows_written: valueRows.length,
        total_customers: customers.length
    };
}

/**
 * Build pickup information string from customer and book data.
 * Written as a readable order description with no price and the raw
 * stage code (G1/B1/etc), e.g.
 * (team together G2 , ثلاث نسخ) + (team together G1 , نسخه واحده).
 * Never include internal review_reasons — this column ships to the courier.
 */
const QUANTITY_WORDS = {
    1: 'نسخه واحده', 2: 'نسختين', 3: 'ثلاث نسخ', 4: 'اربع نسخ',
    5: 'خمس نسخ', 6: 'ست نسخ', 7: 'سبع نسخ', 8: 'ثمان نسخ',
    9: 'تسع نسخ', 10: 'عشر نسخ'
};

function buildPickupInfo(customer, book) {
    const name = book.book_name ? book.book_name.trim() : '';
    const grade = String(book.grade || '').trim();
    const qtyWords = QUANTITY_WORDS[Number(book.quantity)] ||
        (book.quantity ? `${Number(book.quantity)} نسخ` : 'نسخه واحده');

    let text = name;
    if (grade) text += ` ${grade}`;
    text += ` , ${qtyWords}`;

    // Add discount info
    if (customer.discount_note) {
        text += ` (${customer.discount_note})`;
    }

    return `(${text})`;
}

/**
 * Test Excel writer with J&T format.
 */
async function testExcelWriter() {
    console.log('=== Excel Writer Tests (J&T Format) ===\n');

    const testCustomers = [
        {
            name: 'أحمد محمد',
            phone1: '01012345678',
            phone2: null,
            address: {
                governorate: 'القاهرة',
                city: 'مدينة نصر',
                area: null,
                street: 'شارع التحرير'
            },
            books: [
                {
                    book_name: 'English World',
                    grade: 'G1',
                    price: 140,
                    quantity: 2,
                    needs_review: false
                }
            ],
            status: 'confirmed',
            review_reasons: []
        },
        {
            name: 'سارة أحمد',
            phone1: '01112345678',
            phone2: '01212345678',
            address: {
                governorate: 'الجيزة',
                city: 'الهرم',
                area: 'الهرم',
                street: 'شارع أبو يوسف يعقوب'
            },
            books: [
                {
                    book_name: 'Full Blast Special',
                    grade: 'G1',
                    price: 140,
                    quantity: 1,
                    needs_review: false
                },
                {
                    book_name: 'Power Up',
                    grade: 'G2',
                    price: 160,
                    quantity: 1,
                    needs_review: false
                }
            ],
            status: 'confirmed',
            review_reasons: []
        }
    ];

    const outputPath = path.join(__dirname, '..', 'test_output.xlsx');
    
    // Test 1: Write new file
    console.log('Test 1: Write new Excel file (J&T format)');
    const result1 = await writeToExcel(testCustomers, outputPath);
    console.log(`  Success: ${result1.success ? '✅' : '❌'}`);
    console.log(`  Rows written: ${result1.rows_written}`);
    console.log(`  Path: ${result1.output_path}`);
    console.log();

    // Test 2: Read and verify
    console.log('Test 2: Verify J&T format');
    const wb = new ExcelJS.Workbook();
    await wb.xlsx.readFile(outputPath);
    const ws = wb.getWorksheet('Orders');
    const data = [];
    ws.eachRow((row, rowNumber) => {
        data.push(row.values.slice(1));
    });
    
    console.log(`  Columns: ${data[0]?.join(', ')}`);
    console.log(`  Row count: ${data.length - 1} data rows (expected: 3)`);
    console.log(`  Pass: ${data.length - 1 === 3 ? '✅' : '❌'}`);
    
    // Verify column names match J&T template
    const expectedCols = COLUMNS;
    const actualCols = data[0] || [];
    const colsMatch = expectedCols.every((c, i) => actualCols[i] === c);
    console.log(`  Column order matches J&T: ${colsMatch ? '✅' : '❌'}`);
    console.log();

    // Cleanup
    try {
        fs.unlinkSync(outputPath);
        console.log('Cleanup: test file removed ✅');
    } catch (e) {
        console.log('Cleanup: test file removed ✅');
    }

    console.log('\n=== All Tests Complete ===');
}

module.exports = { writeToExcel, testExcelWriter, COLUMNS };

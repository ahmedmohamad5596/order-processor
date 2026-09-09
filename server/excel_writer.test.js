/**
 * Task 17 Excel Export Tests - J&T Format
 */
const { writeToExcel, COLUMNS } = require('./excel_writer');
const XLSX = require('xlsx');
const path = require('path');
const fs = require('fs');

const TEST_OUTPUT = path.join(__dirname, '..', 'test_task17.xlsx');

async function runTests() {
    console.log('=== Task 17 Excel Export Tests (J&T Format) ===\n');

    // Test data with different stages
    const testCustomers = [
        // 1. confirmed
        {
            name: 'أحمد محمد',
            phone1: '01012345678',
            phone2: null,
            address: { governorate: 'القاهرة', city: 'مدينة نصر', area: null, street: 'شارع التحرير' },
            books: [{ book_name: 'Full Blast', grade: 'G1', price: 140, quantity: 2, needs_review: false }],
            status: 'confirmed',
            review_reasons: []
        },
        // 2. needs_review with ambiguous_stage
        {
            name: 'سارة أحمد',
            phone1: '01112345678',
            phone2: '01212345678',
            address: { governorate: 'الجيزة', city: 'الهرم', area: 'الهرم', street: 'شارع أبو يوسف يعقوب' },
            books: [{
                book_name: 'English World',
                grade: null,
                price: null,
                quantity: 1,
                needs_review: true,
                ai_suggestion: {
                    suggestion: 'الكتاب موجود في 7 مراحل...',
                    confidence: 100,
                    type: 'ambiguous_stage',
                    error: null
                }
            }],
            status: 'needs_review',
            review_reasons: ['1 book(s) need review']
        },
        // 3. tech_failure
        {
            name: 'خالد عبدالله',
            phone1: '01212345678',
            phone2: null,
            address: { governorate: null, city: null, area: null, street: 'شارع مجهول' },
            books: [{
                book_name: 'Unknown Book XYZ',
                grade: null,
                price: null,
                quantity: 1,
                needs_review: true,
                ai_suggestion: {
                    suggestion: null,
                    confidence: 0,
                    type: 'no_match',
                    error: 'No JSON found in response'
                }
            }],
            status: 'needs_review',
            review_reasons: ['Book not matched']
        },
        // 4. no_match successful
        {
            name: 'فاطمة حسن',
            phone1: '01551234567',
            phone2: null,
            address: { governorate: 'الإسكندرية', city: 'سيدي جابر', area: null, street: 'شارع التحرير' },
            books: [{
                book_name: 'Full Blast اولي اعدادي',
                grade: null,
                price: null,
                quantity: 1,
                needs_review: true,
                ai_suggestion: {
                    suggestion: 'full blast special',
                    confidence: 70,
                    type: 'no_match',
                    error: null
                }
            }],
            status: 'needs_review',
            review_reasons: ['Book name not matched']
        },
        // 5. no books
        {
            name: 'محمد علي',
            phone1: '01098765432',
            phone2: null,
            address: { governorate: 'المنصورة', city: null, area: null, street: 'شارع الجمهورية' },
            books: [],
            status: 'confirmed',
            review_reasons: []
        }
    ];

    // Test 1: Generate file
    console.log('Test 1: Generate Excel file (J&T format)');
    const result = await writeToExcel(testCustomers, TEST_OUTPUT);
    console.log(`  Success: ${result.success ? '✅' : '❌'}`);
    console.log(`  Filename: ${result.filename}`);
    console.log(`  Rows: ${result.rows_written}`);
    console.log(`  Path exists: ${fs.existsSync(result.output_path) ? '✅' : '❌'}`);
    console.log();

    // Test 2: Verify J&T columns
    console.log('Test 2: Verify J&T 21 columns');
    const wb = XLSX.readFile(result.output_path);
    const ws = wb.Sheets['Orders'];
    const data = XLSX.utils.sheet_to_json(ws);
    
    const expectedCols = COLUMNS;
    const actualCols = Object.keys(data[0] || {});
    const colsMatch = expectedCols.every((c, i) => actualCols[i] === c);
    console.log(`  Expected columns: ${expectedCols.length}`);
    console.log(`  Actual columns: ${actualCols.length}`);
    console.log(`  Columns match: ${colsMatch ? '✅' : '❌'}`);
    console.log();

    // Test 3: Verify row count
    console.log('Test 3: Verify row count');
    console.log(`  Rows: ${data.length} (expected: 5)`);
    console.log(`  Pass: ${data.length === 5 ? '✅' : '❌'}`);
    console.log();

    // Test 4: Verify key fields
    console.log('Test 4: Verify key fields');
    const row1 = data[0];
    console.log(`  Row 1 Receiver: ${row1['*Recevier']}`);
    console.log(`  Row 1 Phone: ${row1["*Recevier's phonenumber"]}`);
    console.log(`  Row 1 Governorate: ${row1['*Arrival governorate']}`);
    console.log(`  Row 1 Item name: ${row1['Item name']}`);
    console.log(`  Row 1 COD amount: ${row1['COD amount']}`);
    console.log(`  Pass: ${row1['*Recevier'] === 'أحمد محمد' ? '✅' : '❌'}`);
    console.log();

    // Test 5: Verify Express product is Standard
    console.log('Test 5: Verify Express product = Standard');
    const allStandard = data.every(r => r['Express product'] === 'Standard');
    console.log(`  All rows have Express product = Standard: ${allStandard ? '✅' : '❌'}`);
    console.log();

    // Test 6: Verify pickup info is descriptive Arabic with no prices
    console.log('Test 6: Verify pickup info format');
    const row1Pickup = row1["Customer's pickup information"];
    console.log(`  Row 1 pickup: ${row1Pickup}`);
    console.log(`  No price in pickup: ${!/جنيه/.test(row1Pickup) ? '✅' : '❌'}`);
    console.log(`  Expected '(Full Blast G1 , نسختين)': ${row1Pickup === '(Full Blast G1 , نسختين)' ? '✅' : '❌'}`);
    console.log(`  Goods weight = 1: ${row1['Goods weight'] === 1 ? '✅' : '❌'}`);
    console.log(`  Item name empty: ${row1['Item name'] === '' ? '✅' : '❌'}`);
    console.log();

    // Cleanup
    fs.unlinkSync(TEST_OUTPUT);
    console.log('Cleanup: test file removed ✅');

    console.log('\n=== All Tests Complete ===');
}

runTests().catch(console.error);

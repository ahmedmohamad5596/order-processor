/**
 * Assembly Layer Tests - Task 8
 */

const { processCustomer, getSummary } = require('./assembly');

async function runTests() {
    const apiKey = process.env.OPENROUTER_API_KEY;
    
    if (!apiKey) {
        console.log('❌ OPENROUTER_API_KEY not set');
        return;
    }

    console.log('=== Assembly Layer Tests (Task 8) ===\n');

    // Test 1: Complete customer with all fields
    console.log('Test 1: Complete customer');
    const customer1 = await processCustomer(
        'أحمد محمد، تليفون 01012345678، العنوان: القاهرة، مدينة نصر، شارع التحرير، المطلوب: كتاب English World للصف الأول الثانوي',
        apiKey
    );
    console.log(`  Name: ${customer1.name}`);
    console.log(`  Phone: ${customer1.phone1}`);
    console.log(`  Status: ${customer1.status}`);
    console.log(`  Books: ${customer1.books.length}`);
    console.log(`  Pass: ${customer1.name === 'أحمد محمد' && customer1.phone1 === '01012345678' ? '✅' : '❌'}\n`);

    // Test 2: Customer with multiple phones
    console.log('Test 2: Multiple phones');
    const customer2 = await processCustomer(
        'سارة أحمد - 01112345678 - 01212345678\nالعنوان: الجيزة، الهرم\nالكتب: Full Blast Special G1',
        apiKey
    );
    console.log(`  Name: ${customer2.name}`);
    console.log(`  Phone1: ${customer2.phone1}`);
    console.log(`  Phone2: ${customer2.phone2}`);
    console.log(`  Status: ${customer2.status}`);
    console.log(`  Pass: ${customer2.phone2 !== null ? '✅' : '❌'}\n`);

    // Test 3: Summary statistics
    console.log('Test 3: Summary statistics');
    const summary = getSummary([customer1, customer2]);
    console.log(`  Total: ${summary.total_customers}`);
    console.log(`  Confirmed: ${summary.confirmed}`);
    console.log(`  Needs Review: ${summary.needs_review}`);
    console.log(`  Total Books: ${summary.total_books}`);
    console.log(`  Pass: ${summary.total_customers === 2 && summary.total_books >= 2 ? '✅' : '❌'}\n`);

    console.log('=== All Tests Complete ===');
}

runTests().catch(console.error);

/**
 * AI Extractor Tests - Task 4
 * 
 * Tests for the OpenRouter-based extraction module.
 * Note: These tests require a valid OPENROUTER_API_KEY.
 */

const { extractCustomerData } = require('./ai_extractor');

// Sample customer texts for testing
const TEST_CUSTOMERS = [
    {
        id: 1,
        text: 'أحمد محمد، تليفون 01012345678، العنوان: القاهرة، مدينة نصر، شارع التحرير، المطلوب: كتاب English World للصف الأول الثانوي'
    },
    {
        id: 2,
        text: 'سارة أحمد - 01112345678 - 01212345678\nالعنوان: الجيزة، الهرم، شارع أبو يوسف يعقوب\nالكتب:\n- Full Blast Special G1\n- Power Up G2'
    },
    {
        id: 3,
        text: 'محمد علي، المندوب يكلمني على 01098765432\nالعنوان: الإسكندرية، سيدي جابر\nالمطلوب: ٢ كتاب New Close up B1'
    },
    {
        id: 4,
        text: 'فاطمة حسن\n01551234567\nالمنصورة، مركز الدقهلية\nPower Up الصف الثاني + Power Up الصف الثالث'
    },
    {
        id: 5,
        text: 'خالد محمود - تالتة إعدادي\nالقاهرة، الزاوية الحمراء\nنسخة من كل مرحلة كتاب Family & Friends'
    }
];

/**
 * Run tests against all sample customers.
 * This requires a valid OPENROUTER_API_KEY environment variable.
 */
async function runTests() {
    const apiKey = process.env.OPENROUTER_API_KEY;
    
    console.log('=== AI Extractor Tests (Task 4) ===\n');
    console.log(`Using model: ${require('./ai_extractor').MODEL_ID}`);
    console.log(`API Key configured: ${apiKey ? '✅ Yes' : '❌ No (tests will fail without key)'}\n`);

    if (!apiKey) {
        console.log('ERROR: OPENROUTER_API_KEY environment variable not set.');
        console.log('Please set it before running these tests:');
        console.log('  $env:OPENROUTER_API_KEY="your-key-here"  (Windows PowerShell)');
        console.log('  export OPENROUTER_API_KEY="your-key-here"  (Linux/Mac)');
        return;
    }

    const results = [];
    
    for (const customer of TEST_CUSTOMERS) {
        console.log(`--- Test ${customer.id}: Customer ${customer.id} ---`);
        console.log(`Input: ${customer.text.substring(0, 60)}...`);
        
        const startTime = Date.now();
        const result = await extractCustomerData(customer.text, apiKey);
        const duration = Date.now() - startTime;
        
        if (result.ok) {
            console.log(`✅ Success (${duration}ms)`);
            console.log(`   Extracted: ${JSON.stringify(result.data, null, 2)}`);

            results.push({ id: customer.id, ok: true, duration });
        } else {
            console.log(`❌ Failed (${duration}ms): ${result.error}`);
            if (result.raw) {
                console.log(`   Raw response: ${result.raw.substring(0, 200)}...`);
            }
            results.push({ id: customer.id, ok: false, error: result.error, duration });
        }
        console.log();
    }

    // Summary
    console.log('=== Test Summary ===');
    const passed = results.filter(r => r.ok).length;
    console.log(`Total: ${results.length}`);
    console.log(`Passed: ${passed}`);
    console.log(`Failed: ${results.length - passed}`);
    
    // Return results for programmatic access
    return results;
}

// Run if executed directly
if (require.main === module) {
    runTests().catch(console.error);
}

module.exports = { runTests, TEST_CUSTOMERS };

/**
 * Address Matcher Integration Tests - Task 15 (ai_suggestion path)
 *
 * Verifies that matchAddress returns an ai_suggestion object for
 * needs_review addresses (type=no_match) and null for confirmed ones.
 *
 * Structure assertions are deterministic (they pass whether or not the
 * OPENROUTER_API_KEY is set). When the key IS set, the suggestion contains
 * a real candidate; otherwise the error field is populated.
 */

const { matchAddress } = require('./address_matcher');

async function runTests() {
    const hasKey = !!process.env.OPENROUTER_API_KEY;
    if (hasKey) console.log('OPENROUTER_API_KEY is set — AI suggestions will be live.\n');
    else console.log('OPENROUTER_API_KEY not set — checking structure only (error field expected).\n');

    let pass = 0, fail = 0;
    const check = (label, cond) => {
        const ok = !!cond;
        console.log(`  ${ok ? '✅' : '❌'} ${label}`);
        ok ? pass++ : fail++;
    };

    // Test 1: confirmed address → ai_suggestion must be null.
    // Area must be a REAL known area (بركة النصر في الزاوية الحمراء) — not a
    // city echo; a city-only address now legitimately goes to needs_review.
    console.log('Test 1: Confirmed address (القاهرة، الزاوية الحمراء، بركة النصر)');
    const r1 = await matchAddress('القاهرة، الزاوية الحمراء، بركة النصر، شارع ١٠');
    check('ok', r1.ok);
    check('needs_review=false', r1.ok && r1.result.needs_review === false);
    check('ai_suggestion is null', r1.ok && r1.result.ai_suggestion === null);
    console.log();

    // Test 2: failing city (governorate resolves, city does not) → ai_suggestion with type=no_match.
    // NOTE: 'القاهرة شارع جمال عبد الناصر جسر السويس' is no longer a failure case — جسر السويس
    // resolves as an area whose parent city is الزاوية الحمراء (area_parent_city). Use a governorate
    // without a same-named capital city so the resolver genuinely cannot find a city.
    console.log('Test 2: Address with no city match (البحيرة شارع الجمهورية)');
    const r2 = await matchAddress('البحيرة شارع الجمهورية');
    check('ok', r2.ok);
    check('needs_review=true', r2.ok && r2.result.needs_review === true);
    if (r2.ok && r2.result.ai_suggestion) {
        const sug = r2.result.ai_suggestion;
        check('ai_suggestion.type is no_match', sug.type === 'no_match');
        check('has confidence number', typeof sug.confidence === 'number');
        check('has suggestion or error', !!(sug.suggestion || sug.error));
        if (hasKey) {
            if (sug.suggestion) {
                console.log(`     → live suggestion: ${sug.suggestion} (${sug.confidence}%)`);
            } else {
                console.log(`     → live AI returned no suggestion: ${sug.error || 'unknown'}`);
            }
        } else {
            check('error populated without key', !sug.suggestion && !!sug.error);
        }
    } else {
        check('ai_suggestion object present', false);
    }
    console.log();

    // Test 2b: learned area without a parent city stays honest — area resolves,
    // city is left unresolved for manual pick (جسر السويس is deliberately NOT
    // auto-mapped to the الزاوية الحمراء district).
    console.log('Test 2b: Area matches but parent city unset → needs review (القاهرة شارع جمال عبد الناصر جسر السويس)');
    const r2b = await matchAddress('القاهرة شارع جمال عبد الناصر جسر السويس');
    check('ok', r2b.ok);
    check('needs_review=true', r2b.ok && r2b.result.needs_review === true);
    check('area=جسر السويس', r2b.ok && r2b.result.area === 'جسر السويس');
    check('city unresolved', r2b.ok && (r2b.result.city === null || r2b.result.city === ''));
    const reasonMatch = r2b.ok && /no matching city/i.test(r2b.result.review_reason || '');
    check('review reason mentions missing city', reasonMatch);
    console.log();
    console.log('Test 3: Address with no governorate match (شارع غير معروف في بلد مجهول)');
    const r3 = await matchAddress('شارع غير معروف في بلد مجهول');
    check('ok', r3.ok);
    if (r3.ok) {
        check('needs_review=true', r3.result.needs_review === true);
        if (r3.result.ai_suggestion) {
            check('ai_suggestion.type is no_match', r3.result.ai_suggestion.type === 'no_match');
        } else {
            check('ai_suggestion object present', false);
        }
    } else {
        check('match returned ok', false);
    }
    console.log();

    console.log(`Result: ${pass} passed, ${fail} failed\n`);
    process.exit(fail > 0 ? 1 : 0);
}

runTests().catch(err => {
    console.error('Test runner error:', err);
    process.exit(1);
});
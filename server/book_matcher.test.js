/**
 * Book Matcher Integration Tests - Task 15 (ai_suggestion path)
 *
 * Verifies that matchBookItem returns an ai_suggestion object when the
 * item needs_review and null when it is confirmed.
 *
 * The ambiguous_stage case (English World) is deterministic and requires
 * NO API key. The no_match case requires OPENROUTER_API_KEY for a live
 * suggestion; with no key, the error field is populated.
 */

const { matchBookItem } = require('./book_matcher');

async function runTests() {
    const hasKey = !!process.env.OPENROUTER_API_KEY;
    if (hasKey) console.log('OPENROUTER_API_KEY is set — AI suggestions will be live.\n');
    else console.log('OPENROUTER_API_KEY not set — no_match suggestions hit the error path (expected).\n');

    let pass = 0, fail = 0;
    const check = (label, cond) => {
        const ok = !!cond;
        console.log(`  ${ok ? '✅' : '❌'} ${label}`);
        ok ? pass++ : fail++;
    };

    // Test 1: confirmed book → no review, ai_suggestion null
    console.log('Test 1: Confirmed book (Pioneer B2 تالتة إعدادي)');
    const r1 = await matchBookItem('Pioneer B2 تالتة إعدادي');
    check('ok', r1.ok);
    if (r1.ok) {
        const item = r1.result[0];
        check('needs_review=false', item.needs_review === false);
        check('ai_suggestion is null', item.ai_suggestion === null);
    } else {
        check('match returned ok', false);
    }
    console.log();

    // Test 2: ambiguous_stage → deterministic suggestion, no API key needed
    console.log('Test 2: Ambiguous stage (English World)');
    const r2 = await matchBookItem('English World');
    check('ok', r2.ok);
    if (r2.ok) {
        const item = r2.result[0];
        check('needs_review=true', item.needs_review === true);
        check('review_reason mentions multiple stages', /multiple stages/.test(item.review_reason || ''));
        if (item.ai_suggestion) {
            check('ai_suggestion.type is ambiguous_stage', item.ai_suggestion.type === 'ambiguous_stage');
            check('confidence is 100', item.ai_suggestion.confidence === 100);
            check('suggestion mentions مراحل', /مراحل/.test(item.ai_suggestion.suggestion || ''));
            check('has options array', Array.isArray(item.ai_suggestion.options) && item.ai_suggestion.options.length > 0);
            console.log(`     → suggestion: ${item.ai_suggestion.suggestion}`);
        } else {
            check('ai_suggestion object present', false);
        }
    } else {
        check('match returned ok', false);
    }
    console.log();

    // Test 3: no_match → suggestion object with type=no_match
    console.log('Test 3: Unknown book (Unknown Book XYZ)');
    const r3 = await matchBookItem('Unknown Book XYZ');
    check('ok', r3.ok);
    if (r3.ok) {
        const item = r3.result[0];
        check('needs_review=true', item.needs_review === true);
        if (item.ai_suggestion) {
            check('ai_suggestion.type is no_match', item.ai_suggestion.type === 'no_match');
            check('has confidence number', typeof item.ai_suggestion.confidence === 'number');
            check('has suggestion or error', !!(item.ai_suggestion.suggestion || item.ai_suggestion.error));
            if (hasKey) {
                if (item.ai_suggestion.suggestion) {
                    console.log(`     → live suggestion: ${item.ai_suggestion.suggestion} (${item.ai_suggestion.confidence}%)`);
                } else {
                    console.log(`     → live AI returned no suggestion: ${item.ai_suggestion.error || 'unknown'}`);
                }
            } else {
                check('error populated without key', !item.ai_suggestion.suggestion && !!item.ai_suggestion.error);
            }
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
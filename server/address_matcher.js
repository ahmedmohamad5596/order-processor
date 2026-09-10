/**
 * Address Matcher Integration - Task 6 (FIXED)
 * 
 * Bridges Node.js frontend with Python address matching engine (Part 1).
 * Uses stdin to pass Arabic text (fixes Windows UTF-8 encoding issues).
 */

const { spawn } = require('child_process');
const path = require('path');

const PYTHON_PATH = process.env.PYTHON_PATH || 'python';
const ENGINE_DIR = path.join(__dirname, '..', 'engine');

/**
 * Match an address using the Python engine.
 * Passes text via stdin to avoid Windows UTF-8 encoding issues.
 * 
 * @param {string} addressText - Raw address text from AI extraction
 * @returns {Promise<{ok: boolean, result?: object, error?: string}>}
 */
async function matchAddress(addressText) {
    if (!addressText || typeof addressText !== 'string' || addressText.trim().length === 0) {
        return { ok: false, error: 'Empty or invalid address text' };
    }

    return new Promise((resolve) => {
        // Python script that reads from stdin
        const pythonScript = `
import sys
sys.path.insert(0, r'${ENGINE_DIR.replace(/\\/g, '\\\\')}')

# Read address from stdin
address_text = sys.stdin.read().strip()

# Debug: print raw input
print(f'[DEBUG] Received {len(address_text)} chars', file=sys.stderr)
print(f'[DEBUG] Raw repr: {repr(address_text[:100])}', file=sys.stderr)

from engine.lookup_builder import build_lookup
from engine.matcher import match_address
from engine.normalizer import normalize_input
from engine.ai_suggestions import sync_suggest_governorate, sync_suggest_city
import json

# Build lookup
lookup = build_lookup()

# Match the address
result = match_address(address_text, lookup)

# AI suggestion for failed fields (Task 15)
ai_suggestion = None
    if result.needs_review:
        all_govs = [v['name_ar'] for v in lookup['governorates'].values()]
        gov_status = result.governorate_status.value if hasattr(result.governorate_status, 'value') else str(result.governorate_status)
        city_status = result.city_status.value if hasattr(result.city_status, 'value') else str(result.city_status)
        if gov_status != 'confirmed':
            s = sync_suggest_governorate(address_text, all_govs)
        elif city_status != 'confirmed':
            # Scope city suggestions to the matched governorate's COMPLETE city
            # list — never the national list (sync_suggest_city refuses it).
            gov_id = None
            for g in lookup['governorates'].values():
                if g['name_ar'] == result.governorate:
                    gov_id = g['id']
                    break
            scoped = [v['name_ar'] for v in lookup['cities'].values()
                      if v.get('governorate_id') == gov_id] if gov_id else []
            s = sync_suggest_city(address_text, result.governorate or '', scoped) if scoped else None
        else:
            s = None
    if s:
        ai_suggestion = {
            'suggestion': s.get('suggestion'),
            'confidence': s.get('confidence'),
            'reasoning': s.get('reasoning'),
            'type': 'no_match',
            'error': s.get('error'),
        }

# Output as JSON
output = {
    'governorate': result.governorate,
    'governorate_status': result.governorate_status.value if hasattr(result.governorate_status, 'value') else str(result.governorate_status),
    'city': result.city,
    'city_status': result.city_status.value if hasattr(result.city_status, 'value') else str(result.city_status),
    'area': result.area,
    'area_status': result.area_status.value if hasattr(result.area_status, 'value') else str(result.area_status),
    'street': result.street,
    'needs_review': result.needs_review,
    'review_reason': result.review_reason,
    'matched_via': result.matched_via,
    'confidence_scores': result.confidence_scores,
    'ai_suggestion': ai_suggestion
}

print(json.dumps(output, ensure_ascii=False))
`;

        const pythonProcess = spawn(PYTHON_PATH, ['-c', pythonScript], {
            cwd: path.join(__dirname, '..'),
            env: {
                ...process.env,
                PYTHONIOENCODING: 'utf-8',
                PYTHONUNBUFFERED: '1'
            },
            encoding: 'utf-8'
        });

        // Send address text via stdin
        pythonProcess.stdin.write(addressText);
        pythonProcess.stdin.end();

        let stdout = '';
        let stderr = '';

        pythonProcess.stdout.on('data', (data) => {
            stdout += data.toString();
        });

        pythonProcess.stderr.on('data', (data) => {
            stderr += data.toString();
        });

        pythonProcess.on('close', (code) => {
            // Log stderr for debugging
            if (stderr.trim()) {
                console.log('[Address Matcher stderr]:', stderr.trim());
            }

            if (code !== 0) {
                resolve({
                    ok: false,
                    error: `Python process exited with code ${code}: ${stderr}`
                });
                return;
            }

            try {
                const result = JSON.parse(stdout.trim());
                resolve({ ok: true, result });
            } catch (e) {
                resolve({
                    ok: false,
                    error: `Failed to parse Python output: ${e.message}`,
                    raw_output: stdout
                });
            }
        });
    });
}

/**
 * Test the address matcher with sample addresses.
 */
async function testAddressMatcher() {
    console.log('=== Address Matcher Tests (Task 6 - FIXED) ===\n');

    const testCases = [
        {
            name: 'Cairo New City',
            address: 'القاهرة، القاهرة الجديدة، التجمع الخامس، شارع سمير شحاته'
        },
        {
            name: 'Giza Haram',
            address: 'الجيزة، الهرم، شارع أبو يوسف يعقوب'
        },
        {
            name: 'Alexandria',
            address: 'الإسكندرية، سيدي جابر، شارع التحرير'
        },
        {
            name: 'Real Customer 1',
            address: '22ش عاطف عيد .الشهير ب الزريبه .متفرع من كراته .الطالبيه الهرم.'
        },
        {
            name: 'Real Customer 2',
            address: 'القاهرة شارع جمال عبد الناصر جسر السويس'
        },
        {
            name: 'Real Customer 3',
            address: 'محافظة القاهرة التجمع الخامس كمبوند ريتاج عمارة ٦ شقة ٣٠١'
        }
    ];

    const results = [];
    for (const tc of testCases) {
        console.log(`Test: ${tc.name}`);
        console.log(`  Input: ${tc.address}`);
        
        const result = await matchAddress(tc.address);
        
        if (result.ok) {
            console.log(`  ✅ Success`);
            console.log(`     Governorate: ${result.result.governorate} (${result.result.governorate_status})`);
            console.log(`     City: ${result.result.city} (${result.result.city_status})`);
            console.log(`     Area: ${result.result.area} (${result.result.area_status})`);
            console.log(`     Street: ${result.result.street}`);
            console.log(`     Needs Review: ${result.result.needs_review}`);
            if (result.result.review_reason) {
                console.log(`     Reason: ${result.result.review_reason}`);
            }
            results.push({ input: tc.address, ...result.result });
        } else {
            console.log(`  ❌ Failed: ${result.error}`);
            if (result.raw_output) {
                console.log(`     Raw output: ${result.raw_output.substring(0, 200)}`);
            }
            results.push({ input: tc.address, error: result.error });
        }
        console.log();
    }

    return results;
}

module.exports = { matchAddress, testAddressMatcher };

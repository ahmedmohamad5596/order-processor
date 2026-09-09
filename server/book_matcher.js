/**
 * Book Matcher Integration - Task 7
 * 
 * Bridges Node.js frontend with Python book matching engine (Part 2).
 * Uses child_process to run book_matcher.py and parse results.
 */

const { spawn } = require('child_process');
const path = require('path');

const PYTHON_PATH = process.env.PYTHON_PATH || 'python';
const ENGINE_DIR = path.join(__dirname, '..', 'engine');

/**
 * Match a book item using the Python engine.
 * 
 * @param {string} itemText - Raw book item text (e.g., "٤ كتب new close up b1")
 * @returns {Promise<{ok: boolean, result?: object, error?: string}>}
 */
async function matchBookItem(itemText) {
    if (!itemText || typeof itemText !== 'string' || itemText.trim().length === 0) {
        return { ok: false, error: 'Empty or invalid item text' };
    }

    return new Promise((resolve) => {
        const pythonCode = `
import sys
sys.path.insert(0, r'${ENGINE_DIR.replace(/\\/g, '\\\\')}')

from engine.book_lookup_builder import build_book_lookup
from engine.book_matcher import match_book_order
from engine.book_ai_suggestions import sync_suggest_book
import json

# Build lookup
lookup = build_book_lookup()

# Build the all_books list for the suggestion engine
all_books = []
for name, entries in lookup['books'].items():
    grades = [e['grade'] for e in entries]
    prices = [e['price'] for e in entries]
    stages = [e['stage'] for e in entries]
    all_books.append({'name': name, 'grades': grades, 'prices': prices, 'stages': stages})

# Match the book item
items = match_book_order('${itemText.replace(/'/g, "\\'")}', lookup)

# Output as JSON array
results = []
for item in items:
    item_dict = {
        'book_name': item.book_name,
        'grade': item.grade,
        'stage': item.stage,
        'price': item.price,
        'quantity': item.quantity,
        'quantity_assumed': item.quantity_assumed,
        'needs_review': item.needs_review,
        'review_reason': item.review_reason,
        'match_type': item.match_type,
        'confidence': item.confidence
    }
    item_dict['ai_suggestion'] = None
    if item.needs_review:
        suggestion = sync_suggest_book(
            item.book_name or '${itemText.replace(/'/g, "\\'")}',
            all_books,
            match_type=item.match_type,
            review_reason=item.review_reason
        )
        item_dict['ai_suggestion'] = {
            'suggestion': suggestion.get('suggestion'),
            'confidence': suggestion.get('confidence'),
            'reasoning': suggestion.get('reasoning'),
            'type': suggestion.get('type'),
            'error': suggestion.get('error'),
            'options': suggestion.get('options')
        }
    results.append(item_dict)

print(json.dumps(results, ensure_ascii=False))
`;

        const pythonProcess = spawn(PYTHON_PATH, ['-c', pythonCode], {
            cwd: path.join(__dirname, '..'),
            env: {
                ...process.env,
                PYTHONIOENCODING: 'utf-8'
            }
        });

        let stdout = '';
        let stderr = '';

        pythonProcess.stdout.on('data', (data) => {
            stdout += data.toString();
        });

        pythonProcess.stderr.on('data', (data) => {
            stderr += data.toString();
        });

        pythonProcess.on('close', (code) => {
            if (code !== 0) {
                resolve({
                    ok: false,
                    error: `Python process exited with code ${code}: ${stderr}`
                });
                return;
            }

            try {
                const results = JSON.parse(stdout.trim());
                resolve({ ok: true, result: results });
            } catch (e) {
                resolve({
                    ok: false,
                    error: `Failed to parse Python output: ${e.message}`
                });
            }
        });
    });
}

/**
 * Match multiple book items (batch processing).
 * 
 * @param {string[]} items - Array of raw book item texts
 * @returns {Promise<{ok: boolean, results?: object[], error?: string}>}
 */
async function matchBookItems(items) {
    if (!Array.isArray(items)) {
        return { ok: false, error: 'Items must be an array' };
    }

    const allResults = [];
    
    for (const item of items) {
        const result = await matchBookItem(item);
        allResults.push({
            input: item,
            ...result
        });
    }

    return { ok: true, results: allResults };
}

/**
 * Test the book matcher with sample items.
 */
async function testBookMatcher() {
    console.log('=== Book Matcher Tests (Task 7) ===\n');

    const testCases = [
        '٤ كتب new close up b1',
        '1 كتاب full blast second edition primary 4',
        'Power Up الصف الثاني نسخه واحده',
        'English World',
        'Aim High 4 للصف الاول الثانوي'
    ];

    const results = [];
    for (const tc of testCases) {
        console.log(`Test: ${tc}`);
        
        const result = await matchBookItem(tc);
        
        if (result.ok) {
            console.log(`  ✅ Success`);
            for (const item of result.result) {
                console.log(`     Book: ${item.book_name}`);
                console.log(`     Grade: ${item.grade}`);
                console.log(`     Price: ${item.price}`);
                console.log(`     Qty: ${item.quantity}`);
                console.log(`     Review: ${item.needs_review}`);
                if (item.review_reason) {
                    console.log(`     Reason: ${item.review_reason}`);
                }
            }
            results.push({ input: tc, ...result });
        } else {
            console.log(`  ❌ Failed: ${result.error}`);
            results.push({ input: tc, error: result.error });
        }
        console.log();
    }

    return results;
}

module.exports = { matchBookItem, matchBookItems, testBookMatcher };

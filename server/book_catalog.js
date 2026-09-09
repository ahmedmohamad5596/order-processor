/**
 * Book Catalog Integration
 *
 * Bridges Node.js to the Python book engine's reference catalog (built from
 * book_prices.xlsx — the single authoritative price source). Powers the edit
 * modal's "add book from the list" picker: book name → stage → quantity →
 * auto price.
 *
 * Output shape matches the engine's `all_books` (name / grades / prices /
 * stages) so the frontend can render the exact same stage options it already
 * shows for ambiguous books.
 */

const { spawn } = require('child_process');
const path = require('path');

const PYTHON_PATH = process.env.PYTHON_PATH || 'python';
const ENGINE_DIR = path.join(__dirname, '..', 'engine');

const PYTHON_PROGRAM = `
import sys
import json

sys.path.insert(0, r'${ENGINE_DIR.replace(/\\/g, '\\\\')}')

from engine.book_lookup_builder import build_book_lookup

lookup = build_book_lookup()
out = []
for name, entries in lookup['books'].items():
    out.append({
        'name': name,
        'grades': [e['grade'] for e in entries],
        'prices': [e['price'] for e in entries],
        'stages': [e['stage'] for e in entries],
    })

print(json.dumps(out, ensure_ascii=False))
`;

/**
 * Load the full book catalog (name + per-stage grade/price).
 * @returns {Promise<{ok: boolean, result?: object[], error?: string}>}
 */
function getBookCatalog() {
    return new Promise((resolve) => {
        const proc = spawn(PYTHON_PATH, ['-c', PYTHON_PROGRAM], {
            cwd: path.join(__dirname, '..'),
            env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
            encoding: 'utf-8'
        });
        let stdout = '';
        let stderr = '';
        proc.stdout.on('data', d => { stdout += d.toString(); });
        proc.stderr.on('data', d => { stderr += d.toString(); });
        proc.on('close', (code) => {
            if (code !== 0) {
                resolve({ ok: false, error: `Book catalog bridge exited ${code}: ${stderr.trim()}` });
                return;
            }
            try {
                resolve({ ok: true, result: JSON.parse(stdout.trim()) });
            } catch (e) {
                resolve({ ok: false, error: `Book catalog parse error: ${e.message}` });
            }
        });
    });
}

module.exports = { getBookCatalog };
/**
 * Geo Reference Integration
 *
 * Bridges Node.js to the Python address engine's canonical reference lists
 * (governorates + cities from egypt_governorates.xlsx) and exposes city
 * canonicalization (city name -> canonical city + governorate) used to re-validate
 * an admin edit the same way the engine would (port of the old system's
 * cityReferenceErrors / geo drop-downs).
 *
 * One Python process per call, input/output as JSON via stdin/stdout (Windows
 * UTF-8 safe). The engine caches the lookup, so repeated calls are cheap.
 */

const { spawn } = require('child_process');
const path = require('path');

const PYTHON_PATH = process.env.PYTHON_PATH || 'python';
const ENGINE_DIR = path.join(__dirname, '..', 'engine');

// Single embedded program handling all commands. request = {cmd, ...}.
const PYTHON_PROGRAM = `
import sys
import json

sys.path.insert(0, r'${ENGINE_DIR.replace(/\\/g, '\\\\')}')

from engine.lookup_builder import build_lookup
from engine.geo_search import search_geo
from engine.save_address import (
    canonicalize_city,
    resolve_address,
    assemble_saved_address,
    record_save_knowledge,
)

lookup = build_lookup()

def gov_id_by_name(name):
    if not name:
        return None
    target = name.strip()
    for gkey, ginfo in lookup['governorates'].items():
        if ginfo['name_ar'] == target:
            return ginfo['id']
    return None

def main():
    req = json.loads(sys.stdin.read() or '{}')
    cmd = req.get('cmd')
    if cmd == 'governorates':
        govs = [{'id': g['id'], 'name_ar': g['name_ar']}
                for g in lookup['governorates'].values()]
        govs.sort(key=lambda g: (len(g['id']), g['id']))
        print(json.dumps({'governorates': govs}, ensure_ascii=False))
    elif cmd == 'cities':
        gid = gov_id_by_name(req.get('governorate'))
        if gid is None:
            print(json.dumps({'error': 'invalid governorate'}, ensure_ascii=False))
            return
        cities = [{'city_id': c['id'], 'name_ar': c['name_ar']}
                  for c in lookup['cities'].values()
                  if c.get('governorate_id') == gid]
        cities.sort(key=lambda c: c['name_ar'])
        print(json.dumps({'governorate': req.get('governorate'), 'cities': cities},
                         ensure_ascii=False))
    elif cmd == 'save_address':
        address, city_errors = assemble_saved_address(
            req.get('previous') or {},
            req.get('updates') or {},
            lookup,
            raw_text=req.get('raw_text') or '',
        )
        recorded, kerr = record_save_knowledge(address, city_errors)
        print(json.dumps({
            'address': address,
            'city_errors': city_errors,
            'knowledge_recorded': recorded,
            'knowledge_error': kerr,
        }, ensure_ascii=False))
    elif cmd == 'search':
        q = req.get('q') or ''
        types = req.get('types') or ''
        limit = req.get('limit')
        results = search_geo(q, types, lookup, limit)
        print(json.dumps({'results': results, 'q': q}, ensure_ascii=False))
    else:
        print(json.dumps({'error': 'unknown cmd'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
`;

/**
 * Run the geo reference program with a JSON request.
 * @param {object} request
 * @returns {Promise<object>}
 */
function runGeo(request) {
    return new Promise((resolve) => {
        const proc = spawn(PYTHON_PATH, ['-c', PYTHON_PROGRAM], {
            cwd: path.join(__dirname, '..'),
            env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
            encoding: 'utf-8'
        });
        proc.stdin.write(JSON.stringify(request));
        proc.stdin.end();
        let stdout = '';
        let stderr = '';
        proc.stdout.on('data', d => { stdout += d.toString(); });
        proc.stderr.on('data', d => { stderr += d.toString(); });
        proc.on('close', (code) => {
            if (code !== 0) {
                resolve({ ok: false, error: `Geo bridge exited ${code}: ${stderr.trim()}` });
                return;
            }
            try {
                const out = JSON.parse(stdout.trim());
                resolve({ ok: true, result: out });
            } catch (e) {
                resolve({ ok: false, error: `Geo bridge parse error: ${e.message}` });
            }
        });
    });
}

/**
 * Canonical 27 governorates for the edit drop-down.
 * @returns {Promise<{ok: boolean, result?: {governorates: {id,name_ar}[]}, error?: string}>}
 */
async function getGovernorates() {
    return runGeo({ cmd: 'governorates' });
}

/**
 * Cities belonging to a governorate (by official name).
 * @param {string} governorate
 * @returns {Promise<{ok, result?: {governorate, cities: {city_id,name_ar}[]}, error?}>}
 */
async function getCitiesForGovernorate(governorate) {
    return runGeo({ cmd: 'cities', governorate });
}

/**
 * Search the full geographic reference (governorates/cities/areas).
 * @param {string} q raw query
 * @param {string} [types] comma-separated entity types; empty = all
 * @param {number} [limit] max results (clamped server-side to 25)
 * @returns {Promise<{ok, result?: {results: object[], q: string}, error?}>}
 */
async function searchGeo(q, types, limit) {
    return runGeo({ cmd: 'search', q, types, limit });
}

/**
 * Assemble + validate a saved address record in one engine pass (fix2 §9/§10):
 * canonicalization against the full reference, resolved ids, raw/manual values,
 * resolution status/confidence/evidence, and knowledge recording for clean
 * human saves. The result is exactly what gets stored.
 * @param {{previous?: object, updates?: object, raw_text?: string}} input
 * @returns {Promise<{ok, result?: {address, city_errors, knowledge_recorded, knowledge_error}, error?}>}
 */
async function assembleSavedAddress({ previous, updates, raw_text } = {}) {
    return runGeo({
        cmd: 'save_address',
        previous: previous || {},
        updates: updates || {},
        raw_text: raw_text || ''
    });
}

module.exports = { getGovernorates, getCitiesForGovernorate, searchGeo, assembleSavedAddress };
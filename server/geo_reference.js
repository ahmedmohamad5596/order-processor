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

// Single embedded program handling all three commands. request = {cmd, ...}.
const PYTHON_PROGRAM = `
import sys
import json

sys.path.insert(0, r'${ENGINE_DIR.replace(/\\/g, '\\\\')}')

from engine.lookup_builder import build_lookup

lookup = build_lookup()

def gov_id_by_name(name):
    if not name:
        return None
    target = name.strip()
    for gkey, ginfo in lookup['governorates'].items():
        if ginfo['name_ar'] == target:
            return ginfo['id']
    return None

def canonicalize(req):
    from engine.matcher import match_address
    from engine.normalizer import normalize_input
    city = (req.get('city') or '').strip()
    gov = (req.get('governorate') or '').strip()
    if not city:
        return {'matched': False, 'error': 'city is required'}
    text = city if not gov else f"{city} \\u060c {gov}"
    res = match_address(text, lookup)
    gs = getattr(res.governorate_status, 'value', str(res.governorate_status))
    cs = getattr(res.city_status, 'value', str(res.city_status))
    matched = cs == 'confirmed' and bool(res.city)
    resolved_city = res.city
    resolved_gov = res.governorate
    conflict = bool(resolved_gov) and bool(gov) and normalize_input(resolved_gov) != normalize_input(gov)
    reason = res.review_reason or ''
    amb = ('ambiguous' in reason.lower()) or ('needs manual selection' in reason.lower())
    return {
        'matched': matched,
        'city': resolved_city,
        'governorate': resolved_gov,
        'gov_status': gs,
        'city_status': cs,
        'conflict': conflict,
        'ambiguous': amb,
        'not_found': bool(not matched and not amb),
        'review_reason': reason,
    }

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
    elif cmd == 'canonicalize':
        print(json.dumps(canonicalize(req), ensure_ascii=False))
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
 * Canonicalize an admin-entered city (and its governorate): canonical name,
 * auto-derived governorate, conflict/ambiguity detection — the edit-time version
 * of the old system's cityReferenceErrors.
 * @param {string} city
 * @param {string} governorate
 * @returns {Promise<{ok, result?: object, error?: string}>}
 */
async function canonicalizeCity(city, governorate) {
    return runGeo({ cmd: 'canonicalize', city, governorate });
}

module.exports = { getGovernorates, getCitiesForGovernorate, canonicalizeCity };
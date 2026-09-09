/**
 * Order Processor Server - Full Integration
 *
 * Part 3: End-to-End Integration
 *
 * Integrated modules:
 * - server/splitter.js (Task 3): Customer boundary splitting
 * - server/ai_extractor.js (Task 4): AI extraction via OpenRouter
 * - server/phone_validator.js (Task 5): Phone validation
 * - server/address_matcher.js (Task 6): Address matching (Python bridge)
 * - server/book_matcher.js (Task 7): Book matching (Python bridge)
 * - server/assembly.js (Task 8): Assembly layer
 * - server/excel_writer.js (Task 9): Excel export
 * - server/state_store.js (Task 18): State persistence
 * - server/logger.js (Task 19): Structured logging
 */

// Load .env before anything reads process.env (native Node, no dependency).
// Missing .env is fine — falls back to the shell environment.
try {
    process.loadEnvFile();
} catch (err) {
    if (err.code !== 'ENOENT') {
        console.error('[env] Failed to load .env:', err.message);
    }
}

const express = require('express');
const path = require('path');
const fs = require('fs');
const { splitCustomers } = require('./splitter');
const { processCustomers, processCustomer } = require('./assembly');
const { validatePhone } = require('./phone_validator');
const { getGovernorates, getCitiesForGovernorate, canonicalizeCity } = require('./geo_reference');
const { getBookCatalog } = require('./book_catalog');
const { writeToExcel } = require('./excel_writer');
const { initDatabase, loadState, saveState, clearState, getPool } = require('./state_store');
const { logger, LEVELS } = require('./logger');

// AI provider key — generic first, OpenRouter kept as a backwards-compatible
// fallback so an AGNES/other OpenAI-compatible key works without renaming.
function configuredApiKey() {
    return process.env.AI_API_KEY || process.env.OPENROUTER_API_KEY || '';
}

const app = express();
const PORT = process.env.PORT || 3000;

// ── Request timing & metrics tracking ──────────────────────────────
const metrics = {
    totalRequests: 0,
    totalProcessingTime: 0,
    totalAICalls: 0,
    totalTechFailures: 0,
    errorCount: 0,
    lastProcessingTime: null,
    lastRequestTime: null
};

// Simple rate limiter (per IP)
const requestCounts = new Map();
const RATE_LIMIT = 60; // requests per minute
const RATE_WINDOW = 60000; // 1 minute

// Periodic cleanup of expired rate-limit entries to avoid unbounded memory growth
setInterval(() => {
    const now = Date.now();
    for (const [ip, entry] of requestCounts) {
        if (now > entry.resetAt) requestCounts.delete(ip);
    }
}, RATE_WINDOW);
requestCounts.unref?.();

// ── Middleware ─────────────────────────────────────────────────────
app.use(express.json({ limit: '1mb' })); // Limit request body size
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, '../public'), {
    // index.html (and JS) are updated from the server side; the browser must always
    // get the current version or the frontend keeps stale delete/export behavior.
    setHeaders(res, filePath) {
        if (filePath.endsWith('.html')) res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    }
}));

// Request logging middleware
app.use((req, res, next) => {
    const start = Date.now();
    metrics.totalRequests++;
    metrics.lastRequestTime = new Date().toISOString();

    // Rate limiting
    const ip = req.ip || req.connection?.remoteAddress || 'unknown';
    const now = Date.now();
    if (!requestCounts.has(ip)) {
        requestCounts.set(ip, { count: 1, resetAt: now + RATE_WINDOW });
    } else {
        const entry = requestCounts.get(ip);
        if (now > entry.resetAt) {
            entry.count = 1;
            entry.resetAt = now + RATE_WINDOW;
        } else {
            entry.count++;
            if (entry.count > RATE_LIMIT) {
                logger.warn('Rate limit exceeded', { ip, count: entry.count });
                return res.status(429).json({ ok: false, error: 'Too many requests' });
            }
        }
    }

    res.on('finish', () => {
        const duration = Date.now() - start;
        logger.logRequest(req, duration);
    });

    next();
});

// ── Health & Metrics Endpoints (Task 20) ───────────────────────────
app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        timestamp: new Date().toISOString(),
        version: '1.0.0',
        uptime: process.uptime()
    });
});

app.get('/api/metrics', async (req, res) => {
    const state = await loadState();
    res.json({
        ok: true,
        metrics: {
            ...metrics,
            avgProcessingTime: metrics.totalRequests > 0
                ? Math.round(metrics.totalProcessingTime / metrics.totalRequests)
                : 0,
            techFailureRate: metrics.totalRequests > 0
                ? ((metrics.totalTechFailures / metrics.totalRequests) * 100).toFixed(1) + '%'
                : '0%'
        },
        state: {
            hasSavedData: Array.isArray(state.customers) && state.customers.length > 0,
            lastSaved: state.savedAt
        }
    });
});

app.get('/api/logs', (req, res) => {
    const logFile = path.join(__dirname, '..', 'logs', 'server.log');
    if (!fs.existsSync(logFile)) {
        return res.json({ ok: true, logs: [], count: 0 });
    }
    try {
        const logs = fs.readFileSync(logFile, 'utf8')
            .split('\n')
            .filter(Boolean)
            .map(line => {
                try { return JSON.parse(line); }
                catch (e) { return { level: 'info', message: line, parse_error: true }; }
            })
            .slice(-100); // Last 100 entries
        res.json({ ok: true, logs, count: logs.length });
    } catch (err) {
        res.status(500).json({ ok: false, error: err.message });
    }
});

// Process orders endpoint (Tasks 3-8)
app.post('/api/process', async (req, res) => {
    const { text } = req.body;

    // Input validation (Task 22)
    if (!text || typeof text !== 'string') {
        return res.status(400).json({ ok: false, error: 'No text provided' });
    }
    if (text.length > 50000) {
        return res.status(400).json({ ok: false, error: 'Text too long (max 50000 characters)' });
    }

    const startTime = Date.now();

    try {
        // Task 3: Split into customers
        const customerTexts = splitCustomers(text);

        if (customerTexts.length === 0) {
            return res.json({
                ok: true,
                result: {
                    message: 'No customer data found',
                    customers: []
                }
            });
        }

        // Tasks 4-8: Full processing pipeline
        const apiKey = configuredApiKey();
        if (!apiKey) {
            return res.status(500).json({
                ok: false,
                error: 'AI_API_KEY environment variable not set (or OPENROUTER_API_KEY)'
            });
        }

        const { results, stats } = await processCustomers(customerTexts, apiKey);

        // Update metrics
        const duration = Date.now() - startTime;
        metrics.totalProcessingTime += duration;
        metrics.totalAICalls += stats.total_ai_calls || 0;
        metrics.totalTechFailures += stats.total_tech_failures || 0;
        metrics.lastProcessingTime = duration;

        // Auto-save to state store — MERGE with existing customers so a new
        // batch never wipes previously saved orders (dedupe by _editId).
        const currentState = await loadState();
        const currentCustomers = Array.isArray(currentState.customers) ? currentState.customers : [];
        const byEditId = new Map(currentCustomers.map(c => [c._editId, c]));
        for (const r of results) {
            byEditId.set(r._editId, r);
        }
        const saveResult = await saveState({
            customers: Array.from(byEditId.values()),
            stats: stats,
            savedAt: new Date().toISOString()
        });
        if (!saveResult.success) {
            logger.error('State save failed', { error: saveResult.error });
        }

        // Error alerting (Task 24)
        const failureRate = stats.total_ai_calls > 0
            ? (stats.total_tech_failures / stats.total_ai_calls) * 100
            : 0;
        if (failureRate > 30) {
            logger.warn('High tech failure rate detected', {
                rate: failureRate.toFixed(1) + '%',
                totalCalls: stats.total_ai_calls,
                failures: stats.total_tech_failures
            });
        }

        logger.info('Processing completed', {
            customers: results.length,
            duration_ms: duration,
            ai_calls: stats.total_ai_calls,
            tech_failures: stats.total_tech_failures
        });

        res.json({
            ok: true,
            result: {
                message: 'Processing completed',
                customer_count: results.length,
                customers: results,
                performance: stats
            }
        });

    } catch (error) {
        metrics.errorCount++;
        logger.error('Processing error', { error: error.message, stack: error.stack });
        res.status(500).json({
            ok: false,
            error: error.message
        });
    }
});

// Export to Excel endpoint (Task 17)
// Source of truth is the server-side state (state.json), never the client copy,
// so deleted/edited orders can't leak into the exported file.
// GET (like the legacy system: /api/orders/export/excel) and POST both work.
app.all('/api/export', async (req, res) => {
    const state = await loadState();
    // Rejected orders are excluded — they must never ship to the courier.
    const customers = (state.customers || []).filter(c => c && c.name && c.status !== 'rejected');

    if (customers.length === 0) {
        return res.status(400).json({
            ok: false,
            error: 'لا توجد بيانات للتصدير'
        });
    }

    try {
        const { writeToExcel } = require('./excel_writer');
        const result = await writeToExcel(customers);
        
        if (!result.success) {
            return res.status(500).json({
                ok: false,
                error: result.error || 'حدث خطأ أثناء تجهيز الـexcel'
            });
        }

        // Send file for download
        res.download(result.output_path, result.filename, (err) => {
            if (err && !res.headersSent) {
                res.status(500).json({
                    ok: false,
                    error: 'حدث خطأ أثناء تحميل الملف'
                });
            }
        });
    } catch (error) {
        res.status(500).json({
            ok: false,
            error: 'حدث خطأ أثناء تجهيز الـexcel'
        });
    }
});

// State management endpoints (Task 18)
app.get('/api/state', async (req, res) => {
    const state = await loadState();
    res.json({ ok: true, state });
});

app.post('/api/save', async (req, res) => {
    const { customers } = req.body;
    if (!customers || !Array.isArray(customers)) {
        return res.status(400).json({ ok: false, error: 'No customers data' });
    }
    const result = await saveState({ customers, savedAt: new Date().toISOString() });
    res.json(result);
});

app.delete('/api/state', async (req, res) => {
    await clearState();
    res.json({ ok: true, message: 'State cleared' });
});

// ── Customer CRUD Endpoints (Edit/Delete) ────────────────────────

// Re-derive status/review reasons from the customer's own (possibly edited)
// fields — the edit-time equivalent of the old system's resolve revalidation.
// Auto-derived reasons are recomputed; stored reasons that still apply (phone
// notes, catalog typos) are kept alongside.
function recomputeStatus(customer, extraErrors) {
    const reasons = (customer.review_reasons || []).filter(r =>
        !r.startsWith('Address:') && !r.startsWith('City:') &&
        !r.startsWith('Book "') && !r.includes('book(s) need review')
    );
    const a = customer.address || {};
    if (a.needs_review || (a.review_reason && String(a.review_reason).trim())) {
        reasons.push(a.review_reason ? `Address: ${a.review_reason}` : 'Address needs review');
    }
    const reviewBooks = (customer.books || []).filter(b => b.needs_review);
    if (reviewBooks.length > 0) {
        reasons.push(`${reviewBooks.length} book(s) need review`);
        for (const book of reviewBooks) {
            if (book.review_reason) reasons.push(`Book "${book.book_name}": ${book.review_reason}`);
        }
    }
    if (customer.phone1) {
        const v = validatePhone(customer.phone1);
        if (!v.valid && v.note) reasons.push(`phone1: ${v.note}`);
    }
    if (customer.phone2) {
        const v = validatePhone(customer.phone2);
        if (!v.valid && v.note) reasons.push(`phone2: ${v.note}`);
    }
    for (const err of (extraErrors || [])) reasons.push(err);
    customer.review_reasons = [...new Set(reasons.filter(Boolean))];
    customer.status = customer.review_reasons.length > 0 ? 'needs_review' : 'confirmed';
}

// PUT /api/customer/:id - Update a single customer (edit + resolve)
// Port of the old system's /resolve: merge admin edits, canonicalize the city
// against the reference, re-validate books, recompute status + review reasons.
app.put('/api/customer/:id', async (req, res) => {
    const customerId = parseInt(req.params.id);
    const updates = req.body;
    
    if (isNaN(customerId)) {
        return res.status(400).json({ ok: false, error: 'Invalid customer ID' });
    }
    
    const state = await loadState();
    const idx = state.customers.findIndex(c => c._editId === customerId);
    
    if (idx === -1) {
        return res.status(404).json({ ok: false, error: 'Customer not found' });
    }

    const customer = state.customers[idx];
    const cityErrors = [];

    // Plain fields
    if (updates.name !== undefined) customer.name = updates.name;
    if (updates.phone1 !== undefined) customer.phone1 = updates.phone1 || '';
    if (updates.phone2 !== undefined) customer.phone2 = updates.phone2 || null;
    if (updates.remarks !== undefined) customer.remarks = updates.remarks || null;
    if (updates.raw_text !== undefined) customer.raw_text = updates.raw_text;
    if (updates.discount_note !== undefined) customer.discount_note = updates.discount_note;
    if (updates.year_edition !== undefined) customer.year_edition = updates.year_edition;

    // Address edit → canonicalize city↔governorate (old cityReferenceErrors).
    if (updates.address) {
        const prev = customer.address || {};
        const a = { ...prev, ...updates.address };
        const city = String(a.city || '').trim();
        const gov = String(a.governorate || '').trim();

        if (city) {
            const ref = await canonicalizeCity(city, gov);
            if (ref.ok) {
                const r = ref.result;
                if (r.matched) {
                    a.city = r.city;
                    a.governorate = r.governorate;
                    if (r.conflict) {
                        cityErrors.push(`city: "${r.city}" belongs to ${r.governorate} per the city reference but the governorate field says "${gov}" — verify`);
                    }
                } else if (r.ambiguous) {
                    cityErrors.push(`city: "${city}" is ambiguous in the city reference — pick from the city list`);
                } else {
                    cityErrors.push(`city: "${city}" not found in the city reference — pick from the city list or correct the spelling`);
                }
            } else {
                cityErrors.push(`city: "${city}" could not be checked — ${ref.error}`);
            }
        } else if (gov) {
            // Empty city is only valid when the governorate is official (locality===governorate case).
            const ref = await getGovernorates();
            const official = ref.ok && ref.result.governorates.some(g => g.name_ar === gov);
            if (!official) {
                cityErrors.push(`governorate: "${gov}" is not an official governorate — pick an official governorate or set the arrival city`);
            }
        }

        if (cityErrors.length) {
            a.needs_review = true;
            a.review_reason = cityErrors.join('؛ ');
        } else if (a.city) {
            a.needs_review = false;
            a.review_reason = '';
            a.governorate_status = 'confirmed';
            a.city_status = 'confirmed';
            if (!a.area) a.area = a.city;
        }
        customer.address = a;
    }

    // Books edit → normalize + every book must carry a positive unit price.
    if (updates.books) {
        customer.books = (updates.books || []).map(b => {
            const nb = { ...b };
            const price = Number(nb.price);
            if (!Number.isFinite(price) || price <= 0) {
                nb.needs_review = true;
                nb.review_reason = 'missing unit price — set a price to confirm';
            } else {
                nb.needs_review = false;
                nb.review_reason = '';
            }
            return nb;
        });
    }

    recomputeStatus(customer, cityErrors);

    const saveResult = await saveState(state);
    if (!saveResult.success) {
        return res.status(500).json({ ok: false, error: 'Failed to save changes' });
    }
    
    logger.info('Customer updated', { id: customerId, status: customer.status });
    res.json({ ok: true, customer: state.customers[idx] });
});

// POST /api/customer/:id/re-extract — re-run the full pipeline on the admin's
// corrected ORIGINAL customer text and return a preview (row NOT saved here).
// Port of the old system's /re-extract ("حفظ وإعادة إرسال").
app.post('/api/customer/:id/re-extract', async (req, res) => {
    const customerId = parseInt(req.params.id);
    const state = await loadState();
    const customer = state.customers.find(c => c._editId === customerId);

    if (!customer) return res.status(404).json({ ok: false, error: 'Customer not found' });

    const rawText = req.body && req.body.raw_text ? String(req.body.raw_text).trim() : '';
    if (!rawText) return res.status(400).json({ ok: false, error: 'raw_text is required' });

    const apiKey = configuredApiKey();
    if (!apiKey) return res.status(500).json({ ok: false, error: 'AI_API_KEY environment variable not set' });

    try {
        const preview = await processCustomer(rawText, apiKey);
        preview._editId = customerId;
        res.json({ ok: true, preview });
    } catch (err) {
        logger.error('Re-extract failed', { error: err.message });
        res.status(500).json({ ok: false, error: `AI re-extraction failed — please retry: ${err.message}` });
    }
});

// POST /api/customer/:id/reject — move to 'rejected' (kept as audit, excluded
// from export). Port of the old system's PATCH /:id/reject.
app.post('/api/customer/:id/reject', async (req, res) => {
    const customerId = parseInt(req.params.id);
    const state = await loadState();
    const idx = state.customers.findIndex(c => c._editId === customerId);

    if (idx === -1) return res.status(404).json({ ok: false, error: 'Customer not found' });

    const customer = state.customers[idx];
    customer.status = 'rejected';
    customer.rejected_reason = (req.body && req.body.reason) ? String(req.body.reason).trim() : 'مرفوض يدويًا';

    const saveResult = await saveState(state);
    if (!saveResult.success) {
        return res.status(500).json({ ok: false, error: 'Failed to save changes' });
    }

    logger.info('Customer rejected', { id: customerId });
    res.json({ ok: true, customer: state.customers[idx] });
});

// DELETE /api/customer/:id - Delete a single customer
app.delete('/api/customer/:id', async (req, res) => {
    const customerId = parseInt(req.params.id);
    
    if (isNaN(customerId)) {
        return res.status(400).json({ ok: false, error: 'Invalid customer ID' });
    }
    
    const state = await loadState();
    const customerIndex = state.customers.findIndex(c => c._editId === customerId);
    
    if (customerIndex === -1) {
        return res.status(404).json({ ok: false, error: 'Customer not found' });
    }
    
    state.customers.splice(customerIndex, 1);
    const saveResult = await saveState(state);
    
    if (!saveResult.success) {
        return res.status(500).json({ ok: false, error: 'Failed to delete customer' });
    }
    
    logger.info('Customer deleted', { id: customerId });
    res.json({ ok: true, message: 'Customer deleted successfully' });
});

// POST /api/customers/delete - Bulk delete customers
app.post('/api/customers/delete', async (req, res) => {
    const { ids } = req.body;
    
    if (!Array.isArray(ids) || ids.length === 0) {
        return res.status(400).json({ ok: false, error: 'No customer IDs provided' });
    }
    
    const state = await loadState();
    const idSet = new Set(ids.map(id => parseInt(id)));
    
    // Filter out deleted customers
    state.customers = state.customers.filter(c => !idSet.has(c._editId));
    
    const saveResult = await saveState(state);
    
    if (!saveResult.success) {
        return res.status(500).json({ ok: false, error: 'Failed to delete customers' });
    }
    
    logger.info('Bulk delete', { count: ids.length });
    res.json({ ok: true, message: `Deleted ${ids.length} customer(s)` });
});

// POST /api/customers/delete-all - Delete all customers
app.post('/api/customers/delete-all', async (req, res) => {
    const state = { customers: [], savedAt: new Date().toISOString() };
    const saveResult = await saveState(state);
    
    if (!saveResult.success) {
        return res.status(500).json({ ok: false, error: 'Failed to clear all data' });
    }
    
    logger.info('All customers deleted');
    res.json({ ok: true, message: 'All customers deleted' });
});

// ── Geo reference endpoints (for the edit drop-downs) ─────────────
// Port of the old system's /api/geo/governorates + /api/geo/cities —
// backs the edit form's canonical governorate/city selects.
app.get('/api/geo/governorates', async (req, res) => {
    const ref = await getGovernorates();
    if (!ref.ok) return res.status(500).json({ ok: false, error: ref.error });
    res.json({ ok: true, governorates: ref.result.governorates });
});

app.get('/api/geo/cities', async (req, res) => {
    const gov = typeof req.query.governorate === 'string' ? req.query.governorate.trim() : '';
    if (!gov) return res.status(400).json({ ok: false, error: 'governorate query param is required' });
    const ref = await getCitiesForGovernorate(gov);
    if (!ref.ok) return res.status(500).json({ ok: false, error: ref.error });
    if (ref.result.error) return res.status(404).json({ ok: false, error: ref.result.error });
    res.json({ ok: true, governorate: ref.result.governorate, cities: ref.result.cities });
});

// Book catalog for the edit modal's add-from-list picker (book → stage → qty → price).
app.get('/api/books/catalog', async (req, res) => {
    const ref = await getBookCatalog();
    if (!ref.ok) return res.status(500).json({ ok: false, error: ref.error });
    res.json({ ok: true, books: ref.result });
});

// Get available models endpoint
app.get('/api/models', (req, res) => {
    res.json({
        address_engine: {
            status: 'ready',
            tests: '82 passed'
        },
        book_engine: {
            status: 'ready',
            tests: '33 passed'
        },
        ai_model: configuredApiKey() ? 'configured' : 'not configured'
    });
});

// Start server
async function start() {
    try {
        await initDatabase();
    } catch (err) {
        logger.error('Database init failed', { error: err.message });
        console.error('[db] Failed to connect to PostgreSQL:', err.message);
        process.exit(1);
    }

    app.listen(PORT, () => {
        logger.info('Server started', { port: PORT });
        console.log(`Server running on http://localhost:${PORT}`);
        console.log(`API endpoints:`);
        console.log(`  GET    /health`);
        console.log(`  GET    /api/metrics`);
        console.log(`  GET    /api/logs`);
        console.log(`  POST   /api/process`);
        console.log(`  POST   /api/export`);
        console.log(`  GET    /api/state`);
        console.log(`  POST   /api/save`);
        console.log(`  DELETE /api/state`);
        console.log(`  GET    /api/models`);
    });
}

start();

function gracefulShutdown(signal) {
    logger.info(`${signal} received — draining database pool`);
    getPool().end()
        .catch(err => console.error('pool.end failed:', err.message))
        .finally(() => process.exit(0));
}
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

module.exports = app;

/**
 * Assembly Layer - Task 16 (Optimized with Batching + Concurrency)
 * 
 * Combines results into final customer records using:
 * 1. Single Python invocation per customer (batch engine)
 * 2. Bounded concurrency pool for customer processing
 * 3. Internal failure_type logging (technical vs low_confidence)
 * 4. openrouter/free fallback on 429
 */

const { spawn } = require('child_process');
const path = require('path');
const { extractCustomerData } = require('./ai_extractor');
const { processPhones } = require('./phone_validator');

const PYTHON_PATH = process.env.PYTHON_PATH || 'python';
const ENGINE_DIR = path.join(__dirname, '..', 'engine');
const BATCH_ENGINE = path.join(ENGINE_DIR, 'customer_batch_engine.py');

/**
 * Process a single customer using the batch Python engine.
 * One Python process per customer — does address + all books + AI suggestions internally.
 * 
 * @param {string} rawText - Raw customer order text
 * @param {string} apiKey - OpenRouter API key
 * @returns {Promise<object>} Final processed customer record
 */
async function processCustomer(rawText, apiKey) {
    const startTime = Date.now();
    
    // Step 1: AI Extraction
    const extraction = await extractCustomerData(rawText, apiKey);
    if (!extraction.ok) {
        return {
            name: null, phone1: '', phone2: null, address: null, books: [],
            discount_note: null, year_edition: null, remarks: null, raw_text: rawText,
            status: 'needs_review',
            review_reasons: [`AI extraction failed: ${extraction.error}`],
            _meta: { timing_ms: Date.now() - startTime, extraction_error: extraction.error }
        };
    }

    const extracted = extraction.data;

    // Step 2: Phone Validation
    const phones = processPhones(extracted.phones);
    
    // Step 3 & 4: Batch matching via single Python process
    const batchInput = {
        address_raw: extracted.address_raw || '',
        items: extracted.items || [],
        grade_hint: extracted.year_edition || '',
        // Pass all_books for AI suggestions (engine builds lookup internally)
    };

    const batchResult = await runBatchEngine(batchInput, apiKey);
    
    if (!batchResult.ok) {
        return {
            name: extracted.name,
            phone1: phones.phone1,
            phone2: phones.phone2,
            address: null,
            books: [],
            discount_note: extracted.discount_note,
            year_edition: extracted.year_edition,
            remarks: null,
            raw_text: rawText,
            status: 'needs_review',
            review_reasons: [`Batch processing failed: ${batchResult.error}`],
            _meta: { timing_ms: Date.now() - startTime, batch_error: batchResult.error }
        };
    }

    // Assemble result
    const result = {
        name: extracted.name,
        phone1: phones.phone1,
        phone2: phones.phone2,
        address: batchResult.result.address,
        books: batchResult.result.books,
        discount_note: extracted.discount_note,
        year_edition: extracted.year_edition,
        remarks: null,
        raw_text: rawText,
        status: 'confirmed',
        review_reasons: [],
        _meta: {
            timing_ms: Date.now() - startTime,
            ai_stats: batchResult.result.ai_stats,
            batch_timing: batchResult.result.timing
        }
    };

    // Collect review reasons
    if (result.address && result.address.needs_review) {
        result.review_reasons.push(`Address: ${result.address.review_reason}`);
    }
    const reviewBooks = result.books.filter(b => b.needs_review);
    if (reviewBooks.length > 0) {
        result.review_reasons.push(`${reviewBooks.length} book(s) need review`);
    }
    
    // Add phone notes
    if (phones.notes.length > 0) {
        result.review_reasons.push(...phones.notes);
    }

    // Add book review reasons
    for (const book of reviewBooks) {
        if (book.review_reason) {
            result.review_reasons.push(`Book "${book.book_name}": ${book.review_reason}`);
        }
    }

    if (result.review_reasons.length > 0) {
        result.status = 'needs_review';
    }

    // Validate: empty customers (no name, no phone, no books) should NOT be confirmed
    const hasName = !!(result.name && result.name.trim());
    const hasPhone = !!(result.phone1 && result.phone1.trim());
    const hasBooks = result.books.length > 0;
    if (!hasName && !hasPhone && !hasBooks) {
        result.status = 'needs_review';
        if (!result.review_reasons.includes('Empty customer record')) {
            result.review_reasons.push('Empty customer record - missing name, phone, and books');
        }
    }

    return result;
}

/**
 * Run the batch Python engine for one customer.
 * Passes input as JSON via stdin, reads JSON output.
 */
function runBatchEngine(customerData, apiKey) {
    return new Promise((resolve) => {
        const env = {
            ...process.env,
            OPENROUTER_API_KEY: apiKey,
            AI_API_KEY: apiKey,
            PYTHONIOENCODING: 'utf-8',
            PYTHONUNBUFFERED: '1'
        };

        const pythonProcess = spawn(PYTHON_PATH, [BATCH_ENGINE], {
            cwd: path.join(__dirname, '..'),
            env,
            encoding: 'utf-8'
        });

        // Send input
        pythonProcess.stdin.write(JSON.stringify(customerData));
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
            // Log stderr for debugging (AI suggestion logs go here)
            if (stderr.trim()) {
                console.log(`[Batch stderr]:`, stderr.trim().replace(/\n/g, ' | '));
            }
            if (code !== 0) {
                resolve({ ok: false, error: `Python exited ${code}: ${stderr.trim()}` });
                return;
            }
            try {
                const result = JSON.parse(stdout.trim());
                if (result.error) {
                    resolve({ ok: false, error: result.error });
                } else {
                    resolve({ ok: true, result });
                }
            } catch (e) {
                resolve({ ok: false, error: `Parse error: ${e.message}` });
            }
        });
    });
}

/**
 * Process multiple customers with bounded concurrency.
 * Uses a proper async pool to ensure true parallelism.
 *
 * @param {string[]} customerTexts - Array of raw customer texts
 * @param {string} apiKey - OpenRouter API key
 * @param {number} concurrency - Max concurrent customers (default: 5)
 * @returns {Promise<{results: object[], stats: object}>}
 */
async function processCustomers(customerTexts, apiKey, concurrency = 5) {
    const results = new Array(customerTexts.length);
    const stats = {
        total: customerTexts.length,
        total_time_ms: 0,
        per_customer_ms: [],
        total_ai_calls: 0,
        total_tech_failures: 0,
        total_low_confidence: 0,
        success: 0,
        needs_review: 0
    };

    // ── Proper async concurrency pool ────────────────────────────────────────
    // Tracks active jobs and queues remaining ones.
    let active = 0;
    let index = 0;

    const next = () => {
        while (active < concurrency && index < customerTexts.length) {
            const i = index++;
            active++;
            runCustomer(i)
                .finally(() => { active--; next(); });
        }
    };

    const runCustomer = async (i) => {
        const startMs = Date.now();
        const ts = (label) => {
            const ms = Date.now() - startMs;
            console.log(`  [C${i + 1} +${ms}ms] ${label}`);
        };
        ts('START');

        const result = await processCustomer(customerTexts[i], apiKey);

        const elapsed = Date.now() - startMs;
        ts('END');

        stats.per_customer_ms.push(elapsed);
        if (result._meta?.ai_stats) {
            stats.total_ai_calls += result._meta.ai_stats.total_calls || 0;
            stats.total_tech_failures += result._meta.ai_stats.technical_failures || 0;
            stats.total_low_confidence += result._meta.ai_stats.low_confidence || 0;
        }
        if (result.status === 'confirmed') stats.success++;
        else stats.needs_review++;

        // Assign unique edit ID
        result._editId = Date.now() + i;

        results[i] = result;
    };

    const startTime = Date.now();
    next(); // kick off the pool
    // Wait until all customers are done
    while (active > 0 || index < customerTexts.length) {
        await new Promise(r => setTimeout(r, 50));
    }

    stats.total_time_ms = Date.now() - startTime;
    stats.avg_time_ms = Math.round(stats.total_time_ms / customerTexts.length);
    stats.min_time_ms = Math.min(...stats.per_customer_ms);
    stats.max_time_ms = Math.max(...stats.per_customer_ms);
    stats.sum_individual_ms = stats.per_customer_ms.reduce((a, b) => a + b, 0);
    stats.parallelism_factor = (stats.sum_individual_ms / stats.total_time_ms).toFixed(2);

    console.log('\n=== Task 16 Performance Summary ===');
    console.log(`Total customers: ${stats.total}`);
    console.log(`Wall-clock time: ${stats.total_time_ms}ms`);
    console.log(`Sum of individual times: ${stats.sum_individual_ms}ms`);
    console.log(`Parallelism factor: ${stats.parallelism_factor}x`);
    console.log(`Avg per customer: ${stats.avg_time_ms}ms`);
    console.log(`Min: ${stats.min_time_ms}ms | Max: ${stats.max_time_ms}ms`);
    console.log(`AI calls made: ${stats.total_ai_calls}`);
    console.log(`Technical failures: ${stats.total_tech_failures} (${stats.total_ai_calls > 0 ? (stats.total_tech_failures/stats.total_ai_calls*100).toFixed(1) : 0}%)`);
    console.log(`Low confidence: ${stats.total_low_confidence}`);
    console.log(`Confirmed: ${stats.success} | Needs review: ${stats.needs_review}`);
    console.log('===================================\n');

    return { results, stats };
}

/**
 * Get summary statistics.
 */
function getSummary(results) {
    const total = results.length;
    const confirmed = results.filter(c => c.status === 'confirmed').length;
    const needsReview = results.filter(c => c.status === 'needs_review').length;
    const totalBooks = results.reduce((sum, c) => sum + c.books.length, 0);
    const reviewBooks = results.reduce((sum, c) => sum + c.books.filter(b => b.needs_review).length, 0);
    
    return { total_customers: total, confirmed, needs_review: needsReview,
             total_books: totalBooks, review_books: reviewBooks };
}

module.exports = { processCustomer, processCustomers, getSummary, runBatchEngine };
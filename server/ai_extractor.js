/**
 * AI Extractor - Task 4
 * 
 * Extracts structured data from raw customer order text using Agnes 2.5 Flash.
 * 
 * Environment variable required: OPENROUTER_API_KEY
 * Optional: AI_API_URL (endpoint, defaults to OpenRouter),
 *           AI_MODEL_ID (defaults to agnes-2.5-flash)
 * 
 * Output JSON schema:
 * {
 *   "name": string | null,           // Customer name
 *   "phones": string[],              // Array of phone numbers
 *   "address_raw": string | null,    // Raw address text (unmodified)
 *   "items": string[],               // Array of book/order line items
 *   "discount_note": string | null,  // Any discount mention
 *   "year_edition": string | null    // Any year/edition mention
 * }
 */

const OPENROUTER_API_URL = process.env.AI_API_URL || 'https://openrouter.ai/api/v1/chat/completions';
const MODEL_ID = process.env.AI_MODEL_ID || 'agnes-2.5-flash';
const FREE_MODEL_ID = process.env.AI_FREE_MODEL || 'openrouter/free';

// Retry configuration
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;  // 1 second between retries

const PROMPT_TEMPLATE = `أنت مساعد متخصص في استخراج بيانات طلبات الكتب من النصوص العربية.
النصوص من عملاء حقيقيين وقد تحتوي أخطاء إملائية (غالباً حروف ناقصة/زائدة/مبدلة) في اسم العميل أو الكتاب أو العنوان،
وكثيراً ما يكتب العملاء اسم الكتاب بنقل حرفي عربي (مثلاً: pioneer تُكتب "بيونير" أو "بايونير"، power up تُكتب "باور اب").
يجب عليك فهم ذلك واستخراج البيانات الصحيحة مع تصحيح أسماء الكتب إلى الاسم الإنجليزي الرسمي.

استخرج المعلومات التالية من نص الطلب واحرص على الدقة:

المدخل: {{INPUT_TEXT}}

أرجع JSON فقط بالصيغة التالية (بدون أي شرح أو نصوص أخرى):
{
  "name": "اسم العميل أو null إذا غير مذكور",
  "phones": ["رقم1", "رقم2"],
  "address_raw": "نص العنوان كما هو تماماً بدون أي تعديل",
  "items": ["سطر1", "سطر2", ...],
  "discount_note": "أي ذكر للخصم أو null",
  "year_edition": "أي سنة أو إصدار مذكور أو null"
}

قائمة أسماء الكتب الرسمية (اختر منها دائماً الاسم الصحيح لكل كتاب):
Aim High, Challenge, Close Up, New Close Up, Focus, Full Blast (Second Edition / Special), Macmillan, Power Up, Superland, Top Score, Team Together, Upstream, New Upstream, English World, Everybody Up, Family and Friends, Our World, Wonderful World (Second Edition), Oxford Discover, Our Discovery Island, Pioneer, World Watchers

ملاحظات مهمة:
- اكتب phones كـ array من السلاسل النصية
- اكتب items كـ array من الأسطر المنفصلة (كل كتاب/كمية في سطر)
- صور أسماء الكتب المكتوبة بالعربية أو بأخطاء إملائية إلى الاسم الإنجليزي الرسمي أعلاه.
  مثال: "بيونير B1" أو "بايونير B1" → "Pioneer B1"، "باور اب" → "Power Up"، "فول بلاست سبشل" → "Full Blast Special"
- احتفظ برقم المرحلة/الصف (B1، B2، أولى إعدادي... إلخ) كما هو مع الاسم الإنجليزي
- صوب الأخطاء الإملائية البسيطة في اسم العميل مع الحفاظ عليه قريباً من الأصل
- لا تغير أي كلمة في address_raw (ولا تصححها — أخطاء العنوان تُعالج لاحقاً)
- إذا لم يوجد معلومات لحقل معين، استخدم null
- أرجع JSON فقط بدون أي نص إضافي`;

/**
 * Extract structured data from raw customer text using Agnes 2.5 Flash.
 * 
 * @param {string} customerText - Raw order text for one customer
 * @param {string} apiKey - AI provider API key
 * @returns {Promise<{ok: boolean, data?: object, error?: string}>}
 */
async function extractCustomerData(customerText, apiKey) {
    if (!apiKey) {
        return { ok: false, error: 'OPENROUTER_API_KEY environment variable not set' };
    }

    if (!customerText || typeof customerText !== 'string' || customerText.trim().length === 0) {
        return { ok: false, error: 'Empty customer text' };
    }

    // Primary model with retries, then a single free-model attempt on failure.
    const primary = await attemptExtraction(customerText, apiKey, MODEL_ID);
    if (primary.ok || !primary.soft) {
        return primary;
    }

    const fallback = await attemptExtraction(customerText, apiKey, FREE_MODEL_ID);
    if (fallback.ok) {
        return fallback;
    }
    return { ok: false, error: `${primary.error} (free-model fallback failed: ${fallback.error})` };
}

/**
 * Single extraction attempt with a given model (retries within the model).
 * Returns {ok, data?, error?, soft} — soft=true when a retry on the free
 * model is worthwhile (empty/prose response), soft=false on hard client errors.
 */
async function attemptExtraction(customerText, apiKey, model) {
    const prompt = PROMPT_TEMPLATE.replace('{{INPUT_TEXT}}', customerText);

    // Retry loop
    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
            const response = await fetch(OPENROUTER_API_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${apiKey}`,
                    'HTTP-Referer': 'http://localhost:3000',  // Required by OpenRouter
                    'X-Title': 'Order Processor'
                },
                body: JSON.stringify({
                    model,
                    messages: [
                        { role: 'system', content: 'أنت مساعد متخصص في استخراج بيانات الطلبات.' },
                        { role: 'user', content: prompt }
                    ],
                    max_tokens: 1000,
                    temperature: 0.1  // Low temperature for consistent extraction
                })
            });

            if (!response.ok) {
                const errorBody = await response.text();

                // 429/408 are transient (rate limit / timeout) — retry with growing backoff
                if (response.status === 429 || response.status === 408) {
                    if (attempt < MAX_RETRIES) {
                        await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt * 2));
                        continue;
                    }
                    return {
                        ok: false,
                        soft: true,
                        error: `API Error ${response.status}: ${errorBody}`
                    };
                }

                // Don't retry on other 4xx errors (client errors)
                if (response.status >= 400 && response.status < 500) {
                    return {
                        ok: false,
                        soft: false,
                        error: `API Error ${response.status}: ${errorBody}`
                    };
                }

                // Retry on 5xx errors (server errors)
                if (attempt < MAX_RETRIES) {
                    await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
                    continue;
                }

                return {
                    ok: false,
                    soft: true,
                    error: `API Error ${response.status}: ${errorBody}`
                };
            }

            const json = await response.json();
            const extractedText = json.choices?.[0]?.message?.content?.trim();

            if (!extractedText) {
                // Retry on empty response
                if (attempt < MAX_RETRIES) {
                    await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
                    continue;
                }
                return { ok: false, soft: true, error: `Empty response from API after ${attempt} attempts` };
            }

            // Parse the JSON response
            try {
                // Try to extract JSON from the response (in case there's extra text)
                const jsonMatch = extractedText.match(/\{[\s\S]*\}/);
                if (!jsonMatch) {
                    // Retry on missing JSON — the model sometimes returns prose
                    if (attempt < MAX_RETRIES) {
                        await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
                        continue;
                    }
                    return { ok: false, soft: true, error: 'No JSON found in response', raw: extractedText };
                }

                const data = JSON.parse(jsonMatch[0]);
                return { ok: true, data };
            } catch (parseError) {
                // Retry on parse error
                if (attempt < MAX_RETRIES) {
                    await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
                    continue;
                }
                return {
                    ok: false,
                    soft: true,
                    error: `JSON parse error: ${parseError.message}`,
                    raw: extractedText
                };
            }

        } catch (error) {
            // Network error - retry
            if (attempt < MAX_RETRIES) {
                await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
                continue;
            }
            return {
                ok: false,
                soft: true,
                error: `Request failed after ${MAX_RETRIES} attempts: ${error.message}`
            };
        }
    }

    return { ok: false, soft: true, error: 'Unexpected: retry loop completed without returning' };
}

/**
 * Validate extracted data structure.
 * 
 * @param {object} data - Extracted data from AI
 * @returns {boolean}
 */
function validateExtractedData(data) {
    if (!data || typeof data !== 'object') {
        return false;
    }

    // name should be string or null
    if (data.name !== null && typeof data.name !== 'string') {
        return false;
    }

    // phones should be array of strings (or null)
    if (data.phones !== null && data.phones !== undefined && !Array.isArray(data.phones)) {
        return false;
    }
    if (Array.isArray(data.phones) && !data.phones.every(p => typeof p === 'string')) {
        return false;
    }

    // address_raw should be string or null
    if (data.address_raw !== null && typeof data.address_raw !== 'string') {
        return false;
    }

    // items should be array of strings
    if (!Array.isArray(data.items)) {
        return false;
    }
    if (!data.items.every(i => typeof i === 'string')) {
        return false;
    }

    // discount_note and year_edition should be string or null
    if (data.discount_note !== null && typeof data.discount_note !== 'string') {
        return false;
    }
    if (data.year_edition !== null && typeof data.year_edition !== 'string') {
        return false;
    }

    return true;
}

module.exports = { extractCustomerData, validateExtractedData, OPENROUTER_API_URL, MODEL_ID };

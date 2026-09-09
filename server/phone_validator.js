/**
 * Phone Validator & Normalizer - Task 5
 * 
 * Validates and normalizes Egyptian phone numbers.
 * 
 * Rules:
 * - Arabic-Indic digits (٠-٩) converted to Western (0-9)
 * - Valid Egyptian mobile: starts with 010/011/012/015, length = 11
 * - Valid Egyptian landline: starts with 03, length = 8-10
 * - If no valid number found → empty string + note
 * - If multiple numbers found → phone1, phone2 fields
 */

/**
 * Convert Arabic-Indic digits to Western digits.
 * 
 * @param {string} text - Input text that may contain Arabic numerals
 * @returns {string} Text with Western digits
 */
function convertArabicDigits(text) {
    if (!text || typeof text !== 'string') return text;
    return text.replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d).toString());
}

/**
 * Extract phone numbers from text.
 * 
 * @param {string} text - Input text
 * @returns {string[]} Array of extracted phone number strings (Western digits)
 */
function extractPhoneNumbers(text) {
    if (!text || typeof text !== 'string') return [];
    
    // First convert Arabic digits to Western
    const normalized = convertArabicDigits(text);
    const phones = [];
    
    // Pattern: Egyptian mobile numbers (010, 011, 012, 015) + 8 digits
    const mobilePattern = /\b(010|011|012|015)\d{8}\b/g;
    // Pattern: Egyptian landline (03) + 7-9 digits
    const landlinePattern = /\b(03)\d{7,9}\b/g;
    
    let match;
    while ((match = mobilePattern.exec(normalized)) !== null) {
        phones.push(match[0]);
    }
    while ((match = landlinePattern.exec(normalized)) !== null) {
        phones.push(match[0]);
    }
    
    return [...new Set(phones)]; // Remove duplicates
}

/**
 * Validate a single Egyptian phone number.
 * 
 * @param {string} phone - Phone number to validate
 * @returns {{ valid: boolean, type: 'mobile'|'landline'|'unknown', note?: string }}
 */
function validatePhone(phone) {
    if (!phone) {
        return { valid: false, type: 'unknown', note: 'Empty phone number' };
    }
    
    const clean = phone.replace(/\D/g, ''); // Remove non-digits
    
    if (clean.length === 11 && /^(010|011|012|015)/.test(clean)) {
        return { valid: true, type: 'mobile' };
    }
    
    if (clean.length >= 8 && clean.length <= 10 && /^03/.test(clean)) {
        return { valid: true, type: 'landline' };
    }
    
    return { 
        valid: false, 
        type: 'unknown', 
        note: `Invalid Egyptian number: ${phone} (length: ${clean.length})`
    };
}

/**
 * Process phone numbers from extracted data.
 * 
 * @param {string|null} rawPhones - Raw phones array from AI extraction
 * @returns {{ phone1: string, phone2: string|null, notes: string[] }}
 */
function processPhones(rawPhones) {
    const result = {
        phone1: '',
        phone2: null,
        notes: []
    };
    
    if (!rawPhones || (Array.isArray(rawPhones) && rawPhones.length === 0)) {
        result.notes.push('No phone number mentioned');
        return result;
    }
    
    // Flatten and clean
    const allNums = rawPhones.flat().map(p => convertArabicDigits(String(p).trim())).filter(Boolean);
    
    if (allNums.length === 0) {
        result.notes.push('No valid phone number found');
        return result;
    }
    
    // Validate and assign
    const validated = allNums.map(p => validatePhone(p));
    const validPhones = validated.filter(v => v.valid);
    const invalidNotes = validated.filter(v => !v.valid).map(v => v.note).filter(Boolean);
    
    if (validPhones.length > 0) {
        result.phone1 = allNums[0];
        if (validPhones.length > 1) {
            result.phone2 = allNums[1];
        }
    }
    
    if (invalidNotes.length > 0) {
        result.notes.push(...invalidNotes);
    }
    
    if (validPhones.length === 0) {
        result.notes.push('Phone numbers found but none match Egyptian format');
    }
    
    return result;
}

module.exports = { convertArabicDigits, extractPhoneNumbers, validatePhone, processPhones };

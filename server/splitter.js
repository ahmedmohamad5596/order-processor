/**
 * Customer Boundary Splitter (Task 3)
 * 
 * Splits raw order text into individual customer blocks
 * based on separators: "||||||||" (primary) or "|" (fallback).
 * 
 * Rules:
 * - If |||||||| separator exists → use it
 * - Else if | separator exists → use it
 * - If no separator → single customer (entire text)
 * - Leading/trailing separators with empty content → ignored
 * - Empty blocks between consecutive separators → ignored
 */

// Try multiple separator patterns (longer separators first)
const SEPARATORS = ['||||||||', '===================', '================', '==', '|'];

/**
 * Find the best separator for the given text
 */
function findSeparator(text) {
    for (const sep of SEPARATORS) {
        if (text.includes(sep)) {
            return sep;
        }
    }
    return null;
}

/**
 * Split raw order text into customer blocks.
 * 
 * @param {string} rawText - The raw order text from the user
 * @returns {string[]} Array of customer text blocks
 */
function splitCustomers(rawText) {
    if (!rawText || typeof rawText !== 'string') {
        return [];
    }

    const text = rawText.trim();
    
    // Find separator
    const separator = findSeparator(text);
    
    // No separator found → single customer
    if (!separator) {
        if (text.length > 0) {
            return [text];
        }
        return [];
    }

    // Split on separator
    const parts = text.split(separator);
    
    // Filter out empty blocks (leading/trailing/consecutive separators)
    const customers = parts
        .map(p => p.trim())
        .filter(p => p.length > 0);

    return customers;
}

/**
 * Get metadata about the split (useful for logging/debugging).
 *
 * @param {string} rawText - The raw order text
 * @returns {{ count: number, separatorsFound: number, emptyBlocks: number }}
 */
function splitMetadata(rawText) {
    if (!rawText || typeof rawText !== 'string') {
        return { count: 0, separatorsFound: 0, emptyBlocks: 0 };
    }

    const text = rawText.trim();
    // Count occurrences of primary separator (|||||||| or ===================)
    const separatorCount = (text.match(/\|{8,}/g) || text.match(/={8,}/g) || []).length;

    let emptyBlocks = 0;
    if (separatorCount > 0) {
        const parts = text.split(/\|{8,}/);
        emptyBlocks = parts.filter(p => p.trim().length === 0).length;
    }
    
    // Also check for ==== separator
    if (separatorCount === 0 && /={8,}/.test(text)) {
        const parts = text.split(/={8,}/);
        emptyBlocks = parts.filter(p => p.trim().length === 0).length;
    }

    const customers = splitCustomers(rawText);

    return {
        count: customers.length,
        separatorsFound: separatorCount,
        emptyBlocks
    };
}

module.exports = { splitCustomers, splitMetadata, SEPARATORS };

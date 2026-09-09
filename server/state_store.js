/**
 * State Store - Task 18
 * 
 * JSON file-based persistence for processed customer data.
 * Auto-saves after each successful processing run.
 * Auto-loads on server start and API requests.
 */

const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, '..', 'state.json');

/**
 * Load current state from file.
 * @returns {object} State object with customers array and metadata
 */
function loadState() {
    try {
        if (fs.existsSync(STATE_FILE)) {
            const data = fs.readFileSync(STATE_FILE, 'utf8');
            const state = JSON.parse(data);
            return state;
        }
    } catch (error) {
        console.error('[StateStore] Error loading state:', error.message);
    }
    return { customers: [], savedAt: null };
}

/**
 * Save state to file.
 * @param {object} state - State object to save
 * @returns {object} Save result with success status
 */
function saveState(state) {
    try {
        const data = JSON.stringify(state, null, 2);
        fs.writeFileSync(STATE_FILE, data, 'utf8');
        return { success: true, savedAt: new Date().toISOString() };
    } catch (error) {
        console.error('[StateStore] Error saving state:', error.message);
        return { success: false, error: error.message };
    }
}

/**
 * Delete state file.
 * @returns {boolean} True if deleted or didn't exist
 */
function clearState() {
    try {
        if (fs.existsSync(STATE_FILE)) {
            fs.unlinkSync(STATE_FILE);
        }
        return true;
    } catch (error) {
        console.error('[StateStore] Error clearing state:', error.message);
        return false;
    }
}

/**
 * Get initial state for frontend.
 * @returns {object} State with loaded data
 */
function getInitial() {
    return loadState();
}

module.exports = { loadState, saveState, clearState, getInitial };

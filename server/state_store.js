const { Pool } = require('pg');

const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false },
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000
});

let initialized = false;

async function initDatabase() {
    if (initialized) return;
    await pool.query(`
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY DEFAULT 'main',
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    `);
    initialized = true;
    console.log('[StateStore] PostgreSQL table ready');
}

async function loadState() {
    try {
        const { rows } = await pool.query(
            "SELECT data FROM app_state WHERE key = 'main'"
        );
        if (rows.length > 0 && rows[0].data) {
            return rows[0].data;
        }
    } catch (error) {
        console.error('[StateStore] Error loading state:', error.message);
    }
    return { customers: [], savedAt: null };
}

async function saveState(state) {
    try {
        await pool.query(
            `INSERT INTO app_state (key, data, updated_at)
             VALUES ('main', $1, NOW())
             ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = NOW()`,
            [state, state]
        );
        return { success: true, savedAt: new Date().toISOString() };
    } catch (error) {
        console.error('[StateStore] Error saving state:', error.message);
        return { success: false, error: error.message };
    }
}

async function clearState() {
    try {
        await pool.query("DELETE FROM app_state WHERE key = 'main'");
        return true;
    } catch (error) {
        console.error('[StateStore] Error clearing state:', error.message);
        return false;
    }
}

function getInitial() {
    return { customers: [], savedAt: null };
}

function getPool() {
    return pool;
}

module.exports = { initDatabase, loadState, saveState, clearState, getInitial, getPool };

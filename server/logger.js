/**
 * Structured Logger - Task 19
 * 
 * Server-side JSON logging for monitoring and debugging.
 * Logs to both console (stderr) and file (logs/server.log).
 */
const fs = require('fs');
const path = require('path');

const LOG_DIR = path.join(__dirname, '..', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'server.log');

// Ensure log directory exists
if (!fs.existsSync(LOG_DIR)) {
    fs.mkdirSync(LOG_DIR, { recursive: true });
}

/**
 * Log levels
 */
const LEVELS = {
    DEBUG: 'DEBUG',
    INFO: 'INFO',
    WARNING: 'WARNING',
    ERROR: 'ERROR'
};

/**
 * Generate a structured log entry
 */
function createLogEntry(level, message, metadata = {}) {
    return {
        timestamp: new Date().toISOString(),
        level,
        message,
        ...metadata
    };
}

/**
 * Write log entry to file (async, non-blocking)
 */
function writeToFile(entry) {
    try {
        const logLine = JSON.stringify(entry) + '\n';
        fs.appendFileSync(LOG_FILE, logLine, 'utf8');
    } catch (err) {
        console.error('[Logger] Failed to write to file:', err.message);
    }
}

/**
 * Main logger function
 */
function log(level, message, metadata = {}) {
    const entry = createLogEntry(level, message, metadata);
    
    // Console output (color-coded by level)
    const colorCodes = {
        [LEVELS.DEBUG]: '\x1b[36m',    // Cyan
        [LEVELS.INFO]: '\x1b[32m',     // Green
        [LEVELS.WARNING]: '\x1b[33m',  // Yellow
        [LEVELS.ERROR]: '\x1b[31m'     // Red
    };
    const reset = '\x1b[0m';
    
    const consoleMsg = `${colorCodes[level] || ''}[${entry.timestamp}] ${level}: ${message} ${reset}`;
    console.error(consoleMsg);
    
    // File output
    writeToFile(entry);
    
    return entry;
}

/**
 * Convenience methods
 */
const logger = {
    debug: (message, metadata) => log(LEVELS.DEBUG, message, metadata),
    info: (message, metadata) => log(LEVELS.INFO, message, metadata),
    warn: (message, metadata) => log(LEVELS.WARNING, message, metadata),
    error: (message, metadata) => log(LEVELS.ERROR, message, metadata),
    
    // Specialized logging
    logRequest: (req, durationMs) => {
        log(LEVELS.INFO, 'HTTP Request', {
            method: req.method,
            path: req.path,
            statusCode: req.statusCode || 200,
            duration_ms: durationMs,
            ip: req.ip || req.connection?.remoteAddress
        });
    },
    
    logProcessing: (customerCount, durationMs, aiCalls, techFailures) => {
        log(LEVELS.INFO, 'Batch Processing Complete', {
            customers: customerCount,
            duration_ms: durationMs,
            ai_calls: aiCalls,
            tech_failures: techFailures
        });
    },
    
    logError: (error, context = {}) => {
        log(LEVELS.ERROR, error.message || 'Unknown error', {
            stack: error.stack,
            ...context
        });
    }
};

module.exports = { logger, LEVELS };

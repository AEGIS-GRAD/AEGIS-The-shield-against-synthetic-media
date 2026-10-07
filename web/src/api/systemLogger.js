/**
 * System Diagnostic Logger for AEGIS Workstation
 * Captures real-time logs, backend requests, detector failures, and errors.
 */

class SystemLogger {
  constructor() {
    this.logs = [];
    this.listeners = new Set();
  }

  log(level, component, message, details = null) {
    const entry = {
      id: `log-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      timestamp: new Date().toLocaleTimeString() + "." + String(new Date().getMilliseconds()).padStart(3, "0"),
      iso: new Date().toISOString(),
      level: level.toUpperCase(), // 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS'
      component,
      message,
      details: details ? (typeof details === "object" ? details : { info: String(details) }) : null,
    };
    
    // Store up to 300 logs
    this.logs = [entry, ...this.logs.slice(0, 299)];
    this.notify();

    // Also output to browser developer console for dual visibility
    const consoleMsg = `[AEGIS ${entry.level}] [${component}] ${message}`;
    if (level === "error") {
      console.error(consoleMsg, details || "");
    } else if (level === "warn") {
      console.warn(consoleMsg, details || "");
    } else {
      console.log(consoleMsg, details || "");
    }
  }

  info(component, message, details) {
    this.log("INFO", component, message, details);
  }

  warn(component, message, details) {
    this.log("WARN", component, message, details);
  }

  error(component, message, details) {
    this.log("ERROR", component, message, details);
  }

  success(component, message, details) {
    this.log("SUCCESS", component, message, details);
  }

  getLogs() {
    return this.logs;
  }

  getErrorCount() {
    return this.logs.filter((l) => l.level === "ERROR").length;
  }

  clear() {
    this.logs = [];
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    this.listeners.forEach((fn) => {
      try {
        fn(this.logs);
      } catch (err) {
        console.error("Error in logger subscriber:", err);
      }
    });
  }
}

export const logger = new SystemLogger();

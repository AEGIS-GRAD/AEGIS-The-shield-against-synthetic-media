"use client";

import React, { useState, useEffect } from "react";
import { logger } from "../api/systemLogger";
import {
  Terminal,
  X,
  Trash2,
  Copy,
  Check,
  Search,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Filter,
  ExternalLink,
} from "lucide-react";

export default function SystemLogsDrawer({ isOpen, onClose }) {
  const [logs, setLogs] = useState([]);
  const [filterLevel, setFilterLevel] = useState("ALL");
  const [searchTerm, setSearchTerm] = useState("");
  const [expandedLogId, setExpandedLogId] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLogs(logger.getLogs());
    const unsubscribe = logger.subscribe((updatedLogs) => {
      setLogs([...updatedLogs]);
    });
    return () => unsubscribe();
  }, []);

  if (!isOpen) return null;

  const filteredLogs = logs.filter((log) => {
    const matchesLevel = filterLevel === "ALL" || log.level === filterLevel;
    const matchesSearch =
      !searchTerm ||
      log.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.component.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (log.details && JSON.stringify(log.details).toLowerCase().includes(searchTerm.toLowerCase()));
    return matchesLevel && matchesSearch;
  });

  const handleCopyLogs = () => {
    const logText = logs
      .map(
        (l) =>
          `[${l.timestamp}] [${l.level}] [${l.component}] ${l.message}${
            l.details ? "\n  Details: " + JSON.stringify(l.details) : ""
          }`
      )
      .join("\n");
    navigator.clipboard.writeText(logText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportJson = () => {
    const jsonStr = JSON.stringify(logs, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-system-logs-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getBadgeStyle = (level) => {
    switch (level) {
      case "ERROR":
        return "bg-rose-100 text-rose-800 border-rose-300";
      case "WARN":
        return "bg-amber-100 text-amber-800 border-amber-300";
      case "SUCCESS":
        return "bg-emerald-100 text-emerald-800 border-emerald-300";
      default:
        return "bg-cyan-100 text-cyan-800 border-cyan-300";
    }
  };

  const getLevelIcon = (level) => {
    switch (level) {
      case "ERROR":
        return <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />;
      case "WARN":
        return <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0" />;
      case "SUCCESS":
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />;
      default:
        return <Info className="w-3.5 h-3.5 text-cyan-600 shrink-0" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="w-full max-w-2xl h-full bg-white border-l border-slate-200 shadow-2xl flex flex-col font-sans">
        
        {/* Header */}
        <div className="p-4 sm:px-6 border-b border-slate-200 bg-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-cyan-50 border border-cyan-200 text-cyan-600">
              <Terminal className="w-5 h-5 text-cyan-600" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-900 tracking-tight">System & Backend Diagnostic Logs</h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-200 text-slate-700 border border-slate-300">
                  {filteredLogs.length} Entries
                </span>
              </div>
              <p className="text-xs text-slate-500">Real-time telemetry, backend errors & detector execution events</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-200 transition-colors cursor-pointer"
            title="Close logs drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Terminal Alert Prompt Banner */}
        <div className="p-3.5 bg-amber-50 border-b border-amber-200 px-6 flex items-start gap-3 text-xs">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-amber-900 leading-relaxed">
            <strong className="text-amber-900 font-bold block">Terminal Inspection Reminder:</strong>
            When backend errors or network failures occur, open your terminal running FastAPI/Uvicorn to view detailed Python stack traces, exception messages, and model container output.
          </div>
        </div>

        {/* Search & Filter Toolbar */}
        <div className="p-4 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search logs by component, message, or error..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-white border border-slate-300 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-cyan-600"
            />
          </div>

          {/* Level Filter Buttons */}
          <div className="flex items-center gap-1 bg-slate-200/80 p-1 rounded-lg border border-slate-300">
            {["ALL", "ERROR", "WARN", "INFO", "SUCCESS"].map((lvl) => (
              <button
                key={lvl}
                onClick={() => setFilterLevel(lvl)}
                className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold transition-all cursor-pointer ${
                  filterLevel === lvl
                    ? "bg-cyan-600 text-white shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {lvl}
              </button>
            ))}
          </div>
        </div>

        {/* Log Entries Stream */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-2.5 font-mono text-xs">
          {filteredLogs.length === 0 ? (
            <div className="text-center py-16 text-slate-400 space-y-2">
              <Terminal className="w-8 h-8 mx-auto text-slate-400 opacity-60" />
              <p className="text-sm text-slate-600 font-bold">No log entries matching criteria.</p>
              <p className="text-xs font-sans">Logs will automatically populate as requests and detector calls execute.</p>
            </div>
          ) : (
            filteredLogs.map((log) => {
              const isExpanded = expandedLogId === log.id;
              return (
                <div
                  key={log.id}
                  className={`p-3 rounded-xl border transition-all ${
                    log.level === "ERROR"
                      ? "bg-rose-50 border-rose-200 hover:border-rose-300"
                      : log.level === "WARN"
                      ? "bg-amber-50 border-amber-200 hover:border-amber-300"
                      : log.level === "SUCCESS"
                      ? "bg-emerald-50 border-emerald-200 hover:border-emerald-300"
                      : "bg-slate-50 border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      {getLevelIcon(log.level)}
                      <span className="text-[11px] text-slate-500 shrink-0 font-bold">{log.timestamp}</span>
                      <span
                        className={`px-1.5 py-0.2 text-[9px] font-bold rounded border uppercase ${getBadgeStyle(
                          log.level
                        )}`}
                      >
                        {log.level}
                      </span>
                      <span className="text-[11px] font-bold text-cyan-800 bg-cyan-50 px-2 py-0.5 rounded border border-cyan-200 shrink-0">
                        [{log.component}]
                      </span>
                    </div>

                    {log.details && (
                      <button
                        onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                        className="text-slate-500 hover:text-cyan-700 text-[10px] flex items-center gap-1 cursor-pointer font-sans font-bold"
                      >
                        <span>{isExpanded ? "Hide Details" : "View Details"}</span>
                        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </button>
                    )}
                  </div>

                  <p className="text-slate-800 mt-1.5 leading-relaxed font-sans text-xs font-semibold break-words">
                    {log.message}
                  </p>

                  {/* Expanded JSON Inspector for log details */}
                  {isExpanded && log.details && (
                    <div className="mt-2.5 p-3 rounded-lg bg-slate-900 border border-slate-800 text-[11px] text-slate-200 overflow-x-auto space-y-1">
                      <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Payload / Exception Context</div>
                      <pre className="whitespace-pre-wrap break-all text-cyan-300 font-mono">
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-4 border-t border-slate-200 bg-slate-100 flex items-center justify-between gap-3">
          <button
            onClick={() => logger.clear()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-slate-600 hover:text-rose-600 hover:bg-slate-200 border border-slate-300 transition-colors cursor-pointer"
            title="Clear all log entries"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear Logs</span>
          </button>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyLogs}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 transition-colors cursor-pointer shadow-xs"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                  <span className="text-emerald-700 font-bold">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-slate-500" />
                  <span>Copy Text</span>
                </>
              )}
            </button>

            <button
              onClick={handleExportJson}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-cyan-600 hover:bg-cyan-700 text-white border border-cyan-600 transition-colors cursor-pointer shadow-xs"
            >
              <Download className="w-3.5 h-3.5 text-white" />
              <span>Export JSON</span>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

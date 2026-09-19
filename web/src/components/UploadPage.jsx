"use client";
// impeccable-disable gray-on-color

import React, { useState, useRef } from "react";
import { submitMediaWithProgress, DEMO_PRESETS, createPresetFile } from "../api/submitMedia";
import WorkstationHeader from "./WorkstationHeader";
import PipelineStepper from "./PipelineStepper";
import DetectorResultsGrid from "./DetectorResultsGrid";
import LiveStatusScreen from "./LiveStatusScreen";
import {
  Upload,
  Film,
  Music,
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  X,
  File,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Sparkles,
  Download,
  Play,
  FileCode2,
} from "lucide-react";

const ALLOWED_TYPES = [
  "video/mp4",
  "video/quicktime",
  "audio/mpeg",
  "audio/wav",
];
const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100MB limit

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return (bytes / Math.pow(k, i)).toFixed(1) + " " + sizes[i];
}

function truncateMiddle(str, maxLength = 36) {
  if (!str || str.length <= maxLength) return str || "";
  const extIndex = str.lastIndexOf(".");
  const ext = extIndex !== -1 ? str.slice(extIndex) : "";
  const nameWithoutExt = extIndex !== -1 ? str.slice(0, extIndex) : str;
  const available = maxLength - ext.length - 3;
  if (available <= 4) return str.slice(0, maxLength) + "...";
  const start = Math.ceil(available / 2);
  const end = Math.floor(available / 2);
  return `${nameWithoutExt.slice(0, start)}...${nameWithoutExt.slice(-end)}${ext}`;
}

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [liveStatus, setLiveStatus] = useState(null);
  const [viewMode, setViewMode] = useState("upload"); // "upload" | "status" | "results"
  const [submitResult, setSubmitResult] = useState(null);
  const [isJsonOpen, setIsJsonOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const fileInputRef = useRef(null);

  const validateFile = (file) => {
    if (!file) return false;

    if (!ALLOWED_TYPES.includes(file.type)) {
      setValidationError(
        `Unsupported file type (${file.type || "unknown"}). Only MP4, MOV, MP3, and WAV media files are supported.`
      );
      return false;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setValidationError(
        `File size (${formatFileSize(file.size)}) exceeds the maximum allowed limit of 100 MB.`
      );
      return false;
    }

    setValidationError(null);
    return true;
  };

  const handleFileSelect = (file) => {
    setSubmitResult(null);
    if (validateFile(file)) {
      setSelectedFile(file);
    } else {
      setSelectedFile(null);
    }
  };

  const handleInputChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleClearFile = () => {
    setSelectedFile(null);
    setValidationError(null);
    setSubmitResult(null);
    setLiveStatus(null);
    setIsJsonOpen(false);
    setCopied(false);
    setViewMode("upload");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleCopyJson = () => {
    if (!submitResult) return;
    const jsonStr = JSON.stringify(submitResult.raw_response || submitResult, null, 2);
    navigator.clipboard.writeText(jsonStr);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadJson = () => {
    if (!submitResult) return;
    const jsonStr = JSON.stringify(submitResult.raw_response || submitResult, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-forensic-report-${selectedFile?.name ? selectedFile.name.replace(/\.[^/.]+$/, "") : "media"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSubmit = async () => {
    if (!selectedFile || validationError || isSubmitting) return;

    setIsSubmitting(true);
    setValidationError(null);
    setViewMode("status");

    try {
      const response = await submitMediaWithProgress(selectedFile, (progressData) => {
        setLiveStatus(progressData);
      });
      setSubmitResult(response);
    } catch (err) {
      setValidationError(err.message || "Failed to submit media file.");
      setViewMode("upload");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRunPreset = async (presetId) => {
    const file = createPresetFile(presetId);
    if (!file) return;

    setSelectedFile(file);
    setValidationError(null);
    setSubmitResult(null);
    setIsSubmitting(true);
    setViewMode("status");

    try {
      const response = await submitMediaWithProgress(file, (progressData) => {
        setLiveStatus(progressData);
      });
      setSubmitResult(response);
    } catch (err) {
      setValidationError(err.message || "Failed to run demo preset.");
      setViewMode("upload");
    } finally {
      setIsSubmitting(false);
    }
  };

  const isVideo = selectedFile?.type?.startsWith("video/");
  const isAudio = selectedFile?.type?.startsWith("audio/");

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100 flex flex-col font-sans selection:bg-cyan-500 selection:text-slate-950">
      {/* Background Subtle Gradient Overlay */}
      <div className="fixed inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(6,182,212,0.12),rgba(255,255,255,0))] pointer-events-none" />

      {/* Persistent Top Navigation Bar */}
      <WorkstationHeader
        onReset={handleClearFile}
        isRunning={isSubmitting || viewMode === "status"}
        activeMode={submitResult?.endpoint_used?.includes("8081") ? "live" : "simulation"}
      />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col items-center py-8 px-4 sm:px-6 lg:px-8 relative z-10 w-full">
        <div className="w-full max-w-5xl space-y-6">

          {/* Pipeline Stepper Breadcrumb */}
          <PipelineStepper
            currentStep={viewMode}
            onStepClick={(step) => {
              if (step === "upload") setViewMode("upload");
              if (step === "status" && liveStatus) setViewMode("status");
              if (step === "results" && submitResult) setViewMode("results");
            }}
          />

          {/* Workstation Container Card */}
          <div className="bg-[#111827]/85 backdrop-blur-xl border border-slate-800/90 rounded-2xl p-6 sm:p-8 shadow-2xl shadow-black/50 space-y-6">

            {/* View Mode 1: Live Status Screen during/after processing */}
            {viewMode === "status" ? (
              <div className="space-y-6 animate-in fade-in duration-300">
                <LiveStatusScreen
                  file={selectedFile}
                  statusData={liveStatus}
                  onComplete={() => setViewMode("results")}
                />

                {/* Return / Cancel */}
                <div className="flex justify-center pt-2">
                  <button
                    onClick={handleClearFile}
                    className="text-xs font-mono text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancel & Return to Ingestion
                  </button>
                </div>
              </div>
            ) : viewMode === "results" && submitResult ? (
              /* View Mode 2: Results Grid */
              <div className="space-y-5 animate-in fade-in duration-200 min-w-0">
                <DetectorResultsGrid
                  fileName={selectedFile?.name}
                  fileSize={formatFileSize(selectedFile?.size || 0)}
                  detectorResponses={submitResult}
                  onViewLogs={() => setViewMode("status")}
                  onExportJson={handleDownloadJson}
                />

                {/* Forensic JSON Inspector (Collapsible) */}
                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => setIsJsonOpen(!isJsonOpen)}
                      className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300 hover:text-cyan-400 font-mono transition-colors cursor-pointer"
                    >
                      {isJsonOpen ? <ChevronDown className="w-4 h-4 text-cyan-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
                      <FileCode2 className="w-4 h-4 text-cyan-400" />
                      <span>Forensic Contract JSON Inspector</span>
                      <span className="text-[10px] text-slate-500 font-normal normal-case hidden sm:inline">
                        ({isJsonOpen ? "Click to collapse" : "Click to view raw evidence payload"})
                      </span>
                    </button>

                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40 hidden sm:inline">
                        HTTP {submitResult.status_code || 200}
                      </span>
                      {isJsonOpen && (
                        <button
                          onClick={handleCopyJson}
                          className="flex items-center gap-1 text-[11px] font-mono text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 px-2.5 py-1 rounded border border-slate-700 transition-colors cursor-pointer"
                        >
                          {copied ? (
                            <>
                              <Check className="w-3.5 h-3.5 text-emerald-400" />
                              <span className="text-emerald-400">Copied!</span>
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5 text-slate-400" />
                              <span>Copy Payload</span>
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>

                  {isJsonOpen && (
                    <div className="space-y-2 animate-in fade-in duration-200">
                      <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 px-1">
                        <span>AEGIS Forensic Schema v1.0 • Pydantic Validated</span>
                        <span>UTF-8 JSON Payload</span>
                      </div>
                      <pre className="font-mono text-xs text-slate-300 bg-slate-950 p-4 rounded-lg border border-slate-800/80 overflow-x-auto max-h-96 whitespace-pre-wrap break-all">
                        <code>{JSON.stringify(submitResult.raw_response || submitResult, null, 2)}</code>
                      </pre>
                    </div>
                  )}
                </div>

                {/* Reset / Run Another Button */}
                <button
                  onClick={handleClearFile}
                  className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-medium text-sm bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition-all cursor-pointer"
                >
                  <RefreshCw className="w-4 h-4" />
                  Analyze Another Media File
                </button>
              </div>
            ) : (
              /* View Mode 3: Ingestion Dropzone & Demo Presets */
              <div className="space-y-6">
                {/* Header Subtitle inside card */}
                <div className="text-center space-y-1">
                  <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
                    Synthetic Media Detection
                  </h1>
                  <p className="text-slate-400 text-xs sm:text-sm max-w-lg mx-auto">
                    Upload video or audio media files for multi-modal deepfake analysis, frame-level boundary inspection, and biological pulse verification.
                  </p>
                </div>

                {/* 1-Click Milestone Demo Presets */}
                <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300 font-mono">
                      <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Month 1 Demo Presets (1-Click Rehearsal)</span>
                    </div>
                    <span className="text-[10px] font-mono text-slate-500 hidden sm:inline">
                      Curated project fixtures
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    {DEMO_PRESETS.map((preset) => (
                      <div
                        key={preset.id}
                        className="flex items-center justify-between gap-3 p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 transition-all"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-xs font-semibold text-slate-200 truncate">
                              {preset.title}
                            </p>
                            <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded border ${preset.badgeColor}`}>
                              {preset.modality.split(" ")[0]}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-400 truncate mt-0.5">
                            {preset.description}
                          </p>
                        </div>

                        <button
                          type="button"
                          onClick={() => handleRunPreset(preset.id)}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-cyan-950/70 hover:bg-cyan-900/80 text-cyan-300 border border-cyan-800/60 text-xs font-mono font-medium transition-colors flex-shrink-0 cursor-pointer"
                          title={`Run ${preset.title}`}
                        >
                          <Play className="w-3 h-3 fill-cyan-300" />
                          <span>Run</span>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Drag and Drop Dropzone */}
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`relative flex flex-col items-center justify-center p-8 sm:p-12 border-2 border-dashed rounded-xl cursor-pointer transition-all duration-200 group ${
                    isDragging
                      ? "border-cyan-500 bg-cyan-950/20 shadow-lg shadow-cyan-500/10 scale-[1.01]"
                      : selectedFile
                      ? "border-slate-700 bg-slate-900/50 hover:border-slate-600"
                      : "border-slate-800 hover:border-cyan-500/50 bg-slate-900/30 hover:bg-slate-900/60"
                  }`}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/mp4,video/quicktime,audio/mpeg,audio/wav"
                    onChange={handleInputChange}
                    className="hidden"
                    id="media-file-input"
                  />

                  <div className="p-4 rounded-full bg-slate-800/80 group-hover:bg-cyan-950/50 group-hover:text-cyan-400 text-slate-400 transition-colors mb-4 border border-slate-700/60">
                    <Upload className="w-7 h-7" />
                  </div>

                  <div className="text-center space-y-1">
                    <p className="text-sm sm:text-base font-medium text-slate-200">
                      <span className="text-cyan-400 group-hover:underline">Click to browse</span> or drag and drop custom media
                    </p>
                    <p className="text-xs text-slate-400 font-mono">
                      Supported: MP4, MOV, MP3, WAV (Max size: 100 MB)
                    </p>
                  </div>
                </div>

                {/* Inline Validation Error Message */}
                {validationError && (
                  <div className="flex items-start gap-3 p-4 rounded-xl bg-rose-950/40 border border-rose-800/60 text-rose-300 text-sm animate-in fade-in slide-in-from-top-2 duration-200">
                    <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <strong className="font-semibold text-rose-200 block">Invalid File</strong>
                      <span>{validationError}</span>
                    </div>
                    <button
                      onClick={() => setValidationError(null)}
                      className="text-rose-400 hover:text-rose-200 transition-colors cursor-pointer"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}

                {/* Selected File Preview Card */}
                {selectedFile && !validationError && (
                  <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between gap-4 animate-in fade-in duration-200">
                    <div className="flex items-center gap-3.5 min-w-0 flex-1">
                      <div className="p-3 rounded-lg bg-cyan-950/50 text-cyan-400 border border-cyan-800/40 flex-shrink-0">
                        {isVideo ? (
                          <Film className="w-6 h-6" />
                        ) : isAudio ? (
                          <Music className="w-6 h-6" />
                        ) : (
                          <File className="w-6 h-6" />
                        )}
                      </div>

                      <div className="min-w-0 flex-1">
                        <p
                          className="text-sm font-semibold text-slate-200 truncate"
                          title={selectedFile.name}
                        >
                          {truncateMiddle(selectedFile.name, 40)}
                        </p>
                        <div className="flex items-center gap-2 text-xs text-slate-400 font-mono mt-0.5">
                          <span>{formatFileSize(selectedFile.size)}</span>
                          <span>•</span>
                          <span className="uppercase text-cyan-400/90">
                            {selectedFile.type || "Media Stream"}
                          </span>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={handleClearFile}
                      disabled={isSubmitting}
                      className="p-2 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer disabled:opacity-50 flex-shrink-0"
                      title="Remove file"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                )}

                {/* Submit Button */}
                <button
                  onClick={handleSubmit}
                  disabled={!selectedFile || !!validationError || isSubmitting}
                  className={`w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl font-semibold text-sm transition-all duration-200 shadow-lg cursor-pointer ${
                    !selectedFile || !!validationError || isSubmitting
                      ? "bg-slate-800 text-slate-500 border border-slate-700/50 cursor-not-allowed shadow-none"
                      : "bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold shadow-cyan-500/20 hover:shadow-cyan-500/30 active:scale-[0.99]"
                  }`}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span>Analyzing Media...</span>
                    </>
                  ) : (
                    <>
                      <span>Submit for Detection</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            )}
          </div>

          {/* Footer Note */}
          <div className="text-center text-xs text-slate-500 font-mono">
            AEGIS Verification Workstation • Senior Graduation Project 2026/2027 • ECU CIS
          </div>
        </div>
      </main>
    </div>
  );
}

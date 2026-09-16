"use client";
// impeccable-disable gray-on-color

import React, { useState, useRef } from "react";
import { submitMediaWithProgress } from "../api/submitMedia";
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
} from "lucide-react";

// TODO: Reconcile allowed MIME types and max file size with Cybersecurity's official schema allowlist.
const ALLOWED_TYPES = [
  "video/mp4",
  "video/quicktime",
  "audio/mpeg",
  "audio/wav",
];
const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100MB limit

/**
 * Formats byte size into human readable string (e.g. 14.2 MB)
 */
function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return (bytes / Math.pow(k, i)).toFixed(1) + " " + sizes[i];
}

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [liveStatus, setLiveStatus] = useState(null);
  const [viewMode, setViewMode] = useState("upload"); // "upload" | "status" | "results"
  const [submitResult, setSubmitResult] = useState(null);

  const fileInputRef = useRef(null);

  /**
   * Client-side file validation
   */
  const validateFile = (file) => {
    if (!file) return false;

    // Check MIME type
    if (!ALLOWED_TYPES.includes(file.type)) {
      setValidationError(
        `Unsupported file type (${file.type || "unknown"}). Only MP4, MOV, MP3, and WAV files are supported.`
      );
      return false;
    }

    // Check File Size
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
    setViewMode("upload");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
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

  const isVideo = selectedFile?.type?.startsWith("video/");
  const isAudio = selectedFile?.type?.startsWith("audio/");

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100 flex flex-col items-center py-12 px-4 sm:px-6 lg:px-8 font-sans selection:bg-cyan-500 selection:text-white">
      {/* Background Subtle Gradient Overlay */}
      <div className="fixed inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(120,119,198,0.15),rgba(255,255,255,0))] pointer-events-none" />

      {/* Main Container — widened from max-w-3xl so four detector cards fit comfortably */}
      <div className="relative w-full max-w-5xl space-y-8">
        {/* Header Title */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider bg-cyan-950/60 border border-cyan-800/40 text-cyan-400">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
            AEGIS Verification Workstation
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl text-white">
            Synthetic Media Detection
          </h1>
          <p className="text-slate-400 text-base max-w-xl mx-auto">
            Upload video or audio media files for multi-modal deepfake analysis, frame-level verification, and forensic reporting.
          </p>
        </div>

        {/* Card Container */}
        <div className="bg-[#111827]/80 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-6 sm:p-8 shadow-2xl shadow-black/50 space-y-6">

          {/* View Mode 1: Live Status Screen during/after processing */}
          {viewMode === "status" ? (
            <div className="space-y-6 animate-in fade-in duration-300">
              <LiveStatusScreen
                file={selectedFile}
                statusData={liveStatus}
                onComplete={() => setViewMode("results")}
              />

              {/* Abort / Upload Another File */}
              <div className="flex justify-center pt-2">
                <button
                  onClick={handleClearFile}
                  className="text-xs font-mono text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                  Cancel & Return to Media Ingestion
                </button>
              </div>
            </div>
          ) : viewMode === "results" && submitResult ? (
            /* View Mode 2: Results Grid */
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
              <div className="flex items-center justify-between p-4 rounded-xl bg-slate-900/90 border border-slate-800">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-6 h-6 text-emerald-400 flex-shrink-0" />
                  <div>
                    <h3 className="font-semibold text-slate-200">Analysis Completed & Submitted</h3>
                    <p className="text-xs text-slate-400 font-mono mt-0.5">{selectedFile?.name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setViewMode("status")}
                    className="text-xs font-mono text-cyan-400 hover:text-cyan-300 px-3 py-1 rounded bg-cyan-950/50 border border-cyan-800/60 transition-colors cursor-pointer"
                  >
                    View Processing Logs
                  </button>
                  <span className="text-xs font-semibold px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
                    {isVideo ? "VIDEO" : "AUDIO"}
                  </span>
                </div>
              </div>

              {/* All four detectors side by side, with clear "not applicable" treatment */}
              <DetectorResultsGrid
                fileName={selectedFile?.name}
                detectorResponses={submitResult}
              />

              {/* Raw JSON viewer section */}
              <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono">
                    Raw Gateway & Detector JSON Response
                  </h3>
                  <span className="text-[11px] font-mono text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40">
                    HTTP {submitResult.status_code || 200} • {submitResult.endpoint_used || "Gateway Endpoint"}
                  </span>
                </div>
                <pre className="font-mono text-xs text-slate-300 bg-slate-950 p-4 rounded-lg border border-slate-800/80 overflow-x-auto max-h-96 whitespace-pre-wrap break-all">
                  <code>{JSON.stringify(submitResult.raw_response || submitResult, null, 2)}</code>
                </pre>
              </div>

              {/* Reset Button */}
              <button
                onClick={handleClearFile}
                className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-medium text-sm bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition-all cursor-pointer"
              >
                <RefreshCw className="w-4 h-4" />
                Upload Another Media File
              </button>
            </div>
          ) : (
            /* View Mode 3: Upload Dropzone */
            <>
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
                  <Upload className="w-8 h-8" />
                </div>

                <div className="text-center space-y-1">
                  <p className="text-base font-medium text-slate-200">
                    <span className="text-cyan-400 group-hover:underline">Click to browse</span> or drag and drop media file
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
                    className="text-rose-400 hover:text-rose-200 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )}

              {/* Selected File Preview Card */}
              {selectedFile && !validationError && (
                <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between gap-4 animate-in fade-in duration-200">
                  <div className="flex items-center gap-3.5 min-w-0">
                    {/* Media Icon Preview */}
                    <div className="p-3 rounded-lg bg-cyan-950/50 text-cyan-400 border border-cyan-800/40 flex-shrink-0">
                      {isVideo ? (
                        <Film className="w-6 h-6" />
                      ) : isAudio ? (
                        <Music className="w-6 h-6" />
                      ) : (
                        <File className="w-6 h-6" />
                      )}

                    </div>

                    {/* File Details */}
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-200 truncate">
                        {selectedFile.name}
                      </p>
                      <div className="flex items-center gap-2 text-xs text-slate-400 font-mono mt-0.5">
                        <span>{formatFileSize(selectedFile.size)}</span>
                        <span>•</span>
                        <span className="uppercase text-cyan-400/90">
                          {selectedFile.type || "Media File"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Remove File Button */}
                  <button
                    onClick={handleClearFile}
                    disabled={isSubmitting}
                    className="p-2 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
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
            </>
          )}
        </div>

        {/* Footer Note */}
        <div className="text-center text-xs text-slate-500 font-mono">
          AEGIS Media Ingestion Protocol v1.0 • Client-side schema validation active
        </div>
      </div>
    </div>
  );
}

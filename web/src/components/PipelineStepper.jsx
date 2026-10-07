"use client";

import React from "react";
import { Upload, Activity, ShieldCheck, Check } from "lucide-react";

const STEPS = [
  {
    id: "upload",
    stepNumber: "01",
    label: "Media Ingestion",
    description: "Format & Stream Validation",
    icon: Upload,
  },
  {
    id: "status",
    stepNumber: "02",
    label: "Parallel Inference",
    description: "Microservice Telemetry & Dispatch",
    icon: Activity,
  },
  {
    id: "results",
    stepNumber: "03",
    label: "Forensic Synthesis",
    description: "Cross-Modal Evidence & Consensus",
    icon: ShieldCheck,
  },
];

export default function PipelineStepper({ currentStep = "upload", onStepClick }) {
  const getStepIndex = (step) => {
    switch (step) {
      case "upload":
        return 0;
      case "status":
        return 1;
      case "results":
        return 2;
      default:
        return 0;
    }
  };

  const currentIndex = getStepIndex(currentStep);

  return (
    <nav aria-label="Pipeline Progress" className="w-full">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {STEPS.map((step, index) => {
          const isCurrent = index === currentIndex;
          const isComplete = index < currentIndex;
          const isPending = index > currentIndex;
          const Icon = step.icon;
          const isClickable = isComplete && onStepClick;

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => isClickable && onStepClick(step.id)}
              disabled={!isClickable}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-xl border text-left transition-all duration-150 relative overflow-hidden ${
                isCurrent
                  ? "bg-white border-cyan-500 shadow-sm ring-1 ring-cyan-500/20"
                  : isComplete
                  ? "bg-slate-50 border-slate-200 hover:border-slate-300 cursor-pointer"
                  : "bg-slate-100/60 border-slate-200 opacity-60 cursor-not-allowed"
              }`}
            >
              {/* Step indicator badge */}
              <div
                className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-mono font-bold transition-colors ${
                  isComplete
                    ? "bg-emerald-100 border border-emerald-300 text-emerald-700"
                    : isCurrent
                    ? "bg-cyan-100 border border-cyan-300 text-cyan-700 font-bold"
                    : "bg-slate-200 border border-slate-300 text-slate-500"
                }`}
              >
                {isComplete ? <Check className="w-3.5 h-3.5 text-emerald-700" /> : <Icon className="w-3.5 h-3.5 text-cyan-700" />}
              </div>

              {/* Step Label & Subtitle */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] font-mono uppercase tracking-wider text-slate-500 font-bold">
                    Step {step.stepNumber}
                  </span>
                  {isCurrent && (
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-600 animate-pulse" />
                  )}
                </div>
                <p
                  className={`text-xs font-bold truncate ${
                    isCurrent
                      ? "text-slate-900"
                      : isComplete
                      ? "text-slate-700"
                      : "text-slate-400"
                  }`}
                >
                  {step.label}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

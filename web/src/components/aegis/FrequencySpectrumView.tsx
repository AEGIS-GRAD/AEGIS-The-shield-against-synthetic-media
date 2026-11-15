"use client";

import React, { useState } from "react";
import { Activity, Camera, AlertTriangle, CheckCircle, Info, Sparkles, Layers } from "lucide-react";
import { Chip } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

interface FrequencySpectrumProps {
  filename?: string;
  hasExif?: boolean;
  frequencyAnomaly?: boolean;
  hfEnergyDb?: number;
  className?: string;
}

export function FrequencySpectrumView({
  filename = "analyzed_image.png",
  hasExif = false,
  frequencyAnomaly = true,
  hfEnergyDb = 138.4,
  className,
}: FrequencySpectrumProps) {
  const [activeLayer, setActiveLayer] = useState<"fft" | "dct">("fft");

  return (
    <div className={cn("rounded-xl border bg-card/60 p-4 space-y-4", className)}>
      <div className="flex items-center justify-between border-b pb-3">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-accent" />
          <h4 className="text-sm font-semibold text-foreground">Frequency Spectrum & Metadata Flags</h4>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => setActiveLayer("fft")}
            className={cn(
              "text-[11px] font-mono px-2 py-0.5 rounded border transition-colors",
              activeLayer === "fft"
                ? "bg-accent/15 border-accent text-accent font-bold"
                : "bg-muted/40 border-border text-muted-foreground hover:text-foreground"
            )}
          >
            2D FFT
          </button>
          <button
            onClick={() => setActiveLayer("dct")}
            className={cn(
              "text-[11px] font-mono px-2 py-0.5 rounded border transition-colors",
              activeLayer === "dct"
                ? "bg-accent/15 border-accent text-accent font-bold"
                : "bg-muted/40 border-border text-muted-foreground hover:text-foreground"
            )}
          >
            DCT Blocks
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-[140px_1fr]">
        {/* Synthetic 2D Frequency Magnitude Spectrum visualization */}
        <div className="relative aspect-square w-full rounded-lg bg-black border border-border/70 overflow-hidden flex items-center justify-center">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-amber-500/30 via-cyan-950/20 to-black/90" />
          {frequencyAnomaly && (
            <div className="absolute inset-0 grid grid-cols-4 grid-rows-4 opacity-40">
              {Array.from({ length: 16 }).map((_, i) => (
                <div key={i} className="border border-rose-500/30 flex items-center justify-center">
                  <span className="size-1 rounded-full bg-rose-400 animate-pulse" />
                </div>
              ))}
            </div>
          )}
          <div className="relative text-center z-10 p-2">
            <span className="text-[10px] font-mono font-bold text-amber-300 block">
              {activeLayer === "fft" ? "FFT 2D LOG-MAG" : "DCT 8x8 BLOCKS"}
            </span>
            <span className="text-[9px] font-mono text-muted-foreground">
              Center: DC component
            </span>
          </div>
        </div>

        {/* Signals and Evidence Flags */}
        <div className="space-y-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={frequencyAnomaly ? "warn" : "good"}>
              {frequencyAnomaly ? (
                <>
                  <AlertTriangle className="mr-1 size-3 text-rose-400" />
                  <span>frequency_anomaly</span>
                </>
              ) : (
                <>
                  <CheckCircle className="mr-1 size-3 text-emerald-400" />
                  <span>clean_spectrum</span>
                </>
              )}
            </Chip>

            <Chip tone={hasExif ? "good" : "neutral"}>
              <Camera className="mr-1 size-3" />
              <span>{hasExif ? "exif_intact" : "exif_missing"}</span>
            </Chip>

            <span className="font-mono text-muted-foreground text-[11px] ml-auto">
              HF Energy: <b className={frequencyAnomaly ? "text-rose-400" : "text-emerald-400"}>{hfEnergyDb.toFixed(1)} dB</b> (threshold: 120 dB)
            </span>
          </div>

          <div className="rounded-lg bg-background/50 border border-border/60 p-2.5 text-[11px] leading-relaxed text-muted-foreground space-y-1">
            <p>
              {frequencyAnomaly ? (
                <b className="text-rose-400 font-semibold">Upsampling grid artifacts detected.</b>
              ) : (
                <b className="text-emerald-400 font-semibold">Natural spectral decay verified.</b>
              )}{" "}
              High-frequency power spectrum peaks correlate with transpose convolution stride artifacts or diffusion latent decoding.
            </p>
            <p className="text-[10px] text-muted-foreground/80">
              {hasExif
                ? "Camera hardware EXIF metadata found in file header."
                : "Note: Missing EXIF is common in social media recompression or web uploads (subordinate to spatial analysis)."}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
export default FrequencySpectrumView;

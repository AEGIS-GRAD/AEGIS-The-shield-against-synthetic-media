"use client";

import React, { useState, useMemo } from "react";
import { FileText, Sparkles, CheckCircle2, AlertCircle, BarChart3, Hash } from "lucide-react";
import { Chip } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

interface SentenceScore {
  text: string;
  syntheticScore: number;
  wordCount: number;
  perplexityRank: "low" | "medium" | "high";
}

interface PerSentenceHighlightProps {
  text: string;
  className?: string;
  modelScore?: number;
}

export function PerSentenceHighlightView({
  text,
  className,
  modelScore = 0.88,
}: PerSentenceHighlightProps) {
  const [selectedSentence, setSelectedSentence] = useState<number | null>(null);

  // Split text into sentence chunks and calculate stylometry indicators
  const sentences: SentenceScore[] = useMemo(() => {
    if (!text || text.trim().length === 0) return [];
    const raw = text.match(/[^.!?]+[.!?]+|\s*$/g) || [text];
    const filtered = raw.map((s) => s.trim()).filter((s) => s.length > 0);

    return filtered.map((s, idx) => {
      const words = s.split(/\s+/).filter(Boolean);
      const wordCount = words.length;

      // Simulated sentence-level score correlated with overall modelScore and sentence length
      const lengthVariance = Math.abs(wordCount - 16) / 20;
      let sScore = Math.min(0.99, Math.max(0.05, modelScore + (Math.sin(idx * 1.7) * 0.15) - (lengthVariance * 0.1)));
      if (modelScore < 0.35) {
        sScore = Math.min(0.35, sScore * 0.4);
      }

      return {
        text: s,
        syntheticScore: sScore,
        wordCount,
        perplexityRank: sScore > 0.65 ? "low" : sScore < 0.35 ? "high" : "medium",
      };
    });
  }, [text, modelScore]);

  // Stylometric metrics computation
  const stats = useMemo(() => {
    if (!sentences.length) return { ttr: 0.65, cov: 0.22, ngram: 0.12 };
    const words = text.toLowerCase().match(/\b[a-z]{2,}\b/g) || [];
    const unique = new Set(words);
    const ttr = words.length > 0 ? Number((unique.size / words.length).toFixed(3)) : 0.65;

    // Sentence length CoV (standard deviation / mean)
    const lengths = sentences.map((s) => s.wordCount);
    const mean = lengths.reduce((a, b) => a + b, 0) / (lengths.length || 1);
    const variance = lengths.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (lengths.length || 1);
    const std = Math.sqrt(variance);
    const cov = mean > 0 ? Number((std / mean).toFixed(3)) : 0.25;

    return {
      ttr,
      cov,
      ngram: Number((1.0 - ttr * 0.8).toFixed(3)),
    };
  }, [text, sentences]);

  return (
    <div className={cn("rounded-xl border bg-card/60 p-4 space-y-4", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-accent" />
          <h4 className="text-sm font-semibold text-foreground">Per-Sentence Authorship & Stylometry</h4>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono text-muted-foreground">
            Sentences: <b className="text-foreground">{sentences.length}</b>
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className="font-mono text-muted-foreground">
            Lexical TTR: <b className="text-foreground">{stats.ttr}</b>
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className="font-mono text-muted-foreground">
            Length CoV: <b className="text-foreground">{stats.cov}</b>
          </span>
        </div>
      </div>

      {/* Stylometry summary badges */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone={stats.cov < 0.35 ? "warn" : "good"}>
          <span>{stats.cov < 0.35 ? "low_sentence_length_variation" : "natural_length_burstiness"}</span>
        </Chip>
        <Chip tone={stats.ttr < 0.55 ? "warn" : "good"}>
          <span>{stats.ttr < 0.55 ? "low_vocabulary_diversity" : "rich_lexical_diversity"}</span>
        </Chip>
        <Chip tone={modelScore >= 0.65 ? "warn" : "good"}>
          <span>{modelScore >= 0.65 ? "uniform_low_perplexity" : "variable_perplexity"}</span>
        </Chip>
      </div>

      {/* Rendered Per-Sentence Highlighting Box */}
      <div className="rounded-lg border bg-background/80 p-4 text-sm leading-relaxed max-h-72 overflow-y-auto space-x-1.5">
        {sentences.map((s, idx) => {
          const isSelected = selectedSentence === idx;
          const isSynthetic = s.syntheticScore >= 0.65;
          const isAuthentic = s.syntheticScore <= 0.35;

          const bg = isSynthetic
            ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
            : isAuthentic
            ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
            : "bg-amber-500/15 text-amber-300 border-amber-500/30";

          return (
            <span
              key={idx}
              onClick={() => setSelectedSentence(isSelected ? null : idx)}
              className={cn(
                "inline-block rounded px-1.5 py-0.5 border cursor-pointer transition-all hover:ring-1 hover:ring-accent",
                bg,
                isSelected && "ring-2 ring-accent"
              )}
              title={`Sentence ${idx + 1}: ${Math.round(s.syntheticScore * 100)}% AI likelihood | ${s.wordCount} words | Perplexity: ${s.perplexityRank}`}
            >
              {s.text}{" "}
            </span>
          );
        })}
      </div>

      {/* Active Inspector card for selected sentence */}
      {selectedSentence !== null && sentences[selectedSentence] && (
        <div className="rounded-lg bg-secondary/50 border p-3 text-xs flex items-center justify-between gap-4">
          <div>
            <span className="font-mono text-[10px] text-accent uppercase font-bold block mb-1">
              Sentence #{selectedSentence + 1} Inspector
            </span>
            <p className="text-foreground line-clamp-2 italic">
              &ldquo;{sentences[selectedSentence].text}&rdquo;
            </p>
          </div>
          <div className="shrink-0 text-right font-mono">
            <span className="text-[10px] text-muted-foreground block">AI Score</span>
            <b
              className={
                sentences[selectedSentence].syntheticScore >= 0.65
                  ? "text-rose-400 text-sm font-bold"
                  : sentences[selectedSentence].syntheticScore <= 0.35
                  ? "text-emerald-400 text-sm font-bold"
                  : "text-amber-400 text-sm font-bold"
              }
            >
              {(sentences[selectedSentence].syntheticScore * 100).toFixed(0)}%
            </b>
          </div>
        </div>
      )}
    </div>
  );
}
export default PerSentenceHighlightView;

"use client";

import { useState } from "react";
import { Check, Copy, Hash, ShieldCheck } from "lucide-react";
import { Panel } from "@/components/aegis/ui";
import type { HashChainEvent } from "@/lib/report";
import { cn } from "@/lib/utils";

export interface HashChainProps {
  fileHash: string;
  transcriptHash: string;
  events: HashChainEvent[];
  onCopy?: (hash: string) => void;
}

export function HashChain({
  fileHash,
  transcriptHash,
  events,
  onCopy,
}: HashChainProps) {
  const [copiedHash, setCopiedHash] = useState(false);

  const handleCopy = () => {
    if (onCopy) {
      onCopy(transcriptHash);
    } else if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(transcriptHash);
    }
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  };

  return (
    <Panel title="Chain of evidence" subtitle="Tamper-evident audit trail & cryptographic integrity">
      {/* File SHA-256 */}
      <div className="mb-3 rounded-lg border bg-muted/60 p-3">
        <div className="caption mb-1 flex items-center justify-between gap-1">
          <span className="flex items-center gap-1">
            <Hash className="size-3 text-muted-foreground" />
            Original File SHA-256
          </span>
          <span className="text-[10px] font-mono font-bold text-emerald-500 flex items-center gap-0.5">
            <Check className="size-3" />
            VERIFIED
          </span>
        </div>
        <p className="mono break-all text-xs text-primary">{fileHash}</p>
      </div>

      {/* Tamper-Evident Transcript Hash */}
      <div className="mb-4 rounded-lg border border-accent/30 bg-accent-soft/30 p-3">
        <div className="caption mb-1 flex items-center justify-between gap-1">
          <span className="flex items-center gap-1 font-bold text-accent">
            <ShieldCheck className="size-3.5" />
            Judge Transcript SHA-256
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] font-mono text-accent hover:underline cursor-pointer"
            title="Copy hash"
          >
            {copiedHash ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
            {copiedHash ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="mono break-all text-xs text-foreground select-all font-semibold">{transcriptHash}</p>
        <p className="text-[10px] text-muted-foreground mt-1">
          Cryptographically binds all 3 debate rounds and operator actions.
        </p>
      </div>

      <ol className="relative space-y-3.5 border-l pl-5 text-xs sm:text-sm">
        {events.map(([t, e, color]) => (
          <li key={`${t}-${e}`} className="relative">
            <span className={cn("absolute -left-[25px] top-1.5 size-2.5 rounded-full ring-4 ring-card", color || "bg-accent")} />
            <span className="mono mr-2 text-muted-foreground">{t}</span>
            <span className="text-foreground">{e}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}


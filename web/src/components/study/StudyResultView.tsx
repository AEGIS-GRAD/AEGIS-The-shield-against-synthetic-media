"use client";

import { Panel, Chip, SiemTierBadge } from "@/components/aegis/ui";
import { AgreementMatrix } from "@/components/report/AgreementMatrix";
import { agreementFromScores } from "@/lib/report";
import { singleScore, type Condition, type StudyScenario } from "@/lib/study";
import { cn } from "@/lib/utils";

const LABEL_TEXT = { authentic: "Likely authentic", uncertain: "Uncertain", synthetic: "Likely synthetic" } as const;
const LABEL_CLS = {
  authentic: "bg-authentic-soft text-authentic-ink border-authentic/30",
  uncertain: "bg-inconclusive-soft text-inconclusive-ink border-inconclusive/30",
  synthetic: "bg-synthetic-soft text-synthetic-ink border-synthetic/30",
} as const;

const JUDGE_TEXT = {
  synthetic: "Manipulated",
  authentic: "Authentic",
  inconclusive: "Inconclusive",
  integrity_unknown: "Integrity unknown",
} as const;

function Header({ s }: { s: StudyScenario }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
      <span className="mono text-foreground">{s.file}</span>
      <span>{s.durationS} s</span>
    </div>
  );
}

export function BaselineView({ s }: { s: StudyScenario }) {
  const { score, label } = singleScore(s);
  return (
    <div data-testid="view-baseline">
    <Panel title="Result">
      <Header s={s} />
      {score === null || label === null ? (
        <p className="text-lg font-semibold">No score available</p>
      ) : (
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <div className="caption">Synthetic score</div>
            <div className="text-5xl font-bold tabular-nums" aria-label={`Synthetic score ${score.toFixed(2)} out of 1`}>
              {score.toFixed(2)}
            </div>
          </div>
          <span className={cn("rounded-full border px-4 py-2 text-base font-semibold", LABEL_CLS[label])}>{LABEL_TEXT[label]}</span>
        </div>
      )}
    </Panel>
    </div>
  );
}

export function EvidenceView({ s }: { s: StudyScenario }) {
  const { score, label } = singleScore(s);
  const ran = s.detectors.filter((d) => d.p !== null);
  const scores = Object.fromEntries(ran.map((d) => [d.id, d.p as number]));
  const ids = ran.map((d) => d.id);
  const brokenChain = !s.chain.intact;

  return (
    <div className="space-y-4" data-testid="view-evidence">
      <Panel title="Result">
        <Header s={s} />
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-xl font-bold">{JUDGE_TEXT[s.judge.verdict]}</span>
          <SiemTierBadge tier={s.judge.tier} size="sm" />
          {score !== null && label !== null && (
            <span className="text-sm text-muted-foreground">
              Average score {score.toFixed(2)} ({LABEL_TEXT[label].toLowerCase()})
            </span>
          )}
        </div>
        <p className="mt-3 text-sm leading-relaxed">{s.judge.justification}</p>
      </Panel>

      <Panel title="What each check found">
        <ul className="grid gap-3 sm:grid-cols-2">
          {s.detectors.map((d) => (
            <li key={d.id} className={cn("rounded-xl border p-3", d.p === null && "bg-muted/40 text-muted-foreground")}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{d.name}</span>
                {d.p === null ? (
                  <Chip>Did not run</Chip>
                ) : (
                  <span className="mono text-sm" aria-label={`Score ${d.p.toFixed(2)}`}>
                    {d.p.toFixed(2)}
                  </span>
                )}
              </div>
              {d.p !== null && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div className={cn("h-full rounded-full", d.p >= 0.65 ? "bg-synthetic" : d.p <= 0.35 ? "bg-authentic" : "bg-inconclusive")} style={{ width: `${d.p * 100}%` }} />
                </div>
              )}
              <p className="mt-2 text-sm">{d.claim}</p>
              {d.quality !== undefined && <p className="caption mt-1">Signal quality {d.quality.toFixed(2)}</p>}
              {d.flags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {d.flags.map((f) => (
                    <Chip key={f} tone="neutral">
                      {f}
                    </Chip>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      </Panel>

      {ids.length > 1 && <AgreementMatrix ids={ids} matrix={agreementFromScores(ids, scores)} />}

      <Panel title="How the checks reasoned">
        <ol className="space-y-2">
          {s.debate.map((t, i) => (
            <li key={i} className={cn("rounded-xl border p-3 text-sm", t.conflict && "border-inconclusive/50 bg-inconclusive-soft")}>
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-semibold">{t.who}</span>
                {t.conflict && <Chip tone="warn">Disagreement</Chip>}
              </div>
              {t.text}
            </li>
          ))}
        </ol>
      </Panel>

      <Panel title="Chain of evidence" subtitle="Record of how this file was handled">
        <div className={cn("mb-3 rounded-lg border p-3 text-sm", brokenChain ? "border-synthetic/40 bg-synthetic-soft text-synthetic-ink" : "bg-muted/60")}>
          <div className="font-semibold">{brokenChain ? "Record broken — file integrity cannot be confirmed" : "Record intact"}</div>
          <div className="mono mt-1 break-all text-xs">SHA-256 {s.chain.fileHash}</div>
        </div>
        <ol className="space-y-2 text-sm">
          {s.chain.events.map((e) => (
            <li key={e.time + e.text} className="flex gap-3">
              <span className="mono shrink-0 text-muted-foreground">{e.time}</span>
              <span className={cn(e.status === "broken" && "font-semibold text-synthetic-ink", e.status === "warn" && "text-inconclusive-ink")}>{e.text}</span>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}

export function StudyResultView({ scenario, condition }: { scenario: StudyScenario; condition: Condition }) {
  return condition === "evidence" ? <EvidenceView s={scenario} /> : <BaselineView s={scenario} />;
}

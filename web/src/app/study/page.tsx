"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Btn } from "@/components/aegis/ui";
import { StudyResultView } from "@/components/study/StudyResultView";
import {
  BACKGROUND_ITEMS,
  CONSENT_STATEMENTS,
  DECISION_OPTIONS,
  DECISION_PROMPT,
  FORCED_CHOICE,
  FORMAT_ITEMS,
  INSTRUCTION_STEPS,
  LIKERT_ANCHORS,
  SCENARIOS,
  SCENARIO_ITEMS,
  SCORE_EXPLAINER,
  buildSession,
  formatItemText,
  isDecisionCorrect,
  postCsv,
  scenarioCsv,
  type Condition,
  type Decision,
  type PostResponse,
  type ScenarioResponse,
  type Session,
  type StudyExport,
} from "@/lib/study";
import { cn } from "@/lib/utils";

type Step = "setup" | "consent" | "background" | "instructions" | "scenario" | "post" | "done";

const STORE = "aegis-rq3-study-v1";

function Likert({ name, text, value, onChange }: { name: string; text: string; value?: number; onChange: (v: number) => void }) {
  return (
    <fieldset className="rounded-xl border p-3">
      <legend className="px-1 text-sm font-medium">{text}</legend>
      <div className="mt-1 grid grid-cols-7 gap-1 text-center">
        {LIKERT_ANCHORS.map((a, i) => {
          const v = i + 1;
          return (
            <label key={v} className={cn("cursor-pointer rounded-lg border px-1 py-2 text-xs transition-colors focus-within:ring-2 focus-within:ring-ring", value === v ? "border-primary bg-primary text-primary-foreground" : "hover:bg-secondary")}>
              <input type="radio" className="sr-only" name={name} value={v} checked={value === v} onChange={() => onChange(v)} />
              <span className="block text-sm font-semibold">{v}</span>
              <span className="hidden sm:block">{a}</span>
            </label>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground sm:hidden">
        <span>1 = {LIKERT_ANCHORS[0]}</span>
        <span>7 = {LIKERT_ANCHORS[6]}</span>
      </div>
    </fieldset>
  );
}

function Choice<T extends string>({ name, legend, options, value, onChange }: { name: string; legend: string; options: { value: T; label: string }[]; value?: T | ""; onChange: (v: T) => void }) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {options.map((o) => (
        <label key={o.value} className={cn("flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm focus-within:ring-2 focus-within:ring-ring", value === o.value ? "border-primary bg-primary-soft" : "hover:bg-secondary")}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

function UnclearBox({ show, value, onChange }: { show: boolean; value: string; onChange: (v: string) => void }) {
  if (!show) return null;
  return (
    <label className="block rounded-xl border border-dashed p-3 text-sm">
      <span className="font-medium">Pilot: was any wording on this screen unclear? Say which words.</span>
      <textarea className="mt-1 w-full rounded-lg border bg-background p-2" rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const emptyPost = (): PostResponse => ({ experience: "", tools: "", evidence: {}, baseline: {}, preference: "", preferenceWhy: "", confusing: "", unclearNotes: {} });

function StudyApp() {
  const params = useSearchParams();
  const facilitator = params.get("facilitator") === "1";
  const pilot = params.get("pilot") === "1";

  const [step, setStep] = useState<Step>("setup");
  const [pid, setPid] = useState(params.get("pid") ?? "");
  const [session, setSession] = useState<Session | null>(null);
  const [consent, setConsent] = useState<boolean[]>(CONSENT_STATEMENTS.map(() => false));
  const [idx, setIdx] = useState(0);
  const [responses, setResponses] = useState<ScenarioResponse[]>([]);
  const [post, setPost] = useState<PostResponse>(emptyPost());
  const [startedAt, setStartedAt] = useState("");
  const [finishedAt, setFinishedAt] = useState("");

  // per-scenario draft
  const [decision, setDecision] = useState<Decision | "">("");
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [note, setNote] = useState("");
  const [override, setOverride] = useState<Condition | null>(null);
  const [toggles, setToggles] = useState(0);
  const t0 = useRef(0);

  const scenario = session ? SCENARIOS.find((s) => s.id === session.order[idx]) : undefined;
  const assigned = scenario && session ? session.conditions[scenario.id] : undefined;
  const shown = override ?? assigned;

  useEffect(() => {
    if (step === "scenario") {
      t0.current = performance.now();
      setDecision("");
      setRatings({});
      setNote("");
      setOverride(null);
      setToggles(0);
      window.scrollTo({ top: 0 });
    }
  }, [step, idx]);

  useEffect(() => {
    if (step !== "setup") window.scrollTo({ top: 0 });
  }, [step]);

  // Backup so a browser refresh in the middle of a session does not lose data.
  useEffect(() => {
    if (!session) return;
    try {
      localStorage.setItem(STORE, JSON.stringify({ session, responses, post, startedAt, pilot }));
    } catch {
      /* storage may be blocked; export still works */
    }
  }, [session, responses, post, startedAt, pilot]);

  const exportData = useMemo<StudyExport | null>(
    () => (session ? { pid: session.pid, startedAt, finishedAt, pilot, session, scenarios: responses, post } : null),
    [session, startedAt, finishedAt, pilot, responses, post]
  );

  const start = () => {
    const id = pid.trim();
    if (!id) return;
    setSession(buildSession(id));
    setStartedAt(new Date().toISOString());
    setStep("consent");
  };

  const submitScenario = () => {
    if (!scenario || !assigned || !shown || decision === "") return;
    const r: ScenarioResponse = {
      scenarioId: scenario.id,
      position: idx + 1,
      category: scenario.category,
      conditionAssigned: assigned,
      conditionAtSubmit: shown,
      facilitatorToggles: toggles,
      decision,
      expected: scenario.expected,
      correct: isDecisionCorrect(decision, scenario.expected),
      trust: ratings.trust,
      understand: ratings.understand,
      confidence: ratings.confidence,
      timeMs: Math.round(performance.now() - t0.current),
      unclearNote: note,
    };
    setResponses((prev) => [...prev.filter((x) => x.scenarioId !== r.scenarioId), r]);
    if (idx + 1 < SCENARIOS.length) setIdx(idx + 1);
    else setStep("post");
  };

  const scenarioReady = decision !== "" && SCENARIO_ITEMS.every((i) => ratings[i.id]);
  const postReady =
    post.experience !== "" &&
    post.tools !== "" &&
    FORMAT_ITEMS.every((i) => post.evidence[i.id] && post.baseline[i.id]) &&
    post.preference !== "";

  const setNoteFor = (key: string, v: string) => setPost((p) => ({ ...p, unclearNotes: { ...p.unclearNotes, [key]: v } }));

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8" aria-live="polite">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Media verification study</h1>
        {step === "scenario" && <span className="caption" role="status">Case {idx + 1} of {SCENARIOS.length}</span>}
      </header>

      {step === "setup" && (
        <section className="surface space-y-4 p-5">
          <h2 className="text-lg font-semibold">Facilitator setup</h2>
          <p className="text-sm text-muted-foreground">Enter the participant code (for example P01). It sets the case order and which cases use which format. Do not enter a name.</p>
          <label className="block text-sm font-medium">
            Participant code
            <input className="mt-1 block w-full rounded-lg border bg-background p-2" value={pid} onChange={(e) => setPid(e.target.value)} placeholder="P01" />
          </label>
          <p className="caption">{pilot ? "Pilot mode on: wording-feedback boxes are shown." : "Add ?pilot=1 to the address for pilot sessions."} {facilitator ? "Facilitator toggle on." : "Add ?facilitator=1 to show the format toggle."}</p>
          <Btn onClick={start} disabled={!pid.trim()}>Start</Btn>
        </section>
      )}

      {step === "consent" && (
        <section className="surface space-y-4 p-5">
          <h2 className="text-lg font-semibold">Consent</h2>
          <p className="text-sm">Please read the information sheet you were given. Tick each box to continue.</p>
          {CONSENT_STATEMENTS.map((c, i) => (
            <label key={c} className="flex items-start gap-3 text-sm">
              <input type="checkbox" className="mt-1" checked={consent[i]} onChange={(e) => setConsent((p) => p.map((v, j) => (j === i ? e.target.checked : v)))} />
              {c}
            </label>
          ))}
          <UnclearBox show={pilot} value={post.unclearNotes.consent ?? ""} onChange={(v) => setNoteFor("consent", v)} />
          <Btn onClick={() => setStep("background")} disabled={!consent.every(Boolean)}>Continue</Btn>
        </section>
      )}

      {step === "background" && (
        <section className="surface space-y-5 p-5">
          <h2 className="text-lg font-semibold">About you</h2>
          {BACKGROUND_ITEMS.map((b) => (
            <Choice
              key={b.id}
              name={b.id}
              legend={b.question}
              options={b.options.map((o) => ({ value: o, label: o }))}
              value={(post as any)[b.id]}
              onChange={(v) => setPost((p) => ({ ...p, [b.id]: v }))}
            />
          ))}
          <UnclearBox show={pilot} value={post.unclearNotes.background ?? ""} onChange={(v) => setNoteFor("background", v)} />
          <Btn onClick={() => setStep("instructions")} disabled={!post.experience || !post.tools}>Continue</Btn>
        </section>
      )}

      {step === "instructions" && (
        <section className="surface space-y-4 p-5">
          <h2 className="text-lg font-semibold">Instructions</h2>
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
            {INSTRUCTION_STEPS.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ol>
          <p className="rounded-lg bg-muted/60 p-3 text-sm">{SCORE_EXPLAINER}</p>
          <UnclearBox show={pilot} value={post.unclearNotes.instructions ?? ""} onChange={(v) => setNoteFor("instructions", v)} />
          <Btn onClick={() => setStep("scenario")}>Begin the first case</Btn>
        </section>
      )}

      {step === "scenario" && scenario && shown && (
        <>
          <section className="surface p-5">
            <h2 className="text-lg font-semibold">{scenario.title}</h2>
            <p className="mt-1 text-sm">{scenario.context}</p>
          </section>

          {facilitator && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed p-3 text-sm" role="group" aria-label="Facilitator format toggle">
              <span className="font-medium">Facilitator: show as</span>
              {(["evidence", "baseline"] as Condition[]).map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={shown === c}
                  className={cn("rounded-lg border px-3 py-1", shown === c ? "bg-primary text-primary-foreground" : "hover:bg-secondary")}
                  onClick={() => {
                    if (c !== shown) setToggles((n) => n + 1);
                    setOverride(c);
                  }}
                >
                  {c === "evidence" ? "Full evidence report" : "Single score"}
                </button>
              ))}
              <span className="caption">Assigned: {assigned}</span>
            </div>
          )}

          <StudyResultView scenario={scenario} condition={shown} />

          <section className="surface space-y-4 p-5">
            <Choice<Decision> name="decision" legend={DECISION_PROMPT} options={DECISION_OPTIONS} value={decision} onChange={setDecision} />
            {SCENARIO_ITEMS.map((it) => (
              <Likert key={`${scenario.id}-${it.id}`} name={`${scenario.id}-${it.id}`} text={it.text} value={ratings[it.id]} onChange={(v) => setRatings((r) => ({ ...r, [it.id]: v }))} />
            ))}
            <UnclearBox show={pilot} value={note} onChange={setNote} />
            <Btn onClick={submitScenario} disabled={!scenarioReady}>{idx + 1 < SCENARIOS.length ? "Next case" : "Finish cases"}</Btn>
          </section>
        </>
      )}

      {step === "post" && session && (
        <section className="surface space-y-6 p-5">
          <h2 className="text-lg font-semibold">Final questionnaire</h2>
          <p className="text-sm">During the study you saw results shown in two ways: <b>the full evidence report</b> (verdict, what each check found, reasoning and chain of evidence) and <b>the single score</b> (one number with a label). Rate each way below.</p>
          {session.formatBlockOrder.map((fmt) => (
            <div key={fmt} className="space-y-3">
              <h3 className="text-base font-semibold capitalize">{fmt === "evidence" ? "The full evidence report" : "The single score"}</h3>
              {FORMAT_ITEMS.map((it) => (
                <Likert key={`${fmt}-${it.id}`} name={`${fmt}-${it.id}`} text={formatItemText(it, fmt)} value={post[fmt][it.id]} onChange={(v) => setPost((p) => ({ ...p, [fmt]: { ...p[fmt], [it.id]: v } }))} />
              ))}
            </div>
          ))}
          <Choice name="preference" legend={FORCED_CHOICE.question} options={FORCED_CHOICE.options} value={post.preference} onChange={(v) => setPost((p) => ({ ...p, preference: v }))} />
          <label className="block text-sm font-medium">
            {FORCED_CHOICE.whyPrompt}
            <textarea className="mt-1 w-full rounded-lg border bg-background p-2" rows={3} value={post.preferenceWhy} onChange={(e) => setPost((p) => ({ ...p, preferenceWhy: e.target.value }))} />
          </label>
          <label className="block text-sm font-medium">
            {FORCED_CHOICE.confusingPrompt}
            <textarea className="mt-1 w-full rounded-lg border bg-background p-2" rows={3} value={post.confusing} onChange={(e) => setPost((p) => ({ ...p, confusing: e.target.value }))} />
          </label>
          <UnclearBox show={pilot} value={post.unclearNotes.post ?? ""} onChange={(v) => setNoteFor("post", v)} />
          <Btn
            onClick={() => {
              setFinishedAt(new Date().toISOString());
              setStep("done");
            }}
            disabled={!postReady}
          >
            Submit
          </Btn>
        </section>
      )}

      {step === "done" && exportData && (
        <section className="surface space-y-4 p-5">
          <h2 className="text-lg font-semibold">Thank you</h2>
          <p className="text-sm">You have finished. Please tell the researcher you are done.</p>
          {facilitator && (
            <div className="flex flex-wrap gap-3">
              <Btn onClick={() => download(`${exportData.pid}_session.json`, JSON.stringify(exportData, null, 2), "application/json")}>Download JSON</Btn>
              <Btn variant="outline" onClick={() => download(`${exportData.pid}_cases.csv`, scenarioCsv(exportData), "text/csv")}>Cases CSV</Btn>
              <Btn variant="outline" onClick={() => download(`${exportData.pid}_questionnaire.csv`, postCsv(exportData), "text/csv")}>Questionnaire CSV</Btn>
            </div>
          )}
          {!facilitator && <p className="caption">Researcher: reopen this page with ?facilitator=1 on the same browser to export. The session is also backed up in this browser.</p>}
        </section>
      )}
    </main>
  );
}

export default function StudyPage() {
  return (
    <Suspense fallback={null}>
      <StudyApp />
    </Suspense>
  );
}

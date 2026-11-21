import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  BACKGROUND_ITEMS,
  DECISION_OPTIONS,
  FORCED_CHOICE,
  FORMAT_ITEMS,
  INSTRUCTION_STEPS,
  SCENARIOS,
  SCENARIO_ITEMS,
  CONSENT_STATEMENTS,
  buildSession,
  formatItemText,
  postCsv,
  scenarioCsv,
  singleScore,
  type StudyExport,
} from "@/lib/study";

const docs = (f: string) => readFileSync(resolve(process.cwd(), "..", "docs", "rq3_study", f), "utf8");

describe("scenarios", () => {
  it("has eight scenarios with the planned mix", () => {
    expect(SCENARIOS).toHaveLength(8);
    const n = (c: string) => SCENARIOS.filter((s) => s.category === c).length;
    expect([n("agreement"), n("conflict"), n("limits")]).toEqual([2, 4, 2]);
  });

  it("conflict scenarios contain genuinely opposing detector scores", () => {
    for (const s of SCENARIOS.filter((x) => x.category === "conflict")) {
      const ps = s.detectors.map((d) => d.p).filter((p): p is number => p !== null);
      expect(Math.max(...ps) - Math.min(...ps)).toBeGreaterThanOrEqual(0.5);
    }
  });

  it("never lets a broken chain read as authentic in the evidence report data", () => {
    const broken = SCENARIOS.filter((s) => !s.chain.intact);
    expect(broken.length).toBeGreaterThan(0);
    for (const s of broken) {
      expect(s.judge.verdict).toBe("integrity_unknown");
      expect(s.expected).toBe("undecided");
    }
  });

  it("baseline score is the mean of detectors that ran", () => {
    const get = (id: string) => singleScore(SCENARIOS.find((s) => s.id === id)!);
    expect(get("S1")).toEqual({ score: 0.84, label: "synthetic" });
    expect(get("S3").label).toBe("uncertain");
    expect(get("S4").label).toBe("uncertain");
    expect(get("S7").label).toBe("authentic"); // the baseline cannot see the broken chain: intentional, see README
  });
});

describe("buildSession", () => {
  it("is deterministic and a permutation", () => {
    const a = buildSession("P03");
    expect(buildSession("P03")).toEqual(a);
    expect([...a.order].sort()).toEqual(SCENARIOS.map((s) => s.id).sort());
  });

  it("gives 4 evidence + 4 baseline, balanced within each category", () => {
    for (const pid of ["P01", "P02", "P03", "P04", "P17"]) {
      const s = buildSession(pid);
      expect(Object.values(s.conditions).filter((c) => c === "evidence")).toHaveLength(4);
      for (const cat of ["agreement", "conflict", "limits"]) {
        const ids = SCENARIOS.filter((x) => x.category === cat).map((x) => x.id);
        const ev = ids.filter((id) => s.conditions[id] === "evidence").length;
        expect(ev).toBe(ids.length / 2);
      }
    }
  });

  it("flips format assignment between adjacent participants", () => {
    const a = buildSession("P01").conditions;
    const b = buildSession("P02").conditions;
    for (const s of SCENARIOS) expect(a[s.id]).not.toBe(b[s.id]);
  });

  it("alternates questionnaire block order across the 4-participant cycle", () => {
    const firsts = ["P00", "P01", "P02", "P03"].map((p) => buildSession(p).formatBlockOrder[0]);
    expect(firsts.filter((f) => f === "evidence")).toHaveLength(2);
  });
});

describe("export", () => {
  const e: StudyExport = {
    pid: "P01", startedAt: "", finishedAt: "", pilot: true,
    session: buildSession("P01"),
    scenarios: [{ scenarioId: "S1", position: 1, category: "agreement", conditionAssigned: "evidence", conditionAtSubmit: "evidence", facilitatorToggles: 0, decision: "manipulated", expected: "manipulated", correct: true, trust: 6, understand: 6, confidence: 5, timeMs: 1234, unclearNote: 'said "hmm", then paused' }],
    post: { experience: "None", tools: "Never", evidence: { rely: 6 }, baseline: { rely: 3 }, preference: "evidence", preferenceWhy: "more, detail", confusing: "", unclearNotes: {} },
  };
  it("escapes CSV fields", () => {
    expect(scenarioCsv(e)).toContain('"said ""hmm"", then paused"');
    expect(postCsv(e)).toContain('"more, detail"');
  });
});

describe("printable docs stay in sync with study.ts", () => {
  const q = docs("questionnaire.md");
  const i = docs("instructions.md");
  const c = docs("consent_sheet.md");
  it("questionnaire", () => {
    for (const t of SCENARIO_ITEMS) expect(q).toContain(t.text);
    for (const o of DECISION_OPTIONS) expect(q).toContain(o.label);
    for (const b of BACKGROUND_ITEMS) { expect(q).toContain(b.question); for (const o of b.options) expect(q).toContain(o); }
    expect(q).toContain(FORCED_CHOICE.question);
    expect(q).toContain(FORCED_CHOICE.whyPrompt);
    expect(q).toContain(FORCED_CHOICE.confusingPrompt);
    for (const it of FORMAT_ITEMS) {
      const ev = formatItemText(it, "evidence");
      const bl = formatItemText(it, "baseline");
      // doc uses a {a | b} template, so check the two renderings against it
      const template = it.text.startsWith("{X}")
        ? it.text.replace("{X}", "{The full evidence report | The single score}")
        : it.text.replace("{X}", "{the full evidence report | the single score}");
      expect(q).toContain(template);
      expect(ev).not.toBe(bl);
    }
  });
  it("instructions", () => { for (const t of INSTRUCTION_STEPS) expect(i).toContain(t); });
  it("consent", () => { for (const t of CONSENT_STATEMENTS) expect(c).toContain(t); });
});

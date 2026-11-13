"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { UploadCloud, Cctv, ArrowRight, ShieldCheck, AlertCircle } from "lucide-react";
import { ModalityIcon, VerdictBadge, DemoBadge, DemoBanner, DemoSwitch } from "@/components/aegis/ui";
import { useDemoMode } from "@/lib/demoMode";

export default function Home() {
  const [demoMode, setDemoMode] = useDemoMode();
  const [recent, setRecent] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [backendError, setBackendError] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    fetch("/api/jobs?demo=false")
      .then((r) => {
        if (!r.ok) throw new Error("Failed to reach /api/jobs");
        return r.json();
      })
      .then((data) => {
        setBackendError(false);
        if (Array.isArray(data) && data.length > 0) {
          setRecent(data.slice(0, 3));
        } else if (demoMode) {
          fetch("/api/jobs?demo=true")
            .then((r) => r.json())
            .then((demo) => setRecent(Array.isArray(demo) ? demo.slice(0, 3) : []))
            .catch(() => setRecent([]));
        } else {
          setRecent([]);
        }
      })
      .catch(() => {
        setBackendError(true);
        if (demoMode) {
          fetch("/api/jobs?demo=true")
            .then((r) => r.json())
            .then((demo) => setRecent(Array.isArray(demo) ? demo.slice(0, 3) : []))
            .catch(() => setRecent([]));
        } else {
          setRecent([]);
        }
      })
      .finally(() => setLoading(false));
  }, [demoMode]);

  return (
    <div className="mx-auto max-w-5xl py-6 space-y-6">
      <div className="text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary">
          <ShieldCheck className="size-3.5" />Forensic-grade verification
        </span>
        <h1 className="mt-4 text-[34px]">What would you like to verify?</h1>
        <p className="mx-auto mt-2 max-w-xl text-muted-foreground">
          AEGIS tells you whether content is authentic or AI-generated — and explains why in plain language.
        </p>
      </div>

      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <EntryCard
          href="/analyze"
          icon={<UploadCloud className="size-7" />}
          title="Analyze a file"
          text="Upload a video, audio clip, image or text. We pick the right detectors and produce a shareable report."
          cta="Start analysis"
        />
        <EntryCard
          href="/live"
          icon={<Cctv className="size-7" />}
          title="Open live surveillance"
          text="Watch your camera feeds in real time and test Task 3 streaming rPPG via live webcam."
          cta="Open camera wall"
          live
        />
      </div>

      {backendError && !demoMode && (
        <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-xs text-destructive-foreground flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="size-4 shrink-0 text-destructive" />
            <span>Backend service unreachable. Showing 0 live reports. Toggle <strong>Demo data</strong> to preview sample reports.</span>
          </div>
          <DemoSwitch checked={demoMode} onChange={setDemoMode} />
        </div>
      )}

      {demoMode && (
        <DemoBanner
          message="Displaying sample evaluation reports because Demo data mode is active."
          onDisable={() => setDemoMode(false)}
        />
      )}

      <div className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3>Recent forensic reports</h3>
            {demoMode ? (
              <DemoBadge />
            ) : (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                LIVE STORE
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <DemoSwitch checked={demoMode} onChange={setDemoMode} />
            <Link href="/reports" className="text-xs font-medium text-accent hover:underline">
              See all →
            </Link>
          </div>
        </div>

        {recent.length === 0 && !loading && (
          <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
            No reports in live store. Click &quot;Start analysis&quot; above to submit media, or toggle &quot;Demo data&quot; to inspect fixtures.
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-3">
          {recent.map((a) => (
            <Link key={a.id} href={`/reports/${a.id}`} className="surface p-4 transition-soft hover:shadow-lift">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <ModalityIcon m={a.modality} />
                  <span className="truncate text-sm font-medium">{a.file}</span>
                </div>
                {a.is_demo ? (
                  <DemoBadge />
                ) : (
                  <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold shrink-0">
                    REAL
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between">
                <VerdictBadge verdict={a.verdict} size="sm" />
                <span className="mono text-muted-foreground text-xs">{a.time}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

function EntryCard({
  href,
  icon,
  title,
  text,
  cta,
  live,
}: {
  href: "/analyze" | "/live";
  icon: React.ReactNode;
  title: string;
  text: string;
  cta: string;
  live?: boolean;
}) {
  return (
    <Link href={href} className="surface group flex flex-col p-8 transition-soft hover:-translate-y-1 hover:shadow-lift">
      <span className={`grid size-16 place-items-center rounded-2xl ${live ? "bg-accent-soft text-accent" : "bg-primary-soft text-primary"}`}>
        {icon}
      </span>
      <h2 className="mt-6 flex items-center gap-2">
        {title}
        {live && (
          <span className="flex items-center gap-1 rounded-full bg-synthetic-soft px-2 py-0.5 text-[11px] font-semibold text-synthetic-ink">
            <span className="size-1.5 rounded-full bg-synthetic animate-live" />LIVE
          </span>
        )}
      </h2>
      <p className="mt-2 text-muted-foreground">{text}</p>
      <span className="mt-6 inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
        {cta}
        <ArrowRight className="size-4 transition-soft group-hover:translate-x-1" />
      </span>
    </Link>
  );
}

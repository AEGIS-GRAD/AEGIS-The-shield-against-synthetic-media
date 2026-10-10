"use client";

import Link from "next/link";
import { UploadCloud, Cctv, ArrowRight, ShieldCheck } from "lucide-react";
import { analyses } from "@/lib/mock";
import { ModalityIcon, VerdictBadge } from "@/components/aegis/ui";

export default function Home() {
  return (
    <div className="mx-auto max-w-5xl py-6">
      <div className="text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary">
          <ShieldCheck className="size-3.5" />Forensic-grade verification
        </span>
        <h1 className="mt-4 text-[34px]">What would you like to verify?</h1>
        <p className="mx-auto mt-2 max-w-xl text-muted-foreground">
          AEGIS tells you whether content is authentic or AI-generated — and explains why in plain language.
        </p>
      </div>

      <div className="mt-10 grid gap-5 md:grid-cols-2">
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
          text="Watch your camera feeds in real time and get alerted the moment footage looks manipulated."
          cta="Open camera wall"
          live
        />
      </div>

      <div className="mt-12">
        <div className="mb-3 flex items-center justify-between">
          <h3>Recent forensic reports</h3>
          <Link href="/reports" className="text-xs font-medium text-accent hover:underline">
            See all →
          </Link>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {analyses.slice(0, 3).map((a) => (
            <Link key={a.id} href={`/reports/${a.id}`} className="surface p-4 transition-soft hover:shadow-lift">
              <div className="flex items-center gap-2">
                <ModalityIcon m={a.modality} />
                <span className="truncate text-sm font-medium">{a.file}</span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <VerdictBadge verdict={a.verdict} size="sm" />
                <span className="mono text-muted-foreground">{a.time}</span>
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

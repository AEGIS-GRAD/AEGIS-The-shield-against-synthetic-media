"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, X, AlertCircle, Check, Minus, Sparkles, Video, AudioLines, Image as ImageIcon, FileText, Play } from "lucide-react";
import { detectors } from "@/lib/mock";
import { Btn, Chip, ModalityIcon, PageHeader, Panel, Toggle } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

type Tab = "media" | "image" | "text";
const MAX = 100 * 1024 * 1024;
const mediaExt = [".mp4", ".mov", ".wav", ".mp3"];
const imageExt = [".jpg", ".jpeg", ".png", ".webp"];

type Meta = { file: File; url: string; kind: "video" | "audio" | "image"; duration?: number; w?: number; h?: number };

export default function UploadPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("media");
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [text, setText] = useState("");
  const [drag, setDrag] = useState(false);
  const [auto, setAuto] = useState(true);
  const [explain, setExplain] = useState(true);
  const [picked, setPicked] = useState<string[]>(["video", "rppg", "syncnet", "aasist"]);
  const input = useRef<HTMLInputElement>(null);

  const accept = (tab === "image" ? imageExt : mediaExt).join(",");

  function handle(f: File) {
    setError(null);
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    const allowed = tab === "image" ? imageExt : mediaExt;
    if (!allowed.includes(ext)) return setError(`“${f.name}” is not a supported type. Allowed: ${allowed.join(", ")}`);
    if (f.size === 0) return setError(`“${f.name}” is empty (0 bytes). Please choose another file.`);
    if (f.size > MAX) return setError(`“${f.name}” is ${(f.size / 1048576).toFixed(1)} MB — the limit is 100 MB.`);
    const url = URL.createObjectURL(f);
    const kind = tab === "image" ? "image" : [".wav", ".mp3"].includes(ext) ? "audio" : "video";
    const m: Meta = { file: f, url, kind };
    setMeta(m);
    if (kind === "image") {
      const img = new Image();
      img.onload = () => setMeta({ ...m, w: img.width, h: img.height });
      img.src = url;
    } else {
      const el = document.createElement(kind);
      el.preload = "metadata";
      el.onloadedmetadata = () => setMeta({ ...m, duration: el.duration, w: (el as HTMLVideoElement).videoWidth, h: (el as HTMLVideoElement).videoHeight });
      el.src = url;
    }
  }

  const ready = tab === "text" ? text.trim().length > 40 : !!meta;
  const fname = tab === "text" ? "pasted_text.txt" : meta?.file.name;

  function runAnalysis() {
    if (!ready) return;
    const query = fname ? `?file=${encodeURIComponent(fname)}` : "";
    router.push(`/analyze/processing${query}`);
  }

  return (
    <div>
      <PageHeader
        title="Offline Analysis"
        subtitle="Upload content and AEGIS will decide whether it is authentic or AI-generated — and explain why."
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Panel>
            <div className="mb-5 flex gap-2">
              {([["media", "Video / Audio", Video], ["image", "Image", ImageIcon], ["text", "Text", FileText]] as const).map(([k, l, I]) => (
                <button
                  key={k}
                  onClick={() => { setTab(k); setMeta(null); setError(null); }}
                  className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition-soft", tab === k ? "border-accent bg-accent-soft text-accent" : "bg-card text-muted-foreground hover:text-primary")}
                >
                  <I className="size-4" />{l}
                </button>
              ))}
            </div>

            {tab === "text" ? (
              <div>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={10}
                  placeholder="Paste an article, statement or message to check whether it was written by a language model…"
                  className="w-full rounded-lg border bg-background p-4 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                />
                <p className="caption mt-2">{text.trim().length} characters · minimum 40 for a reliable Binoculars score</p>
              </div>
            ) : !meta ? (
              <div
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) handle(f); }}
                className={cn("flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-16 text-center transition-soft", drag ? "border-accent bg-accent-soft" : "bg-background/60", error && "border-synthetic/50")}
              >
                <span className="grid size-14 place-items-center rounded-full bg-primary-soft text-primary"><UploadCloud className="size-7" /></span>
                <p className="mt-4 text-[16px] font-semibold text-primary">Drag & drop your {tab === "image" ? "image" : "video or audio file"} here</p>
                <p className="caption mt-1">or</p>
                <Btn className="mt-3" onClick={() => input.current?.click()}>Browse files</Btn>
                <input ref={input} type="file" accept={accept} hidden onChange={(e) => e.target.files?.[0] && handle(e.target.files[0])} />
                <p className="caption mt-5">Allowed: {(tab === "image" ? imageExt : mediaExt).join(" · ")} — max 100 MB</p>
              </div>
            ) : (
              <FileCard meta={meta} onRemove={() => setMeta(null)} />
            )}

            {error && (
              <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-synthetic/30 bg-synthetic-soft px-4 py-3 text-sm text-synthetic-ink">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />{error}
              </div>
            )}
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel title="Detector selection" subtitle="Which models should examine this content?">
            <label className="flex items-center justify-between gap-3 rounded-lg border bg-primary-soft/60 p-3">
              <span className="flex items-center gap-2"><Sparkles className="size-4 text-accent" /><span><span className="block text-sm font-semibold text-primary">Auto</span><span className="caption">Orchestrator decides</span></span></span>
              <Toggle checked={auto} onChange={setAuto} label="Auto detector selection" />
            </label>
            <ul className={cn("mt-3 space-y-1", auto && "opacity-50")}>
              {detectors.map((d) => {
                const on = picked.includes(d.id);
                return (
                  <li key={d.id}>
                    <button
                      disabled={auto}
                      onClick={() => setPicked(on ? picked.filter((x) => x !== d.id) : [...picked, d.id])}
                      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-secondary disabled:cursor-not-allowed"
                    >
                      <span className={cn("grid size-4 place-items-center rounded border", on ? "border-accent bg-accent text-accent-foreground" : "bg-card")}>
                        {on && <Check className="size-3" />}
                      </span>
                      <ModalityIcon m={d.modality} />
                      <span className="flex-1 text-sm">{d.name}</span>
                      <span className="mono text-muted-foreground">~{d.latency}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <label className="mt-4 flex items-center justify-between border-t pt-4 text-sm">
              Explain why detectors were chosen <Toggle checked={explain} onChange={setExplain} label="Explain detector choice" />
            </label>
          </Panel>
          <Btn variant="accent" className="w-full py-3 text-[15px]" disabled={!ready} onClick={runAnalysis}>
            <Play className="size-4" /> Run analysis
          </Btn>
          {!ready && <p className="caption -mt-3 text-center">Add a file or paste text to continue</p>}
        </div>
      </div>
    </div>
  );
}

function FileCard({ meta, onRemove }: { meta: Meta; onRemove: () => void }) {
  const hasVideo = meta.kind === "video";
  const hasAudio = meta.kind !== "image";
  const fmt = (s?: number) => (s && isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "—");
  return (
    <div className="flex flex-col gap-5 rounded-xl border bg-background/60 p-4 sm:flex-row">
      <div className="grid aspect-video w-full shrink-0 place-items-center overflow-hidden rounded-lg bg-primary sm:w-64">
        {meta.kind === "video" && <video src={meta.url} className="size-full object-cover" muted />}
        {meta.kind === "image" && <img src={meta.url} alt="" className="size-full object-cover" />}
        {meta.kind === "audio" && (
          <div className="flex h-16 items-center gap-[3px]">
            {Array.from({ length: 40 }, (_, i) => (
              <span key={i} className="w-1 rounded bg-accent" style={{ height: `${20 + Math.abs(Math.sin(i * 1.7)) * 80}%` }} />
            ))}
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-semibold text-primary">{meta.file.name}</p>
            <p className="caption">Ready for analysis</p>
          </div>
          <button onClick={onRemove} className="rounded-md p-1 text-muted-foreground hover:bg-secondary" aria-label="Remove file">
            <X className="size-4" />
          </button>
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div><dt className="caption">Size</dt><dd className="mono">{(meta.file.size / 1048576).toFixed(1)} MB</dd></div>
          <div><dt className="caption">Duration</dt><dd className="mono">{fmt(meta.duration)}</dd></div>
          <div><dt className="caption">Resolution</dt><dd className="mono">{meta.w ? `${meta.w}×${meta.h}` : "—"}</dd></div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          <Chip tone={hasVideo ? "good" : "neutral"}>
            {hasVideo ? <Check className="mr-1 size-3" /> : <Minus className="mr-1 size-3" />}Video track
          </Chip>
          <Chip tone={hasAudio ? "good" : "warn"}>
            {hasAudio ? <><AudioLines className="mr-1 size-3" />Audio track</> : "No audio track"}
          </Chip>
        </div>
      </div>
    </div>
  );
}

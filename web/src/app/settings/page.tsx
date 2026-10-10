"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Btn, PageHeader, Panel, Toggle } from "@/components/aegis/ui";

export default function SettingsPage() {
  const [t, setT] = useState({ synth: 70, incon: 45 });
  const [n, setN] = useState({ email: true, push: true, live: true, digest: false });
  const [explain, setExplain] = useState(true);

  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Settings"
        subtitle="Personalize how AEGIS works for you."
        actions={<Btn variant="accent" onClick={() => toast.success("Settings saved")}>Save changes</Btn>}
      />
      <div className="space-y-6">
        <Panel title="Profile">
          <div className="grid gap-4 md:grid-cols-2">
            {[["Full name", "AEGIS Analyst"], ["Email", "analyst@aegis-security.internal"], ["Organization", "AEGIS Security Operations"], ["Role", "Forensic Analyst"]].map(([l, v]) => (
              <label key={l} className="text-sm">
                <span className="caption mb-1 block">{l}</span>
                <input defaultValue={v} className="h-9 w-full rounded-lg border bg-background px-3 outline-none focus:border-accent" />
              </label>
            ))}
          </div>
        </Panel>
        <Panel title="Verdict thresholds" subtitle="When should content be called Synthetic or Inconclusive?">
          {([["synth", "Flag as Synthetic above"], ["incon", "Inconclusive above"]] as const).map(([k, l]) => (
            <div key={k} className="mb-4">
              <div className="mb-1 flex justify-between text-sm">
                <span>{l}</span>
                <span className="mono">{t[k]}%</span>
              </div>
              <input type="range" min={10} max={95} value={t[k]} onChange={(e) => setT({ ...t, [k]: +e.target.value })} className="w-full accent-[var(--color-accent)]" />
            </div>
          ))}
          <label className="flex items-center justify-between border-t pt-4 text-sm">
            Always explain why detectors were chosen
            <Toggle checked={explain} onChange={setExplain} label="Explain" />
          </label>
        </Panel>
        <Panel title="Notifications">
          {([["email", "Email me when an analysis finishes"], ["push", "Browser notifications"], ["live", "Instant alerts for live feed manipulation"], ["digest", "Weekly summary"]] as const).map(([k, l]) => (
            <label key={k} className="flex items-center justify-between border-b py-3 text-sm last:border-0">
              {l}
              <Toggle checked={n[k]} onChange={(v) => setN({ ...n, [k]: v })} label={l} />
            </label>
          ))}
        </Panel>
        <Panel title="Data & privacy">
          <label className="text-sm">
            <span className="caption mb-1 block">Keep uploaded files for</span>
            <select className="h-9 rounded-lg border bg-background px-3">
              <option>30 days</option>
              <option>90 days</option>
              <option>1 year</option>
              <option>Delete after report</option>
            </select>
          </label>
          <p className="caption mt-3">Reports and their SHA-256 integrity stamps are kept permanently for chain-of-custody.</p>
        </Panel>
      </div>
    </div>
  );
}

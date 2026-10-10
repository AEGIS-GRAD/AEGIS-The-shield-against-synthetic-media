"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, UploadCloud, Cctv, FileBarChart, Code2, Settings, Search, Bell,
  ChevronLeft, ChevronDown, ChevronUp, Palette, Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { timeline } from "@/lib/mock";

const nav = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/analyze", label: "Offline Analysis", icon: UploadCloud },
  { href: "/live", label: "Live Surveillance", icon: Cctv },
  { href: "/reports", label: "Reports", icon: FileBarChart },
  { href: "/developer", label: "Developer", icon: Code2 },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden>
        <path d="M16 2 4 7v8c0 7.5 5.1 13.4 12 15 6.9-1.6 12-7.5 12-15V7L16 2Z" fill="var(--color-sidebar-primary)" />
        <path d="M8 16h3l2-5 3 10 2-7 1.5 2H24" fill="none" stroke="var(--color-sidebar-primary-foreground)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!collapsed && (
        <div className="leading-tight">
          <div className="text-[15px] font-bold tracking-[0.18em] text-sidebar-accent-foreground">AEGIS</div>
          <div className="text-[10px] text-sidebar-foreground/70">Generative Integrity Screening</div>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [footerOpen, setFooterOpen] = useState(true);
  const pathname = usePathname() || "/";
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const liveMode = pathname.startsWith("/live");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className={cn("hidden shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-soft md:flex", collapsed ? "w-[72px]" : "w-60")}>
        <div className="flex h-16 items-center justify-between px-4">
          <Logo collapsed={collapsed} />
        </div>
        <nav className="mt-2 flex flex-1 flex-col gap-1 px-3">
          {nav.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} title={label}
              className={cn("relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-soft hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                isActive(href) && "bg-sidebar-accent text-sidebar-accent-foreground")}>
              {isActive(href) && <span className="absolute left-0 top-2 bottom-2 w-1 rounded-r bg-sidebar-primary" />}
              <Icon className="size-[18px] shrink-0" />
              {!collapsed && label}
            </Link>
          ))}
        </nav>
        <div className="space-y-1 border-t border-sidebar-border p-3">
          <Link href="/developer/security" className={cn("flex items-center gap-3 rounded-lg px-3 py-2 text-xs hover:bg-sidebar-accent", isActive("/developer/security") && "bg-sidebar-accent text-sidebar-accent-foreground")}>
            <Activity className="size-4 shrink-0" />{!collapsed && "Security & Health"}
          </Link>
          <button onClick={() => setCollapsed(!collapsed)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-xs hover:bg-sidebar-accent">
            <ChevronLeft className={cn("size-4 shrink-0 transition-soft", collapsed && "rotate-180")} />{!collapsed && "Collapse"}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-4 border-b bg-card/80 px-6 backdrop-blur">
          <div className="relative max-w-sm flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input placeholder="Search job ID or filename…" className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-sm outline-none transition-soft focus:border-accent focus:ring-2 focus:ring-accent/20" />
          </div>
          <div className="flex rounded-lg border bg-secondary p-0.5 text-sm font-medium">
            <Link href="/analyze" className={cn("rounded-md px-3 py-1.5 transition-soft", !liveMode ? "bg-card text-primary shadow-soft" : "text-muted-foreground")}>Offline Analysis</Link>
            <Link href="/live" className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-soft", liveMode ? "bg-card text-primary shadow-soft" : "text-muted-foreground")}>
              <span className="size-1.5 rounded-full bg-synthetic animate-live" />Live Surveillance
            </Link>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <Link href="/developer/security" className="hidden items-center gap-1.5 rounded-full bg-inconclusive-soft px-3 py-1.5 text-xs font-medium text-inconclusive-ink lg:flex">
              <Activity className="size-3.5" /> 2 detectors degraded
            </Link>
            <button className="relative grid size-9 place-items-center rounded-lg text-primary hover:bg-secondary" aria-label="Notifications, 4 unread">
              <Bell className="size-[18px]" />
              <span className="absolute right-1 top-1 grid size-4 place-items-center rounded-full bg-accent text-[10px] font-bold text-accent-foreground">4</span>
            </button>
            <button className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 hover:bg-secondary">
              <span className="grid size-8 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">AE</span>
              <span className="hidden text-left leading-tight xl:block">
                <span className="block text-sm font-medium text-primary">AEGIS Analyst</span>
                <span className="caption block">Forensic Operations</span>
              </span>
              <ChevronDown className="size-4 text-muted-foreground" />
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1360px] px-6 py-7">{children}</div>
        </main>

        <footer className="shrink-0 border-t bg-card">
          <div className="flex items-center gap-4 px-6 py-2 text-xs">
            <button onClick={() => setFooterOpen(!footerOpen)} className="flex items-center gap-1.5 font-semibold text-primary">
              {footerOpen ? <ChevronDown className="size-3.5" /> : <ChevronUp className="size-3.5" />} Recent activity
            </button>
            {footerOpen && (
              <div className="flex min-w-0 flex-1 gap-6 overflow-hidden">
                {timeline.slice(0, 3).map((e) => (
                  <span key={e.t + e.text} className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <span className="mono text-[11px]">{e.t}</span>
                    <span className="truncate">{e.text}</span>
                  </span>
                ))}
              </div>
            )}
            <Link href="/developer/logs" className="ml-auto shrink-0 font-medium text-accent hover:underline">View all logs →</Link>
          </div>
        </footer>
      </div>
    </div>
  );
}

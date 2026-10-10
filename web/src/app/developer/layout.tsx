"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, ShieldHalf, ScrollText, Gauge, Webhook, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";

const tabs = [
  { href: "/developer", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/developer/security", label: "Security", icon: ShieldHalf },
  { href: "/developer/logs", label: "Logs", icon: ScrollText },
  { href: "/developer/telemetry", label: "Telemetry", icon: Gauge },
  { href: "/developer/webhooks", label: "Webhooks", icon: Webhook },
  { href: "/developer/api", label: "API configuration", icon: KeyRound },
] as const;

export default function DevLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/developer";

  const isActive = (href: string, exact?: boolean) => {
    if (exact) return pathname === href;
    return pathname.startsWith(href);
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="caption font-medium uppercase tracking-wider">Developer console</p>
          <h1 className="mt-1">Engineering & operations</h1>
        </div>
        <span className="rounded-full bg-info-soft px-3 py-1 text-xs font-medium text-info-ink">
          Visible to developers only
        </span>
      </div>
      <nav className="mb-6 flex flex-wrap gap-1 border-b">
        {tabs.map(({ href, label, icon: Icon, ...t }) => {
          const active = isActive(href, "exact" in t && t.exact);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-soft",
                active
                  ? "border-accent text-primary font-semibold"
                  : "border-transparent text-muted-foreground hover:text-primary"
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}

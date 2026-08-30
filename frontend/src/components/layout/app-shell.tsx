"use client";

import {
  BarChart3,
  Building2,
  ClipboardCheck,
  FileText,
  FolderSearch,
  LayoutDashboard,
  Settings,
  Sparkles
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/analyses", label: "Analyses", icon: FolderSearch },
  { href: "/review", label: "Review Queue", icon: ClipboardCheck },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings }
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen text-ink-950">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-72 border-r border-white/10 bg-graphite-980/92 backdrop-blur-xl lg:block">
        <div className="border-b border-white/10 px-5 py-5">
          <Link href="/" className="flex items-center gap-3 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500">
            <span className="grid h-10 w-10 place-items-center rounded-md border border-ledger-200/25 bg-ledger-500/12 text-ledger-200">
              <BarChart3 aria-hidden="true" className="h-5 w-5" />
            </span>
            <span>
              <span className="block text-sm font-semibold uppercase text-ink-950">DeltaLedger AI</span>
              <span className="block text-xs text-ink-700">Disclosure intelligence</span>
            </span>
          </Link>
          <div className="mt-5 rounded-md border border-white/10 bg-white/[0.04] p-3">
            <div className="flex items-center gap-2 text-xs font-medium text-ledger-200">
              <Sparkles aria-hidden="true" className="h-3.5 w-3.5" />
              AI-assisted analysis
            </div>
            <p className="mt-2 text-xs leading-5 text-ink-700">
              SEC evidence, XBRL verification, and analyst review in one workflow.
            </p>
          </div>
        </div>
        <nav className="space-y-1 px-3 py-4" aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-ink-700 outline-none transition hover:bg-white/[0.06] hover:text-ink-950 focus-visible:ring-2 focus-visible:ring-ledger-500",
                  active && "border border-ledger-200/20 bg-ledger-500/12 text-ledger-100 shadow-glow"
                )}
              >
                <Icon aria-hidden="true" className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="lg:pl-72">
        <header className="sticky top-0 z-10 border-b border-white/10 bg-graphite-980/80 backdrop-blur-xl no-print">
          <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
            <div>
              <p className="text-xs font-semibold uppercase text-ledger-200/80">Financial Disclosure Intelligence</p>
              <h1 className="text-lg font-semibold text-ink-950">Evidence-backed filing change analysis</h1>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-700">
              <span className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1">Hybrid retrieval</span>
              <span className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-1">Human review</span>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto border-t border-white/10 px-3 py-2 lg:hidden" aria-label="Mobile navigation">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "min-w-fit rounded-md px-3 py-2 text-xs text-ink-700 outline-none focus-visible:ring-2 focus-visible:ring-ledger-500",
                    active && "bg-ledger-500/12 text-ledger-100"
                  )}
                >
                  <Icon aria-hidden="true" className="mb-1 h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-6">{children}</main>
      </div>
    </div>
  );
}

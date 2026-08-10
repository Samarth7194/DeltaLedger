"use client";

import {
  BarChart3,
  Building2,
  ClipboardCheck,
  FileText,
  FolderSearch,
  LayoutDashboard,
  Settings
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
    <div className="min-h-screen bg-stone-50 text-ink-950">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-stone-200 bg-white lg:block">
        <div className="flex h-16 items-center border-b border-stone-200 px-5">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-ledger-700">
              DeltaLedger
            </div>
            <div className="text-xs text-stone-500">Analyst Workspace</div>
          </div>
        </div>
        <nav className="space-y-1 px-3 py-4" aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-stone-600 outline-none transition hover:bg-stone-100 focus-visible:ring-2 focus-visible:ring-ledger-600",
                  active && "bg-ledger-100 text-ledger-700"
                )}
              >
                <Icon aria-hidden="true" className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/95 backdrop-blur no-print">
          <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-stone-500">
                Financial Disclosure Intelligence
              </p>
              <h1 className="text-lg font-semibold text-ink-950">
                What changed, what is supported, and what requires review
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
              <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
                Evidence-first
              </span>
              <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
                Human-reviewed
              </span>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto border-t border-stone-100 px-3 py-2 lg:hidden">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <Link key={item.href} href={item.href} className="rounded-md px-3 py-2 text-xs">
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

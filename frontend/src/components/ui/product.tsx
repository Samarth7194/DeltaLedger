import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  children
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-md border border-white/10 bg-gradient-to-br from-white/[0.08] via-graphite-900/80 to-ledger-900/70 p-5 shadow-glow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          {eyebrow ? <p className="text-xs font-semibold uppercase text-ledger-200/85">{eyebrow}</p> : null}
          <h1 className="mt-1 text-2xl font-semibold text-ink-950 sm:text-3xl">{title}</h1>
          {description ? <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-700">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children ? <div className="mt-5">{children}</div> : null}
    </section>
  );
}

export function SignalPill({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const tones = {
    neutral: "border-white/10 bg-white/[0.06] text-ink-800",
    success: "border-emerald-300/25 bg-emerald-400/10 text-emerald-200",
    warning: "border-amber-300/30 bg-amber-400/10 text-amber-200",
    danger: "border-red-300/30 bg-red-400/10 text-red-200"
  };
  return <span className={cn("inline-flex rounded-md border px-2 py-1 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function DataRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
      <div className="text-xs font-semibold uppercase text-ink-700">{label}</div>
      <div className="mt-1 text-sm font-medium text-ink-950">{value}</div>
    </div>
  );
}

export function Kicker({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold uppercase text-ledger-200/80">{children}</div>;
}

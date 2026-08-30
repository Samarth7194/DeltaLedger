import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Metric({
  label,
  value,
  detail,
  icon,
  tone = "neutral"
}: {
  label: string;
  value: string | number;
  detail?: string;
  icon?: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const toneClasses = {
    neutral: "from-white/[0.07] to-white/[0.03] text-ledger-200",
    success: "from-emerald-400/[0.14] to-white/[0.03] text-emerald-200",
    warning: "from-amber-400/[0.15] to-white/[0.03] text-amber-200",
    danger: "from-red-400/[0.14] to-white/[0.03] text-red-200"
  };
  return (
    <div className={cn("rounded-md border border-white/10 bg-gradient-to-br p-4 shadow-panel", toneClasses[tone])}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase text-ink-700">{label}</div>
        {icon ? <div className="text-current">{icon}</div> : null}
      </div>
      <div className="mt-3 text-2xl font-semibold text-ink-950">{value}</div>
      {detail ? <div className="mt-1 text-sm text-ink-700">{detail}</div> : null}
    </div>
  );
}

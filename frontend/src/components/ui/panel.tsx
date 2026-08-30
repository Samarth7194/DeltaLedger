import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <section
      {...props}
      className={cn(
        "rounded-md border border-white/10 bg-graphite-900/82 p-4 shadow-panel backdrop-blur-xl",
        className
      )}
    />
  );
}

export function PanelHeader({
  title,
  eyebrow,
  action,
  detail
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  detail?: string;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        {eyebrow ? <p className="text-xs font-semibold uppercase text-ledger-200/80">{eyebrow}</p> : null}
        <h2 className="text-base font-semibold text-ink-950">{title}</h2>
        {detail ? <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-700">{detail}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

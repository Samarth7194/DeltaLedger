import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <section
      {...props}
      className={cn("rounded-md border border-stone-200 bg-white p-4 shadow-panel", className)}
    />
  );
}

export function PanelHeader({
  title,
  eyebrow,
  action
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        {eyebrow ? (
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
            {eyebrow}
          </p>
        ) : null}
        <h2 className="text-base font-semibold text-ink-950">{title}</h2>
      </div>
      {action}
    </div>
  );
}

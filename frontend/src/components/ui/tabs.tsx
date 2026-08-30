"use client";

import { cn } from "@/lib/utils";

export type TabItem = {
  id: string;
  label: string;
};

export function Tabs({
  tabs,
  active,
  onChange
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="no-print flex gap-1 overflow-x-auto border-b border-white/10 px-2" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-500",
            active === tab.id
              ? "border-ledger-200 text-ledger-100"
              : "border-transparent text-ink-700 hover:text-ink-950"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

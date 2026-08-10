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
    <div className="no-print flex gap-1 overflow-x-auto border-b border-stone-200" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ledger-600",
            active === tab.id
              ? "border-ledger-700 text-ledger-700"
              : "border-transparent text-stone-600 hover:text-ink-950"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

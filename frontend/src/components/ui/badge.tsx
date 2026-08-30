import { labelFor, statusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

export function Badge({ value, label }: { value?: string | null; label?: string }) {
  const tone = statusTone(value);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium",
        tone === "success" && "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
        tone === "warning" && "border-amber-300/35 bg-amber-400/10 text-amber-200",
        tone === "danger" && "border-red-300/35 bg-red-400/10 text-red-200",
        tone === "neutral" && "border-white/10 bg-white/[0.06] text-ink-800"
      )}
    >
      {label ?? labelFor(value)}
    </span>
  );
}

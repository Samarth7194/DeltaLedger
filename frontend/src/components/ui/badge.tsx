import { labelFor, statusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

export function Badge({ value, label }: { value?: string | null; label?: string }) {
  const tone = statusTone(value);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium",
        tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-800",
        tone === "warning" && "border-amber-200 bg-amber-50 text-amber-800",
        tone === "danger" && "border-red-200 bg-red-50 text-red-800",
        tone === "neutral" && "border-stone-200 bg-stone-100 text-stone-700"
      )}
    >
      {label ?? labelFor(value)}
    </span>
  );
}

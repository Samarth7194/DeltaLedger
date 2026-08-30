import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
};

export function Button({ className, variant = "secondary", ...props }: ButtonProps) {
  const variants = {
    primary: "border-ledger-500 bg-ledger-500 text-graphite-980 hover:bg-ledger-200",
    secondary: "border-white/12 bg-white/[0.06] text-ink-950 hover:bg-white/[0.1]",
    ghost: "border-transparent bg-transparent text-ink-900 hover:bg-white/[0.07]",
    danger: "border-red-300/40 bg-red-500/15 text-red-100 hover:bg-red-500/25"
  };
  return (
    <button
      {...props}
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-500 disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className
      )}
    />
  );
}

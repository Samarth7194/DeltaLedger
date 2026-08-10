import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
};

export function Button({ className, variant = "secondary", ...props }: ButtonProps) {
  const variants = {
    primary: "border-ledger-700 bg-ledger-700 text-white hover:bg-ledger-600",
    secondary: "border-stone-300 bg-white text-ink-950 hover:bg-stone-100",
    ghost: "border-transparent bg-transparent text-ink-950 hover:bg-stone-100",
    danger: "border-red-700 bg-red-700 text-white hover:bg-red-600"
  };
  return (
    <button
      {...props}
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-ledger-600 disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className
      )}
    />
  );
}

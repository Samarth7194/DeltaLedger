import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

import { AppShell } from "@/components/layout/app-shell";
import { QueryProvider } from "@/providers/query-provider";

export const metadata: Metadata = {
  title: "DeltaLedger AI",
  description: "Disclosure consistency and evidence review workspace"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}

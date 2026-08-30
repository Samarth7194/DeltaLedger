import Link from "next/link";

import { Panel } from "@/components/ui/panel";

export default function NotFoundPage() {
  return (
    <Panel className="mx-auto max-w-2xl">
      <h1 className="text-lg font-semibold text-ink-950">Page not found</h1>
      <p className="mt-2 text-sm text-ink-700">
        This workspace route does not exist or is not available in the current build.
      </p>
      <Link
        className="mt-4 inline-flex min-h-9 items-center justify-center rounded-md border border-white/12 bg-white/[0.06] px-3 py-2 text-sm font-medium text-ink-950 transition hover:bg-white/[0.1]"
        href="/"
      >
        Return to dashboard
      </Link>
    </Panel>
  );
}

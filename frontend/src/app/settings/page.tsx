import { apiBaseUrl } from "@/lib/api/client";

import { AuthTokenSettings } from "@/components/settings/auth-token-settings";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { PageHeader, SignalPill } from "@/components/ui/product";

export default function SettingsPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Runtime configuration"
        title="Settings"
        description="Manage browser-side API access for the deployed DeltaLedger frontend and verify which backend this workspace is connected to."
      >
        <div className="flex flex-wrap gap-2">
          <SignalPill>Bearer auth</SignalPill>
          <SignalPill>Production API</SignalPill>
        </div>
      </PageHeader>
      <Panel>
        <PanelHeader title="Connection" eyebrow="Environment" />
        <div className="grid gap-3 text-sm">
          <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
            <h3 className="font-semibold text-ink-950">API Base URL</h3>
            <p className="mt-1 break-all font-mono text-xs text-ink-700">{apiBaseUrl()}</p>
          </div>
          <AuthTokenSettings />
        </div>
      </Panel>
    </div>
  );
}

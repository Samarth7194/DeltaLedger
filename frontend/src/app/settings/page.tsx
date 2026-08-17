import { apiBaseUrl } from "@/lib/api/client";

import { AuthTokenSettings } from "@/components/settings/auth-token-settings";
import { Panel, PanelHeader } from "@/components/ui/panel";

export default function SettingsPage() {
  return (
    <Panel>
      <PanelHeader title="Settings" eyebrow="Environment" />
      <div className="grid gap-3 text-sm">
        <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
          <h3 className="font-semibold">API Base URL</h3>
          <p className="mt-1 font-mono text-xs text-stone-700">{apiBaseUrl()}</p>
        </div>
        <AuthTokenSettings />
      </div>
    </Panel>
  );
}

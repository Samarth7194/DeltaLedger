import { apiBaseUrl } from "@/lib/api/client";

import { Panel, PanelHeader } from "@/components/ui/panel";

export default function SettingsPage() {
  return (
    <Panel>
      <PanelHeader title="Settings" eyebrow="Environment" />
      <dl className="grid gap-3 text-sm">
        <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
          <dt className="font-semibold">API Base URL</dt>
          <dd className="mt-1 font-mono text-xs text-stone-700">{apiBaseUrl()}</dd>
        </div>
      </dl>
    </Panel>
  );
}

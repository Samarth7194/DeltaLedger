import { Panel } from "@/components/ui/panel";

export default function LoadingPage() {
  return (
    <Panel className="mx-auto max-w-2xl">
      <div className="h-4 w-40 animate-pulse rounded bg-stone-200" />
      <div className="mt-4 h-3 w-full animate-pulse rounded bg-stone-100" />
      <div className="mt-2 h-3 w-2/3 animate-pulse rounded bg-stone-100" />
    </Panel>
  );
}

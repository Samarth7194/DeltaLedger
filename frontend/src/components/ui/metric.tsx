export function Metric({
  label,
  value,
  detail
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <div className="rounded-md border border-stone-200 bg-white p-4 shadow-panel">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-ink-950">{value}</div>
      {detail ? <div className="mt-1 text-sm text-stone-600">{detail}</div> : null}
    </div>
  );
}

export function formatDate(value?: string | null) {
  if (!value) {
    return "Not available";
  }
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return "Not available";
  }
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit"
  }).format(parsed);
}

export function formatNumber(value?: number | string | null, digits = 2) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(numeric);
}

export function formatPercent(value?: number | string | null) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  return `${formatNumber(numeric, 2)}%`;
}

export function formatPercentagePoint(value?: number | string | null) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  const prefix = numeric > 0 ? "+" : "";
  return `${prefix}${formatNumber(numeric, 2)} percentage points`;
}

export function formatBasisPoints(value?: number | string | null) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  return `${formatNumber(numeric, 0)} bps`;
}

export function formatCurrency(value?: number | string | null) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  const absolute = Math.abs(numeric);
  const divisor = absolute >= 1_000_000_000 ? 1_000_000_000 : absolute >= 1_000_000 ? 1_000_000 : 1;
  const suffix = divisor === 1_000_000_000 ? "B" : divisor === 1_000_000 ? "M" : "";
  return `$${formatNumber(numeric / divisor, divisor === 1 ? 2 : 1)}${suffix}`;
}

export function formatConfidence(value?: number | string | null) {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "Not available";
  }
  return `${Math.round(numeric * 100)}% confidence`;
}

export function compactJson(value: unknown) {
  if (
    !value ||
    (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0)
  ) {
    return "No structured evidence supplied.";
  }
  return JSON.stringify(value, null, 2);
}

export function toNumber(value?: number | string | null) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

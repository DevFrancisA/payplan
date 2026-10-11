const currencyFormatters = new Map<string, Intl.NumberFormat>();

export function formatMoney(amount: string, currency = "USD"): string {
  let formatter = currencyFormatters.get(currency);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", { style: "currency", currency });
    currencyFormatters.set(currency, formatter);
  }
  // Values arrive as exact decimal strings; Number is only used for display formatting.
  return formatter.format(Number(amount));
}

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/** Formats an ISO calendar date ("2026-10-01") without shifting it into the local timezone. */
export function formatDate(isoDate: string): string {
  return dateFormatter.format(new Date(`${isoDate}T00:00:00Z`));
}

export function todayIso(now = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** Integer percentage of `part / whole`, computed in cents to avoid float drift. */
export function percentOf(part: string, whole: string): number {
  const toCents = (v: string) => Math.round(Number(v) * 100);
  const total = toCents(whole);
  return total === 0 ? 0 : Math.round((toCents(part) / total) * 100);
}

export const FREQUENCY_LABEL = {
  weekly: "week",
  biweekly: "2 weeks",
  monthly: "month",
} as const;

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

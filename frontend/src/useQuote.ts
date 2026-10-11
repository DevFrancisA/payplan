import { useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { PlanTerms, Quote } from "./types";

const MONEY = /^\d{1,6}(\.\d{1,2})?$/;

export function validateTerms(terms: PlanTerms): string | null {
  if (!MONEY.test(terms.principal)) return "Enter an amount like 1200 or 1200.00.";
  const principal = Number(terms.principal);
  if (principal < 1 || principal > 100_000) return "Amount must be between $1 and $100,000.";
  const apr = Number(terms.apr);
  if (terms.apr === "" || Number.isNaN(apr) || apr < 0 || apr > 36) return "APR must be between 0% and 36%.";
  if (!terms.first_due_date) return "Choose a first payment date.";
  return null;
}

/** Fetches a quote whenever the terms change, debounced and cancelling stale requests. */
export function useQuote(terms: PlanTerms) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const invalid = validateTerms(terms);
    if (invalid) {
      setError(invalid);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .quote(terms, controller.signal)
        .then((q) => {
          setQuote(q);
          setError(null);
        })
        .catch((err) => {
          if (err.name === "AbortError") return;
          setError(err instanceof ApiError ? err.message : "Could not calculate this plan.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [terms]);

  return { quote: error ? null : quote, loading, error };
}

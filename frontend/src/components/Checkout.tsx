import { useRef, useState } from "react";

import { api, ApiError } from "../api";
import { formatMoney, newIdempotencyKey } from "../format";
import type { PlanTerms, Quote } from "../types";
import { PaymentMethodSelect } from "./PaymentMethodSelect";

interface Props {
  terms: PlanTerms;
  quote: Quote | null;
  onComplete: (planId: string) => void;
}

export function Checkout({ terms, quote, onComplete }: Props) {
  const [method, setMethod] = useState("pm_card_visa");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per checkout attempt. If the request is retried (double click, flaky network)
  // the same key is sent, so the server returns the original plan instead of a new one.
  const attempt = useRef<{ terms: string; key: string } | null>(null);

  async function checkout() {
    const termsKey = JSON.stringify(terms);
    if (attempt.current?.terms !== termsKey) {
      attempt.current = { terms: termsKey, key: newIdempotencyKey() };
    }
    setSubmitting(true);
    setError(null);
    try {
      const plan = await api.createPlan(terms, attempt.current.key);
      attempt.current = null;
      // The first installment is charged at checkout. A decline is not fatal: the plan
      // page shows the failure and lets the shopper retry with another card.
      await api.payInstallment(plan.id, 1, method, newIdempotencyKey()).catch(() => undefined);
      onComplete(plan.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Checkout failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const first = quote?.installments[0];

  return (
    <section className="card checkout">
      <h2 className="card-title">Checkout</h2>
      <PaymentMethodSelect value={method} onChange={setMethod} disabled={submitting} />
      {error && <p className="notice error">{error}</p>}
      <button className="primary" onClick={checkout} disabled={!quote || submitting}>
        {submitting ? "Processing…" : first ? `Confirm plan · pay ${formatMoney(first.amount)}` : "Confirm plan"}
      </button>
      <p className="fine-print">
        You'll see every payment date and amount before you commit. Sandbox mode: no real money moves.
      </p>
    </section>
  );
}

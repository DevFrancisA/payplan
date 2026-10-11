import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api";
import { formatDate, formatMoney, newIdempotencyKey, percentOf } from "../format";
import type { Payment, Plan } from "../types";
import { PaymentMethodSelect } from "./PaymentMethodSelect";

interface Props {
  planId: string;
  onNewPlan: () => void;
}

export function PlanView({ planId, onNewPlan }: Props) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [method, setMethod] = useState("pm_card_visa");
  const [paying, setPaying] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Installment number -> key of the attempt in flight. Kept when the outcome is unknown
  // so the next click retries the *same* payment rather than starting a second one.
  const pendingKeys = useRef(new Map<number, string>());

  const refresh = useCallback(async () => {
    try {
      const [p, history] = await Promise.all([api.getPlan(planId), api.listPayments(planId)]);
      setPlan(p);
      setPayments(history);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this plan.");
    }
  }, [planId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function pay(number: number) {
    const key = pendingKeys.current.get(number) ?? newIdempotencyKey();
    pendingKeys.current.set(number, key);
    setPaying(number);
    setError(null);
    try {
      const payment = await api.payInstallment(planId, number, method, key);
      pendingKeys.current.delete(number);
      if (payment.status === "failed") setError(payment.failure_message ?? "Payment failed.");
    } catch (err) {
      if (!(err instanceof ApiError) || !err.retryable) pendingKeys.current.delete(number);
      setError(err instanceof ApiError ? err.message : "Payment failed.");
    } finally {
      setPaying(null);
      await refresh();
    }
  }

  if (!plan) {
    return <section className="card">{error ? <p className="notice error">{error}</p> : <p>Loading plan…</p>}</section>;
  }

  const progress = percentOf(plan.amount_paid, plan.total_cost);
  const next = plan.installments.find((i) => i.status === "pending");

  return (
    <div className="plan-layout">
      <section className="card plan-summary">
        <div className="plan-head">
          <div>
            <h2 className="card-title">Your payment plan</h2>
            <code className="plan-id">{plan.id}</code>
          </div>
          <span className={`chip ${plan.status}`}>{plan.status}</span>
        </div>

        <div className="progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${progress}%` }} />
        </div>
        <dl className="stats">
          <div>
            <dt>Paid</dt>
            <dd>{formatMoney(plan.amount_paid, plan.currency)}</dd>
          </div>
          <div>
            <dt>Remaining balance</dt>
            <dd>{formatMoney(plan.remaining_balance, plan.currency)}</dd>
          </div>
          <div>
            <dt>Total cost</dt>
            <dd>{formatMoney(plan.total_cost, plan.currency)}</dd>
          </div>
          <div>
            <dt>Next due</dt>
            <dd>{next ? formatDate(next.due_date) : "—"}</dd>
          </div>
        </dl>

        {plan.status === "active" && (
          <PaymentMethodSelect value={method} onChange={setMethod} disabled={paying !== null} />
        )}
        {error && <p className="notice error">{error}</p>}

        <ul className="installments">
          {plan.installments.map((i) => (
            <li key={i.number} className={i.status}>
              <span className="num-badge">{i.number}</span>
              <div>
                <strong>{formatMoney(i.amount, plan.currency)}</strong>
                <small>
                  {i.status === "paid" && i.paid_at ? `Paid ${formatDate(i.paid_at.slice(0, 10))}` : `Due ${formatDate(i.due_date)}`}
                </small>
              </div>
              {i.status === "paid" ? (
                <span className="chip paid">paid</span>
              ) : (
                <button className="secondary" onClick={() => pay(i.number)} disabled={paying !== null}>
                  {paying === i.number ? "Paying…" : "Pay now"}
                </button>
              )}
            </li>
          ))}
        </ul>

        <button className="link" onClick={onNewPlan}>
          ← Simulate another plan
        </button>
      </section>

      <section className="card history">
        <h2 className="card-title">Payment attempts</h2>
        {payments.length === 0 ? (
          <p className="muted">No payments yet.</p>
        ) : (
          <ol>
            {[...payments].reverse().map((p) => (
              <li key={p.id} className={p.status}>
                <div className="history-row">
                  <span>
                    #{p.installment_number} · {formatMoney(p.amount, p.currency)}
                  </span>
                  <span className={`chip ${p.status}`}>{p.status}</span>
                </div>
                <small className="muted">
                  {p.payment_method} · {p.gateway_attempts} gateway attempt{p.gateway_attempts === 1 ? "" : "s"}
                  {p.gateway_reference && ` · ${p.gateway_reference}`}
                </small>
                {p.failure_message && <small className="failure">{p.failure_message}</small>}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

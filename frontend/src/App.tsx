import { useEffect, useState } from "react";

import { Checkout } from "./components/Checkout";
import { PlanView } from "./components/PlanView";
import { QuotePanel } from "./components/QuotePanel";
import { TermsForm } from "./components/TermsForm";
import { todayIso } from "./format";
import type { PlanTerms } from "./types";
import { useQuote } from "./useQuote";

const DEFAULT_TERMS: PlanTerms = {
  principal: "1200.00",
  installment_count: 4,
  frequency: "biweekly",
  apr: "0",
  first_due_date: todayIso(),
};

function planFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("plan");
}

export function App() {
  const [terms, setTerms] = useState<PlanTerms>(DEFAULT_TERMS);
  const [planId, setPlanId] = useState<string | null>(planFromUrl);
  const { quote, loading, error } = useQuote(terms);

  useEffect(() => {
    const onPopState = () => setPlanId(planFromUrl());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function openPlan(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("plan", id);
    else url.searchParams.delete("plan");
    window.history.pushState(null, "", url);
    setPlanId(id);
  }

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/" onClick={(e) => (e.preventDefault(), openPlan(null))}>
          <img src="/favicon.svg" alt="" width={28} height={28} />
          PayPlan
        </a>
        <span className="badge">Sandbox</span>
      </header>

      {planId ? (
        <PlanView planId={planId} onNewPlan={() => openPlan(null)} />
      ) : (
        <>
          <div className="intro">
            <h1>Know exactly what you'll pay before you check out.</h1>
            <p>Every installment date, the total cost, and your remaining balance after each payment.</p>
          </div>
          <main className="checkout-layout">
            <TermsForm terms={terms} onChange={setTerms} />
            <QuotePanel quote={quote} loading={loading} error={error} />
            <Checkout terms={terms} quote={quote} onComplete={openPlan} />
          </main>
        </>
      )}
    </div>
  );
}

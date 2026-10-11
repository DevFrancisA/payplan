import { useEffect, useState } from "react";

import { api } from "../api";
import type { SandboxMethod } from "../types";

const LABELS: Record<string, string> = {
  pm_card_visa: "Visa •••• 4242",
  pm_card_mastercard: "Mastercard •••• 4444",
  pm_card_declined: "Card that gets declined",
  pm_card_insufficient_funds: "Card with insufficient funds",
  pm_card_flaky: "Card behind a flaky network",
  pm_card_processing_error: "Processor outage",
};

interface Props {
  value: string;
  onChange: (token: string) => void;
  disabled?: boolean;
}

export function PaymentMethodSelect({ value, onChange, disabled }: Props) {
  const [methods, setMethods] = useState<SandboxMethod[]>([]);

  useEffect(() => {
    api.sandboxMethods().then(setMethods, () => setMethods([]));
  }, []);

  const selected = methods.find((m) => m.token === value);

  return (
    <label className="field">
      <span>
        Payment method <em className="badge">sandbox</em>
      </span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {(methods.length ? methods : [{ token: value, behavior: "" }]).map((m) => (
          <option key={m.token} value={m.token}>
            {LABELS[m.token] ?? m.token}
          </option>
        ))}
      </select>
      {selected && <small className="hint">{selected.behavior}</small>}
    </label>
  );
}

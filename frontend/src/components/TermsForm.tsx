import type { Frequency, PlanTerms } from "../types";

const PRESETS: { label: string; hint: string; terms: Partial<PlanTerms> }[] = [
  { label: "Pay in 4", hint: "0% APR · every 2 weeks", terms: { installment_count: 4, frequency: "biweekly", apr: "0" } },
  { label: "6 months", hint: "9.99% APR · monthly", terms: { installment_count: 6, frequency: "monthly", apr: "9.99" } },
  { label: "12 months", hint: "19.99% APR · monthly", terms: { installment_count: 12, frequency: "monthly", apr: "19.99" } },
];

const FREQUENCIES: { value: Frequency; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Every 2 weeks" },
  { value: "monthly", label: "Monthly" },
];

interface Props {
  terms: PlanTerms;
  onChange: (terms: PlanTerms) => void;
  disabled?: boolean;
}

export function TermsForm({ terms, onChange, disabled }: Props) {
  const set = <K extends keyof PlanTerms>(key: K, value: PlanTerms[K]) => onChange({ ...terms, [key]: value });
  const activePreset = PRESETS.findIndex(
    (p) =>
      p.terms.installment_count === terms.installment_count &&
      p.terms.frequency === terms.frequency &&
      Number(p.terms.apr) === Number(terms.apr),
  );

  return (
    <fieldset className="card terms" disabled={disabled}>
      <legend className="card-title">Plan terms</legend>

      <label className="field">
        <span>Purchase amount</span>
        <div className="money-input">
          <span aria-hidden>$</span>
          <input
            inputMode="decimal"
            value={terms.principal}
            onChange={(e) => set("principal", e.target.value.replace(/[^\d.]/g, ""))}
            aria-label="Purchase amount in dollars"
          />
        </div>
      </label>

      <div className="presets" role="radiogroup" aria-label="Plan presets">
        {PRESETS.map((preset, i) => (
          <button
            key={preset.label}
            type="button"
            role="radio"
            aria-checked={i === activePreset}
            className={`preset ${i === activePreset ? "active" : ""}`}
            onClick={() => onChange({ ...terms, ...preset.terms })}
          >
            <strong>{preset.label}</strong>
            <small>{preset.hint}</small>
          </button>
        ))}
      </div>

      <div className="field-row">
        <label className="field">
          <span>Installments</span>
          <input
            type="number"
            min={1}
            max={60}
            value={terms.installment_count}
            onChange={(e) => set("installment_count", Math.max(1, Math.min(60, Number(e.target.value) || 1)))}
          />
        </label>
        <label className="field">
          <span>APR %</span>
          <input
            inputMode="decimal"
            value={terms.apr}
            onChange={(e) => set("apr", e.target.value.replace(/[^\d.]/g, ""))}
          />
        </label>
      </div>

      <div className="field">
        <span>Frequency</span>
        <div className="segmented" role="radiogroup" aria-label="Payment frequency">
          {FREQUENCIES.map((f) => (
            <button
              key={f.value}
              type="button"
              role="radio"
              aria-checked={terms.frequency === f.value}
              className={terms.frequency === f.value ? "active" : ""}
              onClick={() => set("frequency", f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <label className="field">
        <span>First payment date</span>
        <input type="date" value={terms.first_due_date} onChange={(e) => set("first_due_date", e.target.value)} />
      </label>
    </fieldset>
  );
}

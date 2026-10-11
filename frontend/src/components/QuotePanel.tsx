import { FREQUENCY_LABEL, formatDate, formatMoney } from "../format";
import type { Quote } from "../types";

interface Props {
  quote: Quote | null;
  loading: boolean;
  error: string | null;
}

export function QuotePanel({ quote, loading, error }: Props) {
  if (error) {
    return (
      <section className="card quote" aria-live="polite">
        <p className="notice error">{error}</p>
      </section>
    );
  }
  if (!quote) {
    return <section className="card quote skeleton" aria-busy="true" />;
  }

  const [first, ...rest] = quote.installments;
  const uniform = rest.every((i) => i.amount === first.amount);
  const regular = rest[0] ?? first;

  return (
    <section className={`card quote ${loading ? "stale" : ""}`} aria-live="polite" aria-busy={loading}>
      <div className="headline">
        {uniform ? (
          <>
            <span className="count">{quote.installment_count} ×</span>
            <span className="amount">{formatMoney(first.amount)}</span>
          </>
        ) : (
          <>
            <span className="amount">{formatMoney(first.amount)}</span>
            <span className="count">
              first, then {rest.length} × {formatMoney(regular.amount)}
            </span>
          </>
        )}
        <span className="cadence">every {FREQUENCY_LABEL[quote.frequency]}</span>
      </div>

      <dl className="stats">
        <div>
          <dt>Total cost</dt>
          <dd>{formatMoney(quote.total_cost)}</dd>
        </div>
        <div>
          <dt>Interest</dt>
          <dd>{formatMoney(quote.total_interest)}</dd>
        </div>
        <div>
          <dt>APR</dt>
          <dd>{quote.apr}%</dd>
        </div>
        <div>
          <dt>Last payment</dt>
          <dd>{formatDate(quote.installments[quote.installments.length - 1].due_date)}</dd>
        </div>
      </dl>

      {quote.installments.length <= 12 && (
        <ol className="timeline" aria-hidden>
          {quote.installments.map((i) => (
            <li key={i.number}>
              <span className="dot" />
              <small>{formatDate(i.due_date).replace(/, \d{4}$/, "")}</small>
            </li>
          ))}
        </ol>
      )}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Due</th>
              <th className="num">Payment</th>
              <th className="num">Interest</th>
              <th className="num">Balance after</th>
            </tr>
          </thead>
          <tbody>
            {quote.installments.map((i) => (
              <tr key={i.number}>
                <td>{i.number}</td>
                <td>{formatDate(i.due_date)}</td>
                <td className="num">{formatMoney(i.amount)}</td>
                <td className="num muted">{formatMoney(i.interest)}</td>
                <td className="num">{formatMoney(i.remaining_balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

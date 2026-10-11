import type { Payment, Plan, PlanTerms, Quote, SandboxMethod } from "./types";

const BASE = `${import.meta.env.VITE_API_URL ?? ""}/api/v1`;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }

  /** Worth retrying with the same Idempotency-Key: the outcome is unknown or still pending. */
  get retryable(): boolean {
    if (this.status === 409) return this.code === "idempotency_key_in_progress";
    return this.status === 0 || this.status >= 500;
  }
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Could not reach the server.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (body?.error) throw new ApiError(response.status, body.error.code, body.error.message);
    const detail = Array.isArray(body?.detail) ? body.detail[0]?.msg : undefined;
    throw new ApiError(response.status, "invalid_request", detail ?? response.statusText);
  }
  return body as T;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * POST with an Idempotency-Key, retrying network failures and in-flight conflicts with the
 * *same* key. Because the key is reused, a retry can never create a second plan or charge.
 */
async function idempotentPost<T>(path: string, body: unknown, key: string, attempts = 4): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await request<T>(path, {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Idempotency-Key": key },
      });
    } catch (err) {
      if (!(err instanceof ApiError) || !err.retryable || attempt >= attempts) throw err;
      await sleep(250 * 2 ** (attempt - 1));
    }
  }
}

export const api = {
  quote: (terms: PlanTerms, signal?: AbortSignal) =>
    request<Quote>("/quotes", { method: "POST", body: JSON.stringify(terms) }, signal),
  createPlan: (terms: PlanTerms, key: string) => idempotentPost<Plan>("/plans", terms, key),
  getPlan: (id: string) => request<Plan>(`/plans/${id}`),
  listPayments: (id: string) => request<Payment[]>(`/plans/${id}/payments`),
  payInstallment: (planId: string, number: number, paymentMethod: string, key: string) =>
    idempotentPost<Payment>(
      `/plans/${planId}/installments/${number}/payments`,
      { payment_method: paymentMethod },
      key,
    ),
  sandboxMethods: () => request<SandboxMethod[]>("/sandbox/payment-methods"),
};

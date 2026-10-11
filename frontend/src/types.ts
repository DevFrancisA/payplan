// Mirrors the API's OpenAPI schemas. Money values are decimal strings ("300.00").

export type Frequency = "weekly" | "biweekly" | "monthly";

export interface PlanTerms {
  principal: string;
  installment_count: number;
  frequency: Frequency;
  apr: string;
  first_due_date: string;
}

export interface InstallmentQuote {
  number: number;
  due_date: string;
  amount: string;
  principal: string;
  interest: string;
  remaining_balance: string;
}

export interface Quote {
  principal: string;
  apr: string;
  frequency: Frequency;
  currency: string;
  installment_count: number;
  total_interest: string;
  total_cost: string;
  installments: InstallmentQuote[];
}

export interface Installment {
  number: number;
  due_date: string;
  amount: string;
  principal: string;
  interest: string;
  status: "pending" | "paid";
  paid_at: string | null;
}

export interface Plan {
  id: string;
  status: "active" | "completed";
  principal: string;
  apr: string;
  frequency: Frequency;
  currency: string;
  installment_count: number;
  total_interest: string;
  total_cost: string;
  amount_paid: string;
  remaining_balance: string;
  created_at: string;
  installments: Installment[];
}

export interface Payment {
  id: string;
  plan_id: string;
  installment_number: number;
  amount: string;
  currency: string;
  payment_method: string;
  status: "pending" | "succeeded" | "failed";
  gateway_attempts: number;
  gateway_reference: string | null;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string;
}

export interface SandboxMethod {
  token: string;
  behavior: string;
}

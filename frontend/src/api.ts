// Typed client for the BAZAAR API. In dev, Vite proxies /api -> :8000.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}

export interface NegotiationStep {
  actor: string;
  price: number;
  note: string;
}

export interface IntentResult {
  intent_text: string;
  max_amount: number;
  max_amount_display: string;
  allowed_categories: string[];
  return_policy_days: number;
  autonomous: boolean;
  expires_at: string;
  confirmable: boolean;
  warnings: string[];
}

export interface Receipt {
  receipt_id: string;
  body: Record<string, unknown>;
  public_key: string;
  signature: string;
}

export interface PurchaseResult {
  mandate_id: string;
  mandate: {
    cap: number;
    cap_display: string;
    categories: string[];
    expires_at: string;
    signature_valid: boolean;
  };
  negotiation: {
    sku: string;
    list_price: number;
    floor_price: number;
    buyer_cap: number;
    agreed_price: number;
    upsold: boolean;
    within_walls: boolean;
    transcript: NegotiationStep[];
  };
  decision: string;
  reason: string;
  risk_score: number;
  effective_decision: string;
  checks: Check[];
  receipt: Receipt;
  razorpay: { status: string; note: string };
}

export interface AttackResult {
  attack_class: string;
  decision: string;
  reason: string;
  detail: string;
  checks: Check[];
  receipt: Receipt;
}

export interface CatalogItem {
  sku: string;
  title: string;
  category: string;
  price: number;
  floor_price: number;
  description: string;
}

export interface AP2Cart {
  payee: string;
  sku: string;
  title: string;
  amount: number;
  amount_display: string;
  currency: string;
  budget: number;
  budget_display: string;
  issuer_kid: string;
  expires_at: string;
}

export interface PriceIntegrity {
  buyer_signed: boolean;
  merchant_signed: boolean;
  attestation_id?: string;
  attested_price?: number;
  attested_price_display?: string;
  reason?: string;
}

export interface AP2Result {
  rail: string;
  verified: boolean;
  stage?: string;
  decision: string;
  reason: string;
  detail?: string;
  variant?: string;
  cart?: AP2Cart;
  txn_id?: string;
  risk_score?: number;
  effective_decision?: string;
  checks?: Check[];
  price_integrity?: PriceIntegrity;
  dual_signed?: boolean;
  receipt?: Receipt;
}

export interface AP2Info {
  rail: string;
  alg: string;
  trusted_credential_providers: string[];
  demo_variants: string[];
}

export const api = {
  health: () => get<{ status: string; razorpay_settlement: string }>("/api/health"),
  catalog: () => get<{ items: CatalogItem[] }>("/api/catalog"),
  intent: (text: string) => post<IntentResult>("/api/intent", { text }),
  purchase: (intent_text: string, upsell: boolean) =>
    post<PurchaseResult>("/api/purchase", { intent_text, upsell }),
  attack: (attack_class: string) => post<AttackResult>("/api/attack", { attack_class }),
  ap2Info: () => get<AP2Info>("/api/ap2/info"),
  ap2Demo: (variant: string) => post<AP2Result>("/api/ap2/demo", { variant }),
  verifyReceipt: (receipt: Receipt) =>
    post<{ valid: boolean }>("/api/receipt/verify", { receipt }),
  audit: () => get<{ length: number; ok: boolean; detail: string }>("/api/audit"),
  benchmark: () => get<{ status: string; scoreboard?: Scoreboard; hint?: string }>("/api/benchmark"),
};

export interface Scoreboard {
  dataset: Record<string, number>;
  four_numbers: {
    adversarial_block_rate: number;
    adversarial_correct_code_rate: number;
    false_block_rate: number;
    held_out_block_rate: number;
    held_out_false_block_rate: number;
    fuzzer_cap_violations: number;
    fuzzer_iterations: number;
    fuzzer_seed: number;
  };
  per_class_blocked: Record<string, number>;
  per_class_correct_code: Record<string, number>;
  escapes: unknown[];
  revenue_axis: {
    aov_baseline_paise: number;
    aov_upsell_paise: number;
    aov_uplift_pct: number;
    share_of_uplift_cleared: number;
  };
  risk_classifier: { precision: number; recall: number; f1: number };
}

export function rupees(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

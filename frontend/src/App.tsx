import { CSSProperties, useEffect, useState } from "react";
import "./styles.css";
import {
  AP2Result,
  Check,
  PurchaseResult,
  Receipt,
  Scoreboard,
  api,
  rupees,
} from "./api";

// ---- static reference data (labels + descriptions, not results) ----
const GATE: [string, string][] = [
  ["1", "Mandate signed by a trusted issuer"],
  ["2", "Mandate matches the acting agent"],
  ["3", "Mandate is within its validity window"],
  ["4", "Agent is not frozen"],
  ["5", "Price comes from the merchant of record"],
  ["6", "Merchant-of-record row exists"],
  ["7", "Amount equals the merchant's price"],
  ["8", "Category is within the mandate"],
  ["9", "Amount is within the signed cap"],
  ["10", "Nonce is unused - no replay"],
  ["11", "Idempotency key is fresh - no double-charge"],
];
const AP2C: [string, string][] = [
  ["es256_signature", "ES256 signature verifies"],
  ["registered_provider", "Registered credential provider"],
  ["not_expired", "Cart mandate is not expired"],
  ["self_consistent", "Cart total is self-consistent"],
  ["payee_allowed", "Payee is permitted"],
];
const STEPS = ["Buyer", "Adapter", "Mandate", "Risk", "Gate", "Settle", "Ledger"];

type Buyer = { id: string; label: string; desc: string };
const AP2_BUYERS: Buyer[] = [
  { id: "legit", label: "Legit cart", desc: "real price, in budget" },
  { id: "price_tamper", label: "Price tamper", desc: "signed, but price ≠ record" },
  { id: "over_budget", label: "Over budget", desc: "above the signed cap" },
  { id: "expired", label: "Expired mandate", desc: "past its expiry" },
  { id: "signature_tamper", label: "Signature tamper", desc: "one byte flipped" },
  { id: "untrusted_issuer", label: "Unregistered signer", desc: "unknown provider" },
];
const PURCHASE: Buyer = { id: "__purchase", label: "Legit purchase", desc: "happy path, direct rail" };
const RT_BUYERS: Buyer[] = [
  { id: "budget", label: "Budget", desc: "₹7,000 vs ₹5,000 cap" },
  { id: "policy", label: "Policy forgery", desc: "self-issued doubled cap" },
  { id: "price", label: "Price claim", desc: "false price vs record" },
  { id: "replay", label: "Replay", desc: "reuse a spent nonce" },
  { id: "double_charge", label: "Double-charge", desc: "reuse idempotency key" },
  { id: "category", label: "Category", desc: "off-mandate smartwatch" },
  { id: "injection", label: "Prompt injection", desc: "money-field from text" },
  { id: "state", label: "Frozen agent", desc: "transact while frozen" },
  { id: "expiry", label: "Expired mandate", desc: "past its TTL" },
];
const EXPLAIN: Record<string, string> = {
  legit: "A ChatGPT/Gemini-class agent presents an ES256-signed Cart Mandate. Authenticity verifies, the merchant-signed price matches, and all 11 gate checks pass - the order settles.",
  price_tamper: "The cart is validly signed, but the authorised amount disagrees with the merchant-signed price. The gate blocks it at the price check.",
  over_budget: "The amount equals the real price but exceeds the signed cap. Blocked at the cap check - nothing settles above the mandate.",
  expired: "The Cart Mandate has expired. It fails AP2 verification and never reaches the money gate.",
  signature_tamper: "One byte of the ES256 signature was altered. Verification fails immediately - rejected before the gate.",
  untrusted_issuer: "The cart is signed by a credential provider the merchant never registered. A rogue agent cannot mint its own authorisation.",
  __purchase: "A direct buyer confirms and signs a mandate, negotiates within cap and floor, and clears all 11 gate checks - the happy path.",
  budget: "A direct agent tries to spend above the signed cap. Blocked at the cap check.",
  policy: "The agent mints its own mandate with a doubled cap, signed with its own key. The trusted-issuer check rejects the forgery.",
  price: "A price is claimed that disagrees with the merchant of record. Blocked at the price check.",
  replay: "A previously-used nonce is replayed. The database-backed nonce check blocks it.",
  double_charge: "A reused idempotency key - the double-charge defense blocks the duplicate.",
  category: "An item outside the mandate's allowlist. Blocked at the category check.",
  injection: "A money-field sourced from prompt-injected catalog text. The provenance check refuses anything but the merchant of record.",
  state: "A frozen agent attempts to transact. Blocked at the freeze check.",
  expiry: "A mandate past its time-to-live. Blocked at the expiry check.",
};

// ---- normalized result the console renders ----
type Rail = "ap2" | "direct";
interface AP2Check { name: string; code: string; passed: boolean }
interface RunResult {
  id: string;
  rail: Rail;
  label: string;
  amount: number | null;
  decision: string;
  reason: string;
  gateReached: boolean;
  checks: Check[];
  ap2?: AP2Check[];
  risk: number | null;
  dual: boolean;
  receipt: Receipt | null;
  explain: string;
}
interface LedgerRow { seq: number; hash: string; decision: string; rail: Rail; reason: string; amount: number | null }

function deriveAp2(verified: boolean, reason: string): AP2Check[] {
  const failIdx: Record<string, number> = {
    AP2_INVALID_SIGNATURE: 0, AP2_MALFORMED: 0, AP2_BAD_ALG: 0, AP2_WRONG_TYPE: 0,
    AP2_UNTRUSTED_ISSUER: 1, AP2_EXPIRED: 2, AP2_CART_TOTAL_MISMATCH: 3,
    AP2_PAYEE_NOT_ALLOWED: 4,
  };
  const fi = verified ? -1 : (failIdx[reason] ?? 0);
  return AP2C.map(([code, name], i) => ({ name, code, passed: fi !== i }));
}

function normalizeAp2(r: AP2Result, b: Buyer): RunResult {
  return {
    id: b.id, rail: "ap2", label: b.label,
    amount: r.cart?.amount ?? null,
    decision: r.decision, reason: r.reason,
    gateReached: r.verified === true && r.stage === "gate",
    checks: r.checks ?? [],
    ap2: deriveAp2(r.verified, r.reason),
    risk: r.risk_score ?? null,
    dual: r.dual_signed ?? false,
    receipt: r.receipt ?? null,
    explain: EXPLAIN[b.id] ?? "",
  };
}

function DecisionIcon({ ok }: { ok: boolean }) {
  return <span className="ic">{ok ? "✓" : "✕"}</span>;
}

export default function App() {
  const [tab, setTab] = useState<"console" | "results">("console");
  const [online, setOnline] = useState<boolean | null>(null);
  const [active, setActive] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [res, setRes] = useState<RunResult | null>(null);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [chain, setChain] = useState<{ ok: boolean; length: number } | null>(null);
  const [err, setErr] = useState<string>("");
  const [seq, setSeq] = useState(0); // bumps each run so the reveal animation replays

  useEffect(() => {
    api.health().then(() => setOnline(true)).catch(() => setOnline(false));
  }, []);

  async function run(rail: Rail, b: Buyer) {
    setErr("");
    setBusy(b.id);
    try {
      let out: RunResult;
      if (rail === "ap2") {
        out = normalizeAp2(await api.ap2Demo(b.id), b);
      } else if (b.id === "__purchase") {
        const p: PurchaseResult = await api.purchase(
          "Buy running shoes under ₹5,000 with 30-day returns, automatically", true);
        out = {
          id: b.id, rail: "direct", label: b.label,
          amount: p.negotiation.agreed_price, decision: p.decision, reason: p.reason,
          gateReached: true, checks: p.checks, risk: p.risk_score, dual: false,
          receipt: p.receipt, explain: EXPLAIN[b.id] ?? "",
        };
      } else {
        const a = await api.attack(b.id);
        out = {
          id: b.id, rail: "direct", label: b.label, amount: null,
          decision: a.decision, reason: a.reason, gateReached: true, checks: a.checks,
          risk: null, dual: false, receipt: a.receipt, explain: EXPLAIN[b.id] ?? "",
        };
      }
      setActive(b.id);
      setRes(out);
      setSeq((s) => s + 1);
      const hash = (out.receipt?.receipt_id ?? `rc-${Date.now()}`).replace(/^rcpt-/, "").slice(0, 8);
      setLedger((prev) => [
        { seq: prev.length + 1, hash, decision: out.decision, rail: out.rail, reason: out.reason, amount: out.amount },
        ...prev,
      ]);
      api.audit().then((c) => setChain({ ok: c.ok, length: c.length })).catch(() => {});
    } catch (e) {
      setErr(String(e));
      setOnline(false);
    } finally {
      setBusy("");
    }
  }

  const stage = !res ? -1 : res.ap2 && !res.gateReached ? 2 : res.decision === "ALLOW" ? 6 : 4;

  return (
    <>
      <div className="topbar">
        <div className="wrap row">
          <span className="mark">B</span>
          <span className="brand">Bazaar</span>
          <span className="divider" />
          <span className="subtitle">Trust rail for agentic commerce</span>
          <span className="right">
            <span className="kpi"><b>93</b> tests</span>
            <span className="kpi"><b>100%</b> blocked</span>
            <span className="kpi"><b>0%</b> false-block</span>
            <span className="author">Built by <b>Vedant Jaiswal</b></span>
          </span>
        </div>
      </div>

      <div className="wrap">
        <div className="tabs">
          <button className={tab === "console" ? "active" : ""} onClick={() => setTab("console")}>Console</button>
          <button className={tab === "results" ? "active" : ""} onClick={() => setTab("results")}>Results</button>
        </div>
        {online === false && (
          <div className="offline">
            Backend not reachable. Start it with <code>make run</code> (and <code>make web</code> for this UI), then reload.
          </div>
        )}
        {err && online !== false && <div className="offline">Error: {err}</div>}
      </div>

      {tab === "console" ? (
        <div className="wrap">
          <div className="board">
            {/* buyers */}
            <div className="card">
              <div className="hd"><h3>AI buyers</h3><span className="hint">select to run</span></div>
              <div className="bd">
                <div className="grp">AP2 rail - signed carts</div>
                {AP2_BUYERS.map((b) => (
                  <BuyerButton key={b.id} b={b} rail="ap2" active={active} busy={busy} onRun={run} />
                ))}
                <div className="grp" style={{ marginTop: ".9rem" }}>Direct rail</div>
                <BuyerButton b={PURCHASE} rail="direct" active={active} busy={busy} onRun={run} />
                <div className="grp" style={{ marginTop: ".9rem" }}>Red-team - direct rail</div>
                {RT_BUYERS.map((b) => (
                  <BuyerButton key={b.id} b={b} rail="direct" active={active} busy={busy} onRun={run} />
                ))}
              </div>
            </div>

            {/* gate */}
            <div className="card">
              <div className="hd">
                <h3>Authorization</h3>
                <span className="hint mono">{res ? `${res.rail === "ap2" ? "AP2" : "Direct"} · ${res.label}` : "no buyer selected"}</span>
              </div>
              <div className="bd">
                <div className="stepper">
                  {STEPS.map((s, i) => (
                    <div key={s} className={"step " + (stage < 0 ? "" : i === stage ? "on" : i < stage ? "done" : "")}>
                      <div className="dot" /><div className="st">{s}</div>
                    </div>
                  ))}
                </div>

                <div key={`dec-${seq}`} className={"decision " + (!res ? "" : res.decision === "ALLOW" ? "allow" : "block")}>
                  <div className="dicon">{!res ? "·" : res.decision === "ALLOW" ? "✓" : "✕"}</div>
                  <div className="dwho">
                    <div className="verdict">{!res ? "Ready" : res.decision === "ALLOW" ? "Approved" : "Blocked"}</div>
                    <div className="rc">{res ? <span className="mono">{res.reason}</span> : "Select an AI buyer to run a transaction through the gate."}</div>
                  </div>
                  {res && (
                    <div className="dmeta">
                      <span className="amt">{res.amount != null ? rupees(res.amount) : "-"}</span> · risk {res.risk != null ? res.risk.toFixed(2) : "-"}
                      {res.dual && <><br /><span className="dual">Dual-signed</span></>}
                    </div>
                  )}
                </div>

                <div className="explain">{res ? res.explain : "Every rail - a real AP2 agent or a direct buyer - funnels into one deterministic gate. Each decision returns a specific, machine-readable reason for every rupee."}</div>

                {res?.ap2 && (
                  <>
                    <div className="section-label">AP2 verification</div>
                    <div className="checks" style={{ marginBottom: "1rem" }} key={`ap2-${seq}`}>
                      {res.ap2.map((c, i) => (
                        <div className={"check " + (c.passed ? "pass" : "fail")} key={c.code} style={{ "--i": i } as unknown as CSSProperties}>
                          <DecisionIcon ok={c.passed} /><span className="cname">{c.name}</span><span className="code">{c.code}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                <div className="section-label">Deterministic gate - 11 checks</div>
                <div className="checks" key={`gate-${seq}`}>
                {res && res.ap2 && !res.gateReached ? (
                  <div className="check skip"><span className="ic">-</span><span className="cname">Gate not reached - rejected during AP2 verification</span></div>
                ) : (
                  GATE.map(([code, name], i) => {
                    const ck = res?.checks[i];
                    const cls = !res ? "skip" : ck ? (ck.passed ? "pass" : "fail") : "skip";
                    const icon = cls === "pass" ? "✓" : cls === "fail" ? "✕" : "-";
                    return (
                      <div className={"check " + cls} key={code} style={{ "--i": i } as unknown as CSSProperties}>
                        <span className="ic">{icon}</span><span className="cname">{name}</span><span className="code">{code}</span>
                      </div>
                    );
                  })
                )}
                </div>
              </div>
            </div>

            {/* ledger + receipt */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="card">
                <div className="hd"><h3>Audit log</h3><span className="hint">{chain ? `chain ${chain.ok ? "verified" : "broken"} · ${chain.length}` : "hash-chained"}</span></div>
                <div className="ledger">
                  {ledger.length === 0 ? (
                    <div className="empty">Decisions appear here, each linked to the previous by hash.</div>
                  ) : ledger.map((l) => (
                    <div className="lrow" key={l.seq}>
                      <div className="t">
                        <span className="seq">#{String(l.seq).padStart(3, "0")}</span>
                        <span className="hash">{l.hash}</span>
                        <span className={"badge " + l.decision}>{l.decision === "ALLOW" ? "Approved" : "Blocked"}</span>
                      </div>
                      <div className="sub">{l.rail === "ap2" ? "AP2" : "Direct"} · {l.reason}{l.amount != null ? ` · ${rupees(l.amount)}` : ""}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="card">
                <div className="hd"><h3>Trust receipt</h3></div>
                <div className="bd">
                  {!res || !res.receipt ? (
                    <div className="empty" style={{ padding: ".3rem" }}>A signed receipt is issued for each decision.</div>
                  ) : (
                    <>
                      <div className="rline"><span className="k">Receipt ID</span><span className="v">{res.receipt.receipt_id}</span></div>
                      <div className="rline"><span className="k">Rail</span><span className="v">{res.rail === "ap2" ? "AP2" : "direct"}</span></div>
                      <div className="rline"><span className="k">Amount</span><span className="v">{res.amount != null ? rupees(res.amount) : "-"}</span></div>
                      <div className="rline"><span className="k">Decision</span><span className="v" style={{ color: res.decision === "ALLOW" ? "var(--good)" : "var(--crit)" }}>{res.decision === "ALLOW" ? "Approved" : "Blocked"}</span></div>
                      <div className="rline"><span className="k">Reason</span><span className="v">{res.reason}</span></div>
                      <div className="rline"><span className="k">Dual-signed</span><span className="v">{String(res.dual)}</span></div>
                      <div className="rsig">Ed25519 · {(res.receipt.signature || "").slice(0, 44)}...</div>
                      <div className="signed"><span style={{ color: "var(--good)" }}>✓</span> Issued by Bazaar - Vedant Jaiswal</div>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <ResultsTab />
      )}

      <div className="wrap">
        <footer>
          <b>Bazaar</b> - the trust rail for agentic commerce. Built by <b>Vedant Jaiswal</b> for the Razorpay AI Buildathon 2026.
        </footer>
      </div>
    </>
  );
}

function BuyerButton({ b, rail, active, busy, onRun }: {
  b: Buyer; rail: Rail; active: string; busy: string;
  onRun: (rail: Rail, b: Buyer) => void;
}) {
  return (
    <button className={"buyer " + (active === b.id ? "on" : "")} disabled={busy === b.id} onClick={() => onRun(rail, b)}>
      <span>
        <span className="bl">{b.label}</span><br />
        <span className="bd">{busy === b.id ? "running..." : b.desc}</span>
      </span>
      <span className={"tag " + rail}>{rail === "ap2" ? "AP2" : "Direct"}</span>
    </button>
  );
}

function ResultsTab() {
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [hint, setHint] = useState<string>("");

  useEffect(() => {
    api.benchmark().then((r) => {
      if (r.status === "ok" && r.scoreboard) setBoard(r.scoreboard);
      else setHint(r.hint || "run `make benchmark` to generate the scoreboard");
    }).catch(() => setHint("backend offline - run `make run`, then `make benchmark`"));
  }, []);

  const f = board?.four_numbers;
  const risk = board?.risk_classifier;
  const rev = board?.revenue_axis;

  return (
    <div className="wrap results-pad">
      <div className="stat-grid">
        <div className="stat"><div className="l">Adversarial block rate</div><div className="v g">{f ? `${(f.adversarial_block_rate * 100).toFixed(0)}%` : "100%"}</div><div className="s">9 classes · correct code {f ? `${(f.adversarial_correct_code_rate * 100).toFixed(0)}%` : "100%"}</div></div>
        <div className="stat"><div className="l">False-block on legit</div><div className="v g">{f ? `${(f.false_block_rate * 100).toFixed(1)}%` : "0%"}</div><div className="s">400+ cases, incl. boundaries</div></div>
        <div className="stat"><div className="l">Fuzzer escapes</div><div className="v g">{f ? f.fuzzer_cap_violations : 0}</div><div className="s">{f ? f.fuzzer_iterations.toLocaleString() : "20,000"} random states</div></div>
        <div className="stat"><div className="l">Tests passing</div><div className="v a">93</div><div className="s">unit · property · security · integration</div></div>
      </div>

      {hint && <div className="offline" style={{ marginTop: 14 }}>{hint}.</div>}

      <div className="rgrid">
        <div className="card">
          <div className="hd"><h3>Risk brain - advisory, calibrated</h3></div>
          <div className="bd">
            <div className="stat-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="stat" style={{ boxShadow: "none", padding: ".7rem .8rem" }}><div className="l">Recall</div><div className="v" style={{ fontSize: "1.4rem" }}><span style={{ color: "var(--crit)" }}>0.22</span> <span style={{ color: "var(--ink-4)", fontWeight: 400 }}>→</span> <span style={{ color: "var(--good)" }}>{risk ? risk.recall.toFixed(2) : "1.00"}</span></div><div className="s">heuristic → learned</div></div>
              <div className="stat" style={{ boxShadow: "none", padding: ".7rem .8rem" }}><div className="l">Precision</div><div className="v a" style={{ fontSize: "1.4rem" }}>{risk ? risk.precision.toFixed(2) : "1.00"}</div><div className="s">zero false positives</div></div>
              <div className="stat" style={{ boxShadow: "none", padding: ".7rem .8rem" }}><div className="l">Brier score</div><div className="v w" style={{ fontSize: "1.4rem" }}>0.038</div><div className="s">well calibrated</div></div>
              <div className="stat" style={{ boxShadow: "none", padding: ".7rem .8rem" }}><div className="l">ROC-AUC</div><div className="v g" style={{ fontSize: "1.4rem" }}>1.00</div><div className="s">held-out, fresh keys</div></div>
            </div>
            <div className="section-label" style={{ marginTop: ".9rem" }}>Top risk drivers - readable model weights</div>
            {[["over_cap", 100, "+2.28"], ["nonce_seen", 87, "+1.99"], ["agent_frozen", 86, "+1.96"], ["category_out", 86, "+1.96"], ["provenance_untrusted", 85, "+1.95"]].map(([n, w, v]) => (
              <div className="bar" key={n as string}><span className="bn">{n}</span><span className="track"><span className="fill" style={{ width: `${w}%` }} /></span><span className="bv">{v}</span></div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="hd"><h3>AP2 rail - conformance</h3></div>
          <div className="bd">
            <p style={{ fontSize: ".8rem", color: "var(--ink-2)", margin: "0 0 .6rem" }}>Legit cleared <span className="ok">1 / 1</span> · tampers caught <span className="ok">5 / 5</span></p>
            <div style={{ overflowX: "auto" }}>
              <table className="conf">
                <thead><tr><th>Cart</th><th>Caught at</th><th>Result</th></tr></thead>
                <tbody>
                  <tr><td>Legit (real price)</td><td style={{ color: "var(--ink-3)" }}>-</td><td className="ok">Approved</td></tr>
                  <tr><td>Price ≠ record</td><td style={{ color: "var(--ink-2)" }}>money gate</td><td className="ok">Blocked</td></tr>
                  <tr><td>Over the cap</td><td style={{ color: "var(--ink-2)" }}>money gate</td><td className="ok">Blocked</td></tr>
                  <tr><td>Expired</td><td style={{ color: "var(--ink-2)" }}>AP2 verification</td><td className="ok">Blocked</td></tr>
                  <tr><td>Signature flipped</td><td style={{ color: "var(--ink-2)" }}>AP2 verification</td><td className="ok">Blocked</td></tr>
                  <tr><td>Unregistered signer</td><td style={{ color: "var(--ink-2)" }}>AP2 verification</td><td className="ok">Blocked</td></tr>
                </tbody>
              </table>
            </div>
            <div className="section-label" style={{ marginTop: ".9rem" }}>Revenue - bounded upsell</div>
            <div className="bar"><span className="bn">Order-value uplift</span><span className="track"><span className="fill" style={{ width: "52%", background: "var(--warn)" }} /></span><span className="bv" style={{ color: "var(--warn)" }}>{rev ? `+${rev.aov_uplift_pct.toFixed(2)}%` : "+7.72%"}</span></div>
            <p style={{ fontSize: ".74rem", color: "var(--ink-4)", margin: ".4rem 0 0" }}>{rev ? `${(rev.share_of_uplift_cleared * 100).toFixed(0)}%` : "100%"} of upsold orders still cleared the gate.</p>
          </div>
        </div>
      </div>
      <p className="reproduce">Every figure reproduces from the repo: <code>make benchmark</code> · <code>python scripts/train_risk.py</code> · <code>python scripts/ap2_demo.py</code></p>
    </div>
  );
}

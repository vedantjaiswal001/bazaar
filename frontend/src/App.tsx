import { useEffect, useState } from "react";
import {
  AttackResult,
  Check,
  IntentResult,
  PurchaseResult,
  Receipt,
  Scoreboard,
  api,
  rupees,
} from "./api";

type Tab = "intent" | "transaction" | "verifier" | "receipt" | "redteam" | "benchmark";

const TABS: { id: Tab; label: string }[] = [
  { id: "intent", label: "1 · Intent" },
  { id: "transaction", label: "2 · Transaction" },
  { id: "verifier", label: "3 · Verifier" },
  { id: "receipt", label: "4 · Trust Receipt" },
  { id: "redteam", label: "5 · Red Team" },
  { id: "benchmark", label: "6 · Benchmark" },
];

const ATTACKS: { cls: string; label: string; desc: string }[] = [
  { cls: "budget", label: "Budget", desc: "Spend ₹7,000 against a ₹5,000 cap" },
  { cls: "policy", label: "Policy", desc: "Rewrite the signed max_amount" },
  { cls: "price", label: "Price", desc: "Claim a false price vs the record" },
  { cls: "replay", label: "Replay", desc: "Resubmit a used nonce" },
  { cls: "double_charge", label: "Double-charge", desc: "Reuse an idempotency key" },
  { cls: "category", label: "Category", desc: "Buy an off-mandate smartwatch" },
  { cls: "injection", label: "Injection", desc: "Money-field from injected text" },
  { cls: "state", label: "State", desc: "Transact while frozen" },
  { cls: "expiry", label: "Expiry", desc: "Submit an expired mandate" },
];

interface LastAction {
  label: string;
  decision: string;
  reason: string;
  checks: Check[];
  receipt: Receipt;
}

function DecisionPill({ decision }: { decision: string }) {
  const cls = decision === "ALLOW" ? "allow" : decision === "REVIEW" ? "review" : "block";
  return <span className={`pill ${cls}`}>{decision}</span>;
}

function Checklist({ checks }: { checks: Check[] }) {
  return (
    <div>
      {checks.map((c) => (
        <div className="check" key={c.name}>
          <span className={`mark ${c.passed ? "pass" : "fail"}`}>{c.passed ? "✓" : "✗"}</span>
          <span className="name">{c.name}</span>
          {c.detail && <span className="muted small">- {c.detail}</span>}
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("intent");
  const [health, setHealth] = useState<string>("");
  const [purchase, setPurchase] = useState<PurchaseResult | null>(null);
  const [last, setLast] = useState<LastAction | null>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    api.health().then((h) => setHealth(h.razorpay_settlement)).catch(() => setHealth("backend offline"));
  }, []);

  async function runPurchase(text: string, upsell: boolean) {
    setErr("");
    try {
      const r = await api.purchase(text, upsell);
      setPurchase(r);
      setLast({ label: "Purchase", decision: r.decision, reason: r.reason, checks: r.checks, receipt: r.receipt });
      setTab("transaction");
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="wrap">
      <header className="masthead">
        <div className="kicker">Razorpay AI Buildathon 2026 · Track 01</div>
        <h1 className="brand">BAZAAR</h1>
        <p className="tagline">
          Adversarial infrastructure for autonomous commerce. AI agents can transact - BAZAAR
          measures whether they <i>should be allowed to</i>.
        </p>
        <div className="invariant">
          <b>LLMs propose. Policies constrain. A deterministic verifier authorizes.</b> Nothing
          probabilistic can widen authority; no path settles above the signed cap.
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>
          Razorpay settlement: <code>{health || "…"}</code>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {err && <div className="panel err">Error: {err} - is the backend running? (<code>make run</code>)</div>}

      {tab === "intent" && <IntentScreen onRun={runPurchase} setErr={setErr} />}
      {tab === "transaction" && <TransactionScreen purchase={purchase} onRun={runPurchase} />}
      {tab === "verifier" && <VerifierScreen last={last} />}
      {tab === "receipt" && <ReceiptScreen last={last} />}
      {tab === "redteam" && <RedTeamScreen setLast={setLast} setErr={setErr} />}
      {tab === "benchmark" && <BenchmarkScreen setErr={setErr} />}
    </div>
  );
}

function IntentScreen({
  onRun,
  setErr,
}: {
  onRun: (t: string, u: boolean) => void;
  setErr: (s: string) => void;
}) {
  const [text, setText] = useState("Buy running shoes under ₹5,000 with 30-day returns, automatically");
  const [result, setResult] = useState<IntentResult | null>(null);

  async function compile() {
    setErr("");
    try {
      setResult(await api.intent(text));
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="panel">
      <h2>Intent → signed mandate</h2>
      <p className="sub">
        A natural-language request is compiled into a structured mandate. The human confirms the
        rendered mandate <i>before</i> it is Ed25519-signed - a bad parse can never become a signed
        boundary.
      </p>
      <label>Natural-language intent</label>
      <textarea value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" onClick={compile}>Compile mandate</button>
      </div>

      {result && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="kv"><span className="k">Spend cap</span><span className="mono">{result.max_amount_display}</span></div>
          <div className="kv"><span className="k">Allowed categories</span><span className="mono">{result.allowed_categories.join(", ") || "-"}</span></div>
          <div className="kv"><span className="k">Return policy</span><span className="mono">{result.return_policy_days} days</span></div>
          <div className="kv"><span className="k">Autonomous</span><span className="mono">{String(result.autonomous)}</span></div>
          <div className="kv"><span className="k">Expires</span><span className="mono">{result.expires_at}</span></div>
          <div className="kv"><span className="k">Confirmable</span><span className="mono">{String(result.confirmable)}</span></div>
          {result.warnings.length > 0 && (
            <p className="err small">⚠ {result.warnings.join("; ")}</p>
          )}
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={!result.confirmable} onClick={() => onRun(text, true)}>
              Confirm &amp; sign → run purchase
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Walls({ n }: { n: PurchaseResult["negotiation"] }) {
  const lo = Math.min(n.floor_price, n.agreed_price) * 0.985;
  const hi = Math.max(n.buyer_cap, n.list_price) * 1.015;
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return (
    <div className="walls">
      <div className="wall floor" style={{ left: `${pos(n.floor_price)}%` }}>
        <span className="lbl">floor {rupees(n.floor_price)}</span>
      </div>
      <div className="wall cap" style={{ left: `${pos(n.buyer_cap)}%` }}>
        <span className="lbl">cap {rupees(n.buyer_cap)}</span>
      </div>
      <div className="dot" style={{ left: `${pos(n.agreed_price)}%` }} title={`agreed ${rupees(n.agreed_price)}`} />
    </div>
  );
}

function TransactionScreen({
  purchase,
  onRun,
}: {
  purchase: PurchaseResult | null;
  onRun: (t: string, u: boolean) => void;
}) {
  const [upsell, setUpsell] = useState(true);
  const text = "Buy running shoes under ₹5,000 with 30-day returns, automatically";
  return (
    <div className="panel">
      <h2>Bounded negotiation → deterministic settlement</h2>
      <p className="sub">
        One negotiation round, clamped between the buyer's cap and the seller's floor. The
        authoritative price comes from the merchant of record - never the seller's word.
      </p>
      <div className="row">
        <label style={{ margin: 0 }}>
          <input type="checkbox" checked={upsell} onChange={(e) => setUpsell(e.target.checked)} /> bounded upsell
        </label>
        <button className="btn" onClick={() => onRun(text, upsell)}>Run purchase</button>
      </div>

      {!purchase && <p className="muted" style={{ marginTop: 14 }}>Run a purchase to see the negotiation and the gate decision.</p>}

      {purchase && (
        <div style={{ marginTop: 16 }}>
          <div className="grid two">
            <div className="stat">
              <div className="cap">Mandate</div>
              <div className="kv"><span className="k">Cap</span><span className="mono">{purchase.mandate.cap_display}</span></div>
              <div className="kv"><span className="k">Signature valid</span><span className="mono">{String(purchase.mandate.signature_valid)}</span></div>
              <div className="kv"><span className="k">Categories</span><span className="mono">{purchase.mandate.categories.join(", ")}</span></div>
            </div>
            <div className="stat">
              <div className="cap">Decision</div>
              <div style={{ fontSize: 22, margin: "6px 0" }}>
                <DecisionPill decision={purchase.decision} /> <span className="mono">{purchase.reason}</span>
              </div>
              <div className="small muted">risk score {purchase.risk_score} → effective {purchase.effective_decision}</div>
              <div className="small muted">Razorpay: {purchase.razorpay.status} - {purchase.razorpay.note}</div>
            </div>
          </div>

          <div style={{ marginTop: 20 }}>
            <label>Negotiation - item {purchase.negotiation.sku} {purchase.negotiation.upsold ? "(upsold)" : ""}</label>
            <Walls n={purchase.negotiation} />
            <div className="transcript">
              {purchase.negotiation.transcript.map((s, i) => (
                <div className="line" key={i}>
                  <span className="actor">{s.actor}</span>
                  <span className="mono">{s.price ? rupees(s.price) : ""}</span>
                  <span className="muted">{s.note}</span>
                </div>
              ))}
            </div>
            <p className="small">
              agreed <b>{rupees(purchase.negotiation.agreed_price)}</b> · within walls:{" "}
              <b>{String(purchase.negotiation.within_walls)}</b>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function VerifierScreen({ last }: { last: LastAction | null }) {
  return (
    <div className="panel">
      <h2>The deterministic authorization gate</h2>
      <p className="sub">
        A fixed checklist. All checks pass → ALLOW. Any check fails → BLOCK with one
        machine-readable reason code - never "the AI decided no."
      </p>
      {!last && <p className="muted">Run a purchase or an attack to populate the checklist.</p>}
      {last && (
        <>
          <div style={{ fontSize: 22, marginBottom: 12 }}>
            {last.label}: <DecisionPill decision={last.decision} /> <span className="mono">{last.reason}</span>
          </div>
          <Checklist checks={last.checks} />
        </>
      )}
    </div>
  );
}

function ReceiptScreen({ last }: { last: LastAction | null }) {
  const [verdict, setVerdict] = useState<string>("");
  const [tampered, setTampered] = useState<boolean>(false);

  async function verify(receipt: Receipt) {
    const r = await api.verifyReceipt(receipt);
    setVerdict(r.valid ? "VALID - signature verifies" : "INVALID - signature does not verify");
  }
  function tamperAndVerify(receipt: Receipt) {
    const forged: Receipt = JSON.parse(JSON.stringify(receipt));
    (forged.body as Record<string, unknown>).amount = 9999900;
    setTampered(true);
    verify(forged);
  }

  return (
    <div className="panel">
      <h2>Trust Receipt - verifiable, tamper-evident</h2>
      <p className="sub">
        Every decision emits a canonical-JSON, Ed25519-signed receipt. Verify it - it passes. Change
        one field - it fails. The cryptography is real, not decorative.
      </p>
      {!last && <p className="muted">Run a purchase or attack first to produce a receipt.</p>}
      {last && (
        <>
          <div className="row">
            <button className="btn" onClick={() => { setTampered(false); verify(last.receipt); }}>Verify signature</button>
            <button className="btn ghost" onClick={() => tamperAndVerify(last.receipt)}>Tamper amount → ₹99,999 &amp; verify</button>
          </div>
          {verdict && (
            <p style={{ marginTop: 10 }}>
              <span className={`pill ${tampered ? "block" : "allow"}`}>{tampered ? "TAMPERED" : "INTACT"}</span>{" "}
              <span className="mono">{verdict}</span>
            </p>
          )}
          <label style={{ marginTop: 12 }}>Receipt {String(last.receipt.receipt_id)}</label>
          <pre className="json">{JSON.stringify(last.receipt, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

function RedTeamScreen({
  setLast,
  setErr,
}: {
  setLast: (a: LastAction) => void;
  setErr: (s: string) => void;
}) {
  const [results, setResults] = useState<Record<string, AttackResult>>({});
  const [busy, setBusy] = useState(false);

  async function fire(cls: string) {
    setErr("");
    try {
      const r = await api.attack(cls);
      setResults((prev) => ({ ...prev, [cls]: r }));
      setLast({ label: `Attack: ${cls}`, decision: r.decision, reason: r.reason, checks: r.checks, receipt: r.receipt });
    } catch (e) {
      setErr(String(e));
    }
  }
  async function fireAll() {
    setBusy(true);
    for (const a of ATTACKS) await fire(a.cls);
    setBusy(false);
  }

  const blocked = Object.values(results).filter((r) => r.decision === "BLOCK").length;

  return (
    <div className="panel">
      <h2>Red-team harness - nine attack classes, live</h2>
      <p className="sub">
        Fire attacks at the live gate. Each returns a specific reason code. Results are measured, not
        asserted - {blocked}/{Object.keys(results).length || 0} blocked so far.
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn" onClick={fireAll} disabled={busy}>{busy ? "Firing…" : "Fire all 9"}</button>
      </div>
      <div className="attack-grid">
        {ATTACKS.map((a) => {
          const r = results[a.cls];
          return (
            <div className="attack-card" key={a.cls} onClick={() => fire(a.cls)}>
              <div className="cls">{a.label}</div>
              <div className="desc">{a.desc}</div>
              {r ? (
                <div>
                  <DecisionPill decision={r.decision} /> <span className="mono small">{r.reason}</span>
                </div>
              ) : (
                <div className="small muted">click to fire</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BenchmarkScreen({ setErr }: { setErr: (s: string) => void }) {
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [hint, setHint] = useState<string>("");

  async function load() {
    setErr("");
    try {
      const r = await api.benchmark();
      if (r.status === "ok" && r.scoreboard) { setBoard(r.scoreboard); setHint(""); }
      else setHint(r.hint || "run `make benchmark`");
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => { load(); }, []);

  const f = board?.four_numbers;
  return (
    <div className="panel">
      <h2>Benchmark scoreboard</h2>
      <p className="sub">
        Every number is produced by <code>make benchmark</code>. The deterministic gate is
        correct/incorrect (block rates); only the advisory risk model gets precision/recall - kept
        separate.
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="btn" onClick={load}>Reload scoreboard</button>
      </div>
      {hint && <p className="muted">Scoreboard not generated yet - {hint}.</p>}
      {board && f && (
        <>
          <div className="grid three">
            <div className="stat"><div className="cap">Adversarial block rate</div><div className="big-num good">{(f.adversarial_block_rate * 100).toFixed(0)}%</div><div className="small muted">correct code {(f.adversarial_correct_code_rate * 100).toFixed(0)}%</div></div>
            <div className="stat"><div className="cap">False-block on legit</div><div className="big-num good">{(f.false_block_rate * 100).toFixed(1)}%</div><div className="small muted">incl. boundary cases</div></div>
            <div className="stat"><div className="cap">Fuzzer cap violations</div><div className="big-num good">{f.fuzzer_cap_violations}</div><div className="small muted">{f.fuzzer_iterations.toLocaleString()} states</div></div>
          </div>
          <div className="grid three" style={{ marginTop: 12 }}>
            <div className="stat"><div className="cap">Held-out block rate</div><div className="big-num good">{(f.held_out_block_rate * 100).toFixed(0)}%</div><div className="small muted">fresh, unseen attacks</div></div>
            <div className="stat"><div className="cap">AOV uplift (bounded upsell)</div><div className="big-num">{board.revenue_axis.aov_uplift_pct.toFixed(2)}%</div><div className="small muted">{(board.revenue_axis.share_of_uplift_cleared * 100).toFixed(0)}% cleared the gate</div></div>
            <div className="stat"><div className="cap">Risk classifier (separate)</div><div className="big-num">{board.risk_classifier.precision.toFixed(2)}</div><div className="small muted">precision · recall {board.risk_classifier.recall.toFixed(2)}</div></div>
          </div>

          <label style={{ marginTop: 18 }}>Per attack class - blocked / correct reason code</label>
          <div>
            {Object.keys(board.per_class_blocked).sort().map((cls) => (
              <div className="kv" key={cls}>
                <span className="k">{cls}</span>
                <span className="mono">
                  {(board.per_class_blocked[cls] * 100).toFixed(0)}% blocked ·{" "}
                  {(board.per_class_correct_code[cls] * 100).toFixed(0)}% correct
                </span>
              </div>
            ))}
          </div>
          <p className="small muted" style={{ marginTop: 10 }}>
            escapes reported honestly: {board.escapes.length === 0 ? "none" : board.escapes.length}
          </p>
        </>
      )}
    </div>
  );
}

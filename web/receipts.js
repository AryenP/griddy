// Receipts on the dashboard: the numbers that prove what happened, computed by the reporter from timelines
// only. GET /api/runs to pick runs, /api/report (Report), /api/compare (Comparison), /api/trace (recent
// OpenTelemetry spans: the audit log). A route that is not there yet, or a run that does not exist, shows
// "not available yet: <route>" with the server's reason; nothing here computes or fills in a number.
"use strict";

const R = { runs: [], runsT: null, reportT: null, compareT: null, traceT: null };

function money(usd) {
  if (usd == null || !isFinite(usd)) return "—";
  return Math.abs(usd) < 0.01 ? `${sig(usd * 100)}¢` : `$${sig(usd)}`;
}
function signed(x, f) { return x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x)); }
function runLabel(r) {
  const mode = r.dispatcher_enabled === false ? "dispatcher off" : r.dispatcher_enabled ? "dispatched" : "mode unknown";
  return `${r.run_id} · ${mode} · ${localClock(r.started)}`;
}

// ---------- runs ----------
function fill(sel, runs, empty) {
  const keep = sel.value;
  setHTML(sel, runs.length ? html`${runs.map((r) => html`<option value="${r.run_id}">${runLabel(r)}</option>`)}`
    : html`<option value="">${empty}</option>`);
  if (runs.some((r) => r.run_id === keep)) sel.value = keep;
}

async function loadRuns() {
  const r = await getJSON("/api/runs");
  if (!r.ok) { $("runs-src").textContent = routeError("/api/runs", r); return false; }
  R.runs = (r.data || []).slice().sort((a, b) => b.started - a.started);
  R.runsT = nowS();
  fill($("rc-run"), R.runs, "no runs on the demo Mac yet");
  fill($("rc-dispatched"), R.runs.filter((x) => x.dispatcher_enabled !== false), "no dispatched run yet");
  fill($("rc-baseline"), R.runs.filter((x) => x.dispatcher_enabled === false), "no dispatcher-off run yet (make baseline)");
  renderSrc();
  return true;
}

// ---------- the event report ----------
function approvalRow(a) {
  const what = a.what === "power_cap" ? "go over the power cap" : `let ${a.what} slip`;
  const reply = a.who ? html`${a.who}: <b>${a.reply || "?"}</b>${a.reason ? html` “${a.reason}”` : ""}${a.new_deadline ? html` → ${isoLabel(a.new_deadline)}` : ""}` : html`<span class="src">no reply</span>`;
  return html`<tr><td>${a.when ? localClock(a.when) : "—"}</td><td>${what}<div class="src">asked ${a.owner || "?"}</div></td>
    <td>${reply}</td><td><span class="badge ${a.decision === "approved" || a.decision === "countered" ? "ok" : a.decision === "refused" ? "bad" : "warn"}">${a.decision || "?"}</span>
    ${a.decided_t ? html`<div class="src">${localClock(a.decided_t)}</div>` : ""}</td></tr>`;
}

// Measured energy with exactly zero cost or carbon means the window was not priced (no live price or mix
// logged yet); the reporter's caveats below say so, and the number must not read as a real zero.
function unpriced(rep, v) { return v === 0 && rep.energy_wh > 0 ? " (see caveats)" : ""; }

function renderReport(rep) {
  const span = rep.window_end - rep.window_start;
  const deadlines = Object.entries(rep.deadlines || {});
  setHTML($("report"), html`<div class="receipt-head">
      <div><div class="value">${rep.reduction_pct == null ? "—" : `${fixed(rep.reduction_pct, 0)}%`}</div><div class="label">reduction, measured</div></div>
      <div><div class="value">${rep.time_to_compliance_s == null ? "—" : dur(rep.time_to_compliance_s)}</div><div class="label">time to compliance</div></div>
      <div><div class="value">${fixed(rep.baseline_w, 1)}<small>W</small> → ${fixed(rep.event_w, 1)}<small>W</small></div><div class="label">mean before → during</div></div>
    </div>
    <div class="kv"><b>window</b> ${localClock(rep.window_start)} to ${localClock(rep.window_end)} (${dur(span)})</div>
    <div class="kv"><b>energy</b> ${fixed(rep.energy_wh, 3)} Wh measured · <b>cost</b> ${money(rep.cost_usd)}${unpriced(rep, rep.cost_usd)} at the live price · <b>carbon</b> ${sig(rep.co2_g)} g${unpriced(rep, rep.co2_g)} at the live mix</div>
    <div class="kv"><b>chat time to first token, p95</b> ${rep.chat_p95_before_s == null ? "—" : `${fixed(rep.chat_p95_before_s, 2)} s`} before · ${rep.chat_p95_during_s == null ? "—" : `${fixed(rep.chat_p95_during_s, 2)} s`} during</div>
    <div class="kv"><b>deadlines</b> ${deadlines.length ? deadlines.map(([j, ok], i) => html`${i ? ", " : ""}${j} <span class="${ok ? "" : "bad-text"}">${ok ? "met" : "MISSED"}</span>`) : "none in the window"}</div>
    ${(rep.approvals || []).length ? html`<table class="rtable"><thead><tr><th>asked</th><th>what</th><th>reply</th><th>decision</th></tr></thead>
        <tbody>${rep.approvals.map(approvalRow)}</tbody></table>` : html`<p class="src">no approvals asked in this run</p>`}
    ${(rep.shortfalls || []).length ? html`<ul class="explanations">${rep.shortfalls.map((s) => html`<li class="warn-line">${s}</li>`)}</ul>` : ""}
    ${rep.narrative ? html`<p class="explain">${rep.narrative}</p><div class="src">the agent's wording of the numbers above</div>` : ""}`);
}

async function loadReport() {
  const run = $("rc-run").value;
  if (!run) { setHTML($("report"), html`<p class="empty">no run to report on yet: start make demo on the demo Mac</p>`); return; }
  $("report-src").textContent = "loading…";
  const path = `/api/report?run=${encodeURIComponent(run)}`;
  const r = await getJSON(path);
  if (!r.ok) { setHTML($("report"), html`<p class="empty">${routeError("/api/report", r)}</p>`); $("report-src").textContent = ""; return; }
  renderReport(r.data);
  R.reportT = nowS(); R.reportRun = run;
  renderSrc();
}

// ---------- dispatched vs dispatcher off ----------
const ROWS = [
  ["Cost at the live price", "cost_usd", (x) => x.cost_usd, money],
  ["Carbon at the live mix", "co2_g", (x) => x.co2_g, (v) => `${sig(v)} g`],
  ["Energy, measured", "energy_wh", (x) => x.energy_wh, (v) => `${fixed(v, 3)} Wh`],
  ["Mean power in the window", "event_w", (x) => x.event_w, (v) => `${fixed(v, 2)} W`],
  ["Time to compliance", "time_to_compliance_s", (x) => x.time_to_compliance_s, dur],
  ["Deadlines met", "deadlines_met", (x) => { const v = Object.values(x.deadlines || {}); return v.length ? v.filter(Boolean).length : null; },
    (v) => String(v)],
  ["Chat time to first token, p95 during", "chat_p95_s", (x) => x.chat_p95_during_s, (v) => `${fixed(v, 2)} s`],
];

function renderCompare(c) {
  const d = c.dispatched, b = c.baseline, delta = c.delta || {};
  const priced = (key, run) => !(key === "cost_usd" || key === "co2_g") || !unpriced(run, get0(key, run));
  const get0 = (key, run) => run[key];
  const cell = (v, f, ok = true) => (!ok ? html`<span class="src">not priced</span>` : v == null || !isFinite(v) ? html`<span class="src">n/a</span>` : f(v));
  const rows = ROWS.map(([label, key, get, f]) => {
    const dOk = priced(key, d), bOk = priced(key, b);
    const dv = get(d), bv = get(b), dl = dOk && bOk ? delta[key] : null;
    const rel = dl != null && bv ? html` <span class="src">(${signed(100 * dl / Math.abs(bv), (v) => `${fixed(v, 0)}%`)})</span>` : "";
    return html`<tr><th>${label}</th><td>${cell(dv, f, dOk)}</td><td>${cell(bv, f, bOk)}</td>
      <td class="${dl < 0 && key !== "deadlines_met" ? "good" : ""}">${dl == null ? html`<span class="src">n/a</span>` : html`${signed(dl, f)}${rel}`}</td></tr>`;
  });
  if (delta.under_cap_pct != null) {
    rows.push(html`<tr><th>Measured time at or under the cap</th><td colspan="2" class="src">per run in the notes below</td>
      <td class="${delta.under_cap_pct > 0 ? "good" : ""}">${signed(delta.under_cap_pct, (v) => `${fixed(v, 0)} points`)}</td></tr>`);
  }
  setHTML($("compare"), html`<table class="rtable compare">
      <thead><tr><th></th><th>Dispatched<div class="src">${d.run_id}</div></th><th>Dispatcher off<div class="src">${b.run_id}</div></th><th>Difference</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <p class="src">${dur(c.window_s)} of each run, each priced at the live price and fuel mix it had; watts measured by macOS powermetrics</p>
    ${(c.notes || []).length ? html`<ul class="explanations src">${c.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}`);
}

async function loadCompare() {
  const d = $("rc-dispatched").value, b = $("rc-baseline").value;
  if (!d || !b) {
    setHTML($("compare"), html`<p class="empty">${!b ? "no dispatcher-off run yet: run make baseline on the demo Mac" : "no dispatched run yet"}</p>`);
    return;
  }
  $("compare-src").textContent = "loading…";
  const r = await getJSON(`/api/compare?dispatched=${encodeURIComponent(d)}&baseline=${encodeURIComponent(b)}`);
  if (!r.ok) { setHTML($("compare"), html`<p class="empty">${routeError("/api/compare", r)}</p>`); $("compare-src").textContent = ""; return; }
  renderCompare(r.data);
  R.compareT = nowS();
  renderSrc();
}

// ---------- the audit trail ----------
const SPAN_KEYS = ["agent.path", "agent.llm_used", "agent.model", "llm.model", "llm.latency_ms", "llm.tokens.input",
  "llm.tokens.output", "agent.attack_detected", "agent.rejected_numbers"];

function renderTrace(spans) {
  if (!spans.length) {
    setHTML($("trace"), html`<p class="empty">no spans yet: the agent and solver record one per decision once the runtime is up</p>`);
    return;
  }
  const rows = spans.slice().reverse().map((s) => {
    const a = s.attributes || {};
    const shown = SPAN_KEYS.filter((k) => k in a);
    const rest = Object.keys(a).length - shown.length;
    return html`<tr class="${s.status === "ERROR" ? "bad-text" : ""}"><td>${s.start ? localClock(s.start) : "—"}</td><td><b>${s.name}</b>
        <div class="src">trace ${String(s.trace_id || "").slice(0, 8)}</div></td>
      <td>${s.duration_ms == null ? "—" : `${fixed(s.duration_ms, s.duration_ms < 10 ? 1 : 0)} ms`}</td>
      <td class="attrs">${shown.map((k) => html`<span class="attr">${k.replace(/^(agent|llm)\./, "")}=${String(a[k])}</span>`)}${rest > 0 ? html`<span class="src"> +${rest} more</span>` : ""}</td></tr>`;
  });
  setHTML($("trace"), html`<table class="rtable trace"><thead><tr><th>start</th><th>span</th><th>took</th><th>attributes</th></tr></thead><tbody>${rows}</tbody></table>`);
}

async function loadTrace() {
  const r = await getJSON("/api/trace?n=50");
  if (!r.ok) { setHTML($("trace"), html`<p class="empty">${routeError("/api/trace", r)}</p>`); return; }
  renderTrace(r.data || []);
  R.traceT = nowS();
  renderSrc();
}

function renderSrc() {
  if (R.runsT) $("runs-src").textContent = `${plural(R.runs.length, "run")} on the demo Mac, list loaded ${age(R.runsT)}`;
  if (R.reportT) $("report-src").textContent = `reporter over run ${R.reportRun}'s timeline, loaded ${age(R.reportT)}`;
  if (R.compareT) $("compare-src").textContent = `reporter over both timelines, loaded ${age(R.compareT)}`;
  if (R.traceT) $("trace-src").textContent = `the 50 newest spans from the runtime's in-memory buffer (also sent to Application Insights when configured), loaded ${age(R.traceT)}`;
}

async function loadReceipts() {
  $("rc-load").disabled = true;
  if (await loadRuns()) await Promise.all([loadReport(), loadCompare()]);
  else for (const id of ["report", "compare"]) setHTML($(id), html`<p class="empty">needs the run list: ${$("runs-src").textContent}</p>`);
  await loadTrace();
  $("rc-load").disabled = false;
}

$("rc-load").addEventListener("click", loadReceipts);
$("rc-trace").addEventListener("click", loadTrace);
setInterval(renderSrc, 5000);
loadReceipts();

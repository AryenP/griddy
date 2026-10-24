// Proof page: three recorded runs of the same scripted utility call, one per policy (ignore the call =
// `baseline`, pause everything = `pause_all`, Brownout = `dispatcher`). Draws what the server sends:
// GET /api/runs (pick runs), GET /api/runs/{id}/series (measured watts at 1 Hz, caps, actions, shortfalls),
// GET /api/compare (Brownout vs each of the other two). The only arithmetic is shifting each trace so 0 s is
// its own cap start; every number shown is the server's.
"use strict";

const POLICIES = [
  { id: "baseline", label: "Ignore the call", color: "var(--muted)" },
  { id: "pause_all", label: "Pause everything", color: "var(--job-train)" },
  { id: "dispatcher", label: "Brownout", color: "var(--ok)" },
];
const P = { runs: [], series: {}, loadedT: null };

function recorded(run) {
  return run ? `${run.run_id}, recorded ${new Date(run.started * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })}` : "—";
}
function money(usd) { return usd == null || !isFinite(usd) ? "—" : Math.abs(usd) < 0.01 ? `${sig(usd * 100)}¢` : `$${sig(usd)}`; }
function signed(x, f) { return x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + f(Math.abs(x)); }

// ---------- runs ----------
async function loadRuns() {
  const r = await getJSON("/api/runs");
  if (!r.ok) { $("runs-src").textContent = routeError("/api/runs", r); return false; }
  P.runs = (r.data || []).slice().sort((a, b) => b.started - a.started);
  for (const pol of POLICIES) {
    const sel = $(`pick-${pol.id}`), keep = sel.value;
    const mine = P.runs.filter((x) => x.policy === pol.id);
    setHTML(sel, mine.length ? html`${mine.map((x) => html`<option value="${x.run_id}">${recorded(x)}</option>`)}`
      : html`<option value="">no ${pol.label.toLowerCase()} run recorded yet</option>`);
    if (mine.some((x) => x.run_id === keep)) sel.value = keep;
  }
  $("runs-src").textContent = `${plural(P.runs.length, "recorded run")} on the demo Mac; newest of each policy picked by default`;
  return true;
}

// ---------- the three traces ----------
function renderTrace() {
  const runs = POLICIES.map((pol) => ({ pol, s: P.series[pol.id] })).filter((x) => x.s);
  if (!runs.length) { setHTML($("trace"), html`<p class="empty">no series to draw: pick runs above</p>`); return; }
  const lines = runs.map(({ pol, s }) => {
    const cap = s.caps[0] || null;
    const t0 = cap ? cap.start : s.power.length ? s.power[0][0] : s.started;
    return { pol, s, cap, pts: s.power.map(([t, w]) => [t - t0, w]), end: cap ? cap.end - t0 : null };
  });
  const xmin = Math.max(-60, Math.min(...lines.map((l) => (l.pts.length ? l.pts[0][0] : 0))));
  const xmax = Math.max(...lines.map((l) => Math.min(l.end ?? Infinity, l.pts.length ? l.pts[l.pts.length - 1][0] : 0)));
  const ymax = Math.max(1, ...lines.flatMap((l) => l.pts.filter(([x]) => x >= xmin && x <= xmax).map(([, w]) => w)),
    ...lines.map((l) => (l.cap && l.cap.target_w) || 0)) * 1.08;
  const W = 1000, H = 320, L = 52, B = 30, T = 10, R = 10;
  const X = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const Y = (w) => T + (1 - w / ymax) * (H - T - B);
  const path = (pts) => pts.filter(([x]) => x >= xmin && x <= xmax).map(([x, w], i) => `${i ? "L" : "M"}${X(x).toFixed(1)} ${Y(w).toFixed(1)}`).join(" ");
  const xt = [], yt = [];
  for (let x = Math.ceil(xmin / 60) * 60; x <= xmax; x += 60) xt.push(x);
  const ystep = ymax > 40 ? 10 : 5;
  for (let y = 0; y <= ymax; y += ystep) yt.push(y);
  const bro = lines.find((l) => l.pol.id === "dispatcher" && l.cap && l.cap.target_w != null);
  setHTML($("trace"), html`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="measured power of the three runs, aligned at the cap start">
      ${yt.map((y) => html`<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y)}" y2="${Y(y)}"/><text class="tick" x="${L - 6}" y="${Y(y) + 4}" text-anchor="end">${y} W</text>`)}
      ${xt.map((x) => html`<text class="tick" x="${X(x)}" y="${H - 8}" text-anchor="middle">${x === 0 ? "cap starts" : `${x / 60} min`}</text>`)}
      ${xmin < 0 ? html`<line class="zero" x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${H - B}"/>` : ""}
      ${bro ? html`<line class="cap" x1="${X(0)}" x2="${X(Math.min(bro.end, xmax))}" y1="${Y(bro.cap.target_w)}" y2="${Y(bro.cap.target_w)}"/>
        <text class="cap-label" x="${X(Math.min(bro.end, xmax)) - 4}" y="${Y(bro.cap.target_w) - 6}" text-anchor="end">cap ${fixed(bro.cap.target_w, 2)} W</text>` : ""}
      ${lines.map((l) => html`<path class="trace" style="stroke:${l.pol.color}" d="${path(l.pts)}"/>`)}
    </svg>`);
  setHTML($("trace-legend"), html`${lines.map((l) => html`<span><i class="sw" style="background:${l.pol.color}"></i><b>${l.pol.label}</b>
    ${recorded(l.s)}${l.cap ? `, cap ${fixed(l.cap.target_w, 2)} W (${sig(l.cap.target_pct)}% below its measured baseline)` : ", no cap recorded"}</span>`)}`);
  $("trace-src").textContent = "watts measured by macOS powermetrics at 1 Hz, from each run's recorded series; recorded, not live";
}

// ---------- the two comparisons ----------
const ROWS = [
  ["Mean power during the call", "event_w", (r) => r.event_w, (v) => `${fixed(v, 2)} W`],
  ["Reduction vs its own pre-call baseline", null, (r) => r.reduction_pct, (v) => `${fixed(Math.abs(v) < 0.5 ? 0 : v, 0)}%`],   // no "-0%"
  ["Time to compliance", "time_to_compliance_s", (r) => r.time_to_compliance_s, (v) => `${fixed(v, 0)} s`],
  ["Training steps done", "work_train", (r) => (r.work_done || {}).train, (v) => `${fixed(v, 0)}`],
  ["Training deadline met", "deadlines_met", (r) => ("train" in (r.deadlines || {}) ? (r.deadlines.train ? 1 : 0) : null), (v) => (v ? "yes" : "no")],
  ["Energy, measured", "energy_wh", (r) => r.energy_wh, (v) => `${fixed(v, 3)} Wh`],
  ["Cost at the live price", "cost_usd", (r) => r.cost_usd, money],
  ["Carbon at the live mix", "co2_g", (r) => r.co2_g, (v) => `${sig(v)} g`],
];

function renderCompare(box, c, otherLabel) {
  const d = c.dispatched, b = c.baseline, delta = c.delta || {};
  const cell = (v, f) => (v == null || !isFinite(v) ? html`<span class="src">n/a</span>` : f(v));
  const rows = ROWS.map(([label, key, get, f]) => {
    const dl = key ? delta[key] : null;
    return html`<tr><th>${label}</th><td>${cell(get(d), f)}</td><td>${cell(get(b), f)}</td>
      <td>${key == null ? html`<span class="src">each against its own baseline</span>` : dl == null ? html`<span class="src">n/a</span>`
        : key === "deadlines_met" ? (dl > 0 ? "Brownout met it, the other did not" : dl < 0 ? "the other met it, Brownout did not" : "same") : signed(dl, f)}</td></tr>`;
  });
  if (delta.under_cap_pct != null) {
    rows.push(html`<tr><th>Measured seconds at or under the cap</th><td colspan="2" class="src">per run in the notes below</td>
      <td>${signed(delta.under_cap_pct, (v) => `${fixed(v, 0)} points`)}</td></tr>`);
  }
  setHTML(box, html`<table class="rtable compare">
      <thead><tr><th></th><th>Brownout<div class="src">${d.run_id}</div></th><th>${otherLabel}<div class="src">${b.run_id}</div></th><th>Brownout minus ${otherLabel.toLowerCase()}</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <p class="src">recorded, not live · ${dur(c.window_s)} from each run's cap start · computed by the reporter from the timelines</p>
    ${(c.notes || []).length ? html`<ul class="explanations src">${c.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
    ${[...new Set(d.shortfalls || [])].length ? html`<ul class="explanations">${[...new Set(d.shortfalls)].map((s) => html`<li class="warn-line">Brownout: ${s}</li>`)}</ul>` : ""}`);
}

async function loadCompare(pol, otherLabel) {
  const d = $("pick-dispatcher").value, b = $(`pick-${pol}`).value, box = $(`vs-${pol}`);
  if (!d || !b) { setHTML(box, html`<p class="empty">${!d ? "no Brownout run recorded yet" : `no ${otherLabel.toLowerCase()} run recorded yet`}</p>`); return; }
  const r = await getJSON(`/api/compare?dispatched=${encodeURIComponent(d)}&baseline=${encodeURIComponent(b)}`);
  if (!r.ok) { setHTML(box, html`<p class="empty">${routeError("/api/compare", r)}</p>`); return; }
  renderCompare(box, r.data, otherLabel);
}

// ---------- what each run did ----------
function renderActions() {
  setHTML($("actions"), html`${POLICIES.map((pol) => {
    const s = P.series[pol.id];
    if (!s) return html`<div><h2 class="sub-h">${pol.label}</h2><p class="empty">no run loaded</p></div>`;
    const t0 = s.caps[0] ? s.caps[0].start : s.started;
    const acts = s.actions.map((a) => {
      const { t, job, previous, ...rest } = a;
      return html`<li><span class="src">${signed(t - t0, (v) => `${fixed(v, 0)} s`)}</span> <b>${job}</b> ${Object.entries(rest).map(([k, v]) => `${k} ${v}`).join(", ")}</li>`;
    });
    const sfs = [...new Set(s.shortfalls.map((x) => x.message))];
    return html`<div><h2 class="sub-h" style="color:${pol.color}">${pol.label}</h2><div class="src">${recorded(s)}</div>
      ${acts.length ? html`<ul class="explanations">${acts}</ul>` : html`<p class="src">no control actions: this policy does not touch the jobs</p>`}
      ${sfs.map((m) => html`<div class="warn-line">${m}</div>`)}</div>`;
  })}`);
}

async function loadAll() {
  $("proof-load").disabled = true;
  if (await loadRuns()) {
    await Promise.all(POLICIES.map(async (pol) => {
      const id = $(`pick-${pol.id}`).value;
      if (!id) { delete P.series[pol.id]; return; }
      const path = `/api/runs/${encodeURIComponent(id)}/series`;
      const r = await getJSON(path);
      if (r.ok) P.series[pol.id] = r.data; else { delete P.series[pol.id]; $("trace-src").textContent = routeError(path, r); }
    }));
    renderTrace(); renderActions();
    await Promise.all([loadCompare("baseline", "Ignore the call"), loadCompare("pause_all", "Pause everything")]);
  } else {
    for (const id of ["trace", "vs-baseline", "vs-pause_all"]) setHTML($(id), html`<p class="empty">needs the run list: ${$("runs-src").textContent}</p>`);
  }
  $("proof-load").disabled = false;
}

$("proof-load").addEventListener("click", loadAll);
window.brownout = { renderTrace, renderCompare, renderActions, P };   // for drawing recorded fixtures from the console
loadAll();

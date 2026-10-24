// Brownout dashboard. One WebSocket (/ws, HANDOFF.md contract), field names from core/types.py.
// Every number on screen carries its source and its age; missing data says what is missing.
"use strict";

const $ = (id) => document.getElementById(id);
const S = {
  grid: null, schedule: null, plan: null, power: null, jobs: {}, calibration: null, policy: null,
  isoOptions: [], dispatcherEnabled: null, agent: null, latency: null, latencyT: null,
};
const LOG_KINDS = new Set(["grid", "event", "plan", "action", "shortfall", "approval", "policy", "note", "schedule"]);
const LOG_MAX = 200;
const JOB_COLORS = { chat: "#4cc9f0", train: "#f8961e", batch: "#90be6d" };

// ---------- formatting ----------
const nowS = () => Date.now() / 1000;
function age(t) {
  if (t == null) return "age unknown";
  const s = Math.max(0, nowS() - t);
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${(s / 3600).toFixed(1)} h ago`;
}
function sig(x, n = 3) {
  if (x == null || !isFinite(x)) return "—";
  if (x === 0) return "0";
  return Math.abs(x) >= 100 ? x.toFixed(0) : Number(x.toPrecision(n)).toString();
}
// Slot times are ISO-8601 in the ISO's local time ("2026-10-24T14:00:00-07:00"); show that clock, not the browser's.
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function isoClock(s) { return s ? s.slice(11, 16) : "—"; }
function isoDay(s) {
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return DAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}
function isoLabel(s) { return `${isoDay(s)} ${isoClock(s)}`; }
function localClock(t) { return new Date(t * 1000).toLocaleTimeString([], { hour12: false }); }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

// ---------- message handling ----------
function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      S.grid = d.grid; S.schedule = d.schedule; S.plan = d.plan; S.power = d.power;
      S.jobs = d.jobs || {}; S.calibration = d.calibration; S.policy = d.policy;
      S.isoOptions = d.iso_options || []; S.dispatcherEnabled = d.dispatcher_enabled; S.agent = d.agent;
      if (S.jobs.chat && S.jobs.chat.p95_60s !== undefined) {
        S.latency = { p95_60s: S.jobs.chat.p95_60s, n_60s: S.jobs.chat.n_60s }; S.latencyT = S.jobs.chat.t;
      }
      renderAll();
      return;
    case "power": S.power = d; renderNumbers(); break;
    case "grid":
      if (d.feed === "signal") { S.grid = d; renderNumbers(); renderCurve(); renderControls(); }
      break;
    case "schedule": S.schedule = d; renderCurve(); renderSolver(); renderJobs(); break;
    case "plan": S.plan = d; renderSolver(); renderCurve(); renderFeedBadge(); break;
    case "state": if (d.job) { S.jobs[d.job] = d; renderJobs(); } break;
    case "latency": S.latency = d; S.latencyT = msg.t; renderNumbers(); break;
    case "policy": S.policy = d; renderControls(); break;
  }
  if (LOG_KINDS.has(msg.kind)) logEvent(msg);
}

// ---------- row 1: the four live numbers ----------
function renderNumbers() {
  const p = S.power, g = S.grid;
  if (p) {
    $("watts").innerHTML = `${p.combined_w.toFixed(1)}<small>W</small>`;
    const parts = [["CPU", p.cpu_w], ["GPU", p.gpu_w], ["ANE", p.ane_w]]
      .filter(([, v]) => v != null).map(([k, v]) => `${k} ${v.toFixed(1)}`).join(" · ");
    $("watts-src").textContent = `SoC power, measured by macOS powermetrics · ${parts} · ${age(p.t)}`;
  }
  if (p && g) {
    // A laptop costs fractions of a cent per hour; show cents so the number stays readable.
    const usdH = p.combined_w / 1e6 * g.price_now;
    $("cost").innerHTML = Math.abs(usdH) < 0.01 ? `${sig(usdH * 100)}<small>¢/h</small>` : `$${sig(usdH)}<small>/h</small>`;
    const at = g.price_interval_start ? ` @ ${isoClock(g.price_interval_start)}` : "";
    $("cost-src").textContent = `measured W × ${g.iso} ${g.location} real-time $${sig(g.price_now, 4)}/MWh${at} · feed ${age(feedT())}`;
    if (g.carbon_now != null) {
      $("carbon").innerHTML = `${sig(p.combined_w / 1000 * g.carbon_now)}<small>gCO2/h</small>`;
      $("carbon-src").textContent = `measured W × ${g.iso} live fuel mix ${sig(g.carbon_now)} gCO2/kWh · feed ${age(feedT())}`;
    } else {
      $("carbon").textContent = "—";
      $("carbon-src").textContent = `${g.iso} feed has no fuel mix right now`;
    }
  } else if (p && !g) {
    $("cost-src").textContent = $("carbon-src").textContent = "no grid feed yet: price and mix unknown";
  } else if (g && !p) {
    $("cost-src").textContent = $("carbon-src").textContent = "no powermetrics reading yet";
  }
  const l = S.latency;
  if (l && l.p95_60s != null) {
    const sla = S.policy && S.policy.sla ? S.policy.sla.chat_p95_s : null;
    $("p95").innerHTML = `${l.p95_60s.toFixed(2)}<small>s</small>`;
    $("p95").classList.toggle("bad", sla != null && l.p95_60s > sla);
    $("p95-src").textContent = `chat proxy, ${l.n_60s} request(s) in 60 s` + (sla != null ? ` · SLA ${sla} s` : "") + ` · ${age(S.latencyT)}`;
  } else if (l) {
    $("p95").textContent = "—";
    $("p95-src").textContent = "no chat requests in the last 60 s";
  }
  renderFeedBadge();
}

// The feed's age at the moment the server stamped it, plus time since then.
function feedT() { return S.grid ? S.grid.t - (S.grid.feed_age_s || 0) : null; }
function renderFeedBadge() {
  const b = $("feed-age"), g = S.grid;
  if (!g) { b.textContent = "no grid feed"; b.className = "badge warn"; return; }
  const stale = g.stale || (S.plan && S.plan.on_last_known_data);
  b.textContent = `${g.iso} feed ${age(feedT())}` + (stale ? " · STALE" : "");
  b.className = "badge " + (stale ? "bad" : "ok");
}

// ---------- row 2: curves with the schedule painted on ----------
let chart = null;
function currentSlotIndex(slots, minutes) {
  const t = Date.now();
  return slots.findIndex((s) => { const a = Date.parse(s); return t >= a && t < a + minutes * 60000; });
}
const slotHighlight = {
  id: "slotHighlight",
  beforeDatasetsDraw(c) {
    const i = c.$currentSlot;
    if (i == null || i < 0) return;
    const x = c.scales.x, a = c.chartArea, w = (a.right - a.left) / c.data.labels.length;
    c.ctx.save();
    c.ctx.fillStyle = "rgba(255,255,255,0.12)";
    c.ctx.fillRect(x.getPixelForValue(i) - w / 2, a.top, w, a.bottom - a.top);
    c.ctx.restore();
  },
};

function renderCurve() {
  const g = S.grid, sc = S.schedule;
  const slots = sc ? sc.slots : g ? g.price_curve.map((p) => p[0]) : [];
  if (!slots.length) return;
  const byT = (pts) => { const m = new Map(pts.map(([t, v]) => [Date.parse(t), v])); return slots.map((s) => m.get(Date.parse(s)) ?? null); };
  const price = g ? byT(g.price_curve) : [];
  const carbon = g ? byT(g.carbon_curve) : [];
  const minutes = sc ? sc.slot_minutes : (S.policy && S.policy.slot_minutes) || 15;
  const cur = currentSlotIndex(slots, minutes);
  const labels = slots.map(isoLabel);
  if (!chart) {
    chart = new Chart($("curve"), {
      type: "line",
      data: { labels, datasets: [
        { label: "price $/MWh", data: price, borderColor: "#f72585", backgroundColor: "#f72585", yAxisID: "y", stepped: true, pointRadius: 0, borderWidth: 2 },
        { label: "carbon gCO2/kWh", data: carbon, borderColor: "#adb5bd", backgroundColor: "#adb5bd", yAxisID: "y2", stepped: true, pointRadius: 0, borderWidth: 2, borderDash: [6, 4] },
      ] },
      options: {
        animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#ccc", maxRotation: 0, autoSkip: true, maxTicksLimit: 9 }, grid: { color: "#333" } },
          y: { position: "left", title: { display: true, text: "$/MWh", color: "#f72585" }, ticks: { color: "#ccc" }, grid: { color: "#333" } },
          y2: { position: "right", title: { display: true, text: "gCO2/kWh", color: "#adb5bd" }, ticks: { color: "#ccc" }, grid: { display: false } },
        },
      },
      plugins: [slotHighlight],
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = price;
    chart.data.datasets[1].data = carbon;
  }
  chart.$currentSlot = cur;
  chart.update();
  renderStrips(slots, cur);

  const src = [];
  if (g) {
    src.push(`price: ${g.iso} ${g.location}, ${g.price_curve_source || "source not stated"}`);
    src.push(g.carbon_curve_is_proxy ? "carbon curve: live mix held flat (proxy)" : "carbon curve: from the feed");
    if (g.source_urls && g.source_urls.length) src.push(g.source_urls.join(", "));
  } else src.push("no grid feed yet");
  if (sc) src.push(`schedule ${sc.id}, solved ${age(sc.solve_t)}`); else src.push("no schedule yet: waiting for the solver");
  if (g && g.alerts && g.alerts.length) src.push(`ALERTS: ${g.alerts.join("; ")}`);
  $("curve-src").textContent = src.join(" · ");
}

// One row per job, one cell per slot, aligned under the chart's plot area.
function renderStrips(slots, cur) {
  const box = $("strips"), sc = S.schedule;
  if (!sc) { box.innerHTML = '<div class="empty">no schedule yet: job rows appear when the solver publishes one</div>'; return; }
  const a = chart.chartArea;
  box.style.paddingLeft = `${a.left}px`;
  box.style.paddingRight = `${chart.width - a.right}px`;
  box.innerHTML = Object.entries(sc.assignments).map(([job, row]) => {
    const color = JOB_COLORS[job] || "#ddd";
    const cells = row.map((x, i) => {
      const cls = ["cell", x.run ? `run-${x.device || "gpu"}` : "", i === cur ? "now" : ""].join(" ");
      const tip = `${job} ${isoLabel(slots[i])}: ` + (x.run ? `run on ${x.device || "?"}` + (x.concurrency ? `, concurrency ${x.concurrency}` : "") : "off");
      return `<span class="${cls}" style="--c:${color}" title="${esc(tip)}"></span>`;
    }).join("");
    return `<div class="strip"><span class="strip-name" style="color:${color}">${esc(job)}</span><div class="cells" style="grid-template-columns:repeat(${row.length},1fr)">${cells}</div></div>`;
  }).join("");
}

// ---------- row 3: job cards ----------
function renderJobs() {
  const ids = [...new Set([...Object.keys(S.jobs), ...(S.schedule ? Object.keys(S.schedule.assignments) : [])])];
  if (!ids.length) { $("jobs").innerHTML = '<div class="tile empty">no job status yet: waiting for the workloads</div>'; return; }
  $("jobs").innerHTML = ids.map((id) => {
    const st = S.jobs[id] || {};
    const lines = [];
    lines.push(`<div class="kv"><b>device</b> ${esc(st.device || "—")}</div>`);
    if (st.concurrency != null) lines.push(`<div class="kv"><b>concurrency</b> ${st.concurrency}${st.inflight != null ? ` (${st.inflight} in flight)` : ""}</div>`);
    if (st.max_tokens != null) lines.push(`<div class="kv"><b>max tokens</b> ${st.max_tokens}${st.model ? ` · ${esc(st.model)}` : ""}</div>`);
    if (st.step != null) lines.push(`<div class="kv"><b>step</b> ${st.step}${st.loss != null ? ` · loss ${sig(st.loss)}` : ""}</div>`);
    if (st.items_done != null) {
      const f = st.fraction != null ? st.fraction : st.total ? st.items_done / st.total : null;
      lines.push(`<div class="kv"><b>items</b> ${st.items_done}${st.total != null ? ` / ${st.total}` : ""}</div>`);
      if (f != null) lines.push(`<div class="bar"><span style="width:${(f * 100).toFixed(1)}%"></span></div>`);
    }
    if (st.rate != null) lines.push(`<div class="kv"><b>rate</b> ${sig(st.rate)} ${id === "train" ? "steps/s" : id === "batch" ? "items/s" : "/s"} (measured by the workload)</div>`);
    const cal = S.calibration && S.calibration.jobs[id] && st.device ? S.calibration.jobs[id][st.device] : null;
    if (cal) lines.push(`<div class="kv"><b>calibrated</b> +${sig(cal.delta_w)} W on ${esc(st.device)} (powermetrics, ${age(S.calibration.measured_at)})</div>`);
    lines.push(`<div class="kv"><b>schedule</b> ${esc(nextRun(id))}</div>`);
    const state = st.state || "no status";
    return `<div class="tile job" style="--c:${JOB_COLORS[id] || "#ddd"}">
      <div class="job-head"><h3>${esc(id)}</h3><span class="badge state-${esc(state)}">${esc(state)}</span></div>
      ${lines.join("")}
      <div class="src">status ${age(st.t)}</div></div>`;
  }).join("");
}

function nextRun(id) {
  const sc = S.schedule;
  if (!sc || !sc.assignments[id]) return "not in the current schedule";
  const row = sc.assignments[id];
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  const from = Math.max(cur, 0);
  const n = row.filter((x) => x.run).length;
  if (cur >= 0 && row[cur].run) return `runs this slot on ${row[cur].device}; ${n} of ${row.length} slots planned`;
  const i = row.findIndex((x, k) => k >= from && x.run);
  return i < 0 ? "no run planned in the remaining horizon" : `next run ${isoLabel(sc.slots[i])} on ${row[i].device}; ${n} of ${row.length} slots planned`;
}

// ---------- row 4: solver plan + explanations, event log ----------
function renderSolver() {
  const p = S.plan, sc = S.schedule;
  if (p) {
    const acts = (p.actions || []).map((a) => `<li><b>${esc(a.job)}</b> → ${esc(a.state)}` +
      (a.device ? ` on ${esc(a.device)}` : "") + (a.concurrency != null ? `, concurrency ${a.concurrency}` : "") + "</li>").join("");
    const head = [`${p.mode === "baseline" ? "BASELINE (dispatcher off)" : "Dispatcher plan"} for slot ${p.slot_start ? isoLabel(p.slot_start) : "—"}`];
    if (p.planned_w != null) head.push(`planned ${sig(p.planned_w)} W (calibrated, not measured)`);
    if (p.cap_w != null) head.push(`cap ${sig(p.cap_w)} W`);
    let html = `<div class="plan-head">${esc(head.join(" · "))}</div><ul>${acts}</ul>`;
    if (p.on_last_known_data) html += '<div class="warn-line">on last known data: the grid feed is stale</div>';
    if (p.needs_approval && p.needs_approval.length) html += `<div class="warn-line">needs approval: ${esc(p.needs_approval.join(", "))}</div>`;
    $("plan").innerHTML = html;
  } else {
    $("plan").innerHTML = '<div class="empty">no plan for the current slot yet</div>';
  }
  if (sc) {
    const items = sc.explanations.map((e) => `<li>${esc(e)}</li>`);
    sc.shortfalls.forEach((s) => items.push(`<li class="bad">shortfall (${esc(s.kind)}${s.job_id ? `, ${esc(s.job_id)}` : ""}): ${esc(s.message)}</li>`));
    sc.deadline_misses.forEach((m) => items.push(`<li class="bad">${esc(m.job_id)} misses its deadline by ${m.slip_min} min</li>`));
    $("explanations").innerHTML = items.join("") || '<li class="empty">the solver gave no explanations</li>';
    $("solve-src").textContent = `CP-SAT ${sc.solver_status || "?"} in ${sig(sc.solve_wall_s)} s` + (sc.relaxed ? " (relaxed: infeasible as asked)" : "") +
      ` · planned 24 h: $${sig(sc.cost_usd)}, ${sig(sc.co2_g)} gCO2 · solved ${age(sc.solve_t)}` + (sc.on_stale_data ? " · on stale data" : "");
  } else {
    $("explanations").innerHTML = '<li class="empty">no schedule yet: waiting for the solver</li>';
    $("solve-src").textContent = "";
  }
}

function summary(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "grid":
      if (d.feed === "signal") return `${d.iso} $${sig(d.price_now, 4)}/MWh` + (d.carbon_now != null ? `, ${sig(d.carbon_now)} gCO2/kWh` : "") + (d.alerts && d.alerts.length ? ` · ALERT ${d.alerts.join("; ")}` : "") + (d.stale ? " · STALE" : "");
      return `${d.feed || "feed"} update`;
    case "schedule": return `new schedule ${d.id}: ${d.solver_status}` + (d.shortfalls && d.shortfalls.length ? `, ${d.shortfalls.length} shortfall(s)` : "");
    case "plan": return `${d.mode || "plan"} for ${d.slot_start ? isoLabel(d.slot_start) : "?"}: ` + (d.actions || []).map((a) => `${a.job} ${a.state}`).join(", ");
    case "action": {
      const { job, previous, ...rest } = d;
      return `${job}: ` + Object.entries(rest).map(([k, v]) => `${k} ${previous && previous[k] != null ? `${previous[k]} → ` : ""}${v}`).join(", ");
    }
    case "shortfall": return d.message || JSON.stringify(d);
    case "approval": return `${d.approver || d.owner || "?"} ${d.decision || d.status || ""} ${d.reason ? `(“${d.reason}”)` : ""}`;
    case "policy": return `policy: objective ${d.objective}` + (d.power_cap_w != null ? `, cap ${d.power_cap_w} W` : "");
    case "event": return d.reason || d.raw || JSON.stringify(d);
    case "note": return d.msg || d.message || d.text || JSON.stringify(d);
  }
  return JSON.stringify(d);
}
function logEvent(msg) {
  const li = document.createElement("li");
  const bad = msg.kind === "shortfall" || (msg.kind === "grid" && msg.data && ((msg.data.alerts || []).length || msg.data.stale));
  li.className = `k-${msg.kind}` + (bad ? " bad" : "");
  li.innerHTML = `<time>${msg.t ? localClock(msg.t) : "—"}</time><span class="kind">${esc(msg.kind)}</span><span>${esc(summary(msg))}</span>`;
  const log = $("log");
  log.prepend(li);
  while (log.children.length > LOG_MAX) log.lastChild.remove();
}

// ---------- header: controls and status badges ----------
function renderControls() {
  const iso = $("iso");
  const current = S.grid ? S.grid.iso : null;
  const want = S.isoOptions.join(",");
  if (iso.dataset.opts !== want) {
    iso.innerHTML = S.isoOptions.map((o) => `<option>${esc(o)}</option>`).join("");
    iso.dataset.opts = want;
  }
  if (current) iso.value = current;
  if (S.policy) $("objective").value = S.policy.objective;
  const b = $("dispatcher");
  if (S.dispatcherEnabled != null) {
    b.textContent = S.dispatcherEnabled ? "DISPATCHER ON" : "DISPATCHER OFF (baseline)";
    b.classList.toggle("off", !S.dispatcherEnabled);
  }
  const ag = $("agent");
  ag.textContent = S.agent === "online" ? "agent online" : S.agent === "offline" ? "agent offline" : "agent ?";
  ag.className = "badge " + (S.agent === "online" ? "ok" : "warn");
}

function renderAll() { renderControls(); renderNumbers(); renderCurve(); renderJobs(); renderSolver(); }

async function post(path, body) {
  try {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return await r.json();
  } catch (e) {
    logEvent({ t: nowS(), kind: "note", data: { msg: `${path} failed: ${e.message}` } });
    return null;
  }
}
$("iso").addEventListener("change", (e) => post("/api/iso", { iso: e.target.value }));
$("objective").addEventListener("change", (e) => post("/api/policy", { objective: e.target.value }));
$("dispatcher").addEventListener("click", async () => {
  const r = await post("/api/dispatcher", { enabled: !S.dispatcherEnabled });
  if (r) { S.dispatcherEnabled = r.enabled; renderControls(); }
});

// ---------- connection ----------
let backoff = 500;
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  const c = $("conn");
  ws.onopen = () => { backoff = 500; c.textContent = "live"; c.className = "badge ok"; };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    c.textContent = "disconnected: reconnecting"; c.className = "badge bad";
    setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 8000);
  };
}
// Ages tick every second even when no message arrives, so a silent feed visibly gets old.
setInterval(() => { renderNumbers(); renderJobs(); }, 1000);
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
renderAll();
connect();

// Brownout dashboard. One WebSocket (/ws, HANDOFF.md contract), field names from core/types.py.
// Every number on screen carries its source and its age; missing data says what is missing.
"use strict";

const S = {
  grid: null, schedule: null, plan: null, power: null, jobs: {}, calibration: null, policy: null,
  isoOptions: [], iso: null, dispatcherEnabled: null, agent: null, agentModel: null, runId: null,
  jobSpecs: {}, quote: null, explanation: null, hardDeadlines: new Set(),
};
const LOG_KINDS = new Set(["grid", "event", "plan", "action", "shortfall", "approval", "policy", "note", "schedule"]);
const LOG_MAX = 200;
const JOB_COLORS = { chat: "#4cc9f0", train: "#f8961e", batch: "#90be6d" };
const STALE_POWER_S = 5, STALE_STATUS_S = 10;

// ---------- message handling ----------
function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      S.grid = d.grid; S.schedule = d.schedule; S.plan = d.plan; S.power = d.power;
      S.jobs = d.jobs || {}; S.calibration = d.calibration; S.policy = d.policy;
      S.isoOptions = d.iso_options || []; S.iso = d.iso || null; S.dispatcherEnabled = d.dispatcher_enabled;
      S.agent = d.agent; S.agentModel = d.agent_model || null; S.runId = d.run_id || null;
      S.jobSpecs = d.job_specs || {}; S.quote = d.quote || null;
      S.explanation = d.explanation ? { data: d.explanation, scheduleId: d.schedule ? d.schedule.id : null, t: null } : null;
      renderAll();
      return;
    case "power": S.power = d; renderNumbers(); break;
    case "grid":
      if (d.feed === "signal") { S.grid = d; S.iso = d.iso; renderNumbers(); renderCurve(); renderControls(); }
      break;
    case "schedule": S.schedule = d; renderCurve(); renderSolver(); renderJobs(); break;
    case "plan": S.plan = d; renderSolver(); renderCurve(); renderFeedBadge(); break;
    case "state": if (d.job) { S.jobs[d.job] = d; renderJobs(); renderNumbers(); } break;
    case "policy": onPolicy(d); break;
    case "note":
      if (d.explanation) { S.explanation = { data: d.explanation, scheduleId: d.schedule_id || null, t: msg.t }; renderSolver(); }
      break;
  }
  if (LOG_KINDS.has(msg.kind)) logEvent(msg);
}

// `policy` events come in several shapes (controller/execute.py): a full Policy dump, an ISO switch,
// a job change, a deadline kept by its owner, a dispatcher toggle.
function onPolicy(d) {
  if (d.objective !== undefined) S.policy = d;
  if (d.dispatcher_enabled !== undefined) S.dispatcherEnabled = d.dispatcher_enabled;
  if (d.reason === "job change" && d.job && d.changes && "deadline" in d.changes && S.jobSpecs[d.job]) {
    S.jobSpecs[d.job].deadline = d.changes.deadline;
  }
  if (d.reason === "deadline kept by owner" && d.job) S.hardDeadlines.add(d.job);
  renderControls(); renderJobs(); renderNumbers();
}

// ---------- row 1: the four live numbers ----------
function renderNumbers() {
  const p = S.power, g = S.grid;
  if (p) {
    const stale = nowS() - p.t > STALE_POWER_S;
    setHTML($("watts"), html`${p.combined_w.toFixed(1)}<small>W</small>`);
    $("watts").classList.toggle("stale", stale);
    const parts = [["CPU", p.cpu_w], ["GPU", p.gpu_w], ["ANE", p.ane_w]]
      .filter(([, v]) => v != null).map(([k, v]) => `${k} ${v.toFixed(1)}`).join(" · ");
    $("watts-src").textContent = (stale ? `STALE: no powermetrics sample for ${age(p.t).replace(" ago", "")} · ` : "") +
      `SoC power, measured by macOS powermetrics · ${parts} · ${age(p.t)}`;
  }
  if (p && g) {
    // A laptop costs fractions of a cent per hour; show cents so the number stays readable.
    const usdH = p.combined_w / 1e6 * g.price_now;
    setHTML($("cost"), Math.abs(usdH) < 0.01 ? html`${sig(usdH * 100)}<small>¢/h</small>` : html`$${sig(usdH)}<small>/h</small>`);
    const at = g.price_interval_start ? ` @ ${isoClock(g.price_interval_start)}` : "";
    $("cost-src").textContent = `measured W × ${g.iso} ${g.location} real-time $${sig(g.price_now, 4)}/MWh${at} · feed ${age(feedT())}` + (g.stale ? " · STALE" : "");
    if (g.carbon_now != null) {
      setHTML($("carbon"), html`${sig(p.combined_w / 1000 * g.carbon_now)}<small>gCO2/h</small>`);
      $("carbon-src").textContent = `measured W × ${g.iso} live fuel mix ${sig(g.carbon_now)} gCO2/kWh · feed ${age(feedT())}` + (g.stale ? " · STALE" : "");
    } else {
      $("carbon").textContent = "—";
      $("carbon-src").textContent = `${g.iso} feed has no fuel mix right now: carbon unknown`;
    }
  } else if (p && !g) {
    $("cost-src").textContent = $("carbon-src").textContent = "no grid feed yet: price and mix unknown";
  } else if (g && !p) {
    $("cost-src").textContent = $("carbon-src").textContent = "no powermetrics reading yet: watts unknown";
  }
  renderChatTile();
  renderFeedBadge();
}

// Chat SLA is time to first token (policy.sla.chat_ttft_p95_s); total latency depends on reply length.
function renderChatTile() {
  const c = S.jobs.chat, sla = S.policy && S.policy.sla ? S.policy.sla.chat_ttft_p95_s : null;
  $("ttft-label").textContent = "Chat time to first token, p95 (60 s)" + (sla != null ? ` · SLA ≤ ${sla} s` : "");
  if (!c || c.t == null) { $("ttft-src").textContent = "no chat proxy status yet"; return; }
  const stale = nowS() - c.t > STALE_STATUS_S;
  if (c.ttft_p95_60s != null) {
    setHTML($("ttft"), html`${c.ttft_p95_60s.toFixed(2)}<small>s</small>`);
    $("ttft").classList.toggle("bad", sla != null && c.ttft_p95_60s > sla);
  } else {
    $("ttft").textContent = "—";
    $("ttft").classList.remove("bad");
  }
  $("ttft").classList.toggle("stale", stale);
  $("total-p95").textContent = c.p95_60s != null ? `total ${c.p95_60s.toFixed(1)} s (depends on reply length)` : "total — (no replies in 60 s)";
  $("ttft-src").textContent = (stale ? "STALE · " : "") + (c.n_60s ? `chat proxy, measured over ${plural(c.n_60s, "reply", "replies")} in 60 s` : "chat proxy: no chat requests in the last 60 s") +
    (sla != null ? ` · SLA from policy` : " · no TTFT SLA in policy") + ` · ${age(c.t)}`;
}

// The feed's age at the moment the server stamped it, plus time since then.
function feedT() { return S.grid ? S.grid.t - (S.grid.feed_age_s || 0) : null; }
function renderFeedBadge() {
  const b = $("feed-age"), g = S.grid;
  if (!g) { b.textContent = "no grid feed yet"; b.className = "badge warn"; return; }
  const stale = g.stale || (S.plan && S.plan.on_last_known_data);
  b.textContent = `${g.iso} feed ${age(feedT())}` + (stale ? " · STALE: plan on last known data" : "");
  b.className = "badge " + (stale ? "bad" : "ok");
}

// ---------- row 2: curves with the schedule painted on ----------
let chart = null;
const slotHighlight = {
  id: "slotHighlight",
  beforeDatasetsDraw(c) {
    const i = c.$currentSlot;
    if (i == null || i < 0) return;
    const x = c.scales.x, a = c.chartArea, w = (a.right - a.left) / c.data.labels.length;
    c.ctx.save();
    c.ctx.fillStyle = "rgba(255,255,255,0.16)";
    c.ctx.fillRect(x.getPixelForValue(i) - w / 2, a.top, w, a.bottom - a.top);
    c.ctx.restore();
  },
};

function renderCurve() {
  const g = S.grid, sc = S.schedule;
  const slots = sc ? sc.slots : g ? g.price_curve.map((p) => p[0]) : [];
  if (!slots.length) {
    $("curve-src").textContent = (g ? "" : "no grid feed yet · ") + "no schedule yet: waiting for the solver";
    renderStrips([], -1);
    return;
  }
  const byT = (pts) => { const m = new Map(pts.map(([t, v]) => [Date.parse(t), v])); return slots.map((s) => m.get(Date.parse(s)) ?? null); };
  const price = g ? byT(g.price_curve) : [];
  const carbon = g ? byT(g.carbon_curve) : [];
  const minutes = sc ? sc.slot_minutes : (S.policy && S.policy.slot_minutes) || 15;
  const cur = currentSlotIndex(slots, minutes);
  const labels = slots.map(isoLabel);
  if (!chart) {
    const tick = { color: "#e1e5ea", font: { size: 14 } };
    chart = new Chart($("curve"), {
      type: "line",
      data: { labels, datasets: [
        { label: "price $/MWh", data: price, borderColor: "#ff4fa3", backgroundColor: "#ff4fa3", yAxisID: "y", stepped: true, pointRadius: 0, borderWidth: 3 },
        { label: "carbon gCO2/kWh", data: carbon, borderColor: "#cfd6dd", backgroundColor: "#cfd6dd", yAxisID: "y2", stepped: true, pointRadius: 0, borderWidth: 2.5, borderDash: [6, 4] },
      ] },
      options: {
        animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { ...tick, maxRotation: 0, autoSkip: true, maxTicksLimit: 9 }, grid: { color: "#353b47" } },
          y: { position: "left", title: { display: true, text: "$/MWh", color: "#ff4fa3", font: { size: 14 } }, ticks: tick, grid: { color: "#353b47" } },
          y2: { position: "right", title: { display: true, text: "gCO2/kWh", color: "#cfd6dd", font: { size: 14 } }, ticks: tick, grid: { display: false } },
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
  if (!sc || !chart) { setHTML(box, html`<div class="empty">no schedule yet: job rows appear when the solver publishes one</div>`); return; }
  const a = chart.chartArea;
  box.style.paddingLeft = `${a.left}px`;
  box.style.paddingRight = `${chart.width - a.right}px`;
  setHTML(box, html`${Object.entries(sc.assignments).map(([job, row]) => {
    const color = JOB_COLORS[job] || "#ddd";
    const cells = row.map((x, i) => {
      const cls = ["cell", x.run ? `run-${x.device || "gpu"}` : "", i === cur ? "now" : ""].join(" ");
      const tip = `${job} ${isoLabel(slots[i])}: ` + (x.run ? `run on ${x.device || "?"}` + (x.concurrency ? `, concurrency ${x.concurrency}` : "") : "off");
      return html`<span class="${cls}" style="--c:${color}" title="${tip}"></span>`;
    });
    return html`<div class="strip"><span class="strip-name" style="color:${color}">${job}</span><div class="cells" style="grid-template-columns:repeat(${row.length},1fr)">${cells}</div></div>`;
  })}`);
}

// ---------- row 3: job cards ----------
function renderJobs() {
  const ids = [...new Set([...Object.keys(S.jobSpecs), ...Object.keys(S.jobs), ...(S.schedule ? Object.keys(S.schedule.assignments) : [])])];
  if (!ids.length) { setHTML($("jobs"), html`<div class="tile empty">no job status yet: waiting for the workloads</div>`); return; }
  setHTML($("jobs"), html`${ids.map(jobCard)}`);
}

function kv(k, v) { return html`<div class="kv"><b>${k}</b> ${v}</div>`; }
function jobCard(id) {
  const st = S.jobs[id] || {}, spec = S.jobSpecs[id];
  const lines = [];
  if (spec) {
    const dl = spec.deadline ? `${isoLabel(spec.deadline)}` + (S.hardDeadlines.has(id) ? " (kept by owner: hard)" : "") : "none";
    lines.push(kv("owner", spec.owner));
    lines.push(kv("deadline", dl));
  }
  lines.push(kv("device", st.device || "—"));
  if (id === "chat") {
    if (st.concurrency != null) lines.push(kv("concurrency", `${st.concurrency}` + (st.inflight != null ? ` (${st.inflight} in flight)` : "")));
    const planned = S.schedule ? (S.schedule.chat_busy_streams != null ? `${sig(S.schedule.chat_busy_streams)} busy streams` : "full concurrency") : "no schedule yet";
    lines.push(kv("traffic", `${st.busy_60s != null ? sig(st.busy_60s) : "—"} busy (measured, 60 s) · plan assumed ${planned}`));
    if (st.max_tokens != null) lines.push(kv("max tokens", `${st.max_tokens}` + (st.model ? ` · ${st.model}` : "")));
  } else if (st.concurrency != null) {
    lines.push(kv("concurrency", st.concurrency));
  }
  if (st.step != null) lines.push(kv("step", `${st.step}` + (spec && spec.target_steps ? ` / ${spec.target_steps}` : "") + (st.loss != null ? ` · loss ${sig(st.loss)}` : "")));
  if (st.step != null && spec && spec.target_steps) lines.push(html`<div class="bar"><span style="width:${Math.min(100, st.step / spec.target_steps * 100).toFixed(1)}%"></span></div>`);
  if (st.items_done != null) {
    const f = st.fraction != null ? st.fraction : st.total ? st.items_done / st.total : null;
    lines.push(kv("items", `${st.items_done}` + (st.total != null ? ` / ${st.total}` : "")));
    if (f != null) lines.push(html`<div class="bar"><span style="width:${(f * 100).toFixed(1)}%"></span></div>`);
  }
  if (st.rate != null) lines.push(kv("rate", `${sig(st.rate)} ${id === "train" ? "steps/s" : id === "batch" ? "items/s" : "/s"} (measured by the workload)`));
  const cal = S.calibration && S.calibration.jobs[id] && st.device ? S.calibration.jobs[id][st.device] : null;
  if (cal) lines.push(kv("calibrated", `+${sig(cal.delta_w)} W on ${st.device} (powermetrics, ${age(S.calibration.measured_at)})`));
  lines.push(kv("schedule", nextRun(id)));
  const state = st.state || "no status";
  const stale = st.t != null && nowS() - st.t > STALE_STATUS_S;
  return html`<div class="tile job" style="--c:${JOB_COLORS[id] || "#ddd"}">
    <div class="job-head"><h3>${id}</h3><span class="badge state-${state}">${state}</span></div>
    ${lines}
    <div class="src">${st.t == null ? "no status from the workload yet" : (stale ? "STALE · " : "") + `status ${age(st.t)}`}${spec ? " · owner and deadline from config/jobs.yaml + approvals" : ""}</div></div>`;
}

function nextRun(id) {
  const sc = S.schedule;
  if (!sc || !sc.assignments[id]) return "not in the current schedule";
  const row = sc.assignments[id];
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  const from = Math.max(cur, 0);
  const n = row.filter((x) => x.run).length;
  const miss = sc.deadline_misses.find((m) => m.job_id === id);
  const tail = miss ? ` · MISSES deadline by ${miss.slip_min} min` : "";
  if (cur >= 0 && row[cur].run) return `runs this slot on ${row[cur].device}; ${n} of ${row.length} slots planned${tail}`;
  const i = row.findIndex((x, k) => k >= from && x.run);
  return (i < 0 ? "no run planned in the remaining horizon" : `next run ${isoLabel(sc.slots[i])} on ${row[i].device}; ${n} of ${row.length} slots planned`) + tail;
}

// ---------- row 4: explanation + solver plan, event log ----------
function renderSolver() {
  const p = S.plan, sc = S.schedule, ex = S.explanation;
  if (ex) {
    const e = ex.data, mine = !sc || !ex.scheduleId || ex.scheduleId === sc.id;
    const who = e.llm_used ? `agent${S.agentModel ? ` · ${S.agentModel}` : ""}` : "facts only";
    setHTML($("explain"), html`<span class="badge ${e.llm_used ? "ok" : "warn"}">${who}</span> <span class="explain-text">${e.text}</span>`);
    $("explain-src").textContent = (e.llm_used ? "written by the agent from the solver's facts below" : "the agent did not write this: the solver's facts, joined") +
      (ex.scheduleId ? ` · for schedule ${ex.scheduleId}` : "") + (mine ? "" : " · OLDER than the current schedule: new explanation pending") + (ex.t ? ` · ${age(ex.t)}` : "");
  } else {
    setHTML($("explain"), html`<span class="empty">no explanation yet: it arrives with the next schedule</span>`);
    $("explain-src").textContent = "";
  }
  if (p) {
    const acts = (p.actions || []).map((a) => html`<li><b>${a.job}</b> → ${a.state}${a.device ? ` on ${a.device}` : ""}${a.concurrency != null ? `, concurrency ${a.concurrency}` : ""}</li>`);
    const head = [`${p.mode === "baseline" ? "BASELINE (dispatcher off)" : "Dispatcher plan"} for slot ${p.slot_start ? isoLabel(p.slot_start) : "—"}`];
    if (p.planned_w != null) head.push(`planned ${sig(p.planned_w)} W (calibrated, not measured)`);
    if (p.cap_w != null) head.push(`cap ${sig(p.cap_w)} W`);
    setHTML($("plan"), html`<div class="plan-head">${head.join(" · ")}</div><ul>${acts}</ul>
      ${p.on_last_known_data ? html`<div class="warn-line">on last known data: the grid feed is stale</div>` : ""}
      ${p.needs_approval && p.needs_approval.length ? html`<div class="warn-line">waiting for approval: ${p.needs_approval.join(", ")}</div>` : ""}`);
  } else {
    setHTML($("plan"), html`<div class="empty">no plan for the current slot yet</div>`);
  }
  if (sc) {
    const items = sc.explanations.map((e) => html`<li>${e}</li>`);
    sc.shortfalls.forEach((s) => items.push(html`<li class="bad">shortfall (${s.kind}${s.job_id ? `, ${s.job_id}` : ""}): ${s.message}</li>`));
    sc.deadline_misses.forEach((m) => items.push(html`<li class="bad">${m.job_id} misses its deadline by ${m.slip_min} min</li>`));
    setHTML($("explanations"), items.length ? html`${items}` : html`<li class="empty">the solver gave no facts</li>`);
    $("solve-src").textContent = `CP-SAT ${sc.solver_status || "?"} in ${sig(sc.solve_wall_s)} s` + (sc.relaxed ? " (relaxed: infeasible as asked)" : "") +
      ` · planned 24 h: $${sig(sc.cost_usd)}, ${sig(sc.co2_g)} gCO2 (calibrated W × forecast curves) · solved ${age(sc.solve_t)}` + (sc.on_stale_data ? " · on stale data" : "");
  } else {
    setHTML($("explanations"), html`<li class="empty">no schedule yet: waiting for the solver</li>`);
    $("solve-src").textContent = "";
  }
}

function summary(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "grid":
      if (d.feed === "signal") return `${d.iso} $${sig(d.price_now, 4)}/MWh` + (d.carbon_now != null ? `, ${sig(d.carbon_now)} gCO2/kWh` : "") + (d.alerts && d.alerts.length ? ` · ALERT ${d.alerts.join("; ")}` : "") + (d.stale ? " · STALE" : "");
      return `${d.iso || ""} ${d.feed || "feed"} update`;
    case "schedule": return `new schedule ${d.id}${d.reason ? ` (${d.reason})` : ""}: ${d.solver_status}` + (d.shortfalls && d.shortfalls.length ? `, ${plural(d.shortfalls.length, "shortfall")}` : "");
    case "plan": return `${d.mode || "plan"} for ${d.slot_start ? isoLabel(d.slot_start) : "?"}: ` + (d.actions || []).map((a) => `${a.job} ${a.state}`).join(", ");
    case "action": {
      const { job, previous, ...rest } = d;
      return `${job}: ` + Object.entries(rest).map(([k, v]) => `${k} ${previous && previous[k] != null ? `${previous[k]} → ` : ""}${v}`).join(", ");
    }
    case "shortfall": return `${d.shortfall_kind || "?"}${d.job_id ? ` (${d.job_id})` : ""}: ${d.message || ""}`;
    case "approval":
      if (d.decision) return `${d.who || "?"} replied to ${d.request_id}: ${d.decision.decision}` + (d.decision.reason ? ` (“${d.decision.reason}”)` : "");
      return `${d.id} ${d.job_id} → ${d.owner}: ${d.status}` + (d.why ? ` (${d.why})` : d.status === "pending" ? ` · “${d.message}”` : "");
    case "policy":
      if (d.reason === "job change") return `${d.job}: ${Object.entries(d.changes || {}).map(([k, v]) => `${k} → ${v == null ? "none" : k === "deadline" ? isoLabel(v) : v}`).join(", ")}`;
      if (d.reason === "deadline kept by owner") return `${d.job}: deadline kept by owner` + (d.owner_reason ? ` (“${d.owner_reason}”)` : "");
      if (d.reason === "dispatcher toggle") return `dispatcher ${d.dispatcher_enabled ? "ON" : "OFF (baseline)"}`;
      if (d.reason === "iso change") return `ISO → ${d.iso} ${d.location || ""}`;
      return `policy: objective ${d.objective}` + (d.power_cap_w != null ? `, cap ${d.power_cap_w} W` : "");
    case "event":
      if (d.intake) return `${d.who || "?"} → intake ${d.intake.kind}: ${d.intake.readback || d.intake.question || d.intake.reason || ""}`;
      return `cap ${d.target_w != null ? `${sig(d.target_w)} W` : `${d.target_pct}%`} from ${isoLabel(d.start)} for ${dur(d.duration_s)} (${d.source})` + (d.reason ? `: ${d.reason}` : "");
    case "note":
      if (d.explanation) return `explanation (${d.explanation.llm_used ? "agent" : "facts only"}): ${d.explanation.text}`;
      return d.msg || d.error || JSON.stringify(d);
  }
  return JSON.stringify(d);
}
function logEvent(msg) {
  const li = document.createElement("li");
  const bad = msg.kind === "shortfall" || (msg.kind === "grid" && msg.data && ((msg.data.alerts || []).length || msg.data.stale)) ||
    (msg.kind === "note" && msg.data && msg.data.level === "error");
  li.className = `k-${msg.kind}` + (bad ? " bad" : "");
  setHTML(li, html`<time>${msg.t ? localClock(msg.t) : "—"}</time><span class="kind">${msg.kind}</span><span>${summary(msg)}</span>`);
  const log = $("log");
  const empty = log.querySelector(".empty");
  if (empty) empty.remove();
  log.prepend(li);
  while (log.children.length > LOG_MAX) log.lastChild.remove();
}

// ---------- header: controls, status badges, quote ----------
function renderControls() {
  const iso = $("iso");
  const current = S.grid ? S.grid.iso : S.iso;
  const want = S.isoOptions.join(",");
  if (iso.dataset.opts !== want) {
    setHTML(iso, html`${S.isoOptions.map((o) => html`<option>${o}</option>`)}`);
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
  ag.textContent = S.agent === "online" ? `agent online${S.agentModel ? ` · ${S.agentModel}` : ""}` : S.agent === "offline" ? "agent offline: solver + controller still run" : "agent ?";
  ag.className = "badge " + (S.agent === "online" ? "ok" : "warn");
  const q = S.quote;
  if (q && q.text) setHTML($("quote"), html`<blockquote>“${q.text}”</blockquote><cite>${q.who}${q.role ? `, ${q.role}` : ""}</cite>`);
  else setHTML($("quote"), html``);
}

function renderAll() { renderControls(); renderNumbers(); renderCurve(); renderJobs(); renderSolver(); }

async function post(path, body) {
  const r = await postJSON(path, body);
  if (!r.ok) logEvent({ t: nowS(), kind: "note", data: { level: "error", msg: `${path} failed: ${r.error}` } });
  return r.ok ? r.data : null;
}
function setObjective(o) { $("objective").value = o; post("/api/policy", { objective: o }); }
async function toggleDispatcher() {
  if (S.dispatcherEnabled == null) return;
  const r = await post("/api/dispatcher", { enabled: !S.dispatcherEnabled });
  if (r) { S.dispatcherEnabled = r.enabled; renderControls(); }
}
$("iso").addEventListener("change", (e) => post("/api/iso", { iso: e.target.value }));
$("objective").addEventListener("change", (e) => post("/api/policy", { objective: e.target.value }));
$("dispatcher").addEventListener("click", toggleDispatcher);

// Ages tick every second even when no message arrives, so a silent feed visibly gets old.
setInterval(() => { renderNumbers(); renderJobs(); }, 1000);
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
renderAll();
connectWS(handle, $("conn"));

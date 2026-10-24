// Grid operator's console (operator.html): the utility's side of DEMO.md 1:15 and 3:00. Free text or a
// dictated transcript -> POST /request; an OpenADR 3.1 EVENT -> POST /openadr/event; active cap events with a
// countdown and a time-to-compliance counter computed from measured watts; the operator's own approval
// requests (job_id "power_cap"); "ask why" -> POST /api/ask; and the SIMULATED neighbourhood's evening-peak replay
// (POST /api/neighbourhood), whose utility call reaches the real dispatcher as a real cap. Nothing here decides: it sends words, the
// agent reads them, the solver re-plans, and this page shows what came back.
"use strict";

const P = {
  operator: null, agent: null, agentModel: null, schedule: null, reqs: new Map(),
  power: [],                 // PowerReading {t, combined_w}, oldest first, last POWER_KEEP_S seconds
  events: new Map(),         // CapEvent id -> CapEvent: the snapshot's cap_events, then `event` WS messages
  plan: null, loadedT: null, loadErr: null,
  nb: null,                  // the snapshot's neighbourhood summary (config), null before the first snapshot
  nbLast: null,              // the newest `neighbourhood` event: SIMULATED, except ours_w
};
const POWER_KEEP_S = 3 * 3600;
const MEAN_S = 10;          // the compliance test: 10-s rolling mean of measured watts at or under the cap

const board = new ApprovalBoard($("op-approvals"), {
  filter: (q) => q.job_id === "power_cap" && (!P.operator || q.owner === P.operator),
  who: () => P.operator || "operator",
  schedule: () => P.schedule,
  empty: () => "Nothing waiting for you. If the solver can only hold a cap by breaking a deadline the owner kept, it asks you here.",
  placeholder: "e.g. approve going over the cap · or: no, hold the cap",
});

// ---------- measured power ----------
function addPower(r) {
  if (!r || r.combined_w == null || r.t == null) return;
  const last = P.power[P.power.length - 1];
  if (last && r.t <= last.t) return;
  P.power.push({ t: r.t, w: r.combined_w });
  const cut = r.t - POWER_KEEP_S;
  while (P.power.length && P.power[0].t < cut) P.power.shift();
}

// Mean of the readings in (t - MEAN_S, t]; null when there are none.
function meanAt(t) {
  let sum = 0, n = 0;
  for (let i = P.power.length - 1; i >= 0 && P.power[i].t > t - MEAN_S; i--) {
    if (P.power[i].t <= t) { sum += P.power[i].w; n++; }
  }
  return n ? sum / n : null;
}

function renderPower() {
  const last = P.power[P.power.length - 1];
  if (!last) { $("power-src").textContent = "waiting for powermetrics"; return; }
  $("power-now").textContent = fixed(last.w, 1);
  $("power-mean").textContent = fixed(meanAt(last.t), 1);
  $("power-src").textContent = `SoC power, measured by macOS powermetrics, last reading ${age(last.t)}`;
}

// ---------- cap events: countdown and time to compliance ----------
// The first reading at or after the event start whose 10-s rolling mean is at or under the cap.
function compliance(ev) {
  const start = Date.parse(ev.start) / 1000;
  const first = P.power[0];
  if (!first || first.t > start + 2) return { known: false };   // this page has no readings from the start
  for (const r of P.power) {
    if (r.t < start) continue;
    const m = meanAt(r.t);
    if (m != null && m <= ev.target_w) return { known: true, at: r.t, after: r.t - start, mean: m };
  }
  return { known: true, at: null };
}

function eventCard(ev) {
  const start = Date.parse(ev.start) / 1000, end = start + ev.duration_s, t = nowS();
  const phase = t < start ? "upcoming" : t < end ? "active" : "ended";
  const target = ev.target_w != null
    ? html`<b>${fixed(ev.target_w, 1)} W</b>${ev.target_pct != null ? html` <span class="src">(${sig(ev.target_pct)}% below the measured baseline)</span>` : ""}`
    : html`<b>${sig(ev.target_pct)}% cut</b> <span class="src">(watts not resolved yet)</span>`;
  const clock = phase === "upcoming" ? html`starts in <b>${dur(start - t)}</b>`
    : phase === "active" ? html`<b>${dur(end - t)}</b> left` : html`ended ${age(end)}`;

  let ttc;
  if (ev.target_w == null) ttc = html`<span class="src">time to compliance needs the cap in watts</span>`;
  else if (phase === "upcoming") ttc = html`<span class="src">time to compliance starts counting at ${localClock(start)}</span>`;
  else {
    const c = compliance(ev);
    const mean = meanAt(Math.min(t, end));
    if (!c.known) {
      ttc = html`<span class="src">time to compliance not measurable on this page: it opened after the event started (the run report has it)</span>`;
    } else if (c.at != null) {
      ttc = html`<div class="ttc ok"><span class="ttc-n">${fixed(c.after, 0)} s</span> to compliance</div>
        <div class="src">10-s mean ${fixed(c.mean, 1)} W at or under ${fixed(ev.target_w, 1)} W at ${localClock(c.at)}${phase === "active" ? `; now ${fixed(mean, 1)} W` : ""}</div>`;
    } else if (phase === "active") {
      ttc = html`<div class="ttc wait"><span class="ttc-n">${fixed(t - start, 0)} s</span> and not yet under the cap</div>
        <div class="src">10-s mean now ${fixed(mean, 1)} W vs cap ${fixed(ev.target_w, 1)} W</div>`;
    } else {
      ttc = html`<div class="ttc bad"><span class="ttc-n">never</span> under the cap</div>
        <div class="src">the 10-s mean of measured watts stayed above ${fixed(ev.target_w, 1)} W for the whole event</div>`;
    }
  }
  return html`<article class="ev ev-${phase}">
    <div class="ev-head"><span class="badge ${phase === "active" ? "warn" : phase === "ended" ? "" : "ok"}">${phase}</span>
      cap ${target} <span class="ev-clock">${clock}</span></div>
    <div class="src">${isoLabel(ev.start)} for ${dur(ev.duration_s)} · from ${ev.source}${ev.reason ? ` · ${ev.reason}` : ""} · ${ev.id}</div>
    ${ttc}
  </article>`;
}

function renderEvents() {
  const list = [...P.events.values()].sort((a, b) => Date.parse(b.start) - Date.parse(a.start));
  if (!list.length) {
    setHTML($("events"), html`<p class="empty">no cap in force or upcoming</p>`);
    $("events-src").textContent = "";
    return;
  }
  setHTML($("events"), html`${list.map(eventCard)}`);
  $("events-src").textContent = "events as the runtime logged them on /ws; watts measured by macOS powermetrics";
}

// ---------- the current slot (what the solver is doing now) ----------
function renderSlot() {
  const sc = P.schedule;
  if (!sc) { setHTML($("sched-now"), html`<p class="empty">no schedule yet: waiting for the solver</p>`); return; }
  const i = currentSlotIndex(sc.slots, sc.slot_minutes);
  if (i < 0) {
    setHTML($("sched-now"), html`<p class="empty">the schedule ${sc.id} does not cover this moment; waiting for the next solve</p>`);
    return;
  }
  const rows = Object.entries(sc.assignments).map(([job, row]) => {
    const a = row[i];
    return html`<li><b>${job}</b> ${a.run ? html`runs on ${a.device}${a.concurrency ? ` at concurrency ${a.concurrency}` : ""}` : "paused"}</li>`;
  });
  const cap = sc.caps_w[i];
  const running = runningPlanLine(sc, P.plan);
  setHTML($("sched-now"), html`<div class="plan-head">slot ${isoLabel(sc.slots[i])}: planned ${fixed(sc.planned_w[i], 1)} W
      ${cap != null ? html`<span class="${sc.planned_w[i] > cap + 1e-6 ? "bad-text" : ""}">vs cap ${fixed(cap, 1)} W</span>` : "(no cap)"}</div>
    ${running ? html`<div class="warn-line">${running}</div>` : ""}
    <ul class="explanations">${rows}</ul>
    ${sc.shortfalls.map((s) => html`<div class="warn-line">short (${s.kind}${s.job_id ? `, ${s.job_id}` : ""}): ${s.message}</div>`)}
    <div class="src">planned from calibrated watts, not measured · ${jobPlanLine(sc, "power_cap")} · CP-SAT ${sc.solver_status} · solved ${age(sc.solve_t)}${sc.on_stale_data ? " · on last known grid data" : ""}</div>`);
}

// ---------- what came back from /request or /openadr/event ----------
const KIND_LABEL = { cap_event: ["cap accepted", "ok"], policy: ["policy change", "ok"], clarify: ["question back", "warn"], rejected: ["rejected", "bad"] };

function intakeResult(box, r, before) {
  const it = r.intake || {};
  const [label, cls] = KIND_LABEL[it.kind] || [it.kind || "?", ""];
  const sc = r.schedule;
  setHTML(box, html`<div class="decision-line"><span class="badge ${cls}">${label}</span> ${it.readback || ""}</div>
    ${it.kind === "clarify" && it.question ? html`<div class="warn-line">${it.question}</div>` : ""}
    ${it.kind === "rejected" && it.reason ? html`<div class="bad-text">${it.reason}</div>` : ""}
    <div class="src">read by ${it.llm_used ? "the agent" : "rules (no model)"} · ${it.source === "openadr" ? "OpenADR parser" : "intake"} · ${localClock(nowS())}</div>
    ${sc ? html`<div class="ask-change"><div class="change-h">Solver re-planned</div>
        <div class="was">before: ${before ? jobPlanLine(before, "power_cap") : "previous schedule not known on this page"}</div>
        <div class="now">after: ${jobPlanLine(sc, "power_cap")} · CP-SAT ${sc.solver_status}</div>
        ${sc.shortfalls.map((s) => html`<div class="warn-line">short (${s.kind}${s.job_id ? `, ${s.job_id}` : ""}): ${s.message}</div>`)}</div>`
      : it.kind === "cap_event" || it.kind === "policy" ? html`<div class="src">no new schedule came back</div>` : ""}`);
}

async function sendRequest() {
  const text = $("req-text").value.trim();
  if (!text || $("req-send").disabled) return;
  $("req-send").disabled = true;
  $("req-result").textContent = "sending: the agent reads it, the solver re-plans…";
  const before = P.schedule;
  const r = await postJSON("/request", { text, who: P.operator || "operator" });
  $("req-send").disabled = false;
  if (!r.ok) { $("req-result").textContent = `not sent: ${routeError("/request", r)}`; return; }
  intakeResult($("req-result"), r.data, before);
  if (r.data.schedule) { P.schedule = r.data.schedule; renderSlot(); }
  $("transcript-label").hidden = true;
}

async function sendOpenADR() {
  let event;
  try { event = JSON.parse($("adr-text").value); } catch (e) {
    $("adr-result").textContent = `not sent: that is not valid JSON (${e.message})`;
    return;
  }
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    $("adr-result").textContent = "not sent: paste one EVENT object, not a list or a value";
    return;
  }
  $("adr-send").disabled = true;
  $("adr-result").textContent = "sending to the OpenADR parser…";
  const before = P.schedule;
  const r = await postJSON("/openadr/event", event);
  $("adr-send").disabled = false;
  if (!r.ok) { $("adr-result").textContent = `not sent: ${routeError("/openadr/event", r)}`; return; }
  intakeResult($("adr-result"), r.data, before);
  if (r.data.schedule) { P.schedule = r.data.schedule; renderSlot(); }
}

async function sendAsk() {
  const question = $("ask-text").value.trim();
  if (!question || $("ask-send").disabled) return;
  $("ask-send").disabled = true;
  $("ask-result").textContent = "asking…";
  const r = await postJSON("/api/ask", { question });
  $("ask-send").disabled = false;
  if (!r.ok) { $("ask-result").textContent = routeError("/api/ask", r); return; }
  const e = r.data || {};
  setHTML($("ask-result"), html`<p class="explain">${e.text || ""}</p>
    <div class="src">${e.llm_used ? "worded by the agent from these facts" : "the solver's facts (agent offline)"} · ${localClock(nowS())}</div>
    ${e.facts && e.facts.length ? html`<ul class="explanations src">${e.facts.map((f) => html`<li>${f}</li>`)}</ul>` : ""}`);
}

// ---------- the SIMULATED neighbourhood (config/neighbourhood.yaml, DECISIONS 05:45) ----------
const NB_STALE_S = 15;      // events come every second during the replay and every 10 s otherwise

function nbClock(h) {
  if (h == null || !isFinite(h)) return "—";
  const m = Math.floor((((h % 24) + 24) % 24) * 60);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function nbRunning() {
  const d = P.nbLast;
  return !!(d && d.scenario && nowS() - d.t < NB_STALE_S);
}

function renderNeighbourhood() {
  const nb = P.nb, d = P.nbLast, btn = $("nb-toggle");
  const sc = (nb && nb.scenario) || {};
  const name = sc.name || "evening peak";
  if (!nb || !nb.enabled) {
    btn.disabled = true;
    btn.textContent = `Replay the ${name} (simulated)`;
    setHTML($("nb-now"), html`<p class="empty">${nb ? "no neighbourhood configured on the server (config/neighbourhood.yaml)" : "waiting for the server"}</p>`);
    $("nb-src").textContent = "";
    return;
  }
  const running = nbRunning();
  btn.disabled = false;
  btn.textContent = running ? "Stop the replay" : `Replay the ${name} (simulated)`;
  const span = sc.hours ? `${nbClock(sc.hours[0])}–${nbClock(sc.hours[1])} of today's forecast in ${sc.seconds} s` : "";
  if (!d) {
    setHTML($("nb-now"), html`<p class="empty">no neighbourhood state yet${span ? `: the replay plays ${span}` : ""}</p>`);
    $("nb-src").textContent = "";
    return;
  }
  const over = d.loading_pct != null && d.loading_pct >= 100;
  const avoided = d.diesel_off_kwh != null && d.diesel_kwh != null ? d.diesel_off_kwh - d.diesel_kwh : null;
  setHTML($("nb-now"), html`
    <div><div class="label">Clock (simulated)</div><div class="value">${nbClock(d.sim_hour)}</div>
      <div class="src">${running ? `${name} replay: ${span}` : "wall clock: no replay running"}</div></div>
    <div><div class="label">Line loading (simulated)</div><div class="value${over ? " bad" : ""}">${fixed(d.loading_pct, 0)}<small>%</small></div>
      <div class="bar${over ? " over" : ""}"><span style="width:${Math.max(0, Math.min(100, d.loading_pct || 0)).toFixed(1)}%"></span></div>
      <div class="src">${sig(d.demand_kw)} kW of a ${sig(d.limit_kw)} kW limit</div></div>
    <div><div class="label">Diesel generator (simulated)</div><div class="value">${sig(d.diesel_kw)}<small>kW</small></div>
      <div class="src">${nb.diesel_kw != null ? `of ${sig(nb.diesel_kw)} kW backup` : "backup generator"}</div></div>
    <div><div class="label">Diesel this replay (simulated)</div><div class="value">${fixed(d.diesel_kwh, 1)}<small>kWh</small></div>
      <div class="src">vs ${fixed(d.diesel_off_kwh, 1)} kWh with Brownout off · ${fixed(avoided, 1)} kWh avoided</div></div>
    <div><div class="label">Our sites (measured)</div><div class="value">${fixed(d.ours_w, 1)}<small>W</small></div>
      <div class="src">${d.response != null ? `${sig(100 * d.response)}% of their pre-cap baseline` : "no cap response yet"}</div></div>`);
  const stale = nowS() - d.t >= NB_STALE_S;
  $("nb-src").textContent = `${stale ? "STALE: " : ""}simulated neighbourhood, updated ${age(d.t)}`
    + (d.cap_id ? " · its utility call is a real cap on the real dispatcher (see Active cap events)" : "");
}

async function toggleNeighbourhood() {
  const btn = $("nb-toggle");
  if (btn.disabled) return;
  const action = nbRunning() ? "stop" : "start";
  btn.disabled = true;
  $("nb-note").textContent = action === "start" ? "starting the replay…" : "stopping…";
  const r = await postJSON("/api/neighbourhood", { action });
  btn.disabled = false;
  if (!r.ok) { $("nb-note").textContent = `not ${action === "start" ? "started" : "stopped"}: ${routeError("/api/neighbourhood", r)}`; return; }
  $("nb-note").textContent = r.data && r.data.running ? "replay running (simulated)" : "replay stopped";
  if (!(r.data && r.data.running) && P.nbLast) P.nbLast = { ...P.nbLast, scenario: null };
  renderNeighbourhood();
}

// ---------- dictation: the browser's speech recognition, shown as a transcript to check before sending ----------
function setupDictation() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { $("mic-note").textContent = "dictation not available in this browser: type instead"; return; }
  const mic = $("mic");
  mic.hidden = false;
  let rec = null;
  mic.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.onresult = (e) => {
      $("req-text").value = [...e.results].map((x) => x[0].transcript).join(" ").trim();
      $("transcript-label").hidden = false;
    };
    rec.onerror = (e) => { $("mic-note").textContent = `dictation stopped: ${e.error}`; };
    rec.onend = () => { rec = null; mic.textContent = "Dictate"; if (!$("mic-note").textContent.startsWith("dictation stopped")) $("mic-note").textContent = ""; };
    $("mic-note").textContent = "listening…";
    mic.textContent = "Stop";
    rec.start();
  });
}

// ---------- approvals addressed to the operator ----------
async function loadPending() {
  if (!P.operator) return;
  const r = await getJSON(`/api/approvals?owner=${encodeURIComponent(P.operator)}&status=pending`);
  if (!r.ok) { P.loadErr = routeError("/api/approvals", r); return; }
  P.loadErr = null; P.loadedT = nowS();
  for (const q of r.data || []) { P.reqs.set(q.id, q); board.upsert(q); }
}

function renderBadges() {
  const a = $("agent");
  a.textContent = P.agent === "online" ? `agent online${P.agentModel ? ` · ${P.agentModel}` : ""}` : P.agent === "offline" ? "agent offline: plain forms only" : "agent ?";
  a.className = "badge " + (P.agent === "online" ? "ok" : "warn");
  const me = $("me");
  me.textContent = P.operator ? `you are ${P.operator}` : "operator ?";
  me.className = "badge" + (P.operator ? " ok" : "");
}

function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      P.operator = (d.policy && d.policy.operator) || null;
      P.agent = d.agent; P.agentModel = d.agent_model || null;
      P.schedule = d.schedule || null; P.plan = d.plan || null;
      addPower(d.power);
      for (const e of d.cap_events || []) P.events.set(e.id, e);   // caps in force or upcoming, target_w resolved
      for (const q of d.approvals || []) { P.reqs.set(q.id, q); board.upsert(q); }
      P.nb = d.neighbourhood || { enabled: false };
      if (P.nb.last) P.nbLast = P.nb.last;
      renderBadges(); renderPower(); renderSlot(); renderEvents(); renderNeighbourhood(); loadPending();
      break;
    case "plan": P.plan = d; renderSlot(); break;
    case "power": addPower(d); renderPower(); break;
    case "event":   // a CapEvent (parsed requests arrive as `intake` since Sat 03:15; the id check skips older ones)
      if (d.id && d.start && d.duration_s != null) { P.events.set(d.id, d); renderEvents(); }
      break;
    case "approval":
      if (d.decision && d.request_id) board.decided(d);
      else if (d.id) { P.reqs.set(d.id, { ...(P.reqs.get(d.id) || {}), ...d }); board.upsert(P.reqs.get(d.id)); }
      break;
    case "schedule": P.schedule = d; board.onSchedule(d); renderSlot(); break;
    case "policy": if (d.operator) { P.operator = d.operator; renderBadges(); } break;
    case "neighbourhood": if (d.simulated === true && d.t != null) { P.nbLast = d; renderNeighbourhood(); } break;
  }
}

$("req-send").addEventListener("click", sendRequest);
$("req-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendRequest(); }
});
$("adr-send").addEventListener("click", sendOpenADR);
$("ask-send").addEventListener("click", sendAsk);
$("nb-toggle").addEventListener("click", toggleNeighbourhood);
$("ask-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendAsk(); }
});
hotkeys({ e: () => $("req-text").focus(), a: () => $("ask-text").focus(), n: toggleNeighbourhood });
setupDictation();
// Countdowns, compliance counters and ages tick every second even when no message arrives.
setInterval(() => { renderPower(); renderEvents(); renderNeighbourhood(); }, 1000);
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
renderSlot();
connectWS(handle, $("conn"));

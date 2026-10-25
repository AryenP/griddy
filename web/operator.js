// Grid operator's console (operator.html): the utility's side of DEMO.md 1:15 and 3:00. Free text or a
// dictated transcript -> POST /request; an OpenADR 3.1 EVENT -> POST /openadr/event; active cap events with a
// countdown and a time-to-compliance counter computed from measured watts; the operator's own approval
// requests (job_id "power_cap"); "ask why" -> POST /api/ask; a real grid emergency replayed through the live software
// (GET /api/replay/events, POST /api/replay, Sat 19:50); and a judge's what-if in their own words (POST /api/whatif/read,
// then /api/whatif). Nothing here decides: it sends words, the
// agent reads them, the solver re-plans, and this page shows what came back.
"use strict";

const P = {
  operator: null, agent: null, agentModel: null, schedule: null, reqs: new Map(),
  power: [],                 // PowerReading {t, combined_w}, oldest first, last POWER_KEEP_S seconds
  events: new Map(),         // CapEvent id -> CapEvent: the snapshot's cap_events, then `event` WS messages
  plan: null, loadedT: null, loadErr: null,
  cat: [], evPick: null, evFetching: false,
  evLast: null,              // the newest `replay` state (EIA-930 hours, measured watts, the estimate at grid scale)
  wiLast: null, wiReading: null,   // the newest `whatif` state; a reading of the judge's words awaiting confirmation
};
const POWER_KEEP_S = 3 * 3600;
const MEAN_S = 10;          // the compliance test: 10-s rolling mean of measured watts at or under the cap

const board = new ApprovalBoard($("op-approvals"), {
  filter: (q) => q.job_id === "power_cap" && (!P.operator || q.owner === P.operator),
  who: () => P.operator || "operator",
  schedule: () => P.schedule,
  empty: () => "All clear. A new request lands here with a ping.",
  placeholder: "or type a reply: yes · no, training has a deadline tonight",
  archive: $("op-archive"),
  quick: true,
  onNew: (q, el) => {                 // a request asked in the last minute is news; older ones are history on load
    if (q.status !== "pending" || q.t == null || nowS() - q.t > 60) return;
    OpFx.ping("ask");
    el.classList.add("fresh");
    setTimeout(() => el.classList.remove("fresh"), 2600);
  },
  onResolved: () => OpFx.ping("done"),
  changed: () => renderCounts(),
});

// What waits, and what is archived: the counts, the tab title, and the archive's empty line.
function renderCounts() {
  const open = $("op-approvals").querySelectorAll(".ask:not(.closed)").length;
  const archived = $("op-archive").querySelectorAll(".ask").length;
  const wc = $("wait-count");
  if (wc.textContent !== String(open) || wc.hidden !== !open) {
    wc.textContent = String(open); wc.hidden = !open;
    if (open) OpFx.bump(wc);
  }
  $("archive-count").textContent = String(archived);
  $("archive-empty").hidden = archived > 0;
  document.title = open ? `(${open}) Griddy · operator` : "Griddy · operator";
}

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

// The cap in force at time t (watts resolved), or null.
function activeCap(t) {
  for (const ev of P.events.values()) {
    const start = Date.parse(ev.start) / 1000;
    if (ev.target_w != null && start <= t && t < start + ev.duration_s) return ev;
  }
  return null;
}

function renderPower() {
  const last = P.power[P.power.length - 1];
  if (!last) { $("power-src").textContent = "waiting for powermetrics"; return; }
  const mean = meanAt(last.t), cap = activeCap(nowS());
  OpFx.tween($("power-now"), last.w, 1);
  OpFx.tween($("power-mean"), mean, 1);
  OpFx.spark($("power-spark"), P.power, cap ? cap.target_w : null);
  const st = $("power-state");
  if (!cap) { st.className = "op-state idle"; st.textContent = "no cap in force"; }
  else if (mean != null && mean <= cap.target_w) { st.className = "op-state ok"; st.textContent = `under the ${fixed(cap.target_w, 1)} W cap`; }
  else { st.className = "op-state over"; st.textContent = `${fixed((mean ?? last.w) - cap.target_w, 1)} W over the ${fixed(cap.target_w, 1)} W cap`; }
  $("power-src").textContent = `SoC power, measured by macOS powermetrics, last reading ${age(last.t)} · line: the last 2 min`;
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

// ---------- a real grid emergency, replayed through the live software (replay/engine.py) ----------
const LIVE_S = 12;          // the replay and a what-if send a state every second
const compactN = (n) => (n >= 1e6 ? `${fixed(n / 1e6, 1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(Math.round(n)));

function evRunning() { const d = P.evLast; return !!(d && d.event && nowS() - d.t < LIVE_S); }

function renderReplay() {
  if ($("ev-picks").children.length !== P.cat.length) {        // built once, so focus survives the 1-s refresh
    setHTML($("ev-picks"), html`${P.cat.map((e) => html`<button type="button" data-ev="${e.id}">${e.title}<small> · ${e.when}</small></button>`)}`);
  }
  const running = evRunning(), pick = running ? P.evLast.event : P.evPick;
  for (const b of $("ev-picks").children) b.setAttribute("aria-pressed", String(b.dataset.ev === pick));
  const btn = $("ev-play");
  btn.disabled = !pick || P.evFetching;
  btn.textContent = running ? "Stop" : P.evFetching ? "Fetching from the EIA…" : "Replay it live";
  const ev = P.cat.find((e) => e.id === pick);
  if (!running) {
    setHTML($("ev-now"), html`<p class="empty">${ev ? `${ev.title}, ${ev.when}. ${ev.impact[0].text}.` : P.cat.length ? "pick an event to replay" : "loading the events…"}</p>`);
    $("ev-src").textContent = ev ? `${ev.data_source}; alerts and impact from the official report, page on each` : "";
    return;
  }
  const d = P.evLast, sc = d.scale, cut = d.measured_cut_pct;
  setHTML($("ev-now"), html`
    <div><div class="label">Hour (${ev ? ev.ba : ""})</div><div class="value">${isoClock(d.hour_ending)}</div><div class="src">${isoLabel(d.hour_ending)} · the last hour that has ended</div></div>
    <div><div class="label">Served / needed</div><div class="value">${fixed(d.demand_mw / 1000, 1)}<small> / ${fixed(d.forecast_mw / 1000, 1)} GW</small></div><div class="src">${ev && ev.simulated ? "simulated: the forecast × Texas's share served each hour (EIA-930)" : "EIA-930 demand and the operator's day-ahead forecast"}</div></div>
    <div><div class="label">Our sites (measured)</div><div class="value">${fixed(d.ours_w, 1)}<small> W</small></div><div class="src">${d.nothing_to_shed ? "nothing running to shed" : cut != null ? `${fixed(Math.abs(cut), 0)}% ${cut >= 0 ? "below" : "above"} the ${fixed(d.baseline_w, 1)} W baseline` : "no cut asked yet"}</div></div>
    <div><div class="label">With Griddy (estimate)</div><div class="value">${sc ? fixed(sc.freed_mw, 0) : "—"}<small>${sc ? " MW per GW" : ""}</small></div><div class="src">${sc ? `a rate: every 1 GW of data centers cutting the ${fixed(sc.share_pct, 0)}% asked${ev && ev.shed_mw && sc.freed_mw > 0 ? `; ${fixed(ev.shed_mw / sc.freed_mw, 0)} GW would cover the gap` : ""}` : "appears once our sites cut"}</div></div>`);
  const src = d.data || {};
  $("ev-src").textContent = `${src.source === "live" ? `Fetched live from api.eia.gov at ${src.fetched_at ? new Date(src.fetched_at).toTimeString().slice(0, 5) : "—"}`
    : `Evidence copy of EIA-930 (${src.why || "api.eia.gov not reached"})`} · ${fixed(100 * d.progress, 0)}% through the replay`;
}

async function toggleReplay() {
  if (evRunning()) {
    $("ev-note").textContent = "stopping…";
    const r = await postJSON("/api/replay", { action: "stop" });
    $("ev-note").textContent = r.ok ? "replay stopped" : routeError("/api/replay", r);
    P.evLast = null; renderReplay(); return;
  }
  if (!P.evPick) return;
  P.evFetching = true; renderReplay();
  const r = await postJSON("/api/replay", { action: "start", event: P.evPick });
  P.evFetching = false;
  if (!r.ok) { $("ev-note").textContent = `not started: ${routeError("/api/replay", r)}`; renderReplay(); return; }
  const src = r.data && r.data.data;
  $("ev-note").textContent = r.data.nothing_to_shed ? "running, but nothing on our sites to shed: give training a deadline on the main page"
    : src && src.source === "live" ? `fetched ${src.rows} hours live from the EIA` : "running on the evidence copy";
  renderReplay();
}

// ---------- break a part (replay/whatif.py, agent/faults.py): words -> a reading with its real size -> confirm ----------
function wiActive() { const w = P.wiLast; return !!(w && w.target && nowS() - w.t < LIVE_S); }

async function readFault() {
  const text = $("wi-text").value.trim();
  if (text.length < 3) { $("wi-text").focus(); return; }
  $("wi-go").hidden = true; P.wiReading = null;
  $("wi-read").textContent = "reading…";
  const r = await postJSON("/api/whatif/read", { text });
  if (!r.ok) { $("wi-read").textContent = r.data && r.data.detail ? String(r.data.detail) : routeError("/api/whatif/read", r); return; }
  const f = r.data, part = f.target === "hub" ? "the substation" : f.target === "city" ? "demand" : `the ${f.target.slice(6).toLowerCase()} fleet`;
  P.wiReading = f;
  $("wi-read").textContent = `${f.how}: “${f.cause}”. ${part[0].toUpperCase()}${part.slice(1)} ${f.target === "city" ? "rises" : "loses"} ${fixed(f.share_pct, 0)}%: `
    + `${f.target === "city" ? "+" : "−"}${fixed(f.size_mw / 1000, 1)} GW of its real ${fixed(f.part_mw / 1000, 1)} GW now.`;
  $("wi-go").hidden = false;
}

async function breakIt() {
  const f = P.wiReading;
  if (!f) return;
  $("wi-go").hidden = true;
  const r = await postJSON("/api/whatif", { target: f.target, share_pct: f.share_pct, cause: f.cause });
  if (!r.ok) { $("wi-read").textContent = `not broken: ${r.data && r.data.detail ? r.data.detail : routeError("/api/whatif", r)}`; return; }
  P.wiLast = r.data; P.wiReading = null; $("wi-read").textContent = ""; renderWhatIf();
}

async function clearFault() {
  const r = await postJSON("/api/whatif", { target: "clear" });
  if (r.ok) { P.wiLast = null; renderWhatIf(); } else $("wi-read").textContent = routeError("/api/whatif", r);
}

function renderWhatIf() {
  const w = wiActive() ? P.wiLast : null;
  $("wi-clear").hidden = !w;
  if (!w) { setHTML($("wi-now"), html``); $("wi-src").textContent = ""; return; }
  const sc = w.scale, cut = w.measured_cut_pct;
  setHTML($("wi-now"), html`
    <div><div class="label">What-if · ${fixed(w.remaining_s, 0)} s left</div><p>${w.label}</p></div>
    <div><div class="label">Without Griddy</div><div class="value${w.shortfall_mw > 0 ? " bad" : ""}">${fixed(w.shortfall_mw / 1000, 1)}<small> GW short</small></div><div class="src">${fixed(w.served_after / 1000, 1)} served of ${fixed(w.needed_after / 1000, 1)} GW needed</div></div>
    <div><div class="label">Our sites (measured)</div><div class="value">${fixed(w.ours_w, 1)}<small> W</small></div><div class="src">${w.nothing_to_shed ? "nothing running to shed" : cut != null ? `${fixed(Math.abs(cut), 0)}% ${cut >= 0 ? "below" : "above"} baseline, ${fixed(w.asked_cut_pct, 0)}% asked` : w.asked_cut_pct ? `${fixed(w.asked_cut_pct, 0)}% cut asked` : "no cut needed"}</div></div>
    <div><div class="label">With Griddy (estimate)</div><div class="value">${sc ? fixed(sc.freed_mw, 0) : "—"}<small>${sc ? " MW per GW" : ""}</small></div><div class="src">${sc ? `a rate: every 1 GW of data centers cutting like this Mac${w.shortfall_mw > 0 && sc.freed_mw > 0 ? `; ${fixed(w.shortfall_mw / sc.freed_mw, 0)} GW would cover the gap` : ""}` : "appears once our sites cut"}</div></div>`);
  $("wi-src").textContent = `arithmetic on ${w.source}`;
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

// The run's measured watts from before this page opened (GET /api/runs/{id}/series), so the sparkline starts full and
// a cap that began earlier still gets its time to compliance. Readings the page already has are kept as they are.
async function seedPower(runId) {
  if (!runId || P.seeded === runId) return;
  P.seeded = runId;
  const r = await getJSON(`/api/runs/${encodeURIComponent(runId)}/series`);
  if (!r.ok || !r.data || !Array.isArray(r.data.power)) return;
  const first = P.power.length ? P.power[0].t : Infinity;
  const older = r.data.power.filter(([t, w]) => t < first && w != null).map(([t, w]) => ({ t, w }));
  P.power = older.concat(P.power);
  const cut = P.power.length ? P.power[P.power.length - 1].t - POWER_KEEP_S : 0;
  while (P.power.length && P.power[0].t < cut) P.power.shift();
  renderPower(); renderEvents();
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
      P.evLast = (d.replay && d.replay.last) || null;
      P.wiLast = d.whatif || null;
      renderBadges(); renderPower(); renderSlot(); renderEvents(); renderReplay(); renderWhatIf(); loadPending();
      seedPower(d.run_id);
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
    case "replay": P.evLast = d; P.evPick = d.event; renderReplay(); break;
    case "whatif": P.wiLast = d; renderWhatIf(); break;
  }
}

$("req-send").addEventListener("click", sendRequest);
$("req-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendRequest(); }
});
$("adr-send").addEventListener("click", sendOpenADR);
$("ask-send").addEventListener("click", sendAsk);
$("ev-picks").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-ev]");
  if (!b || evRunning()) return;
  P.evPick = b.dataset.ev; $("ev-note").textContent = ""; renderReplay();
});
$("ev-play").addEventListener("click", toggleReplay);
$("wi-read-btn").addEventListener("click", readFault);
$("wi-go").addEventListener("click", breakIt);
$("wi-clear").addEventListener("click", clearFault);
$("wi-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); readFault(); }
});
$("ask-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendAsk(); }
});
hotkeys({ e: () => $("req-text").focus(), a: () => $("ask-text").focus(), b: () => $("wi-text").focus() });
setupDictation();
OpFx.bindSound($("sound"));
// An archived card opens to its full message and facts on a click, and folds again on the next.
$("op-archive").addEventListener("click", (e) => {
  const card = e.target.closest(".ask");
  if (card && !e.target.closest("button, textarea, a")) card.classList.toggle("expanded");
});
// Countdowns, compliance counters and ages tick every second even when no message arrives; the cards' own
// "asked … ago" every 15 s.
let ticks = 0;
setInterval(() => {
  renderPower(); renderEvents(); renderReplay(); renderWhatIf();
  if (++ticks % 15 === 0) board.refresh();
}, 1000);
getJSON("/api/replay/events").then((r) => { if (r.ok) { P.cat = r.data || []; renderReplay(); } });
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
renderSlot();
connectWS(handle, $("conn"));

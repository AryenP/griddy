// Griddy dashboard. One WebSocket (/ws, HANDOFF.md contract), field names from core/types.py.
// Every number on screen carries its source and its age; missing data says what is missing.
// Layout: the live load trace and its readout (web/trace.js), the 24-hour map (web/map.js) with a slot
// inspector, the jobs, why this plan, the event log, and the receipts (web/receipts.js).
"use strict";

const S = {
  grid: null, schedule: null, plan: null, power: null, jobs: {}, calibration: null, policy: null,
  isoOptions: [], iso: null, dispatcherEnabled: null, agent: null, agentModel: null, runId: null,
  jobSpecs: {}, quote: null, explanation: null, hardDeadlines: new Set(), capEvents: [], sel: null,
  fleet: [], fleetPower: null, replay: null, replayCat: [], replayLast: null, replayPick: null,
};
const FLEET_FRESH_S = 5;
const LOG_KINDS = new Set(["grid", "event", "intake", "plan", "action", "shortfall", "approval", "policy", "note", "schedule"]);
const LOG_GROUP = { plan: "plan", schedule: "plan", action: "plan", policy: "plan", note: "plan",
  event: "people", intake: "people", approval: "people", shortfall: "people", grid: "grid" };
const LOG_MAX = 200;
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
      S.jobSpecs = d.job_specs || {}; S.quote = d.quote || null; S.capEvents = d.cap_events || [];
      S.fleet = d.fleet || [];
      S.replay = d.replay || null; S.replayLast = S.replay && S.replay.last ? S.replay.last : null;
      S.scale = d.scale || null;
      S.explanation = d.explanation ? { data: d.explanation, scheduleId: d.schedule ? d.schedule.id : null, t: null } : null;
      traceSeed(d.power_history);
      renderAll();
      return;
    case "power": S.power = d; traceAdd(d.t, d.combined_w); renderNumbers(); renderLoad(); break;
    case "replay": S.replayLast = d; S.replayPick = d.event; if (S.replay) S.replay.active = d.event; renderReplay(); break;
    case "scale": S.scale = d; renderScale(); break;
    case "fleet_power": S.fleetPower = d; traceSet(d.t, d.combined_w); renderNumbers(); renderLoad(); break;
    case "grid":
      if (d.feed === "signal") { S.grid = d; S.iso = d.iso; renderNumbers(); renderCurve(); renderControls(); }
      break;
    case "schedule":
      S.schedule = d; renderCurve(); renderSolver(); renderJobs(); renderLoad();
      if (d.reason && d.reason !== "grid update") traceMark(msg.t, `re-plan: ${d.reason}`, d.shortfalls && d.shortfalls.length ? "warn" : "");
      break;
    case "plan": S.plan = d; renderSolver(); renderCurve(); renderFeedBadge(); renderLoad(); break;
    case "state": if (d.job) { S.jobs[d.job] = d; renderJobs(); renderNumbers(); } break;
    case "policy": onPolicy(d, msg.t); break;
    case "event":
      if (!d.intake && d.start) {                      // a CapEvent (intake results have their own kind)
        S.capEvents = [...S.capEvents.filter((e) => e.id !== d.id), d];     // drawn as the cap line and its edge
        renderLoad();
      }
      break;
    case "action": traceMark(msg.t, actionText(d), ""); break;
    case "approval":
      if (d.decision) traceMark(msg.t, `${d.who || "owner"}: ${d.decision.decision}`, "warn");
      break;
    case "note":
      if (d.explanation) { S.explanation = { data: d.explanation, scheduleId: d.schedule_id || null, t: msg.t }; renderSolver(); }
      if (d.trigger === "fleet") { traceMark(msg.t, d.msg.replace("re-solve: ", ""), "warn"); refreshFleet(); }
      if (d.trigger === "background" || d.trigger === "idle") traceMark(msg.t, d.trigger === "idle" ? "idle re-measured" : "outside load", "warn");
      break;
  }
  if (LOG_KINDS.has(msg.kind)) logEvent(msg);
}

function actionText(d) {
  const { job, previous, ...rest } = d;
  return `${job} ` + Object.entries(rest).map(([k, v]) => (k === "state" ? v : `${k} ${v}`)).join(", ");
}

// `policy` events come in several shapes (controller/execute.py): a full Policy dump, an ISO switch,
// a job change, a deadline kept by its owner, a dispatcher toggle.
function onPolicy(d, t) {
  if (d.objective !== undefined) S.policy = d;
  if (d.dispatcher_enabled !== undefined) {
    S.dispatcherEnabled = d.dispatcher_enabled;
    traceMark(t, d.dispatcher_enabled ? "dispatcher on" : "dispatcher off", "warn");
  }
  if (d.reason === "job change" && d.job && d.changes && "deadline" in d.changes && S.jobSpecs[d.job]) {
    S.jobSpecs[d.job].deadline = d.changes.deadline;
  }
  if (d.reason === "deadline kept by owner" && d.job) S.hardDeadlines.add(d.job);
  renderControls(); renderJobs(); renderNumbers(); renderLoad();
}

// ---------- the load panel: readout + live trace ----------
function renderLoad() {
  const bands = capBands(S.capEvents, S.policy), now = nowS();
  const st = capStatus(bands, now);
  const state = $("cap-state"), detail = $("cap-detail");
  let text, cls, sub = "";
  if (!st.last) { text = "Waiting for the meter"; cls = "idle"; sub = "no powermetrics sample yet"; }
  else if (now - st.last[0] > STALE_POWER_S) { text = `Meter silent for ${dur(now - st.last[0])}`; cls = "stale"; sub = "no powermetrics sample: watts unknown"; }
  else if (!st.band) {
    text = "No cap in force"; cls = "idle";
    const next = bands.find((b) => b.start > now);
    sub = next ? `next cap ${fixed(next.w, 1)} W at ${localClock(next.start).slice(0, 5)}` :
      S.dispatcherEnabled === false ? "dispatcher off: every job runs as it comes" : "the solver places work in the cheapest, cleanest slots";
  } else {
    const b = st.band, since = isFinite(b.start) ? `since ${localClock(b.start).slice(0, 5)}` : "standing policy cap";
    if (st.mean == null) { text = `Cap ${fixed(b.w, 1)} W in force`; cls = "idle"; sub = `${since} · waiting for 10 s of samples`; }
    else if (st.mean <= b.w) {
      text = `Within the cap, ${fixed(b.w - st.mean, 1)} W to spare`; cls = "ok";
      sub = `cap ${fixed(b.w, 1)} W ${since}` + (st.ttc != null ? ` · compliant ${dur(st.ttc)} after it began` : "");
    } else {
      text = `Over the cap by ${fixed(st.mean - b.w, 1)} W`; cls = "over";
      // A streaming reply draws most of the GPU for a few seconds (DECISIONS, Sat 10:00); chat keeps full speed
      // unless the operator says otherwise, so say so rather than "adjusting".
      const chat = S.jobs.chat, serving = chat && chat.inflight > 0 ? `chat is serving ${plural(chat.inflight, "request")} at full speed (slowing chat is the operator's call)` : "";
      const why = S.dispatcherEnabled === false ? "dispatcher off: nothing holds the cap"
        : [serving, S.plan && S.plan.needs_approval && S.plan.needs_approval.length ? "waiting for an approval" : serving ? "" : "the plan is adjusting"]
          .filter(Boolean).join(" · ");
      sub = `for ${dur(now - (st.overSince != null ? st.overSince : b.start))} · cap ${fixed(b.w, 1)} W ${since} · ${why}`;
    }
  }
  state.textContent = text;
  state.className = `d-state ${cls}`;
  detail.textContent = sub;
  // The scale-free number: how far measured power sits below its own pre-cap baseline, the same at 20 W or 50 MW.
  const ratio = $("cap-ratio"), base = st.band && isFinite(st.band.start) ? preCapBaseline(st.band.start) : null;
  if (base && st.mean != null) {
    ratio.hidden = false;
    const pct = 100 * (1 - st.mean / base);
    setHTML(ratio, html`<b>${fixed(Math.abs(pct), 0)}%</b> ${pct >= 0 ? "below" : "above"} the 60 s before the cap
      <span class="src">(${fixed(base, 1)} W then, ${fixed(st.mean, 1)} W now; measured)</span>`);
  } else {
    ratio.hidden = true;
  }
  drawLoadTrace($("load-trace"), bands, S.dispatcherEnabled === false ? null : S.schedule);
  $("load-src").textContent = "measured by macOS powermetrics (combined CPU + GPU + ANE, 1 Hz)" +
    (S.schedule && S.dispatcherEnabled !== false ? " · plan line: the current schedule's calibrated watts" : "") +
    " · within or over: the 10-s mean of measured watts, computed on this page; receipts hold the reporter's figure";
}

// ---------- real grid emergencies, replayed through the live software (replay/engine.py, config/events.yaml) ----------
// The grid's side is the operator's own recorded data (EIA-930) and the official reports' alert times, cited on screen;
// our sites' side is this Mac, live and measured. Nothing here is simulated.
async function loadReplayEvents() {
  const r = await getJSON("/api/replay/events");
  if (r.ok) { S.replayCat = r.data; if (!S.replayPick && S.replayCat.length) S.replayPick = S.replayCat[0].id; renderReplay(); }
}
const gwOf = (mw) => (mw == null ? "—" : `${fixed(mw / 1000, 1)} GW`);
function eventClock(iso) { return iso ? iso.slice(11, 16) : ""; }
function replayRunning() { const d = S.replayLast; return !!(d && d.event && nowS() - d.t < 5); }

function renderReplay() {
  const box = $("replay");
  box.hidden = !(S.replay && S.replay.enabled);
  if (box.hidden) return;
  const running = replayRunning(), d = S.replayLast;
  const ev = S.replayCat.find((e) => e.id === (running && d ? d.event : S.replayPick)) || S.replayCat[0];
  $("replay-stop").hidden = !running;
  setHTML($("replay-cards"), html`${S.replayCat.map((e) => html`<div role="listitem" class="d-replay-card${ev && e.id === ev.id ? " on" : ""}">
      <div class="d-replay-title">${e.title}</div><div class="src">${e.when} · ${e.iso}</div>
      <div class="d-replay-hit">${e.impact[0].text}</div>
      <button type="button" class="${ev && e.id === ev.id ? "primary" : ""}" data-replay="${e.id}" ${running ? "disabled" : ""}>Replay it live</button></div>`)}`);
  if (!ev) { $("replay-state").textContent = "Loading the events…"; return; }
  const sentence = [];
  if (running) {
    sentence.push(`Replaying ${ev.title}, ${ev.when}, at ${eventClock(d.sim_time)} local: the grid served ${gwOf(d.demand_mw)} against a forecast of ${gwOf(d.forecast_mw)}${d.gap_mw > 1000 ? `, ${gwOf(d.gap_mw)} short` : ""}. The chart shows only what the software has seen: no later hour.`);
    if (d.nothing_to_shed) sentence.push("Our sites had nothing running to shed, so no cut was sent: give training work and replay again.");
    else if (d.measured_cut_pct != null) sentence.push(`This Mac: ${fixed(d.measured_cut_pct, 0)}% below its baseline, measured.`);
  } else {
    sentence.push(`Pick a real emergency. The grid's data is the operator's own (EIA-930), every alert comes at the time the official report gives, and the response is this Mac, live: ${S.replay.seconds} s of replay.`);
  }
  $("replay-state").textContent = sentence.join(" ");
  // the chart: real demand served (solid) and the operator's day-ahead forecast (dashed) over the window. While it
  // replays, only what the software has seen (Krish K16 #1: the whole curve "reads as it's just replaying"): demand to
  // the last hour that has ended, forecasts to the end of the current day (published the day before). Before play,
  // the full record of what happened.
  const until = running && d ? Date.parse(d.hour_ending || d.sim_time) / 1000 : Infinity;
  const dayEnd = running && d ? Date.parse(`${d.sim_time.slice(0, 10)}T23:59:59${d.sim_time.slice(-6)}`) / 1000 + 1 : Infinity;
  const pts = ev.series.map(([t, dem, fc]) => ({ t: Date.parse(t) / 1000, dem, fc }))
    .map((p) => ({ t: p.t, dem: p.t <= until ? p.dem : null, fc: p.t <= dayEnd ? p.fc : null }));
  const t0 = Date.parse(ev.window[0]) / 1000, t1 = Date.parse(ev.window[1]) / 1000;
  const vals = pts.flatMap((p) => [p.dem, p.fc]).filter((v) => v != null);
  const lo = Math.min(...vals) * 0.95, hi = Math.max(...vals, ev.record_mw || 0) * 1.03;
  const X = (t) => (((t - t0) / (t1 - t0)) * 600).toFixed(1), Y = (v) => (170 - ((v - lo) / (hi - lo)) * 160).toFixed(1);
  const line = (k) => pts.filter((p) => p[k] != null).map((p, i) => `${i ? "L" : "M"}${X(p.t)} ${Y(p[k])}`).join(" ");
  const gap = pts.filter((p) => p.dem != null && p.fc != null);
  const gapPath = gap.length ? `M${gap.map((p) => `${X(p.t)} ${Y(p.fc)}`).join(" L")} L${gap.slice().reverse().map((p) => `${X(p.t)} ${Y(p.dem)}`).join(" L")} Z` : "";
  const marks = ev.alerts.filter((a) => a.at && !a.before_window);
  const fired = new Set(running && d ? d.fired : []);
  const head = running && d ? X(Date.parse(d.sim_time) / 1000) : null;
  setHTML($("replay-chart"), html`<path class="r-gap" d="${gapPath}"/>
    ${ev.record_mw ? html`<line class="r-record" x1="0" x2="600" y1="${Y(ev.record_mw)}" y2="${Y(ev.record_mw)}"/><text class="r-label" x="4" y="${Number(Y(ev.record_mw)) - 3}">record before the event ${gwOf(ev.record_mw)}</text>` : ""}
    <path class="r-fc" d="${line("fc")}"/><path class="r-dem" d="${line("dem")}"/>
    ${marks.map((a) => html`<line class="r-alert ${a.kind}${fired.has(a.label) ? " fired" : ""}" x1="${X(Date.parse(a.at) / 1000)}" x2="${X(Date.parse(a.at) / 1000)}" y1="4" y2="172"/>`)}
    ${head != null ? html`<line class="r-head" x1="${head}" x2="${head}" y1="0" y2="180"/>` : ""}
    <text class="r-label" x="4" y="178">${eventClock(ev.window[0])}</text><text class="r-label" x="560" y="178">${eventClock(ev.window[1])}</text>`);
  $("replay-chart").setAttribute("aria-label", `${ev.title}: demand served and the day-ahead forecast, ${gwOf(lo)} to ${gwOf(hi)}`);
  setHTML($("replay-alerts"), html`${ev.alerts.map((a) => html`<li class="${a.kind}${fired.has(a.label) ? " fired" : ""}">
      <b>${a.before_window ? (a.day ? `days before (${a.day})` : "before the window") : eventClock(a.at)}</b> ${a.label}${a.cut_pct ? html` <span class="d-meas">our sites: −${a.cut_pct}%</span>` : ""}
      <div class="src">${a.source}</div></li>`)}`);
  const sc = running && d ? d.scale : null;
  setHTML($("replay-impact"), html`<h3>What happened</h3>
    <ul>${ev.impact.map((i) => html`<li>${i.text} <span class="src">(${i.source})</span></li>`)}</ul>
    <h3>This Mac, live <span class="d-meas">measured</span></h3>
    <p>${running && d && d.baseline_w ? html`Baseline ${fixed(d.baseline_w, 1)} W before the replay; now ${d.ours_w == null ? "—" : `${fixed(d.ours_w, 1)} W`}${d.measured_cut_pct != null ? html`, <b>${fixed(d.measured_cut_pct, 0)}% below</b>` : ""}.` : "Starts when you press Replay."}</p>
    <h3>At the operator's scale <span class="d-sim">estimate</span></h3>
    <p>${sc ? html`The ${fixed(sc.share_pct, 0)}% cut the grid asked, which this Mac delivered (measured), on ${gwOf(sc.flexible_mw)} of flexible load frees about <b>${fixed(sc.freed_mw, 0)} MW</b>${sc.share_of_shed_pct != null ? html`, <b>${fixed(sc.share_of_shed_pct, 1)}%</b> of the ${fixed(ev.shed_mw, 0)} MW in this event` : ""}${sc.people != null ? html`: about <b>${Math.round(sc.people).toLocaleString()}</b> ${sc.people_unit} at this event's own ratio` : ""}.` : "Appears once our sites have cut."}</p>
    <div class="src">${ev.flexible_source}. Arithmetic on the event's own published numbers and our measured cut; a laptop is not a data center.</div>`);
  setHTML($("replay-src"), html`Data: ${ev.data_source}. Alerts and impact: <a href="${ev.report_url}" target="_blank" rel="noopener">the official report</a> (pages cited per line).`);
}

// At grid scale, live: an ESTIMATE from public data (grid/scale.py), never shown as measured. ERCOT's demand is live;
// the large loads and the queue are cited with their dates; the cut is this Mac's, measured under the same call.
function renderScale() {
  const box = $("live-scale"), x = S.scale;
  box.hidden = !x;
  if (!x) return;
  const gw = (mw) => `${fixed(mw / 1000, 1)} GW`;
  setHTML(box, html`<h3>ERCOT right now <span class="d-sim">estimate from public data</span></h3>
    <p>ERCOT's large loads draw up to <b>${gw(x.large_loads_running_mw)}</b> (the sum of each one's own monthly peak, not what
      runs at once). If they cut the ${fixed(x.our_cut_pct, 0)}% this Mac cut under the same call, that frees up to about <b>${fixed(x.freed_mw, 0)} MW</b>${x.share_of_demand_pct != null ? html`, <b>${fixed(x.share_of_demand_pct, 1)}%</b> of ERCOT's demand right now (${gw(x.demand_mw)}, live)` : ""}.
      Another ${fixed(x.queue_gw, 0)} GW of large loads, mostly data centers, are asking to connect.</p>
    <div class="src">Running and approved (${gw(x.large_loads_approved_mw)}) large loads: <a href="${x.large_loads_url}" target="_blank" rel="noopener">${x.large_loads_source}</a>.
      Queue: <a href="${x.queue_url}" target="_blank" rel="noopener">${x.queue_source}</a>. Demand: ERCOT real-time system conditions${x.demand_t ? `, ${localClock(Date.parse(x.demand_t) / 1000)}` : ""}.
      The cut: ${x.our_cut_source}. A laptop's response is not a data center's; this is arithmetic on public numbers, not a measurement.</div>`);
}

// ---------- the laptops (fleet/hub.py): each one's status, its own battery's watts, its job ----------
function fleetLive() { const f = S.fleetPower; return f && nowS() - f.t <= FLEET_FRESH_S ? f : null; }
function renderFleet() {
  if (!S.fleet.length) { setHTML($("fleet"), html``); return; }
  const live = fleetLive();
  setHTML($("fleet"), html`${S.fleet.map((s) => {
    const w = live && live.sites[s.id] != null ? live.sites[s.id] : null;
    const state = w == null ? s.status : s.run ? "job running" : "job paused";
    // supervisor issue 14: a laptop's battery reading changes about once a minute; say how old it is
    const read = s.reading_changed ? `, reading ${age(s.reading_changed)}` : "";
    return html`<li class="${w == null ? "off" : ""}"><b>${s.name}</b> <span class="d-num-sm">${w == null ? "—" : `${fixed(w, 1)} W`}</span>
      <span class="src">${state}${w != null ? `, measured by its battery${read}` : ""}</span></li>`;
  })}`);
}
async function refreshFleet() {
  const r = await getJSON("/api/state");
  if (r.ok) { S.fleet = r.data.fleet || []; renderFleet(); }
}

// ---------- the live numbers ----------
function renderNumbers() {
  const p = S.power, g = S.grid, live = fleetLive();
  if (p) {
    const stale = nowS() - p.t > STALE_POWER_S;
    const total = live ? live.combined_w : p.combined_w;
    setHTML($("watts"), html`${total.toFixed(1)}<small>${live ? `W measured, this Mac and ${plural(Object.keys(live.sites).length, "laptop")}` : "W measured"}</small>`);
    $("watts").classList.toggle("stale", stale);
    const parts = [["CPU", p.cpu_w], ["GPU", p.gpu_w], ["ANE", p.ane_w]]
      .filter(([, v]) => v != null).map(([k, v]) => `${k} ${v.toFixed(1)}`).join(", ");
    $("watts-src").textContent = (stale ? `STALE: no powermetrics sample for ${age(p.t).replace(" ago", "")}. ` : "") +
      (live ? `this Mac ${fixed(live.mac_w, 1)} W from macOS powermetrics (${parts}); each laptop from its own battery, whose reading changes about once a minute; ` : `SoC power from macOS powermetrics: ${parts}, `) + age(p.t);
  }
  renderFleet();
  if (p && g) {
    // A laptop costs fractions of a cent per hour; show cents so the number stays readable.
    const w = live ? live.combined_w : p.combined_w;
    const usdH = w / 1e6 * g.price_now;
    setHTML($("cost"), Math.abs(usdH) < 0.01 ? html`${sig(usdH * 100)}<small>¢/h</small>` : html`$${sig(usdH)}<small>/h</small>`);
    const at = g.price_interval_start ? ` for ${isoClock(g.price_interval_start)}` : "";
    $("cost-src").textContent = `measured W × ${g.iso} ${g.location} real-time $${sig(g.price_now, 4)}/MWh${at}, feed ${age(feedT())}` + (g.stale ? ", STALE" : "");
    if (g.carbon_now != null) {
      setHTML($("carbon"), html`${sig(w / 1000 * g.carbon_now)}<small>gCO2/h</small>`);
      $("carbon-src").textContent = `measured W × ${g.iso} live fuel mix ${sig(g.carbon_now)} gCO2/kWh, feed ${age(feedT())}` + (g.stale ? ", STALE" : "");
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
  $("ttft-label").textContent = "Chat time to first token, p95 over 60 s" + (sla != null ? `, SLA ${sla} s` : "");
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
  $("total-p95").textContent = c.p95_60s != null ? `whole reply ${c.p95_60s.toFixed(1)} s, which depends on its length` : "no replies in the last 60 s";
  $("ttft-src").textContent = (stale ? "STALE. " : "") + (c.n_60s ? `chat proxy, measured over ${plural(c.n_60s, "reply", "replies")} in 60 s` : "chat proxy: no chat requests in the last 60 s") +
    (sla != null ? ", SLA from policy" : ", no TTFT SLA in policy") + `, ${age(c.t)}`;
}

// The feed's age at the moment the server stamped it, plus time since then.
function feedT() { return S.grid ? S.grid.t - (S.grid.feed_age_s || 0) : null; }
function renderFeedBadge() {
  const b = $("feed-age"), g = S.grid;
  if (!g) { b.textContent = "no grid feed yet"; b.className = "badge warn"; return; }
  const stale = g.stale || (S.plan && S.plan.on_last_known_data);
  b.textContent = `${g.iso} feed ${age(feedT())}` + (stale ? ": STALE, plan on last known data" : "");
  b.className = "badge " + (stale ? "bad" : "ok");
}

// ---------- the 24-hour map and its inspector ----------
function renderCurve() {
  const g = S.grid, sc = S.schedule;
  if (sc && S.sel != null && S.sel >= sc.slots.length) S.sel = null;
  renderMap($("map"), sc, g, S.sel);
  const src = [];
  if (g) {
    src.push(`price: ${g.iso} ${g.location}, ${g.price_curve_source || "source not stated"}`);
    src.push(g.carbon_curve_is_proxy ? "carbon: live mix held flat (proxy), so only price varies across slots" : "carbon curve: from the feed");
    if (g.source_urls && g.source_urls.length) src.push(g.source_urls.join(", "));
  } else src.push("no grid feed yet");
  if (sc) src.push(`schedule ${sc.id}, solved ${age(sc.solve_t)}; plan watts are calibrated, not measured`);
  else src.push("no schedule yet: waiting for the solver");
  if (g && g.alerts && g.alerts.length) src.push(`ALERTS: ${g.alerts.join("; ")}`);
  $("curve-src").textContent = src.join(" · ");
  renderInspector();
}

function renderInspector() {
  const sc = S.schedule, g = S.grid, box = $("inspect");
  if (!sc) { setHTML(box, html`<p class="empty">no schedule yet: the inspector follows the current slot once one arrives</p>`); return; }
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  const i = S.sel != null ? S.sel : cur;
  if (i < 0) { setHTML(box, html`<p class="empty">now is outside this schedule's horizon: a re-solve is due</p>`); return; }
  const price = g ? mapSeries(sc.slots, g.price_curve)[i] : null;
  const carbon = g ? mapSeries(sc.slots, g.carbon_curve)[i] : null;
  const cap = sc.caps_w[i], w = sc.planned_w[i], bg = sc.background_w || 0;
  const jobsHere = Object.entries(sc.assignments).map(([job, row]) => {
    const a = row[i];
    const what = a.run ? (job === "chat" ? `serves at concurrency ${a.concurrency}` : `runs on ${a.device}`) : "waits";
    return html`<li style="--c:${MAP_JOB_COLOR[job] || "var(--text)"}"><b>${job}</b> ${what}</li>`;
  });
  // One solver fact per job, the one that explains this slot: why it runs, or why it waits (paused under a
  // cap when this slot is capped), plus the cap's own fact when there is one.
  const facts = Object.entries(sc.assignments).map(([job, row]) => {
    const own = jobFacts(sc, job);
    const want = row[i].run ? / runs | serves | in every slot/ : cap != null ? /paused|does not fit/ : /skipped|deadline|horizon/;
    return own.find((e) => want.test(e)) || null;
  }).filter(Boolean);
  const capFacts = cap != null ? sc.explanations.filter((e) => /^power cap|^running plan|^measured load/.test(e)).slice(0, 2) : [];
  const tag = i === cur ? html`<span class="badge ok">now</span>` : html`<span class="badge">pinned</span>`;
  setHTML(box, html`<div class="d-insp-head"><b>${isoLabel(sc.slots[i])} to ${slotEndLabel(sc, i).split(" ").pop()}</b> ${tag}</div>
    <dl class="d-insp">
      <div><dt>Price</dt><dd>${price != null ? `$${sig(price, 4)}/MWh` : "no price for this slot"}</dd></div>
      <div><dt>Carbon</dt><dd>${carbon != null ? `${sig(carbon)} gCO2/kWh${g && g.carbon_curve_is_proxy ? ", live mix held flat" : ""}` : "unknown"}</dd></div>
      <div><dt>Cap</dt><dd class="${cap != null ? "d-cap" : ""}">${cap != null ? `${fixed(cap, 1)} W` : "none"}</dd></div>
      <div><dt>Plan</dt><dd>${w != null ? `${fixed(w, 1)} W calibrated` + (bg ? `, of which ${fixed(bg, 1)} W measured outside the plan` : "") : "—"}${cap != null && w > cap + 1e-6 ? html` <span class="badge bad">over the cap</span>` : ""}</dd></div>
    </dl>
    <ul class="d-insp-jobs">${jobsHere}</ul>
    ${facts.length || capFacts.length ? html`<h3 class="d-insp-h">The solver's reasons</h3><ul class="d-insp-facts">${[...facts, ...capFacts].map((f) => html`<li>${f}</li>`)}</ul>` : ""}
    <div class="btn-row d-insp-nav">
      <button type="button" data-act="prev"${i <= 0 ? " disabled" : ""}>Earlier slot</button>
      <button type="button" data-act="now"${S.sel == null ? " disabled" : ""}>Back to now</button>
      <button type="button" data-act="next"${i >= sc.slots.length - 1 ? " disabled" : ""}>Later slot</button>
    </div>`);
}

function pinSlot(i) {
  const sc = S.schedule;
  if (!sc) return;
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  S.sel = i == null || i === cur ? null : Math.max(0, Math.min(sc.slots.length - 1, i));
  renderCurve();
}
function moveSlot(step) {
  const sc = S.schedule;
  if (!sc) return;
  const from = S.sel != null ? S.sel : Math.max(0, currentSlotIndex(sc.slots, sc.slot_minutes));
  pinSlot(from + step);
}

// ---------- the jobs ----------
function renderJobs() {
  const ids = [...new Set([...Object.keys(S.jobSpecs), ...Object.keys(S.jobs), ...(S.schedule ? Object.keys(S.schedule.assignments) : [])])];
  if (!ids.length) { setHTML($("jobs"), html`<p class="empty">no job status yet: waiting for the workloads</p>`); return; }
  setHTML($("jobs"), html`${ids.map(jobRow)}`);
}

function kv(k, v) { return html`<div class="kv"><b>${k}</b> ${v}</div>`; }
function jobRow(id) {
  const st = S.jobs[id] || {}, spec = S.jobSpecs[id];
  const facts = [];
  if (spec) {
    const dl = spec.deadline ? `${isoLabel(spec.deadline)}` + (S.hardDeadlines.has(id) ? " (kept by owner: hard)" : "") : "none";
    facts.push(kv("owner", spec.owner));
    facts.push(kv("deadline", dl));
  }
  facts.push(kv("device", st.device || "—"));
  if (id === "chat") {
    if (st.concurrency != null) facts.push(kv("concurrency", `${st.concurrency}` + (st.inflight != null ? ` (${st.inflight} in flight)` : "")));
    const planned = S.schedule ? (S.schedule.chat_busy_streams != null ? `${sig(S.schedule.chat_busy_streams)} busy streams` : "full concurrency") : "no schedule yet";
    facts.push(kv("traffic", `${st.busy_60s != null ? sig(st.busy_60s) : "—"} busy, measured over 60 s; the plan assumed ${planned}`));
    if (st.max_tokens != null) facts.push(kv("max tokens", `${st.max_tokens}` + (st.model ? `, ${st.model}` : "")));
  } else if (st.concurrency != null) {
    facts.push(kv("concurrency", st.concurrency));
  }
  let progress = "";
  if (st.step != null) {
    facts.push(kv("step", `${st.step}` + (spec && spec.target_steps ? ` of ${spec.target_steps}` : "") + (st.loss != null ? `, loss ${sig(st.loss)}` : "")));
    if (spec && spec.target_steps) progress = html`<div class="bar"><span style="width:${Math.min(100, st.step / spec.target_steps * 100).toFixed(1)}%"></span></div>`;
  }
  if (st.items_done != null) {
    const f = st.fraction != null ? st.fraction : st.total ? st.items_done / st.total : null;
    facts.push(kv("items", `${st.items_done}` + (st.total != null ? ` of ${st.total}` : "")));
    if (f != null) progress = html`<div class="bar"><span style="width:${(f * 100).toFixed(1)}%"></span></div>`;
  }
  if (st.rate != null) facts.push(kv("rate", `${sig(st.rate)} ${id === "train" ? "steps/s" : id === "batch" ? "items/s" : "/s"}, measured by the workload`));
  const cal = S.calibration && S.calibration.jobs[id] && st.device ? S.calibration.jobs[id][st.device] : null;
  if (cal) facts.push(kv("calibrated", `+${sig(cal.delta_w)} W on ${st.device}, powermetrics ${age(S.calibration.measured_at)}`));
  const state = st.state || "no status";
  const stale = st.t != null && nowS() - st.t > STALE_STATUS_S;
  return html`<div class="d-job" style="--c:${MAP_JOB_COLOR[id] || "var(--text)"}">
    <div class="d-job-id"><h3>${id}</h3><span class="badge state-${state}">${state}</span></div>
    <div class="d-job-facts">${facts}${progress}</div>
    <div class="d-job-plan">${nextRun(id)}</div>
    <div class="src d-job-src">${st.t == null ? "no status from the workload yet" : (stale ? "STALE: " : "") + `status ${age(st.t)}`}${spec ? "; owner and deadline from config/jobs.yaml and approvals" : ""}</div></div>`;
}

function nextRun(id) {
  const sc = S.schedule;
  if (!sc || !sc.assignments[id]) return "not in the current schedule";
  const row = sc.assignments[id];
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  const from = Math.max(cur, 0);
  const n = row.filter((x) => x.run).length;
  const miss = sc.deadline_misses.find((m) => m.job_id === id);
  const tail = miss ? `. Misses its deadline by ${miss.slip_min} min` : "";
  if (cur >= 0 && row[cur].run) return `Runs this slot on ${row[cur].device}; ${n} of ${row.length} slots planned${tail}`;
  const i = row.findIndex((x, k) => k >= from && x.run);
  return (i < 0 ? "No run planned in the remaining horizon" : `Next run ${isoLabel(sc.slots[i])} on ${row[i].device}; ${n} of ${row.length} slots planned`) + tail;
}

// ---------- why this plan, and the event log ----------
function renderSolver() {
  const p = S.plan, sc = S.schedule, ex = S.explanation;
  if (ex) {
    const e = ex.data, mine = !sc || !ex.scheduleId || ex.scheduleId === sc.id;
    const who = e.llm_used ? `agent${S.agentModel ? `, ${S.agentModel}` : ""}` : "facts only";
    setHTML($("explain"), html`<span class="badge ${e.llm_used ? "ok" : "warn"}">${who}</span> <span class="explain-text">${e.text}</span>`);
    $("explain-src").textContent = (e.llm_used ? "written by the agent from the solver's facts below" : "the agent did not write this: the solver's facts, joined") +
      (ex.scheduleId ? `, for schedule ${ex.scheduleId}` : "") + (mine ? "" : ". OLDER than the current schedule: a new explanation is pending") + (ex.t ? `, ${age(ex.t)}` : "");
  } else {
    setHTML($("explain"), html`<span class="empty">no explanation yet: it arrives with the next schedule</span>`);
    $("explain-src").textContent = "";
  }
  if (p) {
    const acts = (p.actions || []).map((a) => html`<li><b>${a.job}</b> ${a.state}${a.device ? ` on ${a.device}` : ""}${a.concurrency != null ? `, concurrency ${a.concurrency}` : ""}</li>`);
    const head = [`${p.mode === "dispatcher" ? "Dispatcher plan" : p.mode === "pause_all" ? "Pause everything (dispatcher off)" : "Run everything (dispatcher off)"} for the slot from ${p.slot_start ? isoLabel(p.slot_start) : "—"}`];
    if (p.planned_w != null) head.push(`planned ${sig(p.planned_w)} W, calibrated`);
    if (p.cap_w != null) head.push(`cap ${sig(p.cap_w)} W`);
    const running = runningPlanLine(sc, p);
    setHTML($("plan"), html`<div class="plan-head">${head.join(", ")}</div><ul>${acts}</ul>
      ${running ? html`<div class="warn-line">${running}</div>` : ""}
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
      `. Planned 24 h: $${sig(sc.cost_usd)}, ${sig(sc.co2_g)} gCO2 (calibrated W × forecast curves), solved ${age(sc.solve_t)}` + (sc.on_stale_data ? ", on stale data" : "");
  } else {
    setHTML($("explanations"), html`<li class="empty">no schedule yet: waiting for the solver</li>`);
    $("solve-src").textContent = "";
  }
}

function summary(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "grid":
      if (d.feed === "signal") return `${d.iso} $${sig(d.price_now, 4)}/MWh` + (d.carbon_now != null ? `, ${sig(d.carbon_now)} gCO2/kWh` : "") + (d.alerts && d.alerts.length ? `. ALERT ${d.alerts.join("; ")}` : "") + (d.stale ? ", STALE" : "");
      return `${d.iso || ""} ${d.feed || "feed"} update`;
    case "schedule": return `new schedule ${d.id}${d.reason ? ` (${d.reason})` : ""}: ${d.solver_status}` + (d.shortfalls && d.shortfalls.length ? `, ${plural(d.shortfalls.length, "shortfall")}` : "");
    case "plan": return `${d.mode || "plan"} for ${d.slot_start ? isoLabel(d.slot_start) : "?"}: ` + (d.actions || []).map((a) => `${a.job} ${a.state}`).join(", ");
    case "action": {
      const { job, previous, ...rest } = d;
      return `${job}: ` + Object.entries(rest).map(([k, v]) => `${k} ${previous && previous[k] != null ? `${previous[k]} to ` : ""}${v}`).join(", ");
    }
    case "shortfall": return `${d.shortfall_kind || "?"}${d.job_id ? ` (${d.job_id})` : ""}: ${d.message || ""}`;
    case "approval":
      if (d.decision) return `${d.who || "?"} replied to ${d.request_id}: ${d.decision.decision}` + (d.decision.reason ? ` (“${d.decision.reason}”)` : "");
      return `${d.id} ${d.job_id} to ${d.owner}: ${d.status}` + (d.why ? ` (${d.why})` : d.status === "pending" ? `, “${d.message}”` : "");
    case "policy":
      if (d.reason === "job change") return `${d.job}: ${Object.entries(d.changes || {}).map(([k, v]) => `${k} now ${v == null ? "none" : k === "deadline" ? isoLabel(v) : v}`).join(", ")}`;
      if (d.reason === "deadline kept by owner") return `${d.job}: deadline kept by owner` + (d.owner_reason ? ` (“${d.owner_reason}”)` : "");
      if (d.reason === "dispatcher toggle") return `dispatcher ${d.dispatcher_enabled ? "on" : "off"}`;
      if (d.reason === "iso change") return `grid now ${d.iso} ${d.location || ""}`;
      return `policy: objective ${d.objective}` + (d.power_cap_w != null ? `, cap ${d.power_cap_w} W` : "");
    case "intake":
      return `${d.who || "?"} asked, intake ${d.intake.kind}: ${d.intake.readback || d.intake.question || d.intake.reason || ""}`;
    case "event":   // timelines before Sat 03:15 logged parsed requests as `event` too
      if (d.intake) return `${d.who || "?"} asked, intake ${d.intake.kind}: ${d.intake.readback || d.intake.question || d.intake.reason || ""}`;
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
  li.dataset.group = LOG_GROUP[msg.kind] || "plan";
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
  const obj = S.policy ? S.policy.objective : null;
  $("objective").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.objective === obj)));
  const b = $("dispatcher");
  if (S.dispatcherEnabled != null) {
    b.setAttribute("aria-checked", String(S.dispatcherEnabled));
    $("dispatcher-label").textContent = S.dispatcherEnabled ? "Dispatcher on" : "Dispatcher off: running everything";
    b.classList.toggle("off", !S.dispatcherEnabled);
  }
  const ag = $("agent");
  ag.textContent = S.agent === "online" ? `agent online${S.agentModel ? `, ${S.agentModel}` : ""}` : S.agent === "offline" ? "agent offline: solver and controller still run" : "agent ?";
  ag.className = "badge " + (S.agent === "online" ? "ok" : "warn");
  const q = S.quote;
  if (q && q.text) setHTML($("quote"), html`<blockquote>“${q.text}”</blockquote><cite>${q.who}${q.role ? `, ${q.role}` : ""}</cite>`);
  else setHTML($("quote"), html``);
}

function renderAll() { renderControls(); renderNumbers(); renderLoad(); renderReplay(); renderScale(); renderCurve(); renderJobs(); renderSolver(); }

async function post(path, body) {
  const r = await postJSON(path, body);
  if (!r.ok) logEvent({ t: nowS(), kind: "note", data: { level: "error", msg: `${path} failed: ${r.error}` } });
  return r.ok ? r.data : null;
}
function setObjective(o) {
  $("objective").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.objective === o)));
  post("/api/policy", { objective: o });
}
async function toggleDispatcher() {
  if (S.dispatcherEnabled == null) return;
  const r = await post("/api/dispatcher", { enabled: !S.dispatcherEnabled });
  if (r) { S.dispatcherEnabled = r.enabled; renderControls(); renderLoad(); }
}
function pressOne(group, btn) {
  group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
}

$("iso").addEventListener("change", (e) => post("/api/iso", { iso: e.target.value }));
$("objective").addEventListener("click", (e) => { const b = e.target.closest("button[data-objective]"); if (b) setObjective(b.dataset.objective); });
$("dispatcher").addEventListener("click", toggleDispatcher);
$("replay-cards").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-replay]");
  if (!b) return;
  S.replayPick = b.dataset.replay;
  renderReplay();
  await post("/api/replay", { action: "start", event: b.dataset.replay });
});
$("replay-stop").addEventListener("click", () => post("/api/replay", { action: "stop" }));
$("trace-window").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-window]");
  if (!b) return;
  TRACE.windowS = Number(b.dataset.window);
  pressOne($("trace-window"), b);
  renderLoad();
});
$("log-filter").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-filter]");
  if (!b) return;
  $("log").dataset.filter = b.dataset.filter;
  pressOne($("log-filter"), b);
});
$("map").addEventListener("click", (e) => { const c = e.target.closest("[data-slot]"); if (c) pinSlot(Number(c.dataset.slot)); });
$("map").addEventListener("keydown", (e) => {
  const step = { ArrowLeft: -1, ArrowRight: 1, PageUp: -4, PageDown: 4 }[e.key];
  if (step) { e.preventDefault(); moveSlot(step); } else if (e.key === "Escape") { e.preventDefault(); pinSlot(null); }
});
$("inspect").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  if (b.dataset.act === "now") pinSlot(null); else moveSlot(b.dataset.act === "next" ? 1 : -1);
});
bindLoadTrace($("load-trace"), renderLoad);

// Ages tick every second even when no message arrives, so a silent feed visibly gets old.
setInterval(() => { renderNumbers(); renderJobs(); renderLoad(); if (S.replayLast && nowS() - S.replayLast.t < 8) renderReplay(); }, 1000);
// Laptops join and leave: re-read their status every 5 s while any is configured.
setInterval(() => { if (S.fleet.length) refreshFleet(); }, 5000);
// Driver hotkeys for the table demo (shown in the header): D dispatcher, 1/2/3 objective, R receipts.
hotkeys({ d: toggleDispatcher, 1: () => setObjective("cost"), 2: () => setObjective("carbon"),
  3: () => setObjective("balanced"), r: () => $("receipts").scrollIntoView({ behavior: "smooth", block: "start" }) });
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
renderAll();
connectWS(handle, $("conn"));
loadReplayEvents();

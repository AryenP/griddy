// The judge's page (index.html): the 3D grid world and four choices: the live grid now, or a real emergency replayed
// through the live software (replay/engine.py, its hours fetched live from api.eia.gov). Numbers only, each with its
// source in small type; the detail and every graph live on info.html. A click on a plant, the substation or the city
// breaks it (replay/whatif.py: the fault is invented, its size is real). Contract: snapshot and WebSocket events from
// HANDOFF.md, /api/replay*, /api/whatif.
"use strict";

const D = { grid: null, power: null, replay: null, last: null, whatif: null, cat: [], pick: "live", scale: null, fetching: false,
  capEvents: [], pts: [],
  cities: [], city: null, maps: {}, mapTried: new Set(), places: {},
  shown: new Set(), peaks: {}, specs: {}, jobs: {} };

const gw = (mw) => (mw == null ? "—" : `${fixed(mw / 1000, 1)} GW`);
const compact = (n) => (n >= 1e6 ? `${fixed(n / 1e6, 1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(Math.round(n)));
const running = () => !!(D.last && D.last.event && nowS() - D.last.t < 12);     // ticks 1/s; 12 s rides out a slow link
const faulted = () => !!(D.whatif && D.whatif.target && nowS() - D.whatif.t < 12);

function liveNeeded(sig) {
  // the ISO's own load forecast at this hour (GridSignal.load_forecast: [[time, MW]])
  const pts = (sig && sig.load_forecast) || [];
  const now = Date.now();
  let best = null;
  for (const [t, mw] of pts) { const d = Math.abs(Date.parse(t) - now); if (!best || d < best[0]) best = [d, mw]; }
  return best && best[0] < 2 * 3600e3 ? best[1] : null;
}

// The logo loader (index.html #w-load) plays once, about 2 s, then fades once the page has its first data. If this
// script never runs, world.css fades it at 6 s anyway.
const LOAD_T0 = performance.now(), STILL = matchMedia("(prefers-reduced-motion: reduce)").matches;
let loaderGone = false;
function hideLoader() {
  if (loaderGone) return;
  loaderGone = true;
  setTimeout(() => {
    const el = $("w-load");
    el.classList.add("done"); el.setAttribute("aria-hidden", "true");
    setTimeout(() => { el.hidden = true; }, 500);
  }, Math.max(0, (STILL ? 300 : 2100) - (performance.now() - LOAD_T0)));
}
setTimeout(hideLoader, 4000);                                   // the feed is slow: show the page with what it has

function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      hideLoader();
      D.grid = d.grid; D.power = d.power; D.replay = d.replay || null; D.scale = d.scale || null; D.whatif = d.whatif || null;
      D.places = d.iso_places || {};
      D.specs = d.job_specs || {}; D.jobs = d.jobs || {}; D.capEvents = d.cap_events || [];
      D.pts = (d.power_history || []).filter((x) => x && x[1] != null).slice(-180);
      if (D.replay && D.replay.last) D.last = D.replay.last;
      break;
    case "power":
      D.power = d;
      if (d.combined_w != null) { D.pts.push([d.t, d.combined_w]); if (D.pts.length > 180) D.pts.shift(); }
      break;
    case "event":                                               // a CapEvent: the cap the data center must get under
      if (d.intake || !d.start) return;
      D.capEvents = [...D.capEvents.filter((e) => e.id !== d.id), d];
      break;
    case "state": if (d.job) D.jobs[d.job] = d; break;
    case "grid": if (d.feed === "signal") D.grid = d; break;
    case "replay": D.last = d; D.pick = d.event; onAlerts(d); break;
    case "whatif": D.whatif = d; break;
    case "action": if (running() || faulted()) onAction(d); return;
    case "scale": D.scale = d; break;
    default: return;
  }
  render();
}

// ---------------------------------------------------------------- the data center giving power back (world.js "This Mac")
// Everything here comes from live state or the meter: each rack row is a job's own reported state, the cap is the
// executor's CapEvent, and compliance is the same rule as Info's (trace.js capStatus): the trailing 10-s mean of
// measured watts at or under the cap.
const ROLL_S = 10;
function capNow() {
  const now = nowS();
  const band = D.capEvents.filter((e) => e.target_w != null && e.start).map((e) => {
    const s = Date.parse(e.start) / 1000;
    return { start: s, end: s + e.duration_s, w: e.target_w };
  }).find((b) => b.start <= now && now < b.end);
  if (!band) return null;
  const mean = (t) => { const xs = D.pts.filter(([u]) => u > t - ROLL_S && u <= t).map(([, w]) => w); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; };
  const last = D.pts.length ? D.pts[D.pts.length - 1] : null, m = last && now - last[0] < 5 ? mean(last[0]) : null;
  const hit = D.pts.find(([t]) => t > band.start && mean(t) != null && mean(t) <= band.w);
  const before = D.pts.filter(([t]) => t >= band.start - 60 && t < band.start).map(([, w]) => w);
  return { w: band.w, start: band.start, mean: m, over: m != null && m > band.w, ttc: hit ? hit[0] - band.start : null,
    since: now - band.start, baseline: before.length >= 10 ? before.reduce((a, b) => a + b, 0) / before.length : null };
}
function rackStates() {
  return ["chat", "train", "batch"].map((job) => {
    const st = D.jobs[job] || {}, spec = D.specs[job] || {};
    const slowed = st.state === "running" && ((st.concurrency != null && spec.max_concurrency && st.concurrency < spec.max_concurrency) || st.device === "cpu");
    return { job, state: st.state === "running" ? (slowed ? "slowed" : "running") : "off" };
  });
}

// ---------------------------------------------------------------- switching picks, cleanly
// Numbers roll to their new value (about half a second), alert cards slide out and in, the headline fades in; the
// camera glide is world.js glide(). All of it runs on a change, never on a timer, and not at all under reduced motion.
const ROLLS = new WeakMap();
function setNum(el, text) {
  const m = /^(-?)(\d[\d,]*\.?\d*)(.*)$/.exec(text), prev = ROLLS.get(el);
  if (prev && prev.raf) cancelAnimationFrame(prev.raf);
  const to = m ? (m[1] ? -1 : 1) * parseFloat(m[2].replace(/,/g, "")) : null, unit = m ? m[3] : null;
  const from = prev && prev.v != null && prev.unit === unit ? prev.v : null;
  if (!m || STILL || from == null || from === to) { el.textContent = text; ROLLS.set(el, { v: to, unit }); return; }
  const dec = (m[2].split(".")[1] || "").length, t0 = performance.now(), st = { v: to, unit, raf: 0 };
  const tick = (now) => {
    const f = Math.min(1, (now - t0) / 520), v = from + (to - from) * (1 - Math.pow(1 - f, 3));
    const n = m[2].includes(",") ? Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec }) : Math.abs(v).toFixed(dec);
    el.textContent = f < 1 ? `${v < 0 ? "-" : ""}${n}${unit}` : text;
    if (f < 1) st.raf = requestAnimationFrame(tick);
  };
  st.raf = requestAnimationFrame(tick);
  ROLLS.set(el, st);
}
function clearAlerts() {
  const box = $("w-alerts"), old = [...box.children];
  if (STILL || !old.length) { box.replaceChildren(); return; }
  old.forEach((el) => el.classList.add("leaving"));
  setTimeout(() => old.forEach((el) => el.remove()), 220);
}
function swapIn(...els) {
  if (STILL) return;
  for (const el of els) { el.classList.remove("w-swap"); void el.offsetWidth; el.classList.add("w-swap"); }
}

function onAlerts(d) {
  const ev = D.cat.find((e) => e.id === d.event);
  for (const label of d.fired || []) {
    if (D.shown.has(label)) continue;
    D.shown.add(label);
    const a = ev && ev.alerts.find((x) => x.label === label);
    toast(a ? a.kind : "warning", a ? (a.before_window ? (a.day ? `days before · ${a.day}` : "forecast") : isoClock(a.at)) : "", label, a ? a.source : "");
  }
}
function toast(kind, when, text, source) {
  const el = document.createElement("div");
  el.className = `w-toast ${kind}`;
  setHTML(el, html`<b>${when}</b><span>${text}</span><small>${source}</small>`);
  $("w-alerts").prepend(el);
  while ($("w-alerts").children.length > 4) $("w-alerts").lastChild.remove();
  setTimeout(() => el.classList.add("old"), 9000);
}

// How Griddy fixes it, as it happens: the solver's plan executed on this Mac (controller/knobs.py action events),
// gathered in one card so the alerts stay readable.
const ACTS = {};
let actCard = null;
function onAction(d) {
  const st = { pause: "paused", run: "running", stop: "stopped", resume: "running" };
  const what = d.state ? st[d.state] || d.state : d.concurrency != null ? `${d.concurrency} streams` : d.threads != null ? `${d.threads} threads` : d.device ? `on the ${String(d.device).toUpperCase()}` : null;
  if (!what) return;
  ACTS[d.job] = what;
  if (!actCard) { actCard = document.createElement("div"); actCard.className = "w-toast act"; }
  const el = actCard;
  setHTML(el, html`<b>Griddy acts · ${localClock(nowS())}</b><span>${Object.entries(ACTS).map(([j, w]) => `${j} ${w}`).join(" · ")}</span><small>the solver's plan, executed on this Mac; chat keeps its speed promise</small>`);
  $("w-alerts").prepend(el);
}

// Where the replayed hours came from: fetched live just now, or the evidence copy (and why).
// The data centers' block on the overview: San Francisco's, as OpenStreetMap maps them; a click opens them.
function campus() {
  const m = D.dcMap;
  return m ? { title: `${m.area}'s data centers`, value: `${m.counts.data_centers} mapped`, sub: "each beside its nearest PG&E substation · click to see them" }
    : { title: "Data centers", value: "—", sub: "loading the map" };
}
function provenance(ev, data) {
  if (!data) return html``;
  if (data.simulated) {
    const how = (m, ba) => (m && m.source === "live" ? `fetched live from api.eia.gov (EIA-930, ${ba})` : `the evidence copy (EIA-930, ${ba})`);
    return html`Simulated: ${data.simulated}. California's hours ${how(data, ev ? ev.ba : "")}; Texas's share each hour ${how(data.shape, "ERCO")}. The software sees each hour only once it has ended.`;
  }
  if (data.source === "live") {
    const same = data.max_diff_mw === 0 ? ", identical to the evidence copy" : data.max_diff_mw != null ? `, within ${fixed(data.max_diff_mw, 0)} MW of the evidence copy` : "";
    return html`Grid data fetched live from api.eia.gov at ${data.fetched_at ? new Date(data.fetched_at).toTimeString().slice(0, 5) : "—"} (EIA-930, ${ev ? ev.ba : ""}${same}). The software sees each hour only once it has ended.`;
  }
  return html`Grid data: the evidence copy, ${ev ? ev.data_source : "EIA-930"} (${data.why || "api.eia.gov not reached"}). The software sees each hour once it has ended.`;
}

// Without Griddy / With Griddy, the point of the page (Aryen, Sun 02:50: "it matters"): a big figure and a short line
// each, and one bar on the same scale, the gap: all red without, the mint share Griddy closes with it.
// no = {fig, text, src, gap}, yes = {fig, text, src, pct}: pct of the gap closed, 0 until this Mac has cut.
function versus(no, yes) {
  const el = $("w-versus");
  el.hidden = false;
  if (!D.versusPrev && !STILL) { el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter"); }   // it rises in once
  D.versusOn = true;
  setNum($("w-without-fig"), no.fig || ""); $("w-without").textContent = no.text; $("w-without-src").textContent = no.src;
  setNum($("w-with-fig"), yes.fig || ""); $("w-with").textContent = yes.text; $("w-with-src").textContent = yes.src;
  const bars = !!no.gap && yes.pct != null, pct = bars ? Math.max(0, Math.min(100, yes.pct)) : 0;
  $("w-without-bar").hidden = !bars; $("w-with-bar").hidden = !bars;
  $("w-with-fill").style.width = `${pct > 0 ? Math.max(1, pct).toFixed(1) : 0}%`;   // a sliver stays visible
  $("w-with-bar").setAttribute("aria-label", `each GW of data centers closes ${fixed(pct, 1)}% of the gap`);
}
// The With side is a RATE, never a fleet (Aryen, Sun 04:30: "no invented fleet total anywhere"): what every 1 GW of data
// centers cutting like this Mac frees, and how many GW of them would cover the gap.
function coverGw(sc, gapMw) { return sc && sc.freed_mw > 0 && gapMw > 0 ? (gapMw / sc.freed_mw) * (sc.flexible_mw / 1000) : null; }
function withSide(sc, pct, gapMw, waiting, src) {
  if (!sc) return { fig: "", text: waiting, pct: 0, src };
  const cover = coverGw(sc, gapMw), per = sc.flexible_mw === 1000 ? "every 1 GW" : `every ${gw(sc.flexible_mw)}`;
  return { fig: `${wholeMw(sc.freed_mw)} MW`, pct, src,
    text: `freed by ${per} of data centers cutting like this Mac${cover != null ? `; ${fixed(cover, cover < 10 ? 1 : 0)} GW of them would cover the gap` : ""}${sc.people != null ? ` · about ${Math.round(sc.people).toLocaleString()} ${sc.people_unit} kept on per GW` : ""}` };
}
// the fourth tile in an emergency: how many GW of data centers cutting like this Mac would cover the gap
function impactTile(sc, gapMw, cutWords) {
  const cover = coverGw(sc, gapMw);
  if (cover != null) { setNum($("s-impact"), `${fixed(cover, cover < 10 ? 1 : 0)} GW`); $("s-impact-k").textContent = "of data centers like this Mac would cover the gap"; }
  else if (sc) { setNum($("s-impact"), `${wholeMw(sc.freed_mw)} MW`); $("s-impact-k").textContent = "freed by every 1 GW of data centers"; }
  else { setNum($("s-impact"), "—"); $("s-impact-k").textContent = "data centers like this Mac"; }
  $("s-impact-src").textContent = sc ? `estimate, a rate · each GW frees ${wholeMw(sc.freed_mw)} MW at ${cutWords}` : "appears once this Mac cuts";
}
function bigCount(n) { return n >= 1e6 ? `${fixed(n / 1e6, 1)} million` : Math.round(n).toLocaleString(); }
// the cited sentence a figure comes from (config/events.yaml impact), else the first
function cited(ev, figure) { return ev.impact.find((i) => i.text.includes(figure)) || ev.impact[0]; }

function render() {
  const live = !running() && D.pick === "live";
  const ev = D.cat.find((e) => e.id === (running() ? D.last.event : D.pick));
  if ($("w-picks").children.length !== D.cat.length + 1) {      // built once, so keyboard focus survives the 1-s refresh
    setHTML($("w-picks"), html`<button type="button" data-pick="live">Live now</button>
      ${D.cat.map((e) => html`<button type="button" data-pick="${e.id}">${e.title}<small>${e.when}</small></button>`)}`);
  }
  for (const b of $("w-picks").children) b.setAttribute("aria-pressed", String(b.dataset.pick === D.pick));
  $("w-play-btn").hidden = live;
  $("w-play-btn").textContent = running() ? "Stop" : D.fetching ? "Fetching from the EIA…" : "Replay it live";
  $("w-break-btn").textContent = faulted() ? "Clear the fault" : "Break a part";
  $("w-break-btn").setAttribute("aria-pressed", String(faulted()));
  const train = D.jobs.train;
  $("w-work-btn").hidden = running() || !train || train.state === "running" || train.state === "done";
  const g = D.grid, p = D.power;
  if (g) { $("w-feed").textContent = `${g.iso} · ${g.stale ? "stale" : "live"} · ${fixed(g.feed_age_s, 0)} s`; $("w-feed").className = `badge ${g.stale ? "bad" : "ok"}`; }
  D.versusPrev = D.versusOn; D.versusOn = false;
  $("w-versus").hidden = true;
  World.set({ racks: rackStates(), cap: capNow() });
  followCity(); prefetchMap();
  if (running()) {
    const d = D.last, sc = d.scale;
    if (d.mix_mw) for (const [k, v] of Object.entries(d.mix_mw)) D.peaks[k.toLowerCase()] = Math.max(D.peaks[k.toLowerCase()] || 0, v);
    World.set({ mix: d.mix_mw, served: d.demand_mw, needed: d.forecast_mw, ours_w: d.ours_w, baseline_w: d.baseline_w,
      cut_pct: d.measured_cut_pct, alert: d.cut_kinds.includes("emergency") ? "emergency" : d.cut_kinds.includes("warning") ? "warning" : null,
      peaks: { wind: D.peaks.wind, solar: D.peaks.solar }, with_mw: sc ? sc.freed_mw : null, city: ev ? ev.region : null,
      iso: ev ? ev.iso : null, places: ev ? D.places[ev.iso] || null : null, stand_in: standInNow(), campus: campus() });
    $("w-clock").textContent = `${ev ? ev.title : d.title}${ev && ev.simulated ? " (simulated)" : ""} · ${isoLabel(d.hour_ending || d.sim_time)}`;
    $("w-progress").style.width = `${(100 * d.progress).toFixed(1)}%`;
    $("w-head").textContent = "";
    setNum($("s-served"), gw(d.demand_mw));
    $("s-served-src").textContent = `${ev && ev.simulated ? `simulated · ${ev.ba}'s forecast × Texas's share served (EIA-930)` : `EIA-930 · ${ev ? ev.ba : ""}`} · hour ending ${isoClock(d.hour_ending)}`;
    setNum($("s-needed"), gw(d.forecast_mw)); $("s-needed-src").textContent = "the operator's day-ahead forecast";
    setNum($("s-mac"), d.ours_w == null ? "—" : `${fixed(d.ours_w, 1)} W`);
    const cut = d.measured_cut_pct;
    $("s-mac-src").textContent = d.nothing_to_shed ? "nothing running to shed" : cut != null
      ? `${fixed(Math.abs(cut), 0)}% ${cut >= 0 ? "below" : "above"} its baseline · measured` : "measured by powermetrics";
    impactTile(sc, ev ? ev.shed_mw : null, sc ? `the ${fixed(sc.share_pct, 0)}% the alert asked` : "");
    if (ev) {
      const fig = ev.people_out ? bigCount(ev.people_out) : `${wholeMw(ev.shed_mw)} MW`, c = cited(ev, fig);
      versus({ fig, text: ev.people_out ? `${ev.people_unit || "people"} ${ev.simulated ? "lose power (simulated)" : "lost power"}` : "the grid had to find at the peak",
        src: `${c.text} · ${c.source}`, gap: ev.shed_mw > 0 },
        withSide(sc, sc ? sc.share_of_shed_pct : null, ev.shed_mw, waitingText(d.asked_cut_pct, d.nothing_to_shed),
          sc ? `estimate, a rate: this Mac's measured cut, as far as the alert asked (${fixed(sc.share_pct, 0)}%), on every 1 GW of data centers; no fleet total is assumed${sc.people != null && ev.people_basis ? `; ${ev.people_basis}` : ""}` : "measured on this Mac, live"));
    }
    setHTML($("w-sources"), html`${provenance(ev, d.data)} ${ev ? html`Alerts and impact: <a href="${ev.report_url}" target="_blank" rel="noopener">official report</a>, page on each.` : html``}`);
    overlayFault();
    return;
  }
  // live: the ISO's real fuel mix now, demand served (its generation) against its own forecast, this Mac now
  const mixNow = (g && g.fuel_mix_mw) || {};
  const served = Object.values(mixNow).filter((v) => v > 0).reduce((s, v) => s + v, 0) || null;
  const needed = liveNeeded(g);
  World.set({ mix: mixNow, served, needed, ours_w: p ? p.combined_w : null, baseline_w: null, cut_pct: null, alert: null, peaks: {},
    with_mw: null, city: null, iso: g ? g.iso : null, places: g ? D.places[g.iso] || null : null, stand_in: standInNow(), campus: campus() });
  if (live) {
    $("w-clock").textContent = g ? `Live · ${g.iso} · ${localClock(nowS())}` : "Live · waiting for the grid feed";
    $("w-progress").style.width = "0%";
    $("w-head").textContent = "Pick a real emergency to replay it, or click any part of the grid to break it.";
  } else if (ev) {
    $("w-clock").textContent = `${ev.title} · ${ev.when}`;
    $("w-progress").style.width = "0%";
    $("w-head").textContent = ev.simulated
      ? `Simulated: ${ev.simulated}. Press play to fetch both grids' hours live from the U.S. EIA.`
      : `Press play to fetch the hours live from the U.S. EIA. The software gets them one hour at a time.`;
  }
  setNum($("s-served"), gw(served)); $("s-served-src").textContent = g ? `${g.iso} fuel mix, live` : "";
  setNum($("s-needed"), gw(needed)); $("s-needed-src").textContent = needed ? `${g.iso} load forecast` : "no forecast for this hour";
  setNum($("s-mac"), p ? `${fixed(p.combined_w, 1)} W` : "—");
  $("s-mac-src").textContent = p ? `measured by powermetrics · ${age(p.t)}` : "waiting for the meter";
  setNum($("s-impact"), D.scale ? `${wholeMw(D.scale.freed_mw)} MW` : "—");
  $("s-impact-k").textContent = "freed by every 1 GW of data centers cutting like this Mac";
  $("s-impact-src").textContent = D.scale ? `estimate, a rate · ${fixed(D.scale.our_cut_pct, 1)}% measured cut · ${fixed(D.scale.share_of_demand_pct, 1)}% of ${D.scale.iso} now` : "estimate";
  setHTML($("w-sources"), html`Live grid data: ${g ? g.iso : "—"} via gridstatus. This Mac: macOS powermetrics. Detail and every graph: <a href="/info.html">Info</a>.`);
  overlayFault();
}

// In the city map, the footer says what is real and what is drawn.
function citySources() {
  if (!D.city) return;
  if (D.city.dc) {
    const m = D.dcMap;
    setHTML($("w-sources"), html`Data centers in ${m.area} as mapped in OpenStreetMap (${m.license}), fetched ${m.fetched_at.slice(0, 10)}: what volunteers have mapped, not a census; addresses and footprints only. Each is shown beside its nearest PG&E substation (OpenStreetMap); which substation feeds it is not public, and neither are their sizes. The racks are this Mac's, measured by powermetrics, standing in for each.`);
    return;
  }
  const m = D.maps[D.city.id], h = (m && m.heights) || {};
  setHTML($("w-sources"), html`${D.city.name}${m ? `, ${m.area}` : ""}: buildings, heights, streets and power lines drawn 1:1 from ${m ? m.license : D.city.license}, fetched ${String((m || D.city).fetched_at).slice(0, 10)}${m ? `; ${h.estimated} of ${m.buildings.length} heights estimated from the building's type` : ""}. Homes lit: the grid's real served over needed. Which blocks go dark, and the feeder routing: illustrative.`);
}

// A judge's what-if on top of whatever the world shows: the broken part, the grid's real numbers after it, our cut.
function overlayFault() {
  citySources();
  if (!faulted()) { World.set({ tripped: null, tripped_mw: null, fault: null }); return; }
  const w = D.whatif, sc = w.scale;
  World.set({ tripped: w.target === "city" ? null : w.fuel, tripped_mw: w.lost_mw, fault: w.target, served: w.served_after, needed: w.needed_after,
    alert: w.shortfall_mw > 0 ? "emergency" : null, with_mw: sc ? sc.freed_mw : null, ours_w: w.ours_w, baseline_w: w.baseline_w,
    cut_pct: w.measured_cut_pct });
  setNum($("s-served"), gw(w.served_after));
  $("s-served-src").textContent = `what-if: ${w.lost_mw ? `−${gw(w.lost_mw)}` : "no supply lost"} from ${w.source}`;
  setNum($("s-needed"), gw(w.needed_after));
  $("s-needed-src").textContent = w.surge_mw ? `what-if: +${gw(w.surge_mw)}, the published forecast peak` : "the operator's forecast";
  if (sc) impactTile(sc, w.shortfall_mw, "this Mac's measured cut");
  $("w-head").textContent = `${w.label}. ${Math.round(w.remaining_s)} s left.`;
  const short = w.shortfall_mw > 0;
  versus({ fig: short ? gw(w.shortfall_mw) : "", text: short ? "short: that much demand goes unserved" : "The grid still covers demand: nothing is shed",
    src: `arithmetic on ${w.source}`, gap: short },
    withSide(sc, sc ? sc.share_of_shortfall_pct : null, w.shortfall_mw, w.asked_cut_pct ? waitingText(w.asked_cut_pct, w.nothing_to_shed) : "No cut needed",
      sc ? "estimate, a rate: this Mac's measured cut on every 1 GW of data centers; no fleet total is assumed" : "measured on this Mac, live"));
}

// Before this Mac's measured drop: why there is no "with Griddy" number yet, in words.
function waitingText(asked, nothing) {
  const busy = Object.values(D.jobs).some((j) => j.state === "running" && j.job !== "chat");
  if (nothing || (asked && !busy)) return `Griddy asked our sites for ${asked ? `a ${fixed(asked, 0)}%` : "a"} cut, but nothing deferrable is running on this Mac to shed: give training a deadline, then run it again`;
  return asked ? `Griddy asked our sites for a ${fixed(asked, 0)}% cut: waiting for this Mac's measured drop` : "Waiting for the first alert: this Mac's measured cut decides the number";
}

// ---------------------------------------------------------------- the city map: the real city of what is on screen
function cityNow() {
  const ev = D.cat.find((e) => e.id === (running() ? D.last.event : D.pick));
  const iso = ev ? ev.iso : D.grid ? D.grid.iso : null;
  return D.cities.find((c) => c.iso === iso) || null;
}
// The city view always shows the city of what is on screen (Aryen, Sun 00:35: Uri's Texas numbers were drawn on San
// Francisco): when a replay of another region starts, or the grid changes, the camera flies to that city instead.
let citySwitching = false;
async function followCity() {
  if (!D.city || D.city.dc || citySwitching) return;                  // the data centers' view stays until Back
  const want = cityNow();
  if (want && want.id === D.city.id) return;
  citySwitching = true;
  try { if (want) await openCity(want); else closeCity(); } finally { citySwitching = false; }
}
// The overview names the real building this Mac stands in for, the one the city view outlines: fetch the city's map
// once, ahead of a click (which also makes the fly-in instant). One try per city.
async function prefetchMap() {
  const c = cityNow();
  if (!c || D.maps[c.id] || D.mapTried.has(c.id)) return;
  D.mapTried.add(c.id);
  const r = await getJSON(`/api/cities/${c.id}/map`);
  if (r.ok && !D.maps[c.id]) { D.maps[c.id] = r.data; render(); }
}
function standInNow() {
  const c = cityNow(), m = c && D.maps[c.id], dc = m ? World.standIn(m.data_centers) : null;
  return dc && dc.address ? dc.address : null;
}
function wholeMw(mw) { return mw == null || !isFinite(mw) ? "—" : Math.round(mw).toLocaleString(); }
async function openCity(city) {
  if (!D.maps[city.id]) {                                       // one real square of the city, 1:1 (OpenStreetMap)
    const r = await getJSON(`/api/cities/${city.id}/map`);
    if (!r.ok) { toast("emergency", "city", `No map for ${city.name}: ${routeError(`/api/cities/${city.id}/map`, r)}`, ""); return; }
    D.maps[city.id] = r.data;
  }
  D.city = city; World.openCity(city, D.maps[city.id]); $("w-back").hidden = false; render();
}
// A click on either data center opens San Francisco's, side by side, each beside its nearest substation (Aryen, Sun 03:00:
// "data center needs to expand when clicked"; 04:00: "the datacenters connected to sf"; 04:20: "next to each other").
function openDataCenters() {
  if (!D.dcMap) { toast("emergency", "data centers", "The data centers' map is not loaded: run scripts/fetch_datacenters.py", ""); return; }
  D.city = { id: DC_MAP, name: `${D.dcMap.area}'s data centers`, dc: true };
  World.openCity(D.city, D.dcMap); $("w-back").hidden = false; render();
}
function closeCity() { D.city = null; World.closeCity(); World.glide(D.pick); $("w-back").hidden = true; render(); }
$("w-back").addEventListener("click", closeCity);

// ---------------------------------------------------------------- breaking a part: a confirm card, then the server
function openPop(title, text, buttons, pt, words) {
  $("w-pop-t").textContent = title; $("w-pop-p").textContent = text;
  $("w-pop-f").hidden = !words; $("w-pop-read").textContent = ""; $("w-pop-read").className = ""; $("w-pop-in").value = "";
  POP.words = words || null;
  const box = $("w-pop-b"), nav = $("w-pop-o");
  box.replaceChildren(); nav.replaceChildren();
  for (const [label, cls, fn] of buttons) {                    // a way into a map goes above, the actions below
    const b = document.createElement("button");
    b.type = "button"; b.className = cls; b.textContent = label; b.addEventListener("click", fn);
    (cls === "open" ? nav : box).append(b);
  }
  const pop = $("w-pop");
  pop.hidden = false;
  const r = pop.getBoundingClientRect();
  pop.style.left = `${Math.max(16, Math.min(innerWidth - r.width - 16, pt.x - r.width / 2))}px`;
  pop.style.top = `${Math.max(76, Math.min(innerHeight - r.height - 16, pt.y - r.height - 14))}px`;
  (words ? $("w-pop-in") : nav.firstChild || box.firstChild).focus();
}
function closePop() { $("w-pop").hidden = true; }
const POP = { words: null };
// The judge's own words: read into a part, a share and a cause (POST /api/whatif/read), shown with its real size,
// broken only on confirm.
$("w-pop-f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("w-pop-in").value.trim();
  if (text.length < 3) return;
  $("w-pop-read").className = ""; $("w-pop-read").textContent = "Reading…";
  const r = await postJSON("/api/whatif/read", { text, target: POP.words && POP.words.target, who: "judge" });
  if (!r.ok) { $("w-pop-read").className = "err"; $("w-pop-read").textContent = r.data && r.data.detail ? String(r.data.detail) : routeError("/api/whatif/read", r); return; }
  const f = r.data, part = f.target === "hub" ? "the substation" : f.target === "city" ? "demand" : `the ${f.target.slice(6).toLowerCase()} fleet`;
  $("w-pop-read").textContent = `${f.how}: “${f.cause}”. ${part[0].toUpperCase()}${part.slice(1)} ${f.target === "city" ? "rises" : "loses"} ${fixed(f.share_pct, 0)}%: ${f.target === "city" ? "+" : "−"}${gw(f.size_mw)} of its real ${gw(f.part_mw)} now.`;
  const box = $("w-pop-b");
  box.replaceChildren();
  for (const [label, cls, fn] of [["Break it like that", "go", () => breakIt(f.target, f.share_pct, f.cause)], ["Cancel", "", closePop]]) {
    const b = document.createElement("button");
    b.type = "button"; b.className = cls; b.textContent = label; b.addEventListener("click", fn);
    box.append(b);
  }
});

function confirmBreak(h, pt) {
  const ts = breakable().filter((t) => t.id.startsWith("plant:"));
  const big = ts.reduce((a, b) => (b.mw > (a ? a.mw : 0) ? b : a), null);
  const card = h.id.startsWith("plant:")
    ? [`Trip the ${h.title.toLowerCase()} fleet?`, `What-if: the grid loses this fleet's output right now, ${gw(h.mw)}. Griddy responds live and this Mac's watts are measured.`, "Trip it"]
    : h.id === "hub"
      ? ["Fail the main substation?", `What-if: it cuts off the largest fleet${big ? `, ${big.title.toLowerCase()} (${gw(big.mw)} right now)` : ""}. Griddy responds live.`, "Fail it"]
      : [`Surge demand in ${h.title === "City" ? "the city" : h.title}?`, "What-if: demand jumps to today's highest published forecast. Griddy responds live.", "Surge it"];
  const city = h.id === "city" ? cityNow() : null;
  openPop(card[0], card[1], [...(city ? [[`Open the ${city.name} map`, "open", () => { closePop(); openCity(city); }]] : []),
    [card[2], "go", () => breakIt(h.id)], ["Cancel", "", closePop]], pt, { target: h.id });
}
async function breakIt(id, share = 100, cause = "") {
  closePop();
  const r = await postJSON("/api/whatif", { target: id, share_pct: share, cause, who: "judge" });
  if (!r.ok) { toast("emergency", "what-if", `Could not break it: ${routeError("/api/whatif", r)}`, ""); return; }
  D.whatif = r.data;
  render();
  toast("emergency", "what-if", r.data.label, r.data.shortfall_mw > 0
    ? `the grid is ${gw(r.data.shortfall_mw)} short: Griddy asks our sites for a ${fixed(r.data.asked_cut_pct, 0)}% cut`
    : "the grid still covers demand: no cut needed");
}

World.onPick((h, pt) => (h.id === "datacenters" ? openDataCenters() : confirmBreak(h, pt)));
function breakable() { return World.targets().filter((t) => t.id.startsWith("plant:") || t.id === "hub" || t.id === "city"); }
$("w-break-btn").addEventListener("click", async (e) => {
  if (faulted()) { await postJSON("/api/whatif", { target: "clear", who: "judge" }); D.whatif = null; render(); return; }
  const r = e.currentTarget.getBoundingClientRect();
  openPop("Break a part of the grid", "What-if: you invent the fault. Its size comes from the grid at this moment.",
    [...breakable().map((t) => [t.mw ? `${t.title} · ${gw(t.mw)}` : t.title, "", () => confirmBreak(t, { x: r.left + r.width / 2, y: r.top })]),
      ["Cancel", "", closePop]], { x: r.left + r.width / 2, y: r.top }, { target: null });
});
document.addEventListener("keydown", (e) => { if (e.key !== "Escape") return; if (!$("w-pop").hidden) closePop(); else if (D.city) closeCity(); });
document.addEventListener("pointerdown", (e) => { if (!$("w-pop").hidden && !e.target.closest("#w-pop, #w-break-btn")) closePop(); });

$("w-picks").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-pick]");
  if (!b) return;
  if (running()) await postJSON("/api/replay", { action: "stop" });
  D.pick = b.dataset.pick; D.last = null; D.shown.clear(); clearAlerts();
  World.glide(D.pick); swapIn($("w-head"), $("w-clock"));
  render();
});
// A replay needs something on this Mac to shed. The owner's deadline is the honest lever: with the deadline exactly
// the training's remaining GPU time away, the solver has to run it now (POST /api/jobs/train, a logged job change).
$("w-work-btn").addEventListener("click", async () => {
  const job = "train", mins = (D.specs[job] && D.specs[job].required_runtime_min) || 60;
  const due = new Date(Date.now() + (mins + 5) * 60e3);
  const r = await postJSON(`/api/jobs/${job}`, { deadline: localISO(due), who: "demo driver" });
  toast(r.ok ? "brownout" : "emergency", "training", r.ok ? `Training is due at ${due.toTimeString().slice(0, 5)}, its GPU time from now: the solver runs it now. Replay in about 20 s.` : `Could not set a deadline: ${routeError(`/api/jobs/${job}`, r)}`, "");
});
$("w-play-btn").addEventListener("click", async () => {
  if (running()) { await postJSON("/api/replay", { action: "stop" }); D.last = null; render(); return; }
  if (D.pick === "live") return;
  D.shown.clear(); clearAlerts();
  D.fetching = true; render();
  const r = await postJSON("/api/replay", { action: "start", event: D.pick });
  D.fetching = false;
  if (!r.ok) { toast("emergency", "", `Could not start: ${routeError("/api/replay", r)}`, ""); return; }
  const src = r.data && r.data.data;
  toast("brownout", "data", src && src.source === "live" ? `Fetched ${src.rows} hours live from api.eia.gov` : "api.eia.gov not reached: running on the evidence copy",
    src ? (src.source === "live" ? src.url : src.why) : "");
});

World.mount($("world"));
const keepClear = () => World.safeArea($("conn").closest("header").getBoundingClientRect().bottom + 8,
  innerHeight - document.querySelector(".w-dock").getBoundingClientRect().top + 8,
  innerWidth > 900 && $("w-alerts").children.length ? innerWidth - $("w-alerts").getBoundingClientRect().left + 8 : 0);
new ResizeObserver(keepClear).observe(document.querySelector(".w-dock"));
new MutationObserver(keepClear).observe($("w-alerts"), { childList: true });
addEventListener("resize", keepClear);
getJSON("/api/replay/events").then((r) => { if (r.ok) { D.cat = r.data; render(); } });
getJSON("/api/cities").then((r) => { if (r.ok) D.cities = r.data; });
const DC_MAP = "san-francisco-datacenters";                     // docs/evidence/city/<id>-map.json (the Bay Area's is kept for later)
getJSON(`/api/cities/${DC_MAP}/map`).then((r) => { if (r.ok) { D.dcMap = r.data; render(); } });
setInterval(render, 1000);
connectWS(handle, $("conn"));

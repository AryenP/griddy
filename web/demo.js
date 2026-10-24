// The judge's page (index.html): the 3D grid world and four choices: the live grid now, or a real emergency replayed
// through the live software (replay/engine.py). Numbers only, each with its source in small type; the detail and
// every graph live on info.html. Contract: snapshot and WebSocket events from HANDOFF.md, /api/replay*.
"use strict";

const D = { grid: null, power: null, replay: null, last: null, cat: [], pick: "live", scale: null, shown: new Set(), peaks: {}, specs: {}, jobs: {} };

const gw = (mw) => (mw == null ? "—" : `${fixed(mw / 1000, 1)} GW`);
const compact = (n) => (n >= 1e6 ? `${fixed(n / 1e6, 1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(Math.round(n)));
const running = () => !!(D.last && D.last.event && nowS() - D.last.t < 5);

function liveNeeded(sig) {
  // the ISO's own load forecast at this hour (GridSignal.load_forecast: [[time, MW]])
  const pts = (sig && sig.load_forecast) || [];
  const now = Date.now();
  let best = null;
  for (const [t, mw] of pts) { const d = Math.abs(Date.parse(t) - now); if (!best || d < best[0]) best = [d, mw]; }
  return best && best[0] < 2 * 3600e3 ? best[1] : null;
}

function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      D.grid = d.grid; D.power = d.power; D.replay = d.replay || null; D.scale = d.scale || null;
      D.specs = d.job_specs || {}; D.jobs = d.jobs || {};
      if (D.replay && D.replay.last) D.last = D.replay.last;
      break;
    case "power": D.power = d; break;
    case "state": if (d.job) D.jobs[d.job] = d; break;
    case "grid": if (d.feed === "signal") D.grid = d; break;
    case "replay": D.last = d; D.pick = d.event; onAlerts(d); break;
    case "scale": D.scale = d; break;
    default: return;
  }
  render();
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

function render() {
  const live = !running() && D.pick === "live";
  const ev = D.cat.find((e) => e.id === (running() ? D.last.event : D.pick));
  if ($("w-picks").children.length !== D.cat.length + 1) {      // built once, so keyboard focus survives the 1-s refresh
    setHTML($("w-picks"), html`<button type="button" data-pick="live">Live now</button>
      ${D.cat.map((e) => html`<button type="button" data-pick="${e.id}">${e.title}<small>${e.when}</small></button>`)}`);
  }
  for (const b of $("w-picks").children) b.setAttribute("aria-pressed", String(b.dataset.pick === D.pick));
  $("w-play-btn").hidden = live;
  $("w-play-btn").textContent = running() ? "Stop" : "Replay it live";
  const train = D.jobs.train;
  $("w-work-btn").hidden = running() || !train || train.state === "running" || train.state === "done";
  const g = D.grid, p = D.power;
  if (g) $("w-feed").textContent = `${g.iso} feed ${g.stale ? "STALE" : "live"} · ${fixed(g.feed_age_s, 0)} s`;
  if (running()) {
    const d = D.last, sc = d.scale;
    if (d.mix_mw) for (const [k, v] of Object.entries(d.mix_mw)) D.peaks[k.toLowerCase()] = Math.max(D.peaks[k.toLowerCase()] || 0, v);
    World.set({ mix: d.mix_mw, served: d.demand_mw, needed: d.forecast_mw, ours_w: d.ours_w, baseline_w: d.baseline_w,
      cut_pct: d.measured_cut_pct, alert: d.cut_kinds.includes("emergency") ? "emergency" : d.cut_kinds.includes("warning") ? "warning" : null,
      peaks: { wind: D.peaks.wind, solar: D.peaks.solar },
      campus: ev ? { title: "Data centers", value: gw(ev.flexible_mw), sub: ev.flexible_mw === 1000 ? "a 1 GW unit" : "running in ERCOT (cited)" } : null });
    $("w-clock").textContent = `${ev ? ev.title : d.title} · ${isoLabel(d.sim_time)}`;
    $("w-progress").style.width = `${(100 * d.progress).toFixed(1)}%`;
    $("w-head").textContent = ev ? ev.impact[0].text : "";
    $("s-served").textContent = gw(d.demand_mw); $("s-served-src").textContent = `EIA-930 · ${ev ? ev.ba : ""}`;
    $("s-needed").textContent = gw(d.forecast_mw); $("s-needed-src").textContent = "the operator's day-ahead forecast";
    $("s-mac").textContent = d.ours_w == null ? "—" : `${fixed(d.ours_w, 1)} W`;
    const cut = d.measured_cut_pct;
    $("s-mac-src").textContent = d.nothing_to_shed ? "nothing running to shed" : cut != null
      ? `${fixed(Math.abs(cut), 0)}% ${cut >= 0 ? "below" : "above"} its baseline · measured` : "measured by powermetrics";
    if (sc && sc.people != null) { $("s-impact").textContent = compact(sc.people); $("s-impact-k").textContent = `${sc.people_unit} kept on`; }
    else if (sc) { $("s-impact").textContent = `${fixed(sc.freed_mw, 0)} MW`; $("s-impact-k").textContent = "freed at grid scale"; }
    else { $("s-impact").textContent = "—"; $("s-impact-k").textContent = "at grid scale"; }
    $("s-impact-src").textContent = sc ? `estimate · ${fixed(sc.share_pct, 0)}% cut asked, on ${gw(sc.flexible_mw)}` : "appears once this Mac cuts";
    setHTML($("w-sources"), ev ? html`Grid data: ${ev.data_source}. Alerts and impact: <a href="${ev.report_url}" target="_blank" rel="noopener">official report</a>, page on each alert.` : html``);
    return;
  }
  // live: the ISO's real fuel mix now, demand served (its generation) against its own forecast, this Mac now
  const mixNow = (g && g.fuel_mix_mw) || {};
  const served = Object.values(mixNow).filter((v) => v > 0).reduce((s, v) => s + v, 0) || null;
  const needed = liveNeeded(g);
  World.set({ mix: mixNow, served, needed, ours_w: p ? p.combined_w : null, baseline_w: null, cut_pct: null, alert: null, peaks: {},
    campus: D.scale ? { title: "ERCOT large loads", value: gw(D.scale.large_loads_running_mw), sub: "running, Sep 2026 (cited)" } : null });
  if (live) {
    $("w-clock").textContent = g ? `Live · ${g.iso} · ${localClock(nowS())}` : "Live · waiting for the grid feed";
    $("w-progress").style.width = "0%";
    $("w-head").textContent = "Pick a real emergency to replay it through the live software.";
  } else if (ev) {
    $("w-clock").textContent = `${ev.title} · ${ev.when}`;
    $("w-progress").style.width = "0%";
    $("w-head").textContent = ev.impact[0].text;
  }
  $("s-served").textContent = gw(served); $("s-served-src").textContent = g ? `${g.iso} fuel mix, live` : "";
  $("s-needed").textContent = gw(needed); $("s-needed-src").textContent = needed ? `${g.iso} load forecast` : "no forecast for this hour";
  $("s-mac").textContent = p ? `${fixed(p.combined_w, 1)} W` : "—";
  $("s-mac-src").textContent = p ? `measured by powermetrics · ${age(p.t)}` : "waiting for the meter";
  $("s-impact").textContent = D.scale ? `${fixed(D.scale.freed_mw, 0)} MW` : "—";
  $("s-impact-k").textContent = "ERCOT, if large loads cut like this Mac";
  $("s-impact-src").textContent = D.scale ? `estimate · ${fixed(D.scale.share_of_demand_pct, 1)}% of ERCOT now` : "estimate";
  setHTML($("w-sources"), html`Live grid data: ${g ? g.iso : "—"} via gridstatus. This Mac: macOS powermetrics. Detail and every graph: <a href="/info.html">Info</a>.`);
}

$("w-picks").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-pick]");
  if (!b) return;
  if (running()) await postJSON("/api/replay", { action: "stop" });
  D.pick = b.dataset.pick; D.last = null; D.shown.clear(); $("w-alerts").replaceChildren();
  render();
});
// A replay needs something on this Mac to shed. The owner's deadline is the honest lever: with the deadline exactly
// the training's remaining GPU time away, the solver has to run it now (POST /api/jobs/train, a logged job change).
$("w-work-btn").addEventListener("click", async () => {
  const job = "train", mins = (D.specs[job] && D.specs[job].required_runtime_min) || 60;
  const due = new Date(Date.now() + (mins + 5) * 60e3);
  const r = await postJSON(`/api/jobs/${job}`, { deadline: due.toISOString(), who: "demo driver" });
  toast(r.ok ? "brownout" : "emergency", "training", r.ok ? `Training is due at ${due.toTimeString().slice(0, 5)}, its GPU time from now: the solver runs it now. Replay in about 20 s.` : `Could not set a deadline: ${routeError(`/api/jobs/${job}`, r)}`, "");
});
$("w-play-btn").addEventListener("click", async () => {
  if (running()) { await postJSON("/api/replay", { action: "stop" }); D.last = null; render(); return; }
  if (D.pick === "live") return;
  D.shown.clear(); $("w-alerts").replaceChildren();
  const r = await postJSON("/api/replay", { action: "start", event: D.pick });
  if (!r.ok) toast("emergency", "", `Could not start: ${routeError("/api/replay", r)}`, "");
});

World.mount($("world"));
const keepClear = () => World.safeArea($("conn").closest("header").getBoundingClientRect().bottom + 8,
  innerHeight - document.querySelector(".w-dock").getBoundingClientRect().top + 8);
new ResizeObserver(keepClear).observe(document.querySelector(".w-dock"));
addEventListener("resize", keepClear);
getJSON("/api/replay/events").then((r) => { if (r.ok) { D.cat = r.data; render(); } });
setInterval(render, 1000);
connectWS(handle, $("conn"));

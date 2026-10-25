// The judge's page (index.html): the 3D grid world and four choices: the live grid now, or a real emergency replayed
// through the live software (replay/engine.py, its hours fetched live from api.eia.gov). Numbers only, each with its
// source in small type; the detail and every graph live on info.html. A click on a plant, the substation or the city
// breaks it (replay/whatif.py: the fault is invented, its size is real). Contract: snapshot and WebSocket events from
// HANDOFF.md, /api/replay*, /api/whatif.
"use strict";

const D = { grid: null, power: null, replay: null, last: null, whatif: null, cat: [], pick: "live", scale: null, fetching: false,
  cities: [], city: null,
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

function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      D.grid = d.grid; D.power = d.power; D.replay = d.replay || null; D.scale = d.scale || null; D.whatif = d.whatif || null;
      D.specs = d.job_specs || {}; D.jobs = d.jobs || {};
      if (D.replay && D.replay.last) D.last = D.replay.last;
      break;
    case "power": D.power = d; break;
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
function provenance(ev, data) {
  if (!data) return html``;
  if (data.source === "live") {
    const same = data.max_diff_mw === 0 ? ", identical to the evidence copy" : data.max_diff_mw != null ? `, within ${fixed(data.max_diff_mw, 0)} MW of the evidence copy` : "";
    return html`Grid data fetched live from api.eia.gov at ${data.fetched_at ? new Date(data.fetched_at).toTimeString().slice(0, 5) : "—"} (EIA-930, ${ev ? ev.ba : ""}${same}). The software sees each hour once it has ended, never a later one.`;
  }
  return html`Grid data: the evidence copy, ${ev ? ev.data_source : "EIA-930"} (${data.why || "api.eia.gov not reached"}). The software sees each hour once it has ended.`;
}

function versus(without, withText, withoutSrc, withSrc) {
  $("w-versus").hidden = false;
  $("w-without").textContent = without; $("w-without-src").textContent = withoutSrc;
  $("w-with").textContent = withText; $("w-with-src").textContent = withSrc;
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
  $("w-play-btn").textContent = running() ? "Stop" : D.fetching ? "Fetching from the EIA…" : "Replay it live";
  $("w-break-btn").textContent = faulted() ? "Clear the fault" : "Break a part";
  $("w-break-btn").setAttribute("aria-pressed", String(faulted()));
  const train = D.jobs.train;
  $("w-work-btn").hidden = running() || !train || train.state === "running" || train.state === "done";
  const g = D.grid, p = D.power;
  if (g) $("w-feed").textContent = `${g.iso} feed ${g.stale ? "STALE" : "live"} · ${fixed(g.feed_age_s, 0)} s`;
  $("w-versus").hidden = true;
  if (running()) {
    const d = D.last, sc = d.scale;
    if (d.mix_mw) for (const [k, v] of Object.entries(d.mix_mw)) D.peaks[k.toLowerCase()] = Math.max(D.peaks[k.toLowerCase()] || 0, v);
    World.set({ mix: d.mix_mw, served: d.demand_mw, needed: d.forecast_mw, ours_w: d.ours_w, baseline_w: d.baseline_w,
      cut_pct: d.measured_cut_pct, alert: d.cut_kinds.includes("emergency") ? "emergency" : d.cut_kinds.includes("warning") ? "warning" : null,
      peaks: { wind: D.peaks.wind, solar: D.peaks.solar }, with_mw: sc ? sc.freed_mw : null, city: ev ? ev.region : null,
      campus: ev ? { title: "Data centers", value: gw(ev.flexible_mw), sub: ev.flexible_mw === 1000 ? "a 1 GW unit" : "running in ERCOT (cited)" } : null });
    $("w-clock").textContent = `${ev ? ev.title : d.title} · ${isoLabel(d.hour_ending || d.sim_time)}`;
    $("w-progress").style.width = `${(100 * d.progress).toFixed(1)}%`;
    $("w-head").textContent = "";
    $("s-served").textContent = gw(d.demand_mw); $("s-served-src").textContent = `EIA-930 · ${ev ? ev.ba : ""} · hour ending ${isoClock(d.hour_ending)}`;
    $("s-needed").textContent = gw(d.forecast_mw); $("s-needed-src").textContent = "the operator's day-ahead forecast";
    $("s-mac").textContent = d.ours_w == null ? "—" : `${fixed(d.ours_w, 1)} W`;
    const cut = d.measured_cut_pct;
    $("s-mac-src").textContent = d.nothing_to_shed ? "nothing running to shed" : cut != null
      ? `${fixed(Math.abs(cut), 0)}% ${cut >= 0 ? "below" : "above"} its baseline · measured` : "measured by powermetrics";
    if (sc && sc.people != null) { $("s-impact").textContent = compact(sc.people); $("s-impact-k").textContent = `${sc.people_unit} kept on`; }
    else if (sc) { $("s-impact").textContent = `${fixed(sc.freed_mw, 0)} MW`; $("s-impact-k").textContent = "freed at grid scale"; }
    else { $("s-impact").textContent = "—"; $("s-impact-k").textContent = "at grid scale"; }
    $("s-impact-src").textContent = sc ? `estimate · ${fixed(sc.share_pct, 0)}% cut asked, on ${gw(sc.flexible_mw)}` : "appears once this Mac cuts";
    if (ev) {
      const withText = sc
        ? `${sc.people != null ? `${compact(sc.people)} ${sc.people_unit} kept on: ` : ""}${fixed(sc.freed_mw, 0)} MW freed${sc.share_of_shed_pct != null ? `, ${fixed(sc.share_of_shed_pct, 0)}% of the ${fixed(ev.shed_mw, 0)} MW it had to find` : ""}`
        : waitingText(d.asked_cut_pct, d.nothing_to_shed);
      versus(ev.impact.slice(0, 2).map((i) => i.text).join(". "), withText, ev.impact[0].source,
        sc ? `estimate · this Mac's measured cut, as far as asked (${fixed(sc.share_pct, 0)}%), on ${gw(sc.flexible_mw)} of ${sc.flexible_source}` : "measured on this Mac, live");
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
    with_mw: null, city: null,
    campus: D.scale ? { title: "ERCOT large loads", value: gw(D.scale.large_loads_running_mw), sub: "running, Sep 2026 (cited)" } : null });
  if (live) {
    $("w-clock").textContent = g ? `Live · ${g.iso} · ${localClock(nowS())}` : "Live · waiting for the grid feed";
    $("w-progress").style.width = "0%";
    $("w-head").textContent = "Pick a real emergency to replay it, or click any part of the grid to break it.";
  } else if (ev) {
    $("w-clock").textContent = `${ev.title} · ${ev.when}`;
    $("w-progress").style.width = "0%";
    $("w-head").textContent = ev.iso === "ERCOT" && D.scale && D.scale.demand_mw
      ? `Texas right now: ERCOT is serving ${gw(D.scale.demand_mw)} (live). Press play to run ${ev.when} through the same software.`
      : `Press play: the hours are fetched live from the U.S. EIA and run through the software one hour at a time.`;
  }
  $("s-served").textContent = gw(served); $("s-served-src").textContent = g ? `${g.iso} fuel mix, live` : "";
  $("s-needed").textContent = gw(needed); $("s-needed-src").textContent = needed ? `${g.iso} load forecast` : "no forecast for this hour";
  $("s-mac").textContent = p ? `${fixed(p.combined_w, 1)} W` : "—";
  $("s-mac-src").textContent = p ? `measured by powermetrics · ${age(p.t)}` : "waiting for the meter";
  $("s-impact").textContent = D.scale ? `${fixed(D.scale.freed_mw, 0)} MW` : "—";
  $("s-impact-k").textContent = "ERCOT, if large loads cut like this Mac";
  $("s-impact-src").textContent = D.scale ? `estimate · ${fixed(D.scale.share_of_demand_pct, 1)}% of ERCOT now` : "estimate";
  setHTML($("w-sources"), html`Live grid data: ${g ? g.iso : "—"} via gridstatus. This Mac: macOS powermetrics. Detail and every graph: <a href="/info.html">Info</a>.`);
  overlayFault();
}

// In the city map, the footer says what is real and what is drawn.
function citySources() {
  if (!D.city) return;
  setHTML($("w-sources"), html`${D.city.name}: hospitals are real places, ${D.city.license}, fetched ${String(D.city.fetched_at).slice(0, 10)}. Homes lit: the grid's real served over needed. Substations, feeders and blocks: an illustrative layout. Dark blocks rotate, as rotating outages do.`);
}

// A judge's what-if on top of whatever the world shows: the broken part, the grid's real numbers after it, our cut.
function overlayFault() {
  citySources();
  if (!faulted()) { World.set({ tripped: null, tripped_mw: null, fault: null }); return; }
  const w = D.whatif, sc = w.scale;
  World.set({ tripped: w.target === "city" ? null : w.fuel, tripped_mw: w.lost_mw, fault: w.target, served: w.served_after, needed: w.needed_after,
    alert: w.shortfall_mw > 0 ? "emergency" : null, with_mw: sc ? sc.freed_mw : null, ours_w: w.ours_w, baseline_w: w.baseline_w,
    cut_pct: w.measured_cut_pct });
  $("s-served").textContent = gw(w.served_after);
  $("s-served-src").textContent = `what-if: ${w.lost_mw ? `−${gw(w.lost_mw)}` : "no supply lost"} from ${w.source}`;
  $("s-needed").textContent = gw(w.needed_after);
  $("s-needed-src").textContent = w.surge_mw ? `what-if: +${gw(w.surge_mw)}, the published forecast peak` : "the operator's forecast";
  if (sc) {
    $("s-impact").textContent = `${fixed(sc.freed_mw, 0)} MW`; $("s-impact-k").textContent = "freed at grid scale";
    $("s-impact-src").textContent = `estimate · ${fixed(sc.share_of_shortfall_pct, 1)}% of the shortfall`;
  }
  $("w-head").textContent = `${w.label}. ${Math.round(w.remaining_s)} s left.`;
  versus(w.shortfall_mw > 0 ? `The grid is ${gw(w.shortfall_mw)} short: that much demand goes unserved` : "The grid still covers demand: nothing is shed",
    sc ? `${sc.people != null ? `${compact(sc.people)} ${sc.people_unit} kept on: ` : ""}${fixed(sc.freed_mw, 0)} MW freed by data centers cutting like this Mac, ${fixed(sc.share_of_shortfall_pct, 1)}% of the gap`
      : w.asked_cut_pct ? waitingText(w.asked_cut_pct, w.nothing_to_shed) : "No cut needed",
    `arithmetic on ${w.source}`, sc ? `estimate · this Mac's measured cut on ${gw(sc.flexible_mw)} of ${sc.flexible_source}` : "measured on this Mac, live");
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
function openCity(city) { D.city = city; World.openCity(city); $("w-back").hidden = false; render(); }
function closeCity() { D.city = null; World.closeCity(); $("w-back").hidden = true; render(); }
$("w-back").addEventListener("click", closeCity);

// ---------------------------------------------------------------- breaking a part: a confirm card, then the server
function openPop(title, text, buttons, pt, words) {
  $("w-pop-t").textContent = title; $("w-pop-p").textContent = text;
  $("w-pop-f").hidden = !words; $("w-pop-read").textContent = ""; $("w-pop-read").className = ""; $("w-pop-in").value = "";
  POP.words = words || null;
  const box = $("w-pop-b");
  box.replaceChildren();
  for (const [label, cls, fn] of buttons) {
    const b = document.createElement("button");
    b.type = "button"; b.className = cls; b.textContent = label; b.addEventListener("click", fn);
    box.append(b);
  }
  const pop = $("w-pop");
  pop.hidden = false;
  const r = pop.getBoundingClientRect();
  pop.style.left = `${Math.max(16, Math.min(innerWidth - r.width - 16, pt.x - r.width / 2))}px`;
  pop.style.top = `${Math.max(76, Math.min(innerHeight - r.height - 16, pt.y - r.height - 14))}px`;
  (words ? $("w-pop-in") : box.firstChild).focus();
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
  const ts = World.targets().filter((t) => t.id.startsWith("plant:"));
  const big = ts.reduce((a, b) => (b.mw > (a ? a.mw : 0) ? b : a), null);
  const card = h.id.startsWith("plant:")
    ? [`Trip the ${h.title.toLowerCase()} fleet?`, `What-if: the grid loses its real output at this moment, ${gw(h.mw)}. Griddy reacts live; this Mac's watts are measured.`, "Trip it"]
    : h.id === "hub"
      ? ["Fail the main substation?", `What-if: it cuts off the largest fleet${big ? `, ${big.title.toLowerCase()} (${gw(big.mw)}, its real output)` : ""}. Griddy reacts live.`, "Fail it"]
      : [`Surge demand in ${h.title === "City" ? "the city" : h.title}?`, "What-if: demand jumps to the highest forecast for the rest of today, the operator's real published forecast. Griddy reacts live.", "Surge it"];
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

World.onPick((h, pt) => confirmBreak(h, pt));
$("w-break-btn").addEventListener("click", async (e) => {
  if (faulted()) { await postJSON("/api/whatif", { target: "clear", who: "judge" }); D.whatif = null; render(); return; }
  const r = e.currentTarget.getBoundingClientRect();
  openPop("Break a part of the grid", "What-if: the fault is invented, its size is real, taken from the grid at this moment.",
    [...World.targets().map((t) => [t.mw ? `${t.title} · ${gw(t.mw)}` : t.title, "", () => confirmBreak(t, { x: r.left + r.width / 2, y: r.top })]),
      ["Cancel", "", closePop]], { x: r.left + r.width / 2, y: r.top }, { target: null });
});
document.addEventListener("keydown", (e) => { if (e.key !== "Escape") return; if (!$("w-pop").hidden) closePop(); else if (D.city) closeCity(); });
document.addEventListener("pointerdown", (e) => { if (!$("w-pop").hidden && !e.target.closest("#w-pop, #w-break-btn")) closePop(); });

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
setInterval(render, 1000);
connectWS(handle, $("conn"));

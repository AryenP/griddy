// The live load trace: measured machine watts (macOS powermetrics, 1 Hz) against the utility's cap, with
// the current plan's watts and the moments that changed the plan. The dashboard's centrepiece.
// Points come from the snapshot's power_history and each `power` event. A gap longer than GAP_S stays a
// gap: nothing is drawn for seconds nobody measured. The one thing computed here is the 10-s trailing mean
// that says "within" or "over" the cap, the rule agent/reporter.py uses; receipts carry the official figure.
"use strict";

const TRACE = { pts: [], marks: [], windowS: 300, keepS: 3600, hoverT: null };
const GAP_S = 5, ROLL_S = 10;

function traceSeed(hist) {
  TRACE.pts = (hist || []).map(([t, w]) => [Number(t), Number(w)])
    .filter(([t, w]) => isFinite(t) && isFinite(w)).sort((a, b) => a[0] - b[0]);
}

function traceAdd(t, w) {
  const p = TRACE.pts;
  if (!isFinite(t) || !isFinite(w) || (p.length && t <= p[p.length - 1][0])) return;
  p.push([t, w]);
  const cut = t - TRACE.keepS;
  while (p.length && p[0][0] < cut) p.shift();
}

// The same second measured again with the laptops added (fleet_power): replace, never add a second point.
function traceSet(t, w) {
  const p = TRACE.pts;
  if (p.length && p[p.length - 1][0] === t) p[p.length - 1][1] = w; else traceAdd(t, w);
}

// A moment worth marking on the trace: a cap arriving, a knob moving, an owner's answer, a re-plan.
function traceMark(t, text, tone) {
  if (!isFinite(t)) return;
  TRACE.marks.push({ t, text, tone: tone || "" });
  if (TRACE.marks.length > 200) TRACE.marks.shift();
}

// Cap windows [{start, end, w}] from CapEvents (target_w resolved by the executor) and a standing policy cap.
function capBands(events, policy) {
  const out = (events || []).filter((e) => e.target_w != null && e.start).map((e) => {
    const s = Date.parse(e.start) / 1000;
    return { start: s, end: s + e.duration_s, w: e.target_w, id: e.id };
  });
  if (policy && policy.power_cap_w != null) out.push({ start: -Infinity, end: Infinity, w: policy.power_cap_w, id: "policy" });
  return out.sort((a, b) => a.start - b.start);
}
const bandAt = (bands, t) => bands.find((b) => b.start <= t && t < b.end) || null;

// [t, mean of the samples in (t - ROLL_S, t]] for every sample at or after fromT.
function rollingMeans(fromT) {
  const p = TRACE.pts, out = [];
  let lo = 0, sum = 0;
  for (let hi = 0; hi < p.length; hi++) {
    sum += p[hi][1];
    while (p[lo][0] <= p[hi][0] - ROLL_S) { sum -= p[lo][1]; lo++; }
    if (p[hi][0] >= fromT) out.push([p[hi][0], sum / (hi - lo + 1)]);
  }
  return out;
}

// The reporter's baseline (agent/reporter.py BASELINE_S): the mean measured watts in the 60 s before the cap.
const BASELINE_S = 60;
function preCapBaseline(start) {
  const xs = TRACE.pts.filter(([t]) => t >= start - BASELINE_S && t < start).map(([, w]) => w);
  return xs.length >= BASELINE_S / 2 ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

// The cap as the meter sees it now. null band = no cap in force. `ttc`: seconds from the cap's start to the
// first 10-s mean at or under it; `overSince`: when the 10-s mean last went over (if it is over now).
function capStatus(bands, now) {
  const last = TRACE.pts.length ? TRACE.pts[TRACE.pts.length - 1] : null;
  const band = bandAt(bands, now);
  if (!band) return { band: null, last };
  const start = isFinite(band.start) ? band.start : null;
  const r = rollingMeans(start != null ? start : now - TRACE.keepS);
  const fresh = r.length && now - r[r.length - 1][0] <= GAP_S ? r[r.length - 1][1] : null;
  let ttc = null, overSince = null;
  if (start != null) {
    const hit = r.find(([t, m]) => t > start && m <= band.w);
    ttc = hit ? hit[0] - start : null;
  }
  if (fresh != null && fresh > band.w) {
    overSince = start;
    for (let i = r.length - 1; i >= 0; i--) if (r[i][1] <= band.w) { overSince = r[i][0]; break; }
  }
  return { band, mean: fresh, ttc, overSince, last };
}

function niceStep(max) {
  for (const s of [1, 2, 5, 10, 20, 50, 100, 200]) if (max / s <= 6) return s;
  return 500;
}

// Draw into `box` (an element with a height). `sc`: the current Schedule, for the plan line, drawn only from
// the moment that schedule was solved: an older stretch of the trace ran under an older plan.
function drawLoadTrace(box, bands, sc) {
  const Wd = Math.max(280, Math.round(box.clientWidth)), Ht = Math.max(180, Math.round(box.clientHeight));
  const pad = { l: 46, r: 14, t: 26, b: 26 };
  const now = nowS(), span = TRACE.windowS, t0 = now - span;
  const pts = TRACE.pts.filter(([t]) => t >= t0 - GAP_S);
  const vis = bands.filter((b) => b.end > t0 && b.start < now);
  const plan = [];
  if (sc && sc.planned_w) {
    const from = Math.max(t0, sc.solve_t || t0);
    sc.slots.forEach((s, i) => {
      const a = Date.parse(s) / 1000, e = a + sc.slot_minutes * 60;
      if (e > from && a < now && sc.planned_w[i] != null) plan.push({ a: Math.max(a, from), e: Math.min(e, now), w: sc.planned_w[i] });
    });
  }
  const top = Math.max(5, ...pts.map(([, w]) => w), ...vis.map((b) => b.w), ...plan.map((p) => p.w)) * 1.12;
  const step = niceStep(top), ymax = Math.ceil(top / step) * step;
  const x = (t) => pad.l + ((t - t0) / span) * (Wd - pad.l - pad.r);
  const y = (w) => pad.t + (1 - w / ymax) * (Ht - pad.t - pad.b);
  const f = (v) => v.toFixed(1);

  // measured: one path per run of samples without a gap, plus the area under it
  const runs = [];
  pts.forEach(([t, w], i) => {
    if (!i || t - pts[i - 1][0] > GAP_S) runs.push([]);
    runs[runs.length - 1].push([Math.max(t, t0), w]);
  });
  const line = runs.map((r) => "M" + r.map(([t, w]) => `${f(x(t))} ${f(y(w))}`).join(" L")).join(" ");
  const area = runs.filter((r) => r.length > 1).map((r) =>
    `M${f(x(r[0][0]))} ${f(y(0))} L` + r.map(([t, w]) => `${f(x(t))} ${f(y(w))}`).join(" L") + ` L${f(x(r[r.length - 1][0]))} ${f(y(0))} Z`).join(" ");

  const grid = [];
  for (let w = 0; w <= ymax + 1e-9; w += step) {
    grid.push(html`<line class="t-grid" x1="${pad.l}" x2="${Wd - pad.r}" y1="${f(y(w))}" y2="${f(y(w))}"/>
      <text class="t-axis" x="${pad.l - 8}" y="${f(y(w) + 4)}" text-anchor="end">${w} W</text>`);
  }
  const tick = span <= 300 ? 60 : span <= 900 ? 180 : 600;
  for (let t = Math.ceil(t0 / tick) * tick; t <= now; t += tick) {
    grid.push(html`<line class="t-grid t-v" x1="${f(x(t))}" x2="${f(x(t))}" y1="${pad.t}" y2="${f(y(0))}"/>
      <text class="t-axis" x="${f(x(t))}" y="${Ht - 6}" text-anchor="middle">${localClock(t).slice(0, 5)}</text>`);
  }

  const clips = vis.map((b) => html`<rect x="${f(x(Math.max(b.start, t0)))}" y="0" width="${f(Math.max(0, x(Math.min(b.end, now)) - x(Math.max(b.start, t0))))}" height="${f(y(b.w))}"/>`);
  const caps = vis.map((b) => {
    const xa = x(Math.max(b.start, t0)), xe = x(Math.min(b.end, now));
    const label = `cap ${fixed(b.w, 1)} W`;
    const narrow = xe - xa < 90;              // a cap that just began: label it to the left of its start
    return html`<line class="t-cap" x1="${f(xa)}" x2="${f(xe)}" y1="${f(y(b.w))}" y2="${f(y(b.w))}"/>
      ${b.start > t0 ? html`<line class="t-cap-edge" x1="${f(xa)}" x2="${f(xa)}" y1="${pad.t}" y2="${f(y(0))}"/>` : ""}
      <text class="t-cap-label" x="${f(narrow ? xa - 6 : xa + 6)}" y="${f(y(b.w) - 7)}" text-anchor="${narrow ? "end" : "start"}">${label}</text>`;
  });
  const planD = plan.map((p) => `M${f(x(p.a))} ${f(y(p.w))} L${f(x(p.e))} ${f(y(p.w))}`).join(" ");

  let lastLabel = -Infinity;
  const marks = TRACE.marks.filter((m) => m.t >= t0 && m.t <= now).map((m) => {
    const mx = x(m.t), show = mx - lastLabel > 120;
    if (show) lastLabel = mx;
    const short = m.text.length > 22 ? m.text.slice(0, 21) + "…" : m.text;
    return html`<g class="t-mark ${m.tone}"><title>${localClock(m.t)} ${m.text}</title>
      <line x1="${f(mx)}" x2="${f(mx)}" y1="${pad.t - 4}" y2="${f(y(0))}"/>
      ${show ? html`<text x="${f(mx + 4)}" y="${pad.t - 10}">${short}</text>` : ""}</g>`;
  });

  const last = pts.length ? pts[pts.length - 1] : null;
  const label = last ? `Measured power over the last ${dur(span)}: now ${fixed(last[1], 1)} W` +
    (vis.length ? `, cap ${fixed(vis[vis.length - 1].w, 1)} W` : ", no cap in force") : "No measured power yet";
  setHTML(box.querySelector(".d-plot"), html`<svg viewBox="0 0 ${Wd} ${Ht}" width="${Wd}" height="${Ht}" role="img" aria-label="${label}">
    <defs><clipPath id="t-over-cap">${clips}</clipPath></defs>
    ${grid}
    ${area ? html`<path class="t-area" d="${area}"/>` : ""}
    ${area && clips.length ? html`<path class="t-over" d="${area}" clip-path="url(#t-over-cap)"/>` : ""}
    ${planD ? html`<path class="t-plan" d="${planD}"/>` : ""}
    ${caps}
    ${line ? html`<path class="t-meas" d="${line}"/>` : ""}
    ${last && last[0] >= t0 ? html`<circle class="t-dot" cx="${f(x(last[0]))}" cy="${f(y(last[1]))}" r="4"/>` : ""}
    ${marks}
    ${pts.length ? "" : html`<text class="t-empty" x="${Wd / 2}" y="${Ht / 2}" text-anchor="middle">waiting for the first powermetrics sample</text>`}
  </svg>`);
  TRACE.geom = { t0, span, pad, Wd, ymax, Ht, x, y, plan, vis };
  drawLoadHover(box);
}

// Crosshair readout for the time under the pointer: the measured sample nearest it, the plan and the cap then.
function drawLoadHover(box) {
  const hov = box.querySelector(".d-hover"), g = TRACE.geom;
  if (TRACE.hoverT == null || !g || !TRACE.pts.length) { hov.hidden = true; return; }
  const p = TRACE.pts;
  let lo = 0, hi = p.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (p[mid][0] < TRACE.hoverT) lo = mid + 1; else hi = mid; }
  const near = lo > 0 && Math.abs(p[lo - 1][0] - TRACE.hoverT) < Math.abs(p[lo][0] - TRACE.hoverT) ? p[lo - 1] : p[lo];
  if (Math.abs(near[0] - TRACE.hoverT) > GAP_S || near[0] < g.t0) { hov.hidden = true; return; }
  const plan = g.plan.find((s) => s.a <= near[0] && near[0] < s.e);
  const cap = g.vis.find((b) => b.start <= near[0] && near[0] < b.end);
  const parts = [`${localClock(near[0])}`, `measured ${fixed(near[1], 1)} W`];
  if (plan) parts.push(`plan ${fixed(plan.w, 1)} W`);
  if (cap) parts.push(`cap ${fixed(cap.w, 1)} W` + (near[1] > cap.w ? `, over by ${fixed(near[1] - cap.w, 1)}` : ""));
  hov.hidden = false;
  hov.style.left = `${g.x(near[0])}px`;
  hov.querySelector(".d-hover-text").textContent = parts.join(" · ");
  hov.classList.toggle("flip", g.x(near[0]) > g.Wd * 0.6);
}

function bindLoadTrace(box, redraw) {
  const plot = box.querySelector(".d-plot");
  const at = (clientX) => {
    const g = TRACE.geom;
    if (!g) return null;
    const px = clientX - plot.getBoundingClientRect().left;
    return g.t0 + ((px - g.pad.l) / (g.Wd - g.pad.l - g.pad.r)) * g.span;
  };
  plot.addEventListener("pointermove", (e) => { TRACE.hoverT = at(e.clientX); drawLoadHover(box); });
  plot.addEventListener("pointerleave", () => { TRACE.hoverT = null; drawLoadHover(box); });
  let pending = null;
  new ResizeObserver(() => { clearTimeout(pending); pending = setTimeout(redraw, 80); }).observe(box);
}

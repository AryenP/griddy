// The 24-hour dispatch map. One grid, one column per 15-minute slot:
//   price (and carbon) on top, hour marks, cap windows with their W limit, one row per job
//   (colour = job, bright solid = runs on GPU, hatched = runs on CPU, recessed = deferred), and the plan's
//   watts (calibrated, not measured) against the cap, with the measured load outside the plan hatched at the
//   foot of each bar. The current slot is outlined through every row; a pinned slot gets its own outline and
//   the inspector beside the map explains it. Every cell carries data-slot so a click or a key can pin it.
// Everything comes from the Schedule and GridSignal as the server sent them; nothing is interpolated.
"use strict";

const MAP_JOB_COLOR = { chat: "var(--job-chat)", train: "var(--job-train)", batch: "var(--job-batch)" };

function mapSeries(slots, pts) {
  const m = new Map((pts || []).map(([t, v]) => [Date.parse(t), v]));
  return slots.map((s) => m.get(Date.parse(s)) ?? null);
}

// A stepped line through n columns in a 0..n x 0..H box; null values break the line.
function stepPath(vals, lo, hi, H) {
  const y = (v) => (hi === lo ? H / 2 : H - 3 - ((v - lo) / (hi - lo)) * (H - 6));
  let d = "", open = false;
  vals.forEach((v, i) => {
    if (v == null) { open = false; return; }
    const yy = y(v).toFixed(2);
    d += open ? ` L${i} ${yy} L${i + 1} ${yy}` : ` M${i} ${yy} L${i + 1} ${yy}`;
    open = true;
  });
  return d.trim();
}

function mapCapBands(caps) {
  const bands = [];
  caps.forEach((c, i) => {
    const last = bands[bands.length - 1];
    if (c == null) return;
    if (last && last.end === i && Math.abs(last.w - c) < 1e-6) last.end = i + 1;
    else bands.push({ start: i, end: i + 1, w: c });
  });
  return bands;
}

// The solver's facts that name a job (dispatcher/schedule.py words them "train runs ...", "batch paused ...").
function jobFacts(sc, job) {
  return sc.explanations.filter((e) => e.startsWith(`${job} `) || e.includes(` ${job} `));
}

function slotTip(sc, job, i, price) {
  const a = sc.assignments[job][i];
  const parts = [`${job} · ${isoLabel(sc.slots[i])}: ` + (a.run ? `runs on ${a.device}${a.concurrency ? ` at concurrency ${a.concurrency}` : ""}` : "deferred")];
  if (price[i] != null) parts.push(`price $${sig(price[i], 4)}/MWh`);
  if (sc.caps_w[i] != null) parts.push(`cap ${fixed(sc.caps_w[i], 1)} W`);
  return parts.join(" · ") + " · click to pin";
}

// box: the #map element; sel: the pinned slot index or null. Returns the current slot index (or -1).
function renderMap(box, sc, g, sel) {
  if (!sc) {
    setHTML(box, html`<p class="empty">no schedule yet: the map appears when the solver publishes one</p>`);
    return -1;
  }
  const n = sc.slots.length;
  const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
  const price = g ? mapSeries(sc.slots, g.price_curve) : new Array(n).fill(null);
  const carbon = g ? mapSeries(sc.slots, g.carbon_curve) : new Array(n).fill(null);
  const pv = price.filter((v) => v != null), cv = carbon.filter((v) => v != null);
  const H = 48;
  // Every item gets an explicit row: an explicitly placed marker would otherwise push auto-placed rows down.
  const col = (i, span = 1, r) => `grid-column:${i + 2} / span ${span};grid-row:${r}`;
  const lab = (r) => `grid-row:${r}`;
  let r = 1;

  const priceRow = html`<div class="map-label" style="${lab(r)}">price<div class="map-scale">${pv.length ? `$${sig(Math.min(...pv), 3)}–${sig(Math.max(...pv), 3)}` : "no feed"}</div></div>
    <div class="map-curve" style="${col(0, n, r)}">${pv.length ? html`<svg viewBox="0 0 ${n} ${H}" preserveAspectRatio="none" aria-label="price per slot">
        ${cv.length && Math.max(...cv) > Math.min(...cv) ? html`<path class="carbon" d="${stepPath(carbon, Math.min(...cv), Math.max(...cv), H)}"/>` : ""}
        <path class="price" d="${stepPath(price, Math.min(...pv), Math.max(...pv), H)}"/></svg>` : html`<span class="empty">no price curve yet</span>`}</div>`;

  // hour marks every 3 h, in the ISO's local clock
  r += 1;
  const hourRow = r;
  const hours = sc.slots.map((s, i) => {
    const m = /T(\d\d):00/.exec(s);
    if (!m || Number(m[1]) % 3) return "";
    // the day only at midnight; on a phone only every 6 h (class h6) so the labels do not collide
    return html`<span class="map-hour${Number(m[1]) % 6 ? "" : " h6"}" style="${col(i, 1, hourRow)}">${m[1] === "00" ? isoLabel(s) : isoClock(s)}</span>`;
  });

  const bands = mapCapBands(sc.caps_w);
  if (bands.length) r += 1;
  const capR = r;
  const capRow = bands.length ? html`<div class="map-label" style="${lab(capR)}">cap</div>${bands.map((b) =>
    html`<div class="map-cap" data-slot="${b.start}" style="${col(b.start, b.end - b.start, capR)}" title="${`cap ${fixed(b.w, 1)} W, ${isoLabel(sc.slots[b.start])} for ${dur((b.end - b.start) * sc.slot_minutes * 60)}`}"><span>${fixed(b.w, 1)} W</span></div>`)}` : "";

  const jobRows = Object.keys(sc.assignments).map((job) => {
    const row = sc.assignments[job];
    const runs = row.filter((x) => x.run).length;
    const jr = (r += 1);
    return html`<div class="map-label" style="${lab(jr)};--c:${MAP_JOB_COLOR[job] || "var(--text)"}"><b>${job}</b><div class="map-scale">${runs}/${n} slots</div></div>
      ${row.map((a, i) => html`<div class="map-cell ${a.run ? `run-${a.device || "gpu"}` : "off"}" data-slot="${i}" style="${col(i, 1, jr)};--c:${MAP_JOB_COLOR[job] || "var(--text)"}" title="${slotTip(sc, job, i, price)}"></div>`)}`;
  });

  const maxW = Math.max(1, ...sc.planned_w, ...sc.caps_w.filter((c) => c != null));
  const bg = sc.background_w || 0;
  if (sc.planned_w.length) r += 1;
  const planR = r;
  const planRow = sc.planned_w.length ? html`<div class="map-label" style="${lab(planR)}">plan W<div class="map-scale">${bg ? "hatched: outside the plan" : "calibrated"}</div></div>
    ${sc.planned_w.map((w, i) => {
      const over = sc.caps_w[i] != null && w > sc.caps_w[i] + 1e-6;
      const tip = `${isoLabel(sc.slots[i])}: planned ${fixed(w, 1)} W` + (bg ? `, of which ${fixed(bg, 1)} W measured outside the plan` : "") +
        (sc.caps_w[i] != null ? ` vs cap ${fixed(sc.caps_w[i], 1)} W` : "") + " (calibrated, not measured)";
      return html`<div class="map-bar${over ? " over" : ""}" data-slot="${i}" style="${col(i, 1, planR)}" title="${tip}"><i class="${bg ? "has-bg" : ""}" style="height:${Math.max(4, (100 * w) / maxW).toFixed(1)}%;--bgp:${w > 0 ? ((100 * Math.min(bg, w)) / w).toFixed(1) : 0}%"></i></div>`;
    })}` : "";

  const now = cur >= 0 ? html`<div class="map-now" style="grid-column:${cur + 2};grid-row:1 / span ${r}" aria-label="current slot"></div>` : "";
  const pin = sel != null && sel !== cur && sel >= 0 && sel < n
    ? html`<div class="map-pin" style="grid-column:${sel + 2};grid-row:1 / span ${r}" aria-label="pinned slot"></div>` : "";
  setHTML(box, html`<div class="map-grid" style="--n:${n}">${priceRow}<div class="map-label" style="${lab(hourRow)}"></div>${hours}${capRow}${jobRows}${planRow}${now}${pin}</div>`);
  return cur;
}

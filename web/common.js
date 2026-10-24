// Shared by every page: escaping, formatting, the HTTP/WebSocket calls (HANDOFF.md contract).
// The only innerHTML write in web/ is setHTML(), and it accepts only html`...` output, whose
// interpolations are escaped. So text from the server can reach the DOM only escaped or as textContent.
"use strict";

const $ = (id) => document.getElementById(id);

// ---------- escaping ----------
class SafeHTML { constructor(s) { this.s = s; } toString() { return this.s; } }
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ESC[c]); }
function htmlPart(v) {
  if (v instanceof SafeHTML) return v.s;
  if (Array.isArray(v)) return v.map(htmlPart).join("");
  if (v == null || v === false) return "";
  return esc(v);
}
// Tagged template: html`<b>${text}</b>` escapes every interpolation; nested html`` and arrays of them pass through.
function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => { out += htmlPart(v) + strings[i + 1]; });
  return new SafeHTML(out);
}
function setHTML(el, safe) {
  if (!(safe instanceof SafeHTML)) throw new TypeError("setHTML takes html`...` only");
  el.innerHTML = safe.s;
}

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
function fixed(x, n) { return x == null || !isFinite(x) ? "—" : Number(x).toFixed(n); }
function dur(s) {
  if (s == null || !isFinite(s)) return "—";
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return r ? `${m}:${String(r).padStart(2, "0")} min` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}
// Slot times are ISO-8601 in the ISO's local time ("2026-10-24T14:00:00-07:00"); show that clock, not the browser's.
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function isoClock(s) { return s ? String(s).slice(11, 16) : "—"; }
function isoDay(s) {
  const [y, m, d] = String(s).slice(0, 10).split("-").map(Number);
  return DAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}
function isoLabel(s) { return s ? `${isoDay(s)} ${isoClock(s)}` : "—"; }
function localClock(t) { return new Date(t * 1000).toLocaleTimeString([], { hour12: false }); }
function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + "s"}`; }

// ---------- HTTP ----------
// Both return {ok, status, data, error}; a 404 means the route is not wired on the server yet.
async function call(method, path, body) {
  try {
    const opt = { method, headers: {} };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    if (!r.ok) {
      const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : text.slice(0, 200);
      return { ok: false, status: r.status, data, error: `${r.status} ${detail}` };
    }
    return { ok: true, status: r.status, data, error: null };
  } catch (e) {
    return { ok: false, status: 0, data: null, error: `server unreachable (${e.message})` };
  }
}
const getJSON = (path) => call("GET", path);
const postJSON = (path, body) => call("POST", path, body);
// "not available yet: /api/report" for a route machine 1 has not wired; the error otherwise.
function routeError(path, r) { return r.status === 404 && !(r.data && typeof r.data.detail === "string" && r.data.detail !== "Not Found") ? `not available yet: ${path}` : `${path}: ${r.error}`; }

// ---------- WebSocket ----------
// One /ws per page: a snapshot first, then every timeline event. Reconnects with backoff.
function connectWS(onMsg, badge) {
  let backoff = 500;
  const open = () => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { backoff = 500; if (badge) { badge.textContent = "live"; badge.className = "badge ok"; } };
    ws.onmessage = (e) => onMsg(JSON.parse(e.data));
    ws.onclose = () => {
      if (badge) { badge.textContent = "disconnected: reconnecting"; badge.className = "badge bad"; }
      setTimeout(open, backoff); backoff = Math.min(backoff * 2, 8000);
    };
  };
  open();
}

// ---------- schedule facts shared by the pages ----------
function currentSlotIndex(slots, minutes) {
  const t = Date.now();
  return slots.findIndex((s) => { const a = Date.parse(s); return t >= a && t < a + minutes * 60000; });
}
// One line saying what a schedule does with a job (or, for "power_cap", with the cap). Facts only.
function jobPlanLine(sc, jobId) {
  if (!sc) return "no schedule yet";
  if (jobId === "power_cap") {
    const capped = sc.caps_w.map((c, i) => [c, sc.planned_w[i]]).filter(([c]) => c != null);
    if (!capped.length) return `schedule ${sc.id}: no cap in the horizon`;
    const over = capped.filter(([c, w]) => w > c + 1e-6);
    const worst = Math.max(...capped.map(([c, w]) => w - c));
    return over.length
      ? `schedule ${sc.id}: planned ${sig(worst)} W over the cap in ${plural(over.length, "slot")} of ${capped.length} capped`
      : `schedule ${sc.id}: planned under the cap in all ${plural(capped.length, "capped slot")}`;
  }
  const row = sc.assignments[jobId];
  if (!row) return `schedule ${sc.id}: ${jobId} not in it`;
  const runs = row.map((x, i) => (x.run ? i : -1)).filter((i) => i >= 0);
  const miss = sc.deadline_misses.find((m) => m.job_id === jobId);
  const parts = [`schedule ${sc.id}: ${plural(runs.length, "slot")} of ${row.length} planned`];
  if (runs.length) {
    const cur = currentSlotIndex(sc.slots, sc.slot_minutes);
    const next = runs.find((i) => i >= Math.max(cur, 0));
    if (cur >= 0 && row[cur].run) parts.push(`running now on ${row[cur].device}`);
    else if (next != null) parts.push(`next run ${isoLabel(sc.slots[next])} on ${row[next].device}`);
    const last = runs[runs.length - 1];
    parts.push(`last planned slot ends ${slotEndLabel(sc, last)}`);
  }
  if (miss) parts.push(`MISSES deadline ${isoLabel(miss.deadline)} by ${miss.slip_min} min` + (miss.finishes_at ? ` (finishes ${isoLabel(miss.finishes_at)})` : ""));
  return parts.join(" · ");
}

// The "last planned slot ends" clock in the ISO's offset, not UTC: rebuild it from the slot strings.
function slotEndLabel(sc, i) {
  const start = sc.slots[i];
  const off = String(start).slice(19);                       // "-07:00" or "Z"
  const ms = Date.parse(start) + sc.slot_minutes * 60000;
  const m = /^([+-])(\d\d):(\d\d)$/.exec(off);
  const offMin = m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : 0;
  const local = new Date(ms + offMin * 60000).toISOString().slice(0, 16);
  return isoLabel(local + ":00" + (m ? off : "Z"));
}

// The solver's "running plan: ..." fact (dispatcher/solve.py) when the cap cannot be met as asked. While an
// approval is pending and the cap is held, say so in plain words (DECISIONS 02:55). null when there is none.
function runningPlanLine(sc, plan) {
  const fact = sc && sc.explanations.find((e) => e.startsWith("running plan: "));
  if (!fact) return null;
  const mode = fact.slice("running plan: ".length);
  const waiting = plan && plan.needs_approval && plan.needs_approval.length;
  return mode.startsWith("cap held") && waiting ? `Cap held while the operator decides (${mode})` : `Running plan: ${mode}`;
}

// Keyboard shortcuts that never fire while typing in a box.
function hotkeys(map) {
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target && e.target.tagName) || "";
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable)) return;
    const fn = map[e.key.toLowerCase()];
    if (fn) { e.preventDefault(); fn(); }
  });
}

// ---------- live parts (the Brownout design system kit) ----------
// Motion only shows change: digits roll to a new reading, a panel's corner ticks flare when its data lands,
// the 3D scene's current flows at the measured watts. All of it stops under prefers-reduced-motion.
const REDUCED_MOTION = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

// Flare a .panel's corner ticks when fresh data lands in it.
function pulsePanel(el) {
  if (!el || REDUCED_MOTION) return;
  el.classList.remove("pulse");
  void el.offsetWidth;
  el.classList.add("pulse");
  clearTimeout(el._pulse);
  el._pulse = setTimeout(() => el.classList.remove("pulse"), 550);
}

// A number whose digits roll to their new value. set(v, {tone, text}) where tone is live | over | stale | null;
// `text` replaces the number with words ("never", "—"). A screen-reader copy stays in sync.
function readout(el, { unit = "", decimals = 1 } = {}) {
  el.classList.add("ro");
  el.replaceChildren();
  const sr = document.createElement("span"); sr.className = "src-only"; sr.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)";
  const num = document.createElement("span"); num.className = "ro-num"; num.setAttribute("aria-hidden", "true");
  const u = document.createElement("span"); u.className = "ro-unit"; u.setAttribute("aria-hidden", "true"); u.textContent = unit;
  el.append(sr, num, u);
  let shape = "", last = null;
  const build = (s) => {
    num.replaceChildren(...[...s].map((ch) => {
      if (ch < "0" || ch > "9") { const c = document.createElement("span"); c.className = "ro-c"; c.textContent = ch; return c; }
      const box = document.createElement("span"); box.className = "ro-d";
      const strip = document.createElement("span");
      for (let n = 0; n <= 9; n++) { const i = document.createElement("i"); i.textContent = String(n); strip.appendChild(i); }
      box.appendChild(strip);
      return box;
    }));
  };
  return {
    el,
    set(v, { tone = null, text = null, unit: un } = {}) {
      const s = text != null ? String(text) : fixed(v, decimals);
      const sh = s.replace(/[0-9]/g, "0");
      if (sh !== shape) { build(s); shape = sh; }
      [...s].forEach((ch, i) => { if (ch >= "0" && ch <= "9") num.children[i].firstChild.style.setProperty("--n", ch); });
      if (un != null) u.textContent = un;
      sr.textContent = `${s} ${u.textContent}`.trim();
      if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
      if (last != null && v != null && v !== last && !REDUCED_MOTION) { el.classList.remove("flare"); void el.offsetWidth; el.classList.add("flare"); }
      last = v;
    },
  };
}

// Measured watts on a dial against the cap: the cap is a red tick two-thirds round, the arc turns red past it.
function capGauge(el) {
  const C = 120, R = 100, START = 135, SWEEP = 270;
  const pt = (a, r) => { const t = a * Math.PI / 180; return [(C + r * Math.cos(t)).toFixed(2), (C + r * Math.sin(t)).toFixed(2)]; };
  const arc = (r) => { const [x0, y0] = pt(START, r), [x1, y1] = pt(START + SWEEP, r); return `M${x0} ${y0} A${r} ${r} 0 1 1 ${x1} ${y1}`; };
  const ticks = Array.from({ length: 41 }, (_, i) => {
    const a = START + SWEEP * i / 40, major = i % 10 === 0, [x1, y1] = pt(a, R + 14), [x2, y2] = pt(a, R + (major ? 24 : 19));
    return html`<line class="g-tick${major ? " major" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
  });
  const [cx0, cy0] = pt(START, R - 12), [cx1, cy1] = pt(START, R + 12);
  el.classList.add("gauge");
  setHTML(el, html`<svg viewBox="0 0 240 240" aria-hidden="true">${ticks}<path class="g-track" d="${arc(R)}"/>
    <path class="g-val" d="${arc(R)}" pathLength="1000"/><line class="g-cap" x1="${cx0}" y1="${cy0}" x2="${cx1}" y2="${cy1}"/></svg>
    <div class="gauge-mid"><span class="g-num"></span><span class="label g-label"></span></div>`);
  const val = el.querySelector(".g-val"), cap = el.querySelector(".g-cap"), lab = el.querySelector(".g-label");
  const ro = readout(el.querySelector(".g-num"), { unit: "W", decimals: 1 });
  return {
    set(w, capW) {
      const max = Math.max((capW || 0) * 1.5, (w || 0) * 1.15, 1);
      val.style.strokeDashoffset = String(1000 - Math.max(0, Math.min(1, (w || 0) / max)) * 1000);
      const over = capW != null && w != null && w > capW;
      el.classList.toggle("over", over);
      cap.style.display = capW == null ? "none" : "";
      if (capW != null) cap.style.transform = `rotate(${SWEEP * Math.min(1, capW / max)}deg)`;
      ro.set(w, { tone: over ? "over" : null });
      lab.textContent = capW == null ? "no cap in force" : `${over ? "over" : "under"} the ${fixed(capW, 1)} W cap`;
    },
  };
}

// The grid feeding this machine, in 3D: a pylon carries three phases of current (white, flowing at the measured
// watts) to a transformer and on to the load column, idle at the base and each running job stacked above, with the
// utility's cap as a glass plane through it; anything above the plane burns red. Drawn on a 2D canvas with its own
// projection: no library, no network. Drag or use the arrow keys to turn it. update({watts, idle, jobs, cap, grid, live}).
function gridScene(host) {
  host.classList.add("scene");
  host.replaceChildren();
  if (!host.hasAttribute("tabindex")) host.tabIndex = 0;
  host.setAttribute("role", "img");
  const cv = document.createElement("canvas"), tagBox = document.createElement("div");
  tagBox.className = "scene-tags"; tagBox.setAttribute("aria-hidden", "true");
  host.append(cv, tagBox);
  const ctx = cv.getContext("2d");
  const rgb = (c) => {
    c = (c || "").trim();
    let m = /^#([0-9a-f]{3,8})$/i.exec(c);
    if (m) { let h = m[1]; if (h.length <= 4) h = [...h].map((x) => x + x).join(""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); }
    m = /rgba?\(([^)]+)\)/i.exec(c);
    return m ? m[1].split(/[ ,/]+/).slice(0, 3).map(Number) : [242, 242, 242];
  };
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const frac = (x) => ((x % 1) + 1) % 1;
  const col = {};
  const colours = () => {
    const cs = getComputedStyle(host);
    for (const n of ["current", "current-dim", "limit", "ink-muted", "job-idle", "recess"]) col[n] = rgb(cs.getPropertyValue(`--${n}`));
  };
  colours();

  const state = { watts: 0, idle: 0, jobs: [], cap: null, grid: null, live: true, kind: "" };
  const shown = { seg: {}, cap: null, capA: 0, max: 10 };
  const tags = new Map();
  let W = 1, H = 1, dpr = 1, k = 30, cx = 0, cy = 0, cs = 1, sn = 0, yaw = -0.72, yawUser = 0;
  const yawBase = -0.72, sp = Math.sin(0.56), cp = Math.cos(0.56);
  const resize = () => {
    const r = host.getBoundingClientRect();
    dpr = Math.min(2, window.devicePixelRatio || 1); W = Math.max(1, r.width); H = Math.max(1, r.height);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  };
  resize();
  if (window.ResizeObserver) new ResizeObserver(resize).observe(host);
  const P = (x, y, z) => { const xr = x * cs - y * sn, yr = x * sn + y * cs; return [cx + xr * k, cy + (yr * sp - z * cp) * k, yr * cp + z * sp]; };

  // painter's algorithm over the whole scene: polygons, segments and glowing points sorted by depth
  let prims = [];
  const poly = (pts, fill, stroke, lw, glow) => {
    const pp = pts.map((p) => P(...p));
    prims.push({ t: 0, pp, z: pp.reduce((a, p) => a + p[2], 0) / pp.length, fill, stroke, lw: lw || 1, glow });
  };
  const seg = (a, b, stroke, lw, glow, bias = 0) => {
    const pa = P(...a), pb = P(...b);
    prims.push({ t: 1, pp: [pa, pb], z: (pa[2] + pb[2]) / 2 + bias, stroke, lw: lw || 1, glow });
  };
  const dot = (p, r, fill, glow, z) => { const q = P(...p); prims.push({ t: 2, pp: [q], z: z == null ? q[2] + 0.01 : z, r, fill, glow }); };
  const LIGHT = [-0.35, -0.55, 0.76];
  const box = (x0, y0, z0, x1, y1, z1, c, a, edge, glow) => {
    const v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
    const faces = [[[0, 1, 2, 3], [0, 0, -1]], [[4, 5, 6, 7], [0, 0, 1]], [[0, 1, 5, 4], [0, -1, 0]],
      [[2, 3, 7, 6], [0, 1, 0]], [[1, 2, 6, 5], [1, 0, 0]], [[3, 0, 4, 7], [-1, 0, 0]]];
    for (const [idx, n] of faces) {
      const sh = 0.55 + 0.45 * Math.max(0, n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]);
      poly(idx.map((i) => v[i]), rgba(c.map((x) => Math.round(x * sh)), a * (n[2] > 0 ? 1.15 : 1)), edge, 1, glow);
    }
  };
  const ring = (x, y, r, stroke, lw, n = 64) => {
    for (let i = 0; i < n; i++) {
      const a0 = i / n * 2 * Math.PI, a1 = (i + 1) / n * 2 * Math.PI;
      seg([x + r * Math.cos(a0), y + r * Math.sin(a0), 0.01], [x + r * Math.cos(a1), y + r * Math.sin(a1), 0.01], stroke, lw, false, -50);
    }
  };

  const COL = [1.6, 0.5], FOOT = 1.05, PY = [-4.6, -2.3], TR = [-1.5, -1.1], HMAX = 5.6;
  const wires = [-1.15, 0, 1.15].map((o, i) => [[PY[0] + o * 0.7, PY[1] - o * 0.7, 4.55 + (i === 1 ? 0.35 : 0)], [TR[0] + o * 0.25, TR[1] - o * 0.25, 1.15]]);
  const wirePt = ([a, b], t) => [0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * t).map((v, i) => (i === 2 ? v - 0.9 * 4 * t * (1 - t) : v));
  const CONDUIT = [[TR[0], TR[1], 0.02], [TR[0] + 1.2, TR[1], 0.02], [COL[0] - FOOT - 0.3, COL[1], 0.02], [COL[0] - FOOT, COL[1], 0.02]];
  const conduitPt = (t) => {
    const n = CONDUIT.length - 1, f = t * n, i = Math.min(n - 1, Math.floor(f)), u = f - i, a = CONDUIT[i], b = CONDUIT[i + 1];
    return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, 0.02];
  };
  let pulses = [];

  function build(dt, time) {
    prims = [];
    const live = state.live, cur = col.current, lim = col.limit;
    const ease = (rate) => (REDUCED_MOTION ? 1 : 1 - Math.exp(-dt * rate));
    // the floor: a platform and a fading dot grid
    poly([[-6.6, -4.2, 0], [5.4, -4.2, 0], [5.4, 3.6, 0], [-6.6, 3.6, 0]], rgba(col.recess, 0.55), rgba(col["current-dim"], 0.35), 1);
    prims[prims.length - 1].z = -1e6;
    for (let gx = -6; gx <= 5; gx++) for (let gy = -4; gy <= 3; gy++) {
      dot([gx, gy, 0], 1.2, rgba(cur, Math.max(0, 0.3 - Math.hypot(gx - 0.5, gy * 1.3) / 7 * 0.3)), false, -9e5);
    }
    // the pylon: a tapered lattice
    const lw = rgba(cur, live ? 0.82 : 0.35), top = 5.3, lev = [0, 1.4, 2.7, 3.9, top];
    const corner = (z, sx, sy) => { const hw = 0.75 + (0.22 - 0.75) * (z / top); return [PY[0] + sx * hw, PY[1] + sy * hw, z]; };
    const c4 = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
    c4.forEach(([sx, sy]) => seg(corner(0, sx, sy), corner(top, sx, sy), lw, 1.4, live));
    for (let li = 1; li < lev.length; li++) for (let ci = 0; ci < 4; ci++) {
      const a = c4[ci], b = c4[(ci + 1) % 4];
      seg(corner(lev[li], a[0], a[1]), corner(lev[li], b[0], b[1]), lw, 1, live);
      seg(corner(lev[li - 1], a[0], a[1]), corner(lev[li], b[0], b[1]), rgba(cur, live ? 0.38 : 0.18), 0.8, false);
    }
    [[1, -1], [-1, 1]].forEach(([sx, sy]) => seg([PY[0], PY[1], 4.55], [PY[0] + sx * 1.006, PY[1] + sy * 1.006, 4.55], lw, 1.4, live));
    seg([PY[0], PY[1], top], [PY[0], PY[1], top + 0.35], lw, 1.4, live);
    box(TR[0] - 0.55, TR[1] - 0.45, 0, TR[0] + 0.55, TR[1] + 0.45, 1.05, col["current-dim"], 0.28, rgba(cur, live ? 0.72 : 0.3), live);
    // wires and the current in them, faster the more the machine draws
    const load = Math.min(1, (state.watts || 0) / Math.max(shown.max, 1));
    const flow = live && !REDUCED_MOTION ? 0.12 + load * 0.55 : 0;
    wires.forEach((w, wi) => {
      let prev = wirePt(w, 0);
      for (let i = 1; i <= 18; i++) { const q = wirePt(w, i / 18); seg(prev, q, rgba(cur, live ? 0.42 : 0.2), 1.1, false); prev = q; }
      if (!live) return;
      const n = 3 + Math.round(load * 7);
      for (let i = 0; i < n; i++) dot(wirePt(w, frac(time * flow * 0.35 + i / n + wi * 0.13)), 2.1, rgba(cur, 0.95), true);
    });
    for (let i = 0; i < CONDUIT.length - 1; i++) seg(CONDUIT[i], CONDUIT[i + 1], rgba(cur, live ? 0.5 : 0.2), 2, live, -40);
    if (live) { const n = 5 + Math.round(load * 9); for (let i = 0; i < n; i++) dot(conduitPt(frac(time * flow * 0.5 + i / n)), 2.3, rgba(cur, 1), true, -30); }
    // the load column
    const scale = HMAX / Math.max(shown.max, 1);
    const stack = [{ id: "_idle", label: "Idle", watts: state.idle || 0, c: col["job-idle"], tc: col["ink-muted"] }]
      .concat(state.jobs.map((j) => ({ ...j, c: rgb(getComputedStyle(host).getPropertyValue(`--job-${j.id}`)) })));
    const tagList = [];
    let z = 0;
    for (const s of stack) {
      const target = Math.max(0, s.watts || 0) * scale;
      const h = shown.seg[s.id] == null ? target : shown.seg[s.id] + (target - shown.seg[s.id]) * ease(5);
      shown.seg[s.id] = h;
      if (h < 0.02) {
        if (s.id !== "_idle" && s.state && s.state !== "running") {
          box(COL[0] - FOOT, COL[1] - FOOT, z + 0.05, COL[0] + FOOT, COL[1] + FOOT, z + 0.13, s.c, 0.08, rgba(s.c, 0.45), false);
          tagList.push({ id: s.id, z: z + 0.1, text: s.label, note: s.state, c: s.c });
        }
        continue;
      }
      box(COL[0] - FOOT, COL[1] - FOOT, z + (z ? 0.05 : 0), COL[0] + FOOT, COL[1] + FOOT, z + h, s.c, s.id === "_idle" ? 0.5 : 0.42, rgba(s.c, live ? 0.9 : 0.4), live && s.id !== "_idle");
      tagList.push({ id: s.id, z: z + h / 2, text: s.label, w: s.watts, c: s.tc || s.c });
      z += h;
    }
    // the cap plane: descends into place when a cap arrives, fades when it lifts
    if (state.cap != null) {
      const target = state.cap * scale;
      shown.cap = shown.cap == null ? HMAX * 1.3 : shown.cap + (target - shown.cap) * ease(3);
      shown.capA += (1 - shown.capA) * ease(4);
    } else shown.capA += (0 - shown.capA) * ease(4);
    const over = state.cap != null && state.watts > state.cap;
    if (shown.capA > 0.02 && shown.cap != null) {
      const cz = shown.cap, E = 2.1, A = shown.capA, beat = over && !REDUCED_MOTION ? 0.5 + 0.5 * Math.sin(time * 6) : 0.5;
      poly([[COL[0] - E, COL[1] - E, cz], [COL[0] + E, COL[1] - E, cz], [COL[0] + E, COL[1] + E, cz], [COL[0] - E, COL[1] + E, cz]],
        rgba(lim, (0.1 + (over ? 0.08 * beat : 0)) * A), rgba(lim, 0.95 * A), 1.6, true);
      if (over && z > cz) box(COL[0] - FOOT - 0.06, COL[1] - FOOT - 0.06, cz, COL[0] + FOOT + 0.06, COL[1] + FOOT + 0.06, z, lim, 0.12 + 0.12 * beat, rgba(lim, 0.95), true);
    }
    // floor rings: a resting halo, and one ripple per meter sample
    ring(COL[0], COL[1], 1.9, rgba(over ? lim : col["current-dim"], 0.7), 1.2);
    pulses = pulses.filter((p) => time - p < 1.6);
    for (const p of pulses) { const f = (time - p) / 1.6; ring(COL[0], COL[1], 1.9 + f * 2.4, rgba(over ? lim : cur, (1 - f) * 0.6), 1.5, 48); }
    return { tagList, top: z, over };
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    prims.sort((a, b) => a.z - b.z);
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    for (const p of prims) {
      if (p.t === 2) {
        ctx.globalCompositeOperation = p.glow ? "lighter" : "source-over";
        if (p.glow) { ctx.fillStyle = p.fill.replace(/[\d.]+\)$/, "0.18)"); ctx.beginPath(); ctx.arc(p.pp[0][0], p.pp[0][1], p.r * 3.2, 0, 6.283); ctx.fill(); }
        ctx.fillStyle = p.fill; ctx.beginPath(); ctx.arc(p.pp[0][0], p.pp[0][1], p.r, 0, 6.283); ctx.fill();
        continue;
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.beginPath();
      ctx.moveTo(p.pp[0][0], p.pp[0][1]);
      for (let j = 1; j < p.pp.length; j++) ctx.lineTo(p.pp[j][0], p.pp[j][1]);
      if (p.t === 0) { ctx.closePath(); if (p.fill) { ctx.fillStyle = p.fill; ctx.fill(); } }
      if (!p.stroke) continue;
      if (p.glow) { ctx.globalCompositeOperation = "lighter"; ctx.strokeStyle = p.stroke.replace(/[\d.]+\)$/, "0.16)"); ctx.lineWidth = p.lw + 4; ctx.stroke(); }
      ctx.globalCompositeOperation = p.glow ? "lighter" : "source-over";
      ctx.strokeStyle = p.stroke; ctx.lineWidth = p.lw; ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  // tags: HTML over the canvas with leader lines, pushed apart so they never overlap
  let taken = [];
  const tag = (id, tone) => {
    let t = tags.get(id);
    if (!t) { t = document.createElement("div"); t.className = "scene-tag"; tagBox.appendChild(t); tags.set(id, t); }
    if (tone) t.dataset.tone = tone; else delete t.dataset.tone;
    t.seen = true;
    return t;
  };
  const fill = (t, bold, rest) => { const b = document.createElement("b"); b.textContent = bold; t.replaceChildren(b, document.createTextNode(rest)); };
  const place = (t, x, y, side) => {
    const w = t.offsetWidth, h = t.offsetHeight;
    let px = Math.max(4, Math.min(W - w - 4, side === "left" ? x - w - 14 : x + 14));
    let py = Math.max(4, Math.min(H - h - 4, y - h / 2));
    for (let n = 0; n < 8; n++) {
      const hit = taken.find((r) => px < r[0] + r[2] + 6 && px + w + 6 > r[0] && py < r[1] + r[3] + 4 && py + h + 4 > r[1]);
      if (!hit) break;
      py = hit[1] + hit[3] + 6;
    }
    taken.push([px, py, w, h]);
    t.style.transform = `translate(${px.toFixed(1)}px,${py.toFixed(1)}px)`;
    return [px, py, w, h];
  };
  const leader = (x0, y0, x1, y1, c) => {
    ctx.strokeStyle = c; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x0, y0, 2, 0, 6.283); ctx.fill();
  };
  const watts = (w) => `${fixed(w, w < 100 ? 1 : 0)} W`;

  function label(res) {
    for (const t of tags.values()) t.seen = false;
    taken = [];
    if (state.grid) {
      const g = P(PY[0], PY[1], 5.65), t = tag("grid", "grid");
      t.replaceChildren(document.createTextNode(`${state.grid.label} `));
      if (state.grid.price != null) { const b = document.createElement("b"); b.textContent = `$${fixed(state.grid.price, 2)}/MWh`; t.appendChild(b); }
      place(t, g[0] - t.offsetWidth / 2 - 14, g[1] - 20, "right");
    }
    const segs = res.tagList.map((s) => {
      const a = P(COL[0] + FOOT, COL[1] - FOOT, s.z), t = tag(`seg-${s.id}`);
      t.style.setProperty("--c", rgba(s.c, 1));
      fill(t, s.text, s.w == null ? ` ${s.note}` : ` ${watts(s.w)}${state.kind && s.id !== "_idle" ? ` ${state.kind}` : ""}`);
      t.style.opacity = s.w == null ? "0.75" : "";
      return { t, ax: a[0], ay: a[1], y: a[1], c: rgba(s.c, 0.8) };
    }).sort((p, q) => p.ay - q.ay);
    for (let i = 1; i < segs.length; i++) if (segs[i].y - segs[i - 1].y < 30) segs[i].y = segs[i - 1].y + 30;
    const lx = Math.max(0, ...segs.map((s) => s.ax)) + 26;
    for (const s of segs) { const r = place(s.t, lx, s.y, "right"); leader(s.ax, s.ay, r[0], r[1] + r[3] / 2, s.c); }
    const tp = P(COL[0] - FOOT, COL[1] - FOOT, res.top), tt = tag("total", "total");
    fill(tt, watts(state.watts), state.live ? " measured" : " last measured");
    const rr = place(tt, tp[0], tp[1] - 22, "left");
    leader(tp[0], tp[1], rr[0] + rr[2], rr[1] + rr[3] / 2, rgba(col.current, 0.8));
    if (state.cap != null && shown.capA > 0.3) {
      const c = P(COL[0] - 2.1, COL[1] + 2.1, shown.cap), ct = tag("cap", "limit");
      ct.textContent = `${res.over ? "Over the cap: " : "Cap "}${watts(state.cap)}`;
      const r = place(ct, c[0], c[1], "left");
      leader(c[0], c[1], r[0] + r[2], r[1] + r[3] / 2, rgba(col.limit, 0.9));
    }
    for (const [id, t] of tags) if (!t.seen) { t.remove(); tags.delete(id); }
  }

  // turning: drag or arrow keys; it drifts back to rest after six seconds alone
  let drag = null, lastTouch = -1e9;
  host.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y0: yawUser }; host.setPointerCapture(e.pointerId); lastTouch = performance.now(); });
  host.addEventListener("pointermove", (e) => { if (drag) { yawUser = drag.y0 + (e.clientX - drag.x) * 0.008; lastTouch = performance.now(); } });
  host.addEventListener("pointerup", () => { drag = null; });
  host.addEventListener("pointercancel", () => { drag = null; });
  host.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    yawUser += e.key === "ArrowLeft" ? -0.12 : 0.12; lastTouch = performance.now(); e.preventDefault();
  });
  let visible = true, t0 = performance.now(), last = t0;
  if (window.IntersectionObserver) new IntersectionObserver((es) => { visible = es[0].isIntersecting; }).observe(host);
  const tick = (now) => {
    requestAnimationFrame(tick);
    if (!visible || document.hidden) { last = now; return; }
    const dt = Math.min(0.1, Math.max(0, now - last) / 1000), time = Math.max(0, now - t0) / 1000;
    last = now;
    if ((now - lastTouch) / 1000 > 6 && !drag) yawUser *= Math.exp(-dt * 0.6);
    yaw = yawBase + yawUser + (REDUCED_MOTION ? 0 : 0.22 * Math.sin(time * 0.09));
    k = Math.min(W / 13, H / 9.4); cx = W * 0.48; cy = H * 0.6; cs = Math.cos(yaw); sn = Math.sin(yaw);
    const res = build(dt, time);
    draw();
    label(res);
  };
  requestAnimationFrame(tick);

  return {
    update(s) {
      Object.assign(state, s);
      const sum = (state.idle || 0) + state.jobs.reduce((a, j) => a + (j.watts || 0), 0);
      const need = Math.max(sum, state.watts || 0, state.cap || 0, 1) * 1.2;
      if (need > shown.max || need < shown.max * 0.55) shown.max = need;
      if (s.watts != null) pulses.push(Math.max(0, performance.now() - t0) / 1000);
      const over = state.cap != null && state.watts > state.cap;
      host.setAttribute("aria-label", `This machine draws ${fixed(state.watts, 1)} W measured` +
        (state.cap != null ? `, ${over ? "over" : "under"} the ${fixed(state.cap, 1)} W cap` : ", no cap in force") +
        (state.jobs.length ? `. ${state.jobs.map((j) => `${j.label} ${j.watts ? `${fixed(j.watts, 1)} W` : j.state}`).join(", ")}` : ""));
    },
    recolour: colours,
  };
}

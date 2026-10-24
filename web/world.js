// The grid as a small 3D world (Aryen, Sat 16:30): drawn on one canvas with no library, so it works offline.
// The layout is a schematic; every quantity in it is real and comes from World.set():
//   - power plants: one per fuel in the grid's real generation mix (EIA-930 for a replayed event, the ISO's live
//     fuel mix otherwise); a plant's height follows its share, turbines spin with wind output, panels glow with solar;
//   - the city: the share of lit windows is the demand the grid served over the demand it needed (its own day-ahead
//     forecast), so when the grid sheds load (Uri) the blocks go dark in proportion;
//   - our data center: this Mac, its light band and beacon set by its measured watts against its baseline;
//   - the lines: light flows at a speed set by the power served; they turn amber on a warning and red in an emergency.
// Every value eases toward its new reading, so nothing jumps. Motion respects prefers-reduced-motion: no sway, no
// flowing light, no smoke, no easing; the picture still shows every number.
"use strict";

const World = (() => {
  const REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const C = {
    floor: "#04070a", grid: "rgba(150,210,195,",
    wall: [214, 226, 232], glassWall: [150, 190, 220], glass: [96, 170, 255], lit: [255, 210, 140], dark: [22, 30, 38],
    concrete: [190, 198, 204], steel: [168, 180, 190], mint: [125, 240, 191],
    lineOk: [72, 160, 255], lineCity: [70, 230, 150], lineWarn: [255, 190, 70], lineBad: [255, 80, 80],
  };
  const S = {
    cv: null, ctx: null, w: 0, h: 0, dpr: 1, yaw: -0.62, pitch: 0.6, scale: 18, cx: 0, cy: 0, baseYaw: -0.62,
    drag: null, last: 0, t: 0, running: false, labels: [], smoke: [], smokeAcc: 0, safe: { top: 72, bottom: 230 },
    data: { mix: {}, served: null, needed: null, ours_w: null, baseline_w: null, cut_pct: null, alert: null, campus: null, peaks: {} },
    v: { served: 0, needed: 0, lit: 1, ours: 0.5, mix: {}, tint: { gen: [...C.lineOk], city: [...C.lineCity] } },
  };

  // ------------------------------------------------------------------ easing: every value glides to its reading
  function ease(cur, target, dt, rate = 2.6) { return REDUCE ? target : cur + (target - cur) * (1 - Math.exp(-dt * rate)); }
  function easeColor(cur, target, dt) { return cur.map((c, i) => ease(c, target[i], dt, 3)); }
  function step(dt) {
    const d = S.data, v = S.v;
    v.served = ease(v.served, d.served || 0, dt);
    v.needed = ease(v.needed, d.needed || 0, dt);
    const lit = d.needed ? Math.max(0, Math.min(1, (d.served || 0) / d.needed)) : 1;
    v.lit = ease(v.lit, lit, dt, 1.6);
    const ours = d.ours_w != null && d.baseline_w ? Math.min(1.4, d.ours_w / d.baseline_w) : d.ours_w != null ? Math.min(1, d.ours_w / 25) : 0.5;
    v.ours = ease(v.ours, ours, dt, 2);
    for (const [k, mw] of Object.entries(d.mix || {})) v.mix[k] = ease(v.mix[k] == null ? mw : v.mix[k], Math.max(0, mw), dt);
    for (const k of Object.keys(v.mix)) if (!(k in (d.mix || {}))) v.mix[k] = ease(v.mix[k], 0, dt);
    const alertColor = d.alert === "emergency" || d.alert === "outage" ? C.lineBad : d.alert === "warning" ? C.lineWarn : null;
    v.tint.gen = easeColor(v.tint.gen, alertColor || C.lineOk, dt);
    v.tint.city = easeColor(v.tint.city, alertColor || C.lineCity, dt);
  }

  // ------------------------------------------------------------------ projection: x right, z toward us, y up
  function P(x, y, z) {
    const c = Math.cos(S.yaw), s = Math.sin(S.yaw), cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);
    const xr = x * c - z * s, zr = x * s + z * c;
    const depth = zr * cp + y * sp;
    const k = S.scale / (1 - depth / 120);
    return [S.cx + xr * k, S.cy - (y * cp - zr * sp) * k, depth];
  }
  const rgb = (a, al = 1) => `rgba(${a[0] | 0},${a[1] | 0},${a[2] | 0},${al})`;
  const mix = (a, b, f) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  const shade = (base, f) => mix([10, 14, 18], base, f);
  const area = (pts) => pts.reduce((s, p, i) => { const q = pts[(i + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
  function hash(n) { const x = Math.sin(n * 12.9898 + 4.1414) * 43758.5453; return x - Math.floor(x); }

  function poly(pts, fill, stroke, lw = 1) {
    const g = S.ctx;
    g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
    g.closePath();
    if (fill) { g.fillStyle = fill; g.fill(); }
    if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
  }
  function line3(a, b, color, w = 1) {
    const p = P(...a), q = P(...b), g = S.ctx;
    g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.strokeStyle = color; g.lineWidth = w; g.stroke();
  }
  function glowDot(x, y, z, r, color, alpha) {
    const p = P(x, y, z), g = S.ctx, grd = g.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
    grd.addColorStop(0, rgb(mix(color, [255, 255, 255], 0.55), alpha)); grd.addColorStop(1, rgb(color, 0));
    g.globalCompositeOperation = "lighter"; g.fillStyle = grd; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
    g.globalCompositeOperation = "source-over";
  }

  // ------------------------------------------------------------------ primitives
  // A box: shaded faces with a soft vertical gradient, optional windows (lit to `lit`, stable per window), optional
  // horizontal light band (our data center), optional roof cap.
  function box(x, z, w, d, h, o = {}) {
    const y0 = o.y || 0, base = o.color || C.wall, al = o.alpha || 1, g = S.ctx;
    const c = [[x, y0, z], [x + w, y0, z], [x + w, y0, z + d], [x, y0, z + d]];
    const t = c.map(([a, , b]) => [a, y0 + h, b]);
    const faces = [[c[0], c[1], t[1], t[0], 0.6], [c[1], c[2], t[2], t[1], 0.78], [c[2], c[3], t[3], t[2], 0.92], [c[3], c[0], t[0], t[3], 0.7]];
    for (const [a, b, e, f, sh] of faces) {
      const pts = [a, b, e, f].map((v) => P(...v));
      if (area(pts) >= 0) continue;                                 // facing away
      const top = (pts[2][1] + pts[3][1]) / 2, bot = (pts[0][1] + pts[1][1]) / 2;
      const grd = g.createLinearGradient(0, top, 0, bot);
      grd.addColorStop(0, rgb(shade(base, Math.min(1, sh + 0.12)), al)); grd.addColorStop(1, rgb(shade(base, sh * 0.82), al));
      poly(pts, grd, o.edge ? rgb(base, 0.28) : null, 0.6);
      if (o.windows) windows(a, b, e, f, h, o);
      if (o.band != null) band(a, b, h, o);
    }
    poly(t.map((v) => P(...v)), rgb(shade(base, 1.02), al), rgb([255, 255, 255], 0.08), 0.6);
    if (o.cap) box(x - 0.08, z - 0.08, w + 0.16, d + 0.16, 0.14, { y: y0 + h, color: o.capColor || shade(base, 0.85) });
  }
  function windows(a, b, e, f, h, o) {
    const rows = Math.max(1, Math.round(h / (o.floor || 0.6))), cols = o.cols || 3, lit = o.lit == null ? 1 : o.lit;
    const at = (u, v) => [a[0] + (b[0] - a[0]) * u, a[1] + (f[1] - a[1]) * v, a[2] + (b[2] - a[2]) * u];
    const g = S.ctx;
    g.globalCompositeOperation = "lighter";
    for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
      const u0 = (k + 0.2) / cols, u1 = (k + 0.8) / cols, v0 = (r + 0.28) / rows, v1 = (r + 0.74) / rows;
      const on = hash((o.seed || 1) * 97 + r * 13.1 + k * 7.3 + (a[0] + a[2]) * 3.7) < lit;
      const pts = [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)].map((v) => P(...v));
      poly(pts, on ? rgb(o.litColor || C.lit, 0.62 + 0.25 * hash(r * 3 + k)) : rgb(C.dark, 0.55));
    }
    g.globalCompositeOperation = "source-over";
  }
  function band(a, b, h, o) {                                         // a glowing stripe: our data center's watts
    const y = (o.y || 0) + h * 0.55, g = S.ctx;
    const pts = [[a[0], y, a[2]], [b[0], y, b[2]], [b[0], y + 0.22, b[2]], [a[0], y + 0.22, a[2]]].map((v) => P(...v));
    g.save(); g.globalCompositeOperation = "lighter"; g.shadowColor = rgb(o.bandColor || C.mint, 0.9); g.shadowBlur = 12 * o.band;
    poly(pts, rgb(o.bandColor || C.mint, 0.25 + 0.7 * o.band)); g.restore();
  }
  // A body of revolution through `profile` [[radius, height], ...]: stacks, cooling towers, tanks, domes.
  function lathe(x, z, profile, o = {}) {
    const n = o.n || 18, y0 = o.y || 0, base = o.color || C.wall, al = o.alpha || 1;
    const ringAt = ([r, hh]) => Array.from({ length: n }, (_, i) => { const a = (i / n) * Math.PI * 2; return [x + Math.cos(a) * r, y0 + hh, z + Math.sin(a) * r, a]; });
    const rings = profile.map(ringAt);
    for (let j = 0; j < rings.length - 1; j++) for (let i = 0; i < n; i++) {
      const b0 = rings[j][i], b1 = rings[j][(i + 1) % n], t1 = rings[j + 1][(i + 1) % n], t0 = rings[j + 1][i];
      const pts = [b0, b1, t1, t0].map((v) => P(v[0], v[1], v[2]));
      if (area(pts) >= 0) continue;
      const light = 0.5 + 0.45 * Math.max(0, Math.cos(b0[3] + S.yaw + 1.2));
      poly(pts, rgb(shade(base, light), al));
    }
    const top = rings[rings.length - 1];
    if (!o.open) poly(top.map((v) => P(v[0], v[1], v[2])), rgb(shade(base, 0.9), al));
    else poly(top.map((v) => P(v[0], v[1], v[2])), rgb([8, 10, 12], 0.95), rgb(base, 0.6), 0.8);
    if (o.stripes) for (const [hh, col] of o.stripes) {
      const r = profile.reduce((best, p) => (Math.abs(p[1] - hh) < Math.abs(best[1] - hh) ? p : best))[0];
      const ring = ringAt([r * 1.01, hh]).map((v) => P(v[0], v[1], v[2]));
      S.ctx.save(); S.ctx.beginPath(); ring.forEach((p, i) => (i ? S.ctx.lineTo(p[0], p[1]) : S.ctx.moveTo(p[0], p[1]))); S.ctx.closePath();
      S.ctx.strokeStyle = col; S.ctx.lineWidth = 2.2; S.ctx.stroke(); S.ctx.restore();
    }
  }
  function platform(x, z, w, d, glow, edgeColor) {
    box(x, z, w, d, 0.35, { color: [24, 32, 36] });
    const pts = [[x, 0.36, z], [x + w, 0.36, z], [x + w, 0.36, z + d], [x, 0.36, z + d]].map((v) => P(...v));
    const g = S.ctx, breathe = REDUCE ? 1 : 0.8 + 0.2 * Math.sin(S.t * 1.3 + x);
    g.save(); g.shadowColor = edgeColor || "rgba(120,255,200,0.9)"; g.shadowBlur = 16 * breathe;
    poly(pts, null, edgeColor || `rgba(150,255,215,${glow * breathe})`, 1.4);
    g.restore();
  }

  // ------------------------------------------------------------------ labels: glass cards with leader lines, drawn last
  function label(x, y, z, title, value, sub, anchorY) {
    const p = P(x, y, z), a = P(x, anchorY == null ? y - 1.5 : anchorY, z);
    S.labels.push({ x: p[0], y: p[1], ax: a[0], ay: a[1], title, value, sub });
  }
  function drawLabels() {
    const g = S.ctx;
    const items = S.labels.map((L) => {
      g.font = "300 19px Inter, system-ui, sans-serif"; const vw = g.measureText(L.value).width;
      g.font = "600 9.5px Inter, system-ui, sans-serif"; const tw = g.measureText(L.title.toUpperCase()).width;
      g.font = "500 10px Inter, system-ui, sans-serif"; const sw = L.sub ? g.measureText(L.sub).width : 0;
      const w = Math.max(vw, tw, sw) + 22, h = L.sub ? 52 : 40;
      return { ...L, w, h, bx: L.x - w / 2, by: L.y - h };
    });
    const top = S.safe.top, bottom = S.h - S.safe.bottom;            // keep cards clear of the page's bars
    for (const L of items) { L.by = Math.max(top, Math.min(bottom - L.h, L.by)); L.bx = Math.max(8, Math.min(S.w - L.w - 8, L.bx)); }
    items.sort((a, b) => a.by - b.by);                                // nudge apart: a later card moves below an earlier one
    for (let i = 0; i < items.length; i++) for (let j = 0; j < i; j++) {
      const A = items[j], B = items[i];
      if (A.bx < B.bx + B.w && B.bx < A.bx + A.w && A.by < B.by + B.h && B.by < A.by + A.h) B.by = A.by + A.h + 6;
    }
    for (const L of items) {
      g.save();
      g.strokeStyle = "rgba(170,240,215,0.45)"; g.lineWidth = 1; g.setLineDash([2, 3]);
      g.beginPath(); g.moveTo(L.x, L.by + L.h); g.lineTo(L.ax, L.ay); g.stroke(); g.setLineDash([]);
      g.fillStyle = "rgba(170,240,215,0.9)"; g.beginPath(); g.arc(L.ax, L.ay, 2.2, 0, 7); g.fill();
      g.fillStyle = "rgba(8,14,14,0.72)"; g.strokeStyle = "rgba(160,235,210,0.22)";
      g.beginPath(); g.roundRect(L.bx, L.by, L.w, L.h, 10); g.fill(); g.stroke();
      g.textAlign = "left";
      g.font = "600 9.5px Inter, system-ui, sans-serif"; g.fillStyle = "rgba(170,205,198,0.85)"; g.fillText(L.title.toUpperCase(), L.bx + 11, L.by + 15);
      g.font = "300 19px Inter, system-ui, sans-serif"; g.fillStyle = "#f2fbf7"; g.fillText(L.value, L.bx + 11, L.by + 35);
      if (L.sub) { g.font = "500 10px Inter, system-ui, sans-serif"; g.fillStyle = "rgba(170,200,195,0.75)"; g.fillText(L.sub, L.bx + 11, L.by + 47); }
      g.restore();
    }
  }

  // ------------------------------------------------------------------ the routes and their flowing light
  const ROUTES = {
    gen: [[-14, 0.05, -9], [-10.5, 0.05, -9], [-10.5, 0.05, 0.4], [-2.2, 0.05, 0.4]],
    city: [[2.2, 0.05, -0.6], [5.5, 0.05, -0.6], [5.5, 0.05, -8.5], [8, 0.05, -8.5]],
    dc: [[-0.8, 0.05, 2.6], [-0.8, 0.05, 7.5], [-4.5, 0.05, 7.5]],
    campus: [[0.8, 0.05, 2.6], [0.8, 0.05, 8.5], [6.5, 0.05, 8.5]],
  };
  const lenOf = (pts) => pts.slice(1).reduce((s, q, i) => s + Math.hypot(q[0] - pts[i][0], q[2] - pts[i][2]), 0);
  function along(pts, f) {
    let d = f * lenOf(pts);
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1], seg = Math.hypot(b[0] - a[0], b[2] - a[2]);
      if (d <= seg) { const u = d / seg; return [a[0] + (b[0] - a[0]) * u, a[1], a[2] + (b[2] - a[2]) * u]; }
      d -= seg;
    }
    return pts[pts.length - 1];
  }
  function route(pts, color, flow) {
    const g = S.ctx, pp = pts.map((v) => P(...v));
    g.save(); g.lineCap = "round"; g.lineJoin = "round";
    g.beginPath(); pp.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
    g.shadowColor = rgb(color, 0.9); g.shadowBlur = 18; g.strokeStyle = rgb(color, 0.3); g.lineWidth = 8; g.stroke();
    g.shadowBlur = 0; g.strokeStyle = rgb(mix(color, [255, 255, 255], 0.5), 0.9); g.lineWidth = 1.5; g.stroke();
    g.restore();
    if (REDUCE || flow <= 0) return;
    const L = lenOf(pts), n = Math.max(2, Math.round(L / 4)), speed = (0.9 * flow) / L;  // same speed on every route
    for (let i = 0; i < n; i++) {
      const head = (S.t * speed + i / n) % 1;
      for (let k = 0; k < 4; k++) {                                   // a head and a fading trail
        const f = head - k * 0.012;
        if (f < 0) continue;
        const q = along(pts, f);
        glowDot(q[0], q[1], q[2], 8 - k * 1.4, color, 0.95 - k * 0.22);
      }
    }
  }

  // ------------------------------------------------------------------ the plants, one per real fuel
  const FUELS = [   // [match, title, kind]
    [/gas/i, "Gas", "gas"], [/coal/i, "Coal", "coal"], [/nuclear/i, "Nuclear", "nuclear"], [/wind/i, "Wind", "wind"],
    [/solar/i, "Solar", "solar"], [/hydro/i, "Hydro", "hydro"], [/import/i, "Imports", "imports"],
  ];
  function plants() {
    const out = [];
    for (const [re, title, kind] of FUELS) {
      const mw = Object.entries(S.v.mix).filter(([k, v]) => re.test(k) && v > 0).reduce((s, [, v]) => s + v, 0);
      if (mw > 1) out.push({ title, kind, mw });
    }
    return out.slice(0, 6);
  }
  function drawPlant(p, x, z, total) {
    const share = total ? p.mw / total : 0, y = 0.36, peaks = S.data.peaks || {};
    platform(x - 2.2, z - 2.2, 4.4, 4.4, 0.5);
    let top = 3;
    if (p.kind === "gas" || p.kind === "coal") {
      const coal = p.kind === "coal", hh = 1.0 + 2.2 * share;
      box(x - 1.7, z - 0.8, 2.4, 1.8, hh, { y, color: coal ? [150, 156, 162] : C.wall, windows: true, cols: 4, floor: 0.5, lit: 0.55, seed: coal ? 9 : 3, litColor: C.glass, cap: true });
      box(x - 1.6, z + 1.1, 1.2, 0.9, hh * 0.6, { y, color: C.steel });          // heat-recovery boiler / bunker
      const stacks = coal ? [[x + 1.2, z - 0.6, 0.42, 3.4 + 3.2 * share]] : [[x + 0.9, z - 1.0, 0.3, 2.4 + 2.6 * share], [x + 1.5, z - 0.2, 0.3, 2.4 + 2.6 * share]];
      for (const [sx, sz, r, sh] of stacks) {
        lathe(sx, sz, [[r * 1.15, 0], [r, sh * 0.85], [r * 0.95, sh]], { y, color: [214, 218, 222], open: true, n: 14,
          stripes: [[sh * 0.86, "rgba(220,60,60,0.85)"], [sh * 0.93, "rgba(240,240,240,0.9)"]] });
        smokeFrom(sx, y + sh, sz, 0.3 + 1.5 * share);
        top = Math.max(top, sh);
      }
    } else if (p.kind === "nuclear") {
      const th = 2.6 + 2.4 * share;
      for (const [tx, tz, s] of [[x - 0.8, z - 0.4, 1], [x + 1.0, z + 0.6, 0.85]]) {
        lathe(tx, tz, [[1.05 * s, 0], [0.75 * s, th * 0.62 * s], [0.82 * s, th * s]], { y, color: [228, 232, 234], open: true, n: 20 });
        smokeFrom(tx, y + th * s, tz, 0.5, true);
      }
      lathe(x + 1.0, z - 1.3, [[0.6, 0], [0.6, 0.8], [0.5, 1.15], [0.3, 1.35], [0.0, 1.42]], { y, color: [205, 212, 218], n: 16 });
      top = th + 0.5;
    } else if (p.kind === "wind") {
      const speed = peaks.wind ? p.mw / peaks.wind : Math.min(1, p.mw / 8000);
      for (let k = 0; k < 4; k++) {
        const tx = x - 1.2 + (k % 2) * 2.3, tz = z - 1.2 + Math.floor(k / 2) * 2.2, th = 2.9;
        lathe(tx, tz, [[0.09, 0], [0.05, th]], { y, color: [235, 240, 242], n: 8 });
        const hub = [tx, y + th, tz];
        box(tx - 0.06, tz - 0.18, 0.12, 0.36, 0.14, { y: y + th - 0.07, color: [235, 240, 242] });
        const a0 = (REDUCE ? 0.3 : S.t * (0.4 + 3.6 * speed)) + k * 1.7;
        for (let b = 0; b < 3; b++) {
          const a = a0 + (b * Math.PI * 2) / 3, r = 1.0;
          line3(hub, [tx + Math.cos(a) * r * Math.cos(S.baseYaw + 0.9), y + th + Math.sin(a) * r, tz + Math.cos(a) * r * Math.sin(S.baseYaw + 0.9)], "rgba(244,250,250,0.95)", 1.4);
        }
        glowDot(tx, y + th, tz, 3, [255, 80, 80], 0.6 + 0.4 * Math.sin(S.t * 2 + k));   // aviation light
      }
      top = 4;
    } else if (p.kind === "solar") {
      const glow = peaks.solar ? p.mw / peaks.solar : Math.min(1, p.mw / 15000);
      for (let r = 0; r < 4; r++) for (let k = 0; k < 3; k++) {
        const px = x - 1.75 + k * 1.2, pz = z - 1.6 + r * 0.9;
        const pts = [[px, y + 0.18, pz], [px + 1.05, y + 0.18, pz], [px + 1.05, y + 0.6, pz + 0.58], [px, y + 0.6, pz + 0.58]].map((v) => P(...v));
        const grd = S.ctx.createLinearGradient(pts[0][0], pts[0][1], pts[2][0], pts[2][1]);
        grd.addColorStop(0, rgb(mix([18, 34, 64], C.glass, 0.15 + 0.7 * glow), 0.98));
        grd.addColorStop(1, rgb(mix([30, 56, 96], [190, 225, 255], 0.1 + 0.6 * glow), 0.98));
        poly(pts, grd, rgb([200, 220, 235], 0.35 + 0.4 * glow), 0.7);
      }
      top = 1.6;
    } else if (p.kind === "hydro") {
      const hh = 1.6 + 1.4 * share;
      box(x - 1.9, z - 0.5, 3.8, 0.9, hh, { y, color: C.concrete, cap: true });
      for (let k = 0; k < 3; k++) box(x - 1.3 + k * 1.1, z + 0.4, 0.5, 0.5, 0.5, { y, color: C.steel });
      const water = [[x - 1.9, y + hh * 0.7, z - 2.1], [x + 1.9, y + hh * 0.7, z - 2.1], [x + 1.9, y + hh * 0.7, z - 0.5], [x - 1.9, y + hh * 0.7, z - 0.5]].map((v) => P(...v));
      poly(water, rgb(mix(C.glass, [200, 235, 255], REDUCE ? 0.2 : 0.2 + 0.15 * Math.sin(S.t * 1.5)), 0.5));
      top = hh + 0.5;
    } else {
      pylon(x, z, 3.6);
      top = 4;
    }
    label(x, y + top + 2.4, z, p.title, `${(p.mw / 1000).toFixed(1)} GW`, `${Math.round(share * 100)}% of supply`, y + top);
  }
  function pylon(x, z, h) {
    const y = 0.36, c = "rgba(205,228,232,0.8)", w = 0.7;
    const legs = [[-w, -w], [w, -w], [w, w], [-w, w]];
    legs.forEach(([a, b]) => line3([x + a, y, z + b], [x + a * 0.25, y + h, z + b * 0.25], c, 1));
    for (let k = 1; k <= 4; k++) {
      const f = k / 4.6, yy = y + h * f, s = 1 - 0.75 * f;
      legs.forEach(([a, b], i) => { const [c2, d2] = legs[(i + 1) % 4]; line3([x + a * s, yy, z + b * s], [x + c2 * s, yy, z + d2 * s], c, 0.8); });
      if (k < 4) legs.forEach(([a, b], i) => { const [c2, d2] = legs[(i + 1) % 4]; const f2 = (k + 1) / 4.6, s2 = 1 - 0.75 * f2;
        line3([x + a * s, yy, z + b * s], [x + c2 * s2, y + h * f2, z + d2 * s2], "rgba(205,228,232,0.35)", 0.6); });
    }
    line3([x - 1.5, y + h * 0.82, z], [x + 1.5, y + h * 0.82, z], c, 1.1);
    line3([x - 1.1, y + h * 0.62, z], [x + 1.1, y + h * 0.62, z], c, 1);
  }
  // A city tower: a base, a setback, a crown, windows lit to the city's share, an antenna on the tallest.
  function tower(bx, bz, bw, bd, bh, seed, lit) {
    const y = 0.36, color = mix([200, 222, 240], C.glassWall, hash(seed) * 0.5);
    const lower = bh > 3 ? bh * 0.62 : bh;
    box(bx, bz, bw, bd, lower, { y, color, windows: true, cols: Math.max(2, Math.round(bw * 2)), floor: 0.5, lit, seed, cap: bh <= 3 });
    if (bh > 3) {
      const inset = Math.min(bw, bd) * 0.18;
      box(bx + inset, bz + inset, bw - 2 * inset, bd - 2 * inset, bh - lower, { y: y + lower, color, windows: true, cols: Math.max(2, Math.round(bw * 1.6)), floor: 0.5, lit, seed: seed + 50, cap: true });
      if (bh > 4.4) { const ax = bx + bw / 2, az = bz + bd / 2; line3([ax, y + bh + 0.14, az], [ax, y + bh + 1.1, az], "rgba(220,235,240,0.8)", 1.1); glowDot(ax, y + bh + 1.1, az, 3.5, [255, 90, 90], REDUCE ? 0.7 : 0.45 + 0.45 * Math.sin(S.t * 2.2 + seed)); }
    }
  }

  // ------------------------------------------------------------------ the scene
  function frame(now) {
    if (!S.running) return;
    if (S.last && now - S.last < 32) { requestAnimationFrame(frame); return; }   // 30 fps: this page runs on the Mac we measure
    const dt = Math.min(0.1, (now - (S.last || now)) / 1000);
    S.last = now; S.t += dt; S.dt = dt;
    if (!S.drag) S.yaw = ease(S.yaw, S.baseYaw + 0.26 * Math.sin(S.t * 0.045), dt, 1.5);   // a slow sway, easing back after a drag
    step(dt);
    draw(dt);
    requestAnimationFrame(frame);
  }
  function draw(dt = 0) {
    const g = S.ctx, d = S.data, v = S.v;
    S.labels = [];
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    const bg = g.createRadialGradient(S.w * 0.5, S.h * 0.42, 40, S.w * 0.5, S.h * 0.5, Math.max(S.w, S.h) * 0.8);
    bg.addColorStop(0, "#0f2420"); bg.addColorStop(0.55, "#071211"); bg.addColorStop(1, C.floor);
    g.fillStyle = bg; g.fillRect(0, 0, S.w, S.h);
    for (let i = -26; i <= 26; i += 2) {                              // the floor grid, fading with distance
      const al = 0.07 * (1 - Math.abs(i) / 28);
      line3([i, 0, -18], [i, 0, 18], `${C.grid}${al})`, 1);
      line3([-28, 0, i * 0.7], [28, 0, i * 0.7], `${C.grid}${al})`, 1);
    }
    const flow = v.served ? Math.min(2.2, 0.4 + v.served / 40000) : 0.4;
    route(ROUTES.gen, v.tint.gen, flow);
    route(ROUTES.city, v.tint.city, flow);
    route(ROUTES.dc, v.tint.city, 0.3 + 1.6 * v.ours);
    route(ROUTES.campus, v.tint.city, flow);

    const ps = plants(), total = ps.reduce((s, p) => s + p.mw, 0);
    const spots = [[-23, -11], [-16, -11], [-23, -4], [-16, -4], [-23, 3], [-16, 3]];
    const items = [];
    ps.forEach((p, i) => items.push({ x: spots[i][0], z: spots[i][1], draw: () => drawPlant(p, spots[i][0], spots[i][1], total) }));
    items.push({ x: 0, z: 0.5, draw: () => {                         // the substation hub
      platform(-2.4, -1.8, 4.8, 4.6, 0.6);
      for (const [tx, ring] of [[-1.2, C.lineCity], [0.5, C.lineOk]]) {
        box(tx - 0.5, -0.4, 1.0, 1.1, 1.0, { y: 0.36, color: C.steel });
        for (let f = 0; f < 4; f++) box(tx - 0.62, -0.3 + f * 0.26, 0.12, 0.1, 0.8, { y: 0.4, color: [150, 160, 170] });  // cooling fins
        lathe(tx, 0.15, [[0.12, 0], [0.12, 0.6]], { y: 1.36, color: [235, 238, 240], n: 8, stripes: [[0.3, rgb(ring, 0.9)]] });
      }
      pylon(0, 1.7, 3.8);
      label(0, 6.6, 0.4, "Grid", v.served ? `${(v.served / 1000).toFixed(1)} GW` : "—", "served", 4.4);
    } });
    items.push({ x: 13, z: -9, draw: () => {                         // the city: lit windows = served / needed
      platform(8, -13.5, 10, 9, 0.6, v.lit < 0.97 ? `rgba(255,${(90 + 120 * v.lit) | 0},90,0.9)` : null);
      const blocks = [[8.6, -13, 1.6, 1.6, 4.6], [10.6, -13, 1.4, 1.4, 3.4], [12.6, -13, 1.8, 1.6, 5.4], [15, -13, 1.6, 1.8, 4],
        [8.8, -10.6, 1.5, 1.6, 2.8], [10.8, -10.4, 1.8, 1.6, 4.2], [13.2, -10.2, 1.4, 1.4, 2.6], [15.2, -10.4, 1.6, 1.6, 4.8],
        [10, -8, 1.5, 1.4, 2.2], [12.6, -7.9, 1.8, 1.5, 3.2], [15, -7.9, 1.5, 1.4, 2]];
      blocks.map((b, i) => ({ b, i, depth: P(b[0] + b[2] / 2, 0, b[1] + b[3] / 2)[2] })).sort((a, b) => a.depth - b.depth)
        .forEach(({ b: [bx, bz, bw, bd, bh], i }) => tower(bx, bz, bw, bd, bh, i + 11, v.lit));
      label(13, 8.2, -10.5, "City", d.needed ? `${Math.round(v.lit * 100)}% lit` : "—",
        d.needed ? `${(v.served / 1000).toFixed(1)} of ${(v.needed / 1000).toFixed(1)} GW needed` : "", 6.2);
    } });
    items.push({ x: -7, z: 8, draw: () => {                          // our data center: this Mac, measured
      platform(-9.6, 5.7, 5, 4.6, 0.85);
      const on = Math.min(1, v.ours);
      box(-9.1, 6.2, 4.0, 3.6, 2.0, { y: 0.36, color: [222, 232, 240], band: on, edge: true });
      for (let k = 0; k < 3; k++) {                                   // rooftop chillers with fans
        box(-8.7 + k * 1.2, 6.7, 0.9, 0.9, 0.35, { y: 2.36, color: [170, 180, 188] });
        const c = P(-8.25 + k * 1.2, 2.73, 7.15), rr = 5, a = REDUCE ? 0 : S.t * (2 + 8 * on);
        S.ctx.strokeStyle = "rgba(40,50,58,0.9)"; S.ctx.lineWidth = 1.2;
        for (let b = 0; b < 3; b++) { S.ctx.beginPath(); S.ctx.moveTo(c[0], c[1]); S.ctx.lineTo(c[0] + Math.cos(a + b * 2.1) * rr, c[1] + Math.sin(a + b * 2.1) * rr * 0.5); S.ctx.stroke(); }
      }
      glowDot(-7.1, 2.9, 8, 6 + 10 * on, C.mint, REDUCE ? 0.6 : 0.35 + 0.5 * on * (0.75 + 0.25 * Math.sin(S.t * (1 + 4 * on))));
      label(-7.1, 6.2, 8, "This Mac", d.ours_w != null ? `${d.ours_w.toFixed(1)} W` : "—",
        d.cut_pct != null ? `${Math.abs(Math.round(d.cut_pct))}% ${d.cut_pct >= 0 ? "below" : "above"} baseline · measured` : "measured by powermetrics", 3.2);
    } });
    items.push({ x: 9.5, z: 9, draw: () => {                         // the large loads: the grid's data centers
      platform(6.5, 6.5, 7.2, 5.2, 0.55);
      const on = Math.min(1, v.ours);
      [[7, 7, 2.8], [10.1, 7, 2.8], [7, 9.5, 2.8], [10.1, 9.5, 2.8]].forEach(([bx, bz, bw], i) =>
        box(bx, bz, bw, 2, 1.4, { y: 0.36, color: [205, 218, 228], band: on * (0.7 + 0.1 * i), cap: true }));
      if (d.campus) label(10.1, 5.2, 9.3, d.campus.title, d.campus.value, d.campus.sub, 2.1);
    } });
    items.sort((a, b) => P(a.x, 0, a.z)[2] - P(b.x, 0, b.z)[2]);  // far first
    items.forEach((it) => it.draw());
    smoke(dt);
    drawLabels();
  }

  // ------------------------------------------------------------------ smoke: spawned at a rate per second, not per frame
  function smokeFrom(x, y, z, rate, steam) {
    if (REDUCE) return;
    S.smokeAcc += rate * 3 * (S.dt || 0);                             // puffs per second, whatever the frame rate
    while (S.smokeAcc >= 1) {
      S.smokeAcc -= 1;
      const j = S.smoke.length + Math.floor(S.t * 10);
      S.smoke.push({ x, y, z, age: 0, max: 2.2 + 1.6 * hash(j), drift: 0.6 + 0.8 * hash(j + 1), steam: !!steam });
    }
  }
  function smoke(dt) {
    if (REDUCE) { S.smoke = []; return; }
    const g = S.ctx;
    S.smoke = S.smoke.filter((s) => (s.age += dt) < s.max).slice(-260);
    for (const s of S.smoke) {
      const f = s.age / s.max, p = P(s.x + f * s.drift, s.y + f * 2.8, s.z - f * 0.35), r = 2.5 + 13 * f;
      g.fillStyle = s.steam ? `rgba(235,242,245,${0.22 * (1 - f)})` : `rgba(205,212,214,${0.16 * (1 - f)})`;
      g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
    }
  }

  // ------------------------------------------------------------------ mounting and input
  function resize() {
    const r = S.cv.getBoundingClientRect();
    S.dpr = Math.min(2, window.devicePixelRatio || 1);
    S.w = r.width; S.h = r.height;
    S.cv.width = Math.round(r.width * S.dpr); S.cv.height = Math.round(r.height * S.dpr);
    S.cx = S.w * 0.5; S.cy = S.h * 0.43; S.scale = Math.min(S.w / 60, S.h / 46);
    if (!S.running) { step(1); draw(); }
  }
  function mount(canvas) {
    S.cv = canvas; S.ctx = canvas.getContext("2d");
    new ResizeObserver(resize).observe(canvas);
    resize();
    canvas.addEventListener("pointerdown", (e) => { S.drag = { x: e.clientX, y: e.clientY, yaw: S.yaw, pitch: S.pitch }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => {
      if (!S.drag) return;
      S.yaw = S.drag.yaw + (e.clientX - S.drag.x) * 0.006;
      S.pitch = Math.max(0.3, Math.min(1.05, S.drag.pitch + (e.clientY - S.drag.y) * 0.004));
      if (!S.running) draw();
    });
    canvas.addEventListener("pointerup", () => { if (S.drag) S.baseYaw = S.yaw; S.drag = null; });
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); S.scale = Math.max(8, Math.min(60, S.scale * (e.deltaY < 0 ? 1.08 : 0.93))); if (!S.running) draw(); }, { passive: false });
    document.addEventListener("visibilitychange", () => { if (document.hidden) S.running = false; else start(); });
    start();
  }
  function start() {
    if (S.running) return;
    S.running = true; S.last = 0;
    if (REDUCE) { S.running = false; step(1); draw(); return; }
    requestAnimationFrame(frame);
  }
  function set(patch) {
    Object.assign(S.data, patch);
    if (!S.running) { step(1); draw(); }
  }
  // the page's bars, in CSS pixels from the top and bottom edges: labels stay between them
  function safeArea(top, bottom) { S.safe = { top, bottom }; }
  return { mount, set, safeArea };
})();

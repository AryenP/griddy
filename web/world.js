// The grid as a small 3D world (Aryen, Sat 16:30): drawn on one canvas with no library, so it works offline.
// The layout is a schematic; every quantity in it is real and comes from World.set():
//   - power plants: one per fuel in the grid's real generation mix (EIA-930 for a replayed event, the ISO's live
//     fuel mix otherwise); a plant's height follows its share, turbines spin with wind output, panels glow with solar;
//   - the city: the share of lit windows is the demand the grid served over the demand it needed (its own day-ahead
//     forecast), so when the grid sheds load (Uri) the blocks go dark in proportion;
//   - our data center: this Mac, glowing with its measured watts against its baseline;
//   - the lines: light flows at a speed set by the power served; they turn amber on a warning and red in an emergency.
// Motion respects prefers-reduced-motion: no orbit, no flowing light, no smoke; the picture still shows the numbers.
"use strict";

const World = (() => {
  const REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const C = {
    floor: "#05080a", grid: "rgba(160,200,190,", slab: "#10171a", slabTop: "#141d21", edge: "rgba(120,255,200,",
    wall: [214, 226, 230], glass: [96, 170, 255], lit: [255, 214, 140], dark: [30, 38, 44],
    lineOk: [72, 160, 255], lineCity: [70, 230, 150], lineWarn: [255, 190, 70], lineBad: [255, 80, 80],
  };
  const S = {
    cv: null, ctx: null, w: 0, h: 0, dpr: 1, yaw: -0.62, pitch: 0.6, scale: 18, cx: 0, cy: 0,
    drag: null, spin: !REDUCE, last: 0, t: 0, running: false,
    data: { mix: {}, served: null, needed: null, ours_w: null, baseline_w: null, alert: null, campus: null },
    smoke: [],
  };

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
  const area = (pts) => pts.reduce((s, p, i) => { const q = pts[(i + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
  function hash(n) { const x = Math.sin(n * 12.9898) * 43758.5453; return x - Math.floor(x); }

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

  // ------------------------------------------------------------------ primitives
  // A box with shaded faces and, optionally, a grid of windows lit to `lit` (0-1) with stable per-window randomness.
  function box(x, z, w, d, h, o = {}) {
    const y0 = o.y || 0, base = o.color || C.wall;
    const c = [[x, y0, z], [x + w, y0, z], [x + w, y0, z + d], [x, y0, z + d]];
    const t = c.map(([a, , b]) => [a, y0 + h, b]);
    const faces = [[c[0], c[1], t[1], t[0], 0.62], [c[1], c[2], t[2], t[1], 0.78], [c[2], c[3], t[3], t[2], 0.9], [c[3], c[0], t[0], t[3], 0.7]];
    for (const [a, b, e, f, shade] of faces) {
      const pts = [a, b, e, f].map((v) => P(...v));
      if (area(pts) >= 0) continue;                                 // facing away
      poly(pts, rgb(mix([12, 16, 20], base, shade), o.alpha || 1), o.edge ? rgb(base, 0.35) : null, 0.6);
      if (o.windows) windows(a, b, e, f, h, o);
    }
    poly(t.map((v) => P(...v)), rgb(mix([12, 16, 20], base, 1), o.alpha || 1), o.edge ? rgb(base, 0.5) : null, 0.6);
    if (o.glow) {                                                     // a light on the roof: our data center's watts
      const top = P(x + w / 2, y0 + h + 0.2, z + d / 2), g = S.ctx, r = 6 + 26 * o.glow;
      const grd = g.createRadialGradient(top[0], top[1], 0, top[0], top[1], r);
      grd.addColorStop(0, rgb(o.glowColor || C.lineCity, 0.85 * o.glow + 0.1)); grd.addColorStop(1, rgb(o.glowColor || C.lineCity, 0));
      g.globalCompositeOperation = "lighter"; g.fillStyle = grd; g.beginPath(); g.arc(top[0], top[1], r, 0, 7); g.fill();
      g.globalCompositeOperation = "source-over";
    }
  }
  function windows(a, b, e, f, h, o) {
    const rows = Math.max(1, Math.round(h / 0.9)), cols = o.cols || 3, lit = o.lit == null ? 1 : o.lit;
    const at = (u, v) => [a[0] + (b[0] - a[0]) * u, a[1] + (f[1] - a[1]) * v, a[2] + (b[2] - a[2]) * u];
    const g = S.ctx;
    g.globalCompositeOperation = "lighter";
    for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
      const u0 = (k + 0.22) / cols, u1 = (k + 0.78) / cols, v0 = (r + 0.25) / rows, v1 = (r + 0.7) / rows;
      const on = hash((o.seed || 1) * 97 + r * 13 + k * 7 + (a[0] + a[2]) * 3) < lit;
      const pts = [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)].map((v) => P(...v));
      poly(pts, on ? rgb(o.litColor || C.lit, 0.75) : rgb(C.dark, 0.5));
    }
    g.globalCompositeOperation = "source-over";
  }
  function cylinder(x, z, r0, r1, h, o = {}) {
    const n = 16, y0 = o.y || 0, base = o.color || C.wall, ring = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      ring.push([[x + Math.cos(a) * r0, y0, z + Math.sin(a) * r0], [x + Math.cos(a) * r1, y0 + h, z + Math.sin(a) * r1], a]);
    }
    for (let i = 0; i < n; i++) {
      const [b0, t0, a] = ring[i], [b1, t1] = ring[(i + 1) % n];
      const pts = [b0, b1, t1, t0].map((v) => P(...v));
      if (area(pts) >= 0) continue;
      poly(pts, rgb(mix([12, 16, 20], base, 0.55 + 0.4 * Math.max(0, Math.cos(a + S.yaw + 1.2))), o.alpha || 1));
    }
    poly(ring.map(([, t]) => P(...t)), rgb(mix([12, 16, 20], base, 0.95), o.alpha || 1));
    if (o.ring) poly(ring.map(([, t]) => P(t[0], t[1] - h * 0.35, t[2])), null, rgb(o.ring, 0.9), 2);
  }
  function platform(x, z, w, d, edgeAlpha, edgeColor) {
    box(x, z, w, d, 0.35, { color: [26, 34, 38] });
    const pts = [[x, 0.36, z], [x + w, 0.36, z], [x + w, 0.36, z + d], [x, 0.36, z + d]].map((v) => P(...v));
    const g = S.ctx;
    g.save(); g.shadowColor = edgeColor || "rgba(120,255,200,0.9)"; g.shadowBlur = 14;
    poly(pts, null, edgeColor || `rgba(150,255,215,${edgeAlpha})`, 1.4);
    g.restore();
  }
  function label(x, y, z, title, value, sub) {
    const p = P(x, y, z), g = S.ctx;
    g.save(); g.textAlign = "center"; g.shadowColor = "rgba(0,0,0,0.85)"; g.shadowBlur = 8;
    g.font = "600 11px Inter, system-ui, sans-serif"; g.fillStyle = "rgba(200,225,220,0.75)";
    g.fillText(title.toUpperCase(), p[0], p[1] - 20);
    g.font = "300 20px Inter, system-ui, sans-serif"; g.fillStyle = "#f2fbf7";
    g.fillText(value, p[0], p[1]);
    if (sub) { g.font = "500 10.5px Inter, system-ui, sans-serif"; g.fillStyle = "rgba(190,215,210,0.85)"; g.fillText(sub, p[0], p[1] + 14); }
    g.restore();
  }

  // ------------------------------------------------------------------ the routes and their flowing light
  const ROUTES = {
    gen: [[-14, 0.05, -9], [-10.5, 0.05, -9], [-10.5, 0.05, 0.4], [-2.2, 0.05, 0.4]],
    city: [[2.2, 0.05, -0.6], [5.5, 0.05, -0.6], [5.5, 0.05, -8.5], [8, 0.05, -8.5]],
    dc: [[-0.8, 0.05, 2.6], [-0.8, 0.05, 7.5], [-4.5, 0.05, 7.5]],
    campus: [[0.8, 0.05, 2.6], [0.8, 0.05, 8.5], [6, 0.05, 8.5]],
  };
  function routeColor(kind) {
    const a = S.data.alert;
    if (a === "emergency" || a === "outage") return C.lineBad;
    if (a === "warning") return C.lineWarn;
    return kind === "gen" ? C.lineOk : C.lineCity;
  }
  function along(pts, f) {
    const seg = pts.slice(1).map((q, i) => Math.hypot(q[0] - pts[i][0], q[2] - pts[i][2]));
    let d = f * seg.reduce((a, b) => a + b, 0);
    for (let i = 0; i < seg.length; i++) {
      if (d <= seg[i]) { const u = d / seg[i], a = pts[i], b = pts[i + 1]; return [a[0] + (b[0] - a[0]) * u, a[1], a[2] + (b[2] - a[2]) * u]; }
      d -= seg[i];
    }
    return pts[pts.length - 1];
  }
  function route(pts, color, flow) {
    const g = S.ctx, pp = pts.map((v) => P(...v));
    g.save(); g.lineCap = "round"; g.lineJoin = "round";
    g.beginPath(); pp.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
    g.shadowColor = rgb(color, 0.9); g.shadowBlur = 16; g.strokeStyle = rgb(color, 0.35); g.lineWidth = 7; g.stroke();
    g.shadowBlur = 0; g.strokeStyle = rgb(mix(color, [255, 255, 255], 0.55), 0.95); g.lineWidth = 1.6; g.stroke();
    g.restore();
    if (REDUCE || flow <= 0) return;
    g.globalCompositeOperation = "lighter";
    const n = 5;
    for (let i = 0; i < n; i++) {
      const p = P(...along(pts, (S.t * 0.08 * flow + i / n) % 1)), r = 9;
      const grd = g.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
      grd.addColorStop(0, rgb(mix(color, [255, 255, 255], 0.6), 0.95)); grd.addColorStop(1, rgb(color, 0));
      g.fillStyle = grd; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
    }
    g.globalCompositeOperation = "source-over";
  }

  // ------------------------------------------------------------------ the plants, one per real fuel
  const FUELS = [   // [match, title, kind]
    [/gas/i, "Gas", "stacks"], [/coal/i, "Coal", "stacks"], [/nuclear/i, "Nuclear", "towers"], [/wind/i, "Wind", "wind"],
    [/solar/i, "Solar", "solar"], [/hydro/i, "Hydro", "hydro"], [/import/i, "Imports", "tower"],
  ];
  function plants() {
    const m = S.data.mix || {}, out = [];
    for (const [re, title, kind] of FUELS) {
      const mw = Object.entries(m).filter(([k, v]) => re.test(k) && v > 0).reduce((s, [, v]) => s + v, 0);
      if (mw > 0) out.push({ title, kind, mw });
    }
    return out.slice(0, 6);
  }
  function drawPlant(p, x, z, total, peakWind, peakSolar) {
    const share = total ? p.mw / total : 0, gw = `${(p.mw / 1000).toFixed(1)} GW`;
    platform(x - 2, z - 2, 4, 4, 0.55);
    const y = 0.36;
    if (p.kind === "stacks") {
      box(x - 1.4, z - 0.6, 2.2, 1.6, 0.9 + 2.2 * share, { y, color: p.title === "Coal" ? [150, 155, 160] : C.wall, windows: true, cols: 3, lit: 0.6, seed: 3, litColor: C.glass });
      for (let k = 0; k < 2; k++) {
        const sx = x + 0.9 + k * 0.7, sz = z - 0.9 + k * 0.5, sh = 2.2 + 3 * share;
        cylinder(sx, sz, 0.28, 0.22, sh, { y, color: [200, 205, 210] });
        if (!REDUCE && Math.random() < 0.25 + share) S.smoke.push({ x: sx, y: y + sh, z: sz, age: 0, max: 2.4 + 2 * share });
      }
    } else if (p.kind === "towers") {
      cylinder(x - 0.7, z, 1.0, 0.65, 2.6 + 2.5 * share, { y, color: [225, 230, 232] });
      cylinder(x + 1.0, z + 0.4, 0.8, 0.55, 2.2 + 2 * share, { y, color: [225, 230, 232] });
      box(x - 0.2, z - 1.6, 1.4, 0.9, 1.2, { y, color: C.wall, windows: true, cols: 2, lit: 0.7, seed: 5, litColor: C.glass });
    } else if (p.kind === "wind") {
      const speed = peakWind ? p.mw / peakWind : 0;
      for (let k = 0; k < 4; k++) {
        const tx = x - 1.2 + (k % 2) * 2.2, tz = z - 1.1 + Math.floor(k / 2) * 2.0, th = 2.8;
        line3([tx, y, tz], [tx, y + th, tz], "rgba(230,240,240,0.9)", 1.4);
        const a0 = (REDUCE ? 0.3 : S.t * (0.6 + 4 * speed)) + k;
        for (let b = 0; b < 3; b++) {
          const a = a0 + (b * Math.PI * 2) / 3;
          line3([tx, y + th, tz], [tx + Math.cos(a) * 0.9 * Math.cos(S.yaw + 0.9), y + th + Math.sin(a) * 0.9, tz + Math.cos(a) * 0.9 * Math.sin(S.yaw + 0.9)], "rgba(240,250,250,0.95)", 1.1);
        }
      }
    } else if (p.kind === "solar") {
      const glow = peakSolar ? p.mw / peakSolar : 0;
      for (let r = 0; r < 4; r++) for (let k = 0; k < 3; k++) {
        const px = x - 1.6 + k * 1.15, pz = z - 1.5 + r * 0.85;
        const pts = [[px, y + 0.15, pz], [px + 1.0, y + 0.15, pz], [px + 1.0, y + 0.55, pz + 0.55], [px, y + 0.55, pz + 0.55]].map((v) => P(...v));
        poly(pts, rgb(mix([20, 40, 70], C.glass, 0.2 + 0.8 * glow), 0.95), rgb(C.glass, 0.4 + 0.5 * glow), 0.6);
      }
    } else if (p.kind === "hydro") {
      box(x - 1.8, z - 0.4, 3.6, 0.9, 1.6 + 1.5 * share, { y, color: [190, 200, 205] });
      poly([[x - 1.8, y + 0.05, z + 0.6], [x + 1.8, y + 0.05, z + 0.6], [x + 1.8, y + 0.05, z + 1.8], [x - 1.8, y + 0.05, z + 1.8]].map((v) => P(...v)), rgb(C.glass, 0.45));
    } else {
      pylon(x, z, 3.5);
    }
    label(x, y + (p.kind === "solar" ? 2.2 : p.kind === "wind" ? 4.6 : 4.2 + 2.5 * share), z, p.title, gw, null);
  }
  function pylon(x, z, h) {
    const y = 0.36, c = "rgba(200,225,230,0.75)", w = 0.7;
    const legs = [[-w, -w], [w, -w], [w, w], [-w, w]];
    legs.forEach(([a, b]) => line3([x + a, y, z + b], [x + a * 0.25, y + h, z + b * 0.25], c, 1));
    for (let k = 1; k <= 3; k++) {
      const f = k / 3.5, yy = y + h * f, s = 1 - 0.75 * f;
      legs.forEach(([a, b], i) => { const [c2, d2] = legs[(i + 1) % 4]; line3([x + a * s, yy, z + b * s], [x + c2 * s, yy, z + d2 * s], c, 0.8); });
    }
    line3([x - 1.4, y + h * 0.8, z], [x + 1.4, y + h * 0.8, z], c, 1);
  }

  // ------------------------------------------------------------------ the scene
  function frame(now) {
    if (!S.running) return;
    if (S.last && now - S.last < 32) { requestAnimationFrame(frame); return; }   // 30 fps: this page runs on the Mac we measure
    const dt = Math.min(0.05, (now - (S.last || now)) / 1000);
    S.last = now; S.t += dt;
    if (S.spin && !S.drag) S.yaw = -0.62 + 0.28 * Math.sin(S.t * 0.05);   // a slow sway, never turning the city away
    draw();
    requestAnimationFrame(frame);
  }
  function draw() {
    const g = S.ctx, d = S.data;
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    const bg = g.createRadialGradient(S.w * 0.5, S.h * 0.45, 40, S.w * 0.5, S.h * 0.5, Math.max(S.w, S.h) * 0.75);
    bg.addColorStop(0, "#0d1f1a"); bg.addColorStop(1, C.floor);
    g.fillStyle = bg; g.fillRect(0, 0, S.w, S.h);
    for (let i = -24; i <= 24; i += 2) {                              // the floor grid, fading with distance
      const al = 0.06 * (1 - Math.abs(i) / 26);
      line3([i, 0, -18], [i, 0, 18], `${C.grid}${al})`, 1);
      line3([-26, 0, i * 0.75], [26, 0, i * 0.75], `${C.grid}${al})`, 1);
    }
    const served = d.served || 0, flow = served ? Math.min(2.2, 0.4 + served / 40000) : 0.4;
    route(ROUTES.gen, routeColor("gen"), flow);
    route(ROUTES.city, routeColor("city"), flow);
    const ours = d.ours_w != null && d.baseline_w ? Math.min(1.4, d.ours_w / d.baseline_w) : d.ours_w != null ? Math.min(1, d.ours_w / 25) : 0.5;
    route(ROUTES.dc, routeColor("dc"), 0.3 + 1.6 * ours);
    route(ROUTES.campus, routeColor("dc"), flow);

    // generation district, left: the real fuel mix
    const ps = plants(), total = ps.reduce((s, p) => s + p.mw, 0);
    const peakWind = Math.max(1, ...(d.peaks ? [d.peaks.wind || 0] : [0]), ps.find((p) => p.kind === "wind")?.mw || 0);
    const peakSolar = Math.max(1, ...(d.peaks ? [d.peaks.solar || 0] : [0]), ps.find((p) => p.kind === "solar")?.mw || 0);
    const spots = [[-23, -11], [-16, -11], [-23, -4], [-16, -4], [-23, 3], [-16, 3]];
    const items = [];
    ps.forEach((p, i) => items.push({ z: spots[i][1], x: spots[i][0], draw: () => drawPlant(p, spots[i][0], spots[i][1], total, peakWind, peakSolar) }));
    // the substation hub, centre
    items.push({ x: 0, z: 0.5, draw: () => {
      platform(-2.2, -1.6, 4.4, 4.2, 0.6);
      cylinder(-1, 0.2, 0.55, 0.55, 1.2, { y: 0.36, color: [200, 210, 215], ring: C.lineCity });
      cylinder(0.6, 0.2, 0.55, 0.55, 1.2, { y: 0.36, color: [200, 210, 215], ring: C.lineOk });
      pylon(0, 1.6, 3.8);
      label(0, 5.6, 0.5, "Grid", d.served != null ? `${(d.served / 1000).toFixed(1)} GW` : "—", "served");
    } });
    // the city, right: lit windows = demand served / demand needed
    const lit = d.needed ? Math.max(0, Math.min(1, served / d.needed)) : 1;
    items.push({ x: 13, z: -9, draw: () => {
      platform(8, -13.5, 10, 9, 0.6, lit < 0.97 ? "rgba(255,90,90,0.9)" : null);
      const blocks = [[8.6, -13, 1.6, 1.6, 4.6], [10.6, -13, 1.4, 1.4, 3.4], [12.6, -13, 1.8, 1.6, 5.4], [15, -13, 1.6, 1.8, 4],
        [8.8, -10.6, 1.5, 1.6, 2.8], [10.8, -10.4, 1.8, 1.6, 4.2], [13.2, -10.2, 1.4, 1.4, 2.6], [15.2, -10.4, 1.6, 1.6, 4.8],
        [10, -8, 1.5, 1.4, 2.2], [12.6, -7.9, 1.8, 1.5, 3.2], [15, -7.9, 1.5, 1.4, 2]];
      blocks.sort((a, b) => P(a[0], 0, a[1])[2] - P(b[0], 0, b[1])[2]);
      blocks.forEach(([bx, bz, bw, bd, bh], i) => box(bx, bz, bw, bd, bh, { y: 0.36, color: [205, 225, 240], windows: true, cols: 3, lit, seed: i + 11 }));
      label(13, 7.4, -10.5, "City", d.needed ? `${Math.round(lit * 100)}% lit` : "—",
        d.needed ? `${(served / 1000).toFixed(1)} of ${(d.needed / 1000).toFixed(1)} GW needed` : "");
    } });
    // our data center, front: this Mac, measured
    items.push({ x: -7, z: 8, draw: () => {
      platform(-9.5, 5.8, 4.8, 4.4, 0.85);
      box(-9, 6.3, 3.8, 3.4, 2.2, { y: 0.36, color: [220, 232, 240], windows: true, cols: 4, lit: Math.min(1, ours), seed: 7, litColor: [120, 255, 190], glow: Math.min(1, ours), edge: true });
      for (let k = 0; k < 3; k++) box(-8.6 + k * 1.15, 6.8, 0.7, 0.7, 0.35, { y: 2.56, color: [180, 190, 195] });
      label(-7.1, 3.4, 8, "This Mac", d.ours_w != null ? `${d.ours_w.toFixed(1)} W` : "—",
        d.cut_pct != null ? `${Math.abs(Math.round(d.cut_pct))}% ${d.cut_pct >= 0 ? "below" : "above"} its baseline, measured` : "measured by powermetrics");
    } });
    // the large loads campus, front right: the grid's data centers (a cited figure, or a stated unit)
    items.push({ x: 9.5, z: 9, draw: () => {
      platform(6.5, 6.5, 7, 5, 0.55);
      [[7, 7, 2.6], [9.9, 7, 2.6], [7, 9.4, 2.6], [9.9, 9.4, 2.6]].forEach(([bx, bz, bw], i) =>
        box(bx, bz, bw, 2, 1.5, { y: 0.36, color: [200, 215, 225], windows: true, cols: 4, lit: Math.min(1, ours), seed: 30 + i, litColor: [120, 255, 190] }));
      if (d.campus) label(10, 4.2, 9, d.campus.title, d.campus.value, d.campus.sub);
    } });
    items.sort((a, b) => P(a.x, 0, a.z)[2] - P(b.x, 0, b.z)[2]);  // far first
    items.forEach((it) => it.draw());
    smoke();
  }
  function smoke() {
    if (REDUCE) { S.smoke = []; return; }
    const g = S.ctx;
    S.smoke = S.smoke.filter((s) => (s.age += 0.016) < s.max).slice(-240);
    for (const s of S.smoke) {
      const f = s.age / s.max, p = P(s.x + f * 1.2, s.y + f * 3.2, s.z - f * 0.4), r = 3 + 14 * f;
      g.fillStyle = `rgba(225,235,235,${0.18 * (1 - f)})`; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
    }
  }

  // ------------------------------------------------------------------ mounting and input
  function resize() {
    const r = S.cv.getBoundingClientRect();
    S.dpr = Math.min(2, window.devicePixelRatio || 1);
    S.w = r.width; S.h = r.height;
    S.cv.width = Math.round(r.width * S.dpr); S.cv.height = Math.round(r.height * S.dpr);
    S.cx = S.w * 0.5; S.cy = S.h * 0.43; S.scale = Math.min(S.w / 60, S.h / 46);
    if (!S.running) draw();
  }
  function mount(canvas) {
    S.cv = canvas; S.ctx = canvas.getContext("2d");
    new ResizeObserver(resize).observe(canvas);
    resize();
    canvas.addEventListener("pointerdown", (e) => { S.drag = { x: e.clientX, y: e.clientY, yaw: S.yaw, pitch: S.pitch }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => {
      if (!S.drag) return;
      S.yaw = S.drag.yaw + (e.clientX - S.drag.x) * 0.006;
      S.pitch = Math.max(0.25, Math.min(1.05, S.drag.pitch + (e.clientY - S.drag.y) * 0.004));
      if (!S.running) draw();
    });
    canvas.addEventListener("pointerup", () => { S.drag = null; });
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); S.scale = Math.max(8, Math.min(60, S.scale * (e.deltaY < 0 ? 1.08 : 0.93))); if (!S.running) draw(); }, { passive: false });
    document.addEventListener("visibilitychange", () => { if (document.hidden) S.running = false; else start(); });
    start();
  }
  function start() {
    if (S.running) return;
    S.running = true; S.last = 0;
    if (REDUCE) { S.running = false; draw(); return; }
    requestAnimationFrame(frame);
  }
  function set(patch) {
    Object.assign(S.data, patch);
    if (!S.running) draw();
  }
  return { mount, set };
})();

// The operator page's feel (Aryen, Sun 06:05: "clean animations, ping sounds, refreshing dynamics"): a short ping
// when a request lands and a soft one when it is answered (Web Audio, synthesised: no sound files), numbers that
// glide to their new value, and the last two minutes of measured watts as a sparkline. Motion stops under
// prefers-reduced-motion; the sound toggle is remembered on this device.
"use strict";

const OpFx = (() => {
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  let ctx = null, on = true;
  try { on = localStorage.getItem("griddy.operator.sound") !== "off"; } catch { /* private mode: sound stays on */ }

  function audio() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }
  // Browsers start audio only after a gesture on the page: the first click or key unlocks it.
  for (const ev of ["pointerdown", "keydown"]) addEventListener(ev, () => { if (on) audio(); }, { once: true, capture: true });

  function tone(a, f, t0, dur, gain) {
    const o = a.createOscillator(), g = a.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(f, t0);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g).connect(a.destination);
    o.start(t0); o.stop(t0 + dur + 0.05);
  }
  // [frequency Hz, start s, length s, gain]
  const SOUNDS = {
    ask: [[880, 0, 0.45, 0.14], [1318.5, 0.12, 0.6, 0.12]],    // two rising notes: something needs you
    done: [[659.3, 0, 0.4, 0.07], [987.8, 0.07, 0.5, 0.05]],    // a soft chord: answered
  };
  function ping(kind = "ask") {
    if (!on) return;
    const a = audio();
    if (!a) return;
    const t = a.currentTime + 0.02;
    for (const [f, dt, len, gain] of SOUNDS[kind] || SOUNDS.ask) tone(a, f, t + dt, len, gain);
  }

  function setSound(next, btn) {
    on = next;
    try { localStorage.setItem("griddy.operator.sound", on ? "on" : "off"); } catch { /* not remembered */ }
    if (btn) { btn.setAttribute("aria-pressed", String(on)); btn.title = on ? "Sound on: a ping when a request arrives" : "Sound off"; }
    if (on) ping("done");
  }
  function bindSound(btn) {
    if (!btn) return;
    btn.setAttribute("aria-pressed", String(on));
    btn.title = on ? "Sound on: a ping when a request arrives" : "Sound off";
    btn.addEventListener("click", () => setSound(!on, btn));
  }

  // The number glides from what it showed to `to` (ease-out, 450 ms); "—" when there is no value.
  function tween(el, to, digits = 1, ms = 450) {
    if (!el) return;
    if (to == null || !isFinite(to)) { cancelAnimationFrame(el._raf); el._v = null; el.textContent = "—"; return; }
    const from = el._v;
    el._v = to;
    if (reduce || from == null || Math.abs(to - from) < 10 ** -digits / 2) { el.textContent = to.toFixed(digits); return; }
    cancelAnimationFrame(el._raf);
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - (1 - k) ** 3;
      el.textContent = (from + (to - from) * e).toFixed(digits);
      if (k < 1) el._raf = requestAnimationFrame(step);
    };
    el._raf = requestAnimationFrame(step);
  }

  // A short lift on a count or badge that just changed.
  function bump(el) {
    if (!el || reduce) return;
    el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
  }

  // Sparkline of measured watts over the last `span` s in an <svg viewBox="0 0 W H"> that holds
  // path.op-spark-area, polyline.op-spark-line and line.op-spark-cap; `cap` in watts or null.
  function spark(svg, pts, cap, span = 120) {
    if (!svg || !pts.length) return;
    const [, , W, H] = svg.getAttribute("viewBox").split(" ").map(Number);
    const tEnd = pts[pts.length - 1].t;
    span = Math.min(span, Math.max(20, tEnd - pts[0].t));     // fewer readings than the span: stretch what there is
    const tStart = tEnd - span;
    const win = pts.filter((p) => p.t >= tStart);
    if (win.length < 2) return;
    let lo = Math.min(...win.map((p) => p.w)), hi = Math.max(...win.map((p) => p.w));
    if (cap != null) { lo = Math.min(lo, cap); hi = Math.max(hi, cap); }
    const pad = Math.max(1, (hi - lo) * 0.15);
    lo -= pad; hi += pad;
    const x = (t) => ((t - tStart) / span) * W, y = (w) => H - ((w - lo) / (hi - lo)) * H;
    const line = win.map((p) => `${x(p.t).toFixed(1)},${y(p.w).toFixed(1)}`).join(" ");
    svg.querySelector(".op-spark-line").setAttribute("points", line);
    svg.querySelector(".op-spark-area").setAttribute("d", `M${x(win[0].t).toFixed(1)},${H} L${line.replaceAll(" ", " L")} L${x(tEnd).toFixed(1)},${H} Z`);
    svg.classList.toggle("capped", cap != null);
    if (cap != null) {
      const c = svg.querySelector(".op-spark-cap");
      c.setAttribute("y1", y(cap).toFixed(1)); c.setAttribute("y2", y(cap).toFixed(1));
    }
  }

  return { ping, bindSound, tween, bump, spark, reduce };
})();

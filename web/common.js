// Shared by every page: escaping, formatting, the HTTP/WebSocket calls (HANDOFF.md contract).
// The only innerHTML write in web/ is setHTML(), and it accepts only html`...` output, whose
// interpolations are escaped. So text from the server can reach the DOM only escaped or as textContent.
"use strict";

const $ = (id) => document.getElementById(id);

// Moving between Grid, Info and Proof (Aryen, Sat 23:45: "a cut feeling, not smooth"): Chrome prerenders the other
// two pages when the pointer rests on their links, so a click shows a page that has already loaded its data and drawn
// its charts, and chrome.css cross-fades into it. Browsers without speculation rules just load the page as before.
try {
  if (HTMLScriptElement.supports && HTMLScriptElement.supports("speculationrules")) {
    const rules = document.createElement("script");
    rules.type = "speculationrules";
    rules.textContent = JSON.stringify({ prerender: [{ source: "list", eagerness: "moderate",
      urls: ["/", "/info.html", "/proof.html"].filter((u) => u !== location.pathname) }] });
    document.head.append(rules);
  }
} catch (e) { /* no prerender: navigation works as before */ }

// A time as ISO 8601 with this browser's own offset ("2026-10-25T00:46:00-07:00"), so a deadline the page sends
// reads in local time everywhere it is shown, the owner's phone included (not "07:46" in UTC).
function localISO(d) {
  const off = -d.getTimezoneOffset(), a = Math.abs(off), p = (x) => String(x).padStart(2, "0");
  return `${new Date(d.getTime() + off * 60000).toISOString().slice(0, 19)}${off >= 0 ? "+" : "-"}${p(Math.floor(a / 60))}:${p(a % 60)}`;
}

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

// Phone chat (served at /chat). POST /api/chat/stream returns NDJSON: {"delta"} lines as tokens arrive,
// then {"done", latency_s, ttft_s, tokens, max_tokens}, or {"error"}. Timings are the server's measurement.
"use strict";

const convo = [];          // [{role, content}] sent with each request so the model keeps the thread
const KEEP = 12;             // messages of context sent back (bounded so requests stay small)
let sla = null;

async function loadInfo() {
  const r = await getJSON("/api/state");
  if (!r.ok) { $("model").textContent = `model: unknown (${routeError("/api/state", r)})`; return; }
  const c = (r.data.jobs || {}).chat || {};
  sla = r.data.policy && r.data.policy.sla ? r.data.policy.sla.chat_ttft_p95_s : null;
  $("model").textContent = `model: ${c.model || "unknown"} on the demo Mac` +
    (c.concurrency != null ? ` · ${c.concurrency} concurrent streams allowed right now` : "") +
    (sla != null ? ` · SLA: time to first token p95 ≤ ${sla} s` : "") + (c.t ? ` · status ${age(c.t)}` : "");
}

function bubble(role, text) {
  const empty = $("thread").querySelector(".empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.className = `msg ${role}`;
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;
  li.appendChild(body);
  const meta = document.createElement("div");
  meta.className = "meta";
  li.appendChild(meta);
  $("thread").appendChild(li);
  li.scrollIntoView({ block: "end" });
  return { li, body, meta };
}

function showDone(meta, d) {
  const late = sla != null && d.ttft_s > sla;
  setHTML(meta, html`<span class="${late ? "bad-text" : ""}">first token ${fixed(d.ttft_s, 2)} s</span> · total ${fixed(d.latency_s, 1)} s · ${d.tokens != null ? d.tokens : "?"} tokens (max ${d.max_tokens != null ? d.max_tokens : "?"}) · measured by the server · ${localClock(nowS())}`);
}

// Reads NDJSON lines as they arrive; falls back to the whole body where streaming reads are unsupported.
async function* ndjson(resp) {
  if (!resp.body || !resp.body.getReader) {
    for (const line of (await resp.text()).split("\n")) if (line.trim()) yield JSON.parse(line);
    return;
  }
  const reader = resp.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let k;
    while ((k = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, k).trim();
      buf = buf.slice(k + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buf.trim()) yield JSON.parse(buf);
}

async function send(text) {
  convo.push({ role: "user", content: text });
  bubble("user", text);
  const out = bubble("assistant", "");
  out.meta.textContent = "waiting for the first token…";
  out.li.classList.add("pending");
  $("send").disabled = true;
  let reply = "", finished = false;
  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: convo.slice(-KEEP) }),
    });
    if (!resp.ok) throw new Error(`${resp.status} ${(await resp.text()).slice(0, 200)}`);
    for await (const ev of ndjson(resp)) {
      if (ev.delta != null) {
        reply += ev.delta;
        out.body.textContent = reply;
        if (out.li.classList.contains("pending")) { out.li.classList.remove("pending"); out.meta.textContent = "writing…"; }
      } else if (ev.done) {
        finished = true;
        showDone(out.meta, ev);
      } else if (ev.error) {
        throw new Error(ev.error);
      }
    }
    if (!finished) throw new Error("the stream ended without a final timing line");
    convo.push({ role: "assistant", content: reply });
  } catch (e) {
    out.li.classList.remove("pending");
    out.li.classList.add("error");
    out.meta.textContent = `chat failed: ${e.message}`;
    if (reply) convo.push({ role: "assistant", content: reply }); else convo.pop();
  } finally {
    $("send").disabled = false;
  }
}

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("msg").value.trim();
  if (!text || $("send").disabled) return;
  $("msg").value = "";
  send(text);
});
$("msg").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("form").requestSubmit(); }
});
loadInfo();

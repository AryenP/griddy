// Job owner's phone console (owner.html). Owners come from the snapshot's job_specs (or ?owner= in the
// URL); requests from GET /api/approvals?owner= and live `approval` events on /ws.
"use strict";

const O = { owner: null, specs: {}, jobs: {}, schedule: null, reqs: new Map(), agent: null, agentModel: null, loadedT: null, loadErr: null };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: the page works without it */ } },
};

const board = new ApprovalBoard($("requests"), {
  filter: (q) => q.owner === O.owner,
  who: () => $("who").value.trim() || O.owner,
  schedule: () => O.schedule,
  empty: () => O.owner ? `Nothing waiting for ${O.owner}. When the solver needs to move one of your jobs, the request appears here.` : "Pick who you are above.",
  placeholder: "e.g. approve · or: no, this has to finish by 9 AM Monday",
});

function owners() { return [...new Set(Object.values(O.specs).map((j) => j.owner).filter(Boolean))]; }

// Default owner: ?owner=, else the last one picked here, else the owner of the first job with a deadline.
function pickOwner() {
  const list = owners();
  const url = new URLSearchParams(location.search).get("owner");
  if (url) return url;
  const saved = store.get("brownout.owner");
  if (saved && list.includes(saved)) return saved;
  const withDeadline = Object.values(O.specs).find((j) => j.deadline);
  return withDeadline ? withDeadline.owner : list[0] || null;
}

function renderOwnerSelect() {
  const list = owners();
  if (O.owner && !list.includes(O.owner)) list.push(O.owner);   // ?owner= someone not in job_specs (e.g. the operator)
  const want = list.join(",");
  const sel = $("owner");
  if (sel.dataset.opts !== want) {
    setHTML(sel, html`${list.map((o) => html`<option value="${o}">${o}${Object.values(O.specs).some((j) => j.owner === o) ? ` (${Object.values(O.specs).filter((j) => j.owner === o).map((j) => j.id).join(", ")})` : ""}</option>`)}`);
    sel.dataset.opts = want;
  }
  if (O.owner) sel.value = O.owner;
}

function setOwner(o) {
  if (o === O.owner) return;
  O.owner = o;
  store.set("brownout.owner", o);
  const u = new URL(location.href);
  u.searchParams.set("owner", o);
  history.replaceState(null, "", u);
  if (!$("who").value || $("who").dataset.auto === "1") { $("who").value = o; $("who").dataset.auto = "1"; }
  board.reset();
  for (const q of O.reqs.values()) board.upsert(q);
  renderOwnerSelect(); renderMine(); loadPending();
}

async function loadPending() {
  if (!O.owner) return;
  const owner = O.owner;
  const r = await getJSON(`/api/approvals?owner=${encodeURIComponent(owner)}&status=pending`);
  if (owner !== O.owner) return;
  if (!r.ok) { O.loadErr = routeError("/api/approvals", r); renderSrc(); return; }
  O.loadErr = null; O.loadedT = nowS();
  for (const q of r.data || []) { O.reqs.set(q.id, q); board.upsert(q); }
  renderSrc();
}

function renderSrc() {
  $("requests-src").textContent = O.loadErr ? O.loadErr
    : `pending requests from /api/approvals, ${O.loadedT ? `loaded ${age(O.loadedT)}` : "loading"}; new ones arrive live`;
}

function renderMine() {
  const mine = Object.values(O.specs).filter((j) => j.owner === O.owner);
  if (!O.owner) { setHTML($("mine"), html`<p class="empty">pick who you are above</p>`); return; }
  if (!mine.length) { setHTML($("mine"), html`<p class="empty">${O.owner} owns no jobs in config/jobs.yaml</p>`); return; }
  setHTML($("mine"), html`${mine.map((j) => {
    const st = O.jobs[j.id] || {};
    return html`<div class="mine-job">
      <div class="job-head"><h3>${j.id}</h3><span class="badge state-${st.state || "none"}">${st.state || "no status"}</span></div>
      <div class="kv"><b>deadline</b> ${j.deadline ? isoLabel(j.deadline) : "none"}</div>
      <div class="kv"><b>plan</b> ${jobPlanLine(O.schedule, j.id)}</div>
      <div class="src">${st.t ? `job status ${age(st.t)}` : "no job status yet"} · ${O.schedule ? `schedule solved ${age(O.schedule.solve_t)}` : "no schedule yet"}</div>
    </div>`;
  })}`);
}

function renderAgent() {
  const a = $("agent");
  a.textContent = O.agent === "online" ? `agent online${O.agentModel ? ` · ${O.agentModel}` : ""}` : O.agent === "offline" ? "agent offline: replies read by rules" : "agent ?";
  a.className = "badge " + (O.agent === "online" ? "ok" : "warn");
}

function handle(msg) {
  const d = msg.data || {};
  switch (msg.kind) {
    case "snapshot":
      O.specs = d.job_specs || {}; O.jobs = d.jobs || {}; O.schedule = d.schedule || null;
      O.agent = d.agent; O.agentModel = d.agent_model || null;
      for (const q of d.approvals || []) O.reqs.set(q.id, q);
      renderAgent();
      if (!O.owner) setOwner(pickOwner());
      else { for (const q of O.reqs.values()) board.upsert(q); loadPending(); }
      renderOwnerSelect(); renderMine();
      break;
    case "approval":
      if (d.decision && d.request_id) board.decided(d);
      else if (d.id) { O.reqs.set(d.id, { ...(O.reqs.get(d.id) || {}), ...d }); board.upsert(O.reqs.get(d.id)); }
      break;
    case "schedule": O.schedule = d; board.onSchedule(d); renderMine(); break;
    case "state": if (d.job) { O.jobs[d.job] = d; } break;
    case "policy":
      if (d.reason === "job change" && O.specs[d.job] && d.changes && "deadline" in d.changes) { O.specs[d.job].deadline = d.changes.deadline; renderMine(); }
      break;
  }
}

$("owner").addEventListener("change", (e) => setOwner(e.target.value));
$("who").addEventListener("input", () => { $("who").dataset.auto = "0"; store.set("brownout.who", $("who").value); });
const savedWho = store.get("brownout.who");
if (savedWho) { $("who").value = savedWho; $("who").dataset.auto = "0"; }
setInterval(() => { renderMine(); renderSrc(); }, 5000);
window.brownout = { handle };   // the WebSocket's handler, exposed for feeding real timelines from the console
connectWS(handle, $("conn"));

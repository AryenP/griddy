// Approval cards, shared by owner.html and operator.html. One card per ApprovalRequest (core/types.py):
// the negotiator's message, the solver's shortfall facts, a free-text reply box that posts to
// POST /api/approvals/{id}/reply, then the parsed OwnerDecision and what the schedule did.
// Cards are DOM nodes updated in place, so a half-typed reply survives live updates.
"use strict";

const DECISION_LABEL = { approve: "APPROVED", refuse: "REFUSED", new_deadline: "NEW DEADLINE", unclear: "NOT UNDERSTOOD" };
const STATUS_CLASS = { pending: "warn", approved: "ok", countered: "ok", refused: "bad", expired: "" };

function shortfallFacts(sf) {
  if (!sf) return "no shortfall attached";
  const what = sf.kind === "deadline" ? `${sf.job_id || "job"} would finish ${sig(sf.amount)} min after its deadline`
    : sf.kind === "cap" ? `the plan goes ${sig(sf.amount)} W over the cap`
    : `chat SLA: ${sig(sf.amount)}`;
  return `${sf.kind} shortfall: ${what}`;
}

class ApprovalBoard {
  // opts: filter(req) -> bool, who() -> name, schedule() -> current Schedule, empty() -> text, placeholder
  constructor(box, opts) { this.box = box; this.opts = opts; this.cards = new Map(); this.renderEmpty(); }

  reset() { this.cards.clear(); this.box.replaceChildren(); this.renderEmpty(); }

  renderEmpty() {
    let e = this.box.querySelector(".board-empty");
    if (this.cards.size) { if (e) e.remove(); return; }
    if (!e) { e = document.createElement("p"); e.className = "empty board-empty"; this.box.appendChild(e); }
    e.textContent = this.opts.empty();
  }

  upsert(req) {
    if (!req || !req.id || !this.opts.filter(req)) return;
    let c = this.cards.get(req.id);
    if (!c) { c = this.build(req); this.cards.set(req.id, c); this.box.prepend(c.el); }
    c.req = { ...c.req, ...req };
    this.paint(c);
    this.renderEmpty();
  }

  // {"request_id", "who", "decision": OwnerDecision} from the WebSocket (a reply from any device).
  decided(d) {
    const c = this.cards.get(d.request_id);
    if (!c || c.sent) return;            // our own reply is shown from the POST response
    c.decision = d.decision; c.decidedBy = d.who; c.before = c.before || this.opts.schedule();
    c.awaiting = d.decision && d.decision.decision !== "unclear";
    this.paint(c);
  }

  // A new schedule after someone else's reply: that is the resulting change.
  onSchedule(sc) {
    for (const c of this.cards.values()) {
      if (c.awaiting) { c.after = sc; c.awaiting = false; this.paint(c); }
    }
  }

  build(req) {
    const el = document.createElement("article");
    el.className = "ask";
    const head = document.createElement("div"); head.className = "ask-head";
    const msg = document.createElement("p"); msg.className = "ask-msg";
    const facts = document.createElement("div"); facts.className = "ask-facts";
    const form = document.createElement("form"); form.className = "ask-reply";
    const ta = document.createElement("textarea");
    ta.rows = 2; ta.maxLength = 4000; ta.required = true;
    ta.placeholder = this.opts.placeholder || "Reply in your own words";
    ta.setAttribute("aria-label", "your reply");
    const row = document.createElement("div"); row.className = "btn-row";
    const btn = document.createElement("button"); btn.type = "submit"; btn.className = "primary"; btn.textContent = "Send reply";
    const note = document.createElement("span"); note.className = "src";
    row.append(btn, note);
    form.append(ta, row);
    const decisionEl = document.createElement("div"); decisionEl.className = "ask-decision";
    const changeEl = document.createElement("div"); changeEl.className = "ask-change";
    el.append(head, msg, facts, form, decisionEl, changeEl);
    const c = { el, head, msg, facts, form, ta, btn, note, decisionEl, changeEl, req };
    form.addEventListener("submit", (e) => { e.preventDefault(); this.reply(c); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
    });
    return c;
  }

  async reply(c) {
    const text = c.ta.value.trim();
    if (!text || c.btn.disabled) return;
    const who = this.opts.who();
    c.btn.disabled = true;
    c.note.textContent = "sending: the agent reads your reply, the solver re-plans…";
    const before = this.opts.schedule();
    const path = `/api/approvals/${encodeURIComponent(c.req.id)}/reply`;
    const r = await postJSON(path, { text, who });
    c.btn.disabled = false;
    if (!r.ok) { c.note.textContent = `not sent: ${routeError(path, r)}`; return; }
    c.note.textContent = "";
    c.sent = true;
    c.decision = r.data.decision; c.decidedBy = who; c.before = before; c.after = r.data.schedule; c.awaiting = false;
    c.replyT = nowS();
    if (c.decision && c.decision.decision !== "unclear") c.ta.value = "";
    else c.sent = false;                 // still pending: let the next reply (from anywhere) show too
    this.paint(c);
  }

  paint(c) {
    const q = c.req;
    setHTML(c.head, html`<b>${q.job_id === "power_cap" ? "power cap" : q.job_id}</b>
      <span class="badge ${STATUS_CLASS[q.status] || ""}">${q.status}</span>
      <span class="src">to ${q.owner} · asked ${q.t ? `${localClock(q.t)} (${age(q.t)})` : "time unknown"} · ${q.id}</span>`);
    c.msg.textContent = q.message;
    setHTML(c.facts, html`<div>${shortfallFacts(q.shortfall)}</div>${q.shortfall && q.shortfall.message ? html`<div class="src">solver: ${q.shortfall.message}</div>` : ""}`);
    // closed once the server says so, or once our own reply was understood (its status event may lag)
    c.form.hidden = q.status !== "pending" || (c.sent && c.decision && c.decision.decision !== "unclear");
    c.el.classList.toggle("closed", q.status !== "pending");
    c.el.classList.toggle("expired", q.status === "expired");

    const d = c.decision;
    if (d) {
      const lines = [html`<div class="decision-line"><span class="badge ${d.decision === "unclear" ? "warn" : d.decision === "refuse" ? "bad" : "ok"}">${DECISION_LABEL[d.decision] || d.decision}</span>
        ${d.new_deadline ? html` <b>${isoLabel(d.new_deadline)}</b>` : ""}${d.reason ? html` · “${d.reason}”` : ""}</div>`];
      lines.push(html`<div class="src">${c.decidedBy ? `${c.decidedBy} wrote` : "reply"}: “${d.raw}” · read by ${d.llm_used ? "the agent" : "rules (agent offline)"}${c.replyT ? ` · ${localClock(c.replyT)}` : ""}</div>`);
      if (d.decision === "unclear") lines.push(html`<div class="warn-line">Not understood, nothing changed. Say approve, no (and why), or a new time.</div>`);
      setHTML(c.decisionEl, html`${lines}`);
    } else if (q.status === "expired") {
      setHTML(c.decisionEl, html`<div class="src">no longer needed${q.why ? `: ${q.why}` : ""}</div>`);
    } else if (q.status !== "pending") {
      setHTML(c.decisionEl, html`<div class="src">${q.status}${q.who ? ` by ${q.who}` : ""}${q.decided_t ? ` at ${localClock(q.decided_t)}` : ""}</div>`);
    } else {
      setHTML(c.decisionEl, html``);
    }

    if (d && d.decision !== "unclear") {
      const job = q.job_id;
      const was = c.before ? jobPlanLine(c.before, job) : "previous schedule not known on this page";
      const now = c.after ? jobPlanLine(c.after, job) : c.awaiting ? "waiting for the re-plan…" : "no re-plan was needed";
      const sfs = c.after ? c.after.shortfalls.filter((s) => s.job_id !== job || s.kind !== "deadline") : [];
      setHTML(c.changeEl, html`<div class="change-h">Schedule change</div><div class="was">before: ${was}</div><div class="now">after: ${now}</div>
        ${sfs.map((s) => html`<div class="warn-line">still short (${s.kind}${s.job_id ? `, ${s.job_id}` : ""}): ${s.message}</div>`)}`);
    } else {
      setHTML(c.changeEl, html``);
    }
  }
}

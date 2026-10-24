"""Run evals/cases.yaml against the agent layer's real functions. Offline by default (`agent.llm.LLM()`, the
deterministic paths only); `live=True` uses `agent.llm.get_llm()`. Every row records which mode answered it.

Statuses: pass, fail, needs_llm (the case needs a model and none is configured; the system said
"agent offline" instead of acting, which is safe but not an answer)."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from agent.explainer import REFUSAL, answer, explain, grid_facts, state_facts, ungrounded
from agent.intake import parse_openadr, parse_request
from agent.llm import LLM, OFFLINE, get_llm
from agent.negotiator import parse_reply
from core.types import ApprovalRequest, GridSignal, Schedule, Shortfall

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("cases.yaml")
CATEGORY_ORDER = ["plain", "policy", "lookalike", "messy", "ambiguous", "out_of_scope", "injection",
                  "openadr", "owner_reply", "explainer"]


@dataclass
class Row:
    suite: str
    category: str
    id: str
    path: str                  # regex | llm | deterministic: which code path the case is meant for
    status: str                # pass | fail | needs_llm
    mode: str                  # "offline" or the model name that was configured
    expected: str
    got: str
    input: str
    llm_used: bool = False


@dataclass
class Result:
    mode: str
    rows: list[Row] = field(default_factory=list)

    def by_category(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.rows:
            c = out.setdefault(r.category, {"pass": 0, "fail": 0, "needs_llm": 0})
            c[r.status] += 1
        order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
        return dict(sorted(out.items(), key=lambda kv: order.get(kv[0], len(order))))


def load_cases(path: Path = CASES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-6


def _offline_answer(*texts: str | None) -> bool:
    return any(t and OFFLINE in t for t in texts)


# ---------------------------------------------------------------------------
# intake (free text)
# ---------------------------------------------------------------------------

def _check_intake(case: dict, r) -> tuple[bool, str]:
    got = r.kind
    if r.cap_event:
        c = r.cap_event
        got += f" pct={c.target_pct} w={c.target_w} dur={c.duration_s}s"
    if r.policy:
        got += f" objective={r.policy.objective} never_pause={r.policy.never_pause}"
    if r.question:
        got += f" q={r.question!r}"
    ok = r.kind == case["expect"]
    if ok and case["expect"] == "cap_event":
        c = r.cap_event
        ok = ((("target_pct" not in case) or _close(c.target_pct, case["target_pct"])) and
              (("target_w" not in case) or _close(c.target_w, case["target_w"])) and
              (("duration_s" not in case) or c.duration_s == case["duration_s"]))
    if ok and case["expect"] == "policy" and "objective" in case:
        ok = r.policy.objective == case["objective"]
    return ok, got


def _expected_intake(case: dict) -> str:
    extra = [f"{k}={case[k]}" for k in ("target_pct", "target_w", "duration_s", "objective") if k in case]
    return " ".join([case["expect"], *extra])


async def _run_intake(cases: dict, llm: LLM, mode: str) -> list[Row]:
    ctx = cases["intake_context"]
    context = {"now": ctx["now"], "baseline_w": ctx["baseline_w"], "jobs": [{"id": j} for j in ctx["jobs"]]}
    rows = []
    for case in cases["intake"]:
        r = await parse_request(case["text"], llm, context)
        ok, got = _check_intake(case, r)
        # The offline fallback is itself a clarify, so an LLM-path case answered "agent offline" proves nothing
        # either way. A regex-path case that fell through to the absent LLM is a regex failure.
        offline = not llm.available and _offline_answer(r.readback, r.question)
        status = "needs_llm" if (case["path"] == "llm" and offline) else "pass" if ok and not offline else "fail"
        rows.append(Row("intake", case["category"], case["id"], case["path"], status, mode,
                        _expected_intake(case), got, case["text"], r.llm_used))
    return rows


# ---------------------------------------------------------------------------
# OpenADR (deterministic parser)
# ---------------------------------------------------------------------------

def _set_path(obj: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    for k in keys[:-1]:
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    last = keys[-1]
    if isinstance(obj, list):
        obj[int(last)] = value
    else:
        obj[last] = value


def _run_openadr(cases: dict, mode: str) -> list[Row]:
    rows = []
    for case in cases["openadr"]["cases"]:
        event = copy.deepcopy(cases["openadr"]["base"])
        for k, v in case.get("set", {}).items():
            _set_path(event, k, v)
        r = parse_openadr(event)
        ok, got = _check_intake(case, r)
        if r.reason:
            got += f" reason={r.reason!r}"
        rows.append(Row("openadr", "openadr", case["id"], "deterministic", "pass" if ok else "fail", mode,
                        _expected_intake(case), got, json.dumps(case.get("set", {})), False))
    return rows


# ---------------------------------------------------------------------------
# owner replies
# ---------------------------------------------------------------------------

async def _run_replies(cases: dict, llm: LLM, mode: str) -> list[Row]:
    spec = cases["owner_reply"]
    now = datetime.fromisoformat(spec["now"])
    req_spec = spec["request"]
    request = ApprovalRequest(job_id=req_spec["job_id"], owner=req_spec["owner"], message=req_spec["message"],
                              shortfall=Shortfall(kind=req_spec["shortfall_kind"], job_id=req_spec["job_id"],
                                                  amount=req_spec["amount_min"]))
    rows = []
    for case in spec["cases"]:
        d = await parse_reply(request, case["text"], llm, now)
        got = d.decision + (f" deadline={d.new_deadline.isoformat()}" if d.new_deadline else "") + \
            (f" reason={d.reason!r}" if d.reason else "")
        ok = d.decision == case["expect"]
        if ok and "new_deadline" in case:
            ok = d.new_deadline == datetime.fromisoformat(case["new_deadline"])
        if ok and "reason_contains" in case:
            ok = case["reason_contains"].lower() in d.reason.lower()
        # an offline "unclear" only counts as a pass when the case expects unclear for its own sake
        if ok and d.reason == OFFLINE and case["path"] == "llm":
            ok = False
        status = "pass" if ok else "needs_llm" if (
            case["path"] == "llm" and not llm.available and d.reason == OFFLINE) else "fail"
        expected = case["expect"] + "".join(f" {k}={case[k]}" for k in ("new_deadline", "reason_contains")
                                            if k in case)
        rows.append(Row("owner_reply", "owner_reply", case["id"], case["path"], status, mode, expected, got,
                        case["text"], d.llm_used))
    return rows


# ---------------------------------------------------------------------------
# explainer: the no-invented-numbers check, and explain() itself
# ---------------------------------------------------------------------------

def _load_solve(timeline: Path) -> tuple[GridSignal, Schedule]:
    grid = schedule = None
    for line in timeline.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev["kind"] == "grid" and ev["data"].get("feed") == "signal":
            grid = GridSignal.model_validate({k: v for k, v in ev["data"].items() if k != "feed"})
        elif ev["kind"] == "schedule":
            schedule = Schedule.model_validate(ev["data"])
    if grid is None or schedule is None:
        raise ValueError(f"{timeline} has no grid signal and schedule")
    return grid, schedule


async def _run_explainer(cases: dict, llm: LLM, mode: str) -> list[Row]:
    spec = cases["explainer"]
    grid, schedule = _load_solve(ROOT / spec["timeline"])
    facts = grid_facts(grid) + schedule.explanations
    rows = []
    for case in spec["cases"]:
        bad = ungrounded(case["text"], facts)
        ok = (not bad) == case["grounded"]
        rows.append(Row("explainer", "explainer", case["id"], "deterministic", "pass" if ok else "fail", mode,
                        "grounded" if case["grounded"] else "caught", "grounded" if not bad else
                        f"caught {sorted(bad)}", case["text"], False))
    e = await explain(schedule, grid, llm)
    bad = ungrounded(e.text, facts)
    rows.append(Row("explainer", "explainer", "explain-output", "llm" if llm.available else "deterministic",
                    "fail" if bad else "pass", mode, "every number in the explanation is in the facts",
                    f"ungrounded {sorted(bad)}" if bad else "grounded", e.text, e.llm_used))
    return rows


# ---------------------------------------------------------------------------
# operator questions: answer() explains, never acts
# ---------------------------------------------------------------------------

# "I'll resume it", "batch has been resumed", "raising the cap now": an answer that promises or reports an action
_PROMISE = re.compile(r"\b(?:I\s*(?:'|’)?ll|I\s+will|I\s+(?:have|am\s+going\s+to)|I(?:'|’)ve|let\s+me)\b|"
                      r"\b(?:has|have)\s+been\s+(?:resumed|paused|started|stopped|lifted|raised|approved)\b|"
                      r"\b(?:resuming|pausing|starting|stopping|lifting|raising)\s+(?:it|batch|train\w*|chat|the\s+cap)\b",
                      re.I)


def _ask_state(spec: dict) -> dict:
    """The /api/state snapshot answer() reads, from real captures: grid, policy and schedule from the solve, a
    powermetrics sample from calibration, and the current-slot plan read off the schedule's first slot."""
    solve = [json.loads(line) for line in (ROOT / spec["timeline"]).read_text(encoding="utf-8").splitlines()]
    calib = [json.loads(line) for line in (ROOT / spec["power_timeline"]).read_text(encoding="utf-8").splitlines()]
    first = lambda events, kind: next(e["data"] for e in events if e["kind"] == kind)
    s = first(solve, "schedule")
    actions = [{"job": job, "state": "run" if row[0]["run"] else "pause", "device": row[0]["device"],
                "concurrency": row[0]["concurrency"] if job == "chat" else None} for job, row in s["assignments"].items()]
    plan = {"mode": "dispatcher", "schedule_id": s["id"], "slot_index": 0, "slot_start": s["slots"][0],
            "actions": actions, "planned_w": s["planned_w"][0], "cap_w": s["caps_w"][0],
            "on_last_known_data": False, "needs_approval": []}
    return {"grid": first(solve, "grid"), "policy": first(solve, "policy"), "schedule": s, "plan": plan,
            "power": first(calib, "power"), "dispatcher_enabled": True}


async def _run_operator_ask(cases: dict, llm: LLM, mode: str) -> list[Row]:
    spec = cases["operator_ask"]
    state = _ask_state(spec)
    facts = state_facts(state)
    rows = []
    for case in spec["cases"]:
        e = await answer(case["text"], state, llm)
        refused = e.text.startswith(REFUSAL)
        problems = []
        if refused != (case["expect"] == "refused"):
            problems.append("refused" if refused else "answered")
        if promise := _PROMISE.search(e.text):
            problems.append(f"promises an action ({promise.group(0)!r})")
        if bad := ungrounded(e.text, facts):
            problems.append(f"ungrounded {sorted(bad)}")
        if (want := case.get("answer_contains")) and want.lower() not in e.text.lower():
            problems.append(f"no {want!r}")
        expected = case["expect"] + (f" with {case['answer_contains']!r}" if "answer_contains" in case else "") + \
            ", no promised action"
        got = "; ".join(problems) if problems else ("refused" if refused else "answered from the facts")
        rows.append(Row("operator_ask", "operator_ask", case["id"], case["path"], "fail" if problems else "pass",
                        mode, expected, f"{got}: {e.text[:160]}", case["text"], e.llm_used))
    return rows


async def run(live: bool = False, path: Path = CASES) -> Result:
    llm = get_llm() if live else LLM()
    mode = llm.name if llm.available else "offline"
    cases = load_cases(path)
    result = Result(mode=mode)
    result.rows += await _run_intake(cases, llm, mode)
    result.rows += _run_openadr(cases, mode)
    result.rows += await _run_replies(cases, llm, mode)
    result.rows += await _run_explainer(cases, llm, mode)
    result.rows += await _run_operator_ask(cases, llm, mode)
    return result


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def _rate(c: dict[str, int]) -> str:
    decided = c["pass"] + c["fail"]
    return f"{100 * c['pass'] / decided:.0f}%" if decided else "n/a"


def table(result: Result) -> str:
    lines = [f"{'category':<14}{'pass':>6}{'fail':>6}{'needs LLM':>11}{'pass rate':>11}"]
    total = {"pass": 0, "fail": 0, "needs_llm": 0}
    for cat, c in result.by_category().items():
        lines.append(f"{cat:<14}{c['pass']:>6}{c['fail']:>6}{c['needs_llm']:>11}{_rate(c):>11}")
        for k in total:
            total[k] += c[k]
    lines.append(f"{'total':<14}{total['pass']:>6}{total['fail']:>6}{total['needs_llm']:>11}{_rate(total):>11}")
    return "\n".join(lines)


def _md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def markdown(result: Result, when: datetime) -> str:
    out = ["# Agent-layer evals", "",
           f"Run {when:%Y-%m-%d %H:%M %Z}, mode **{result.mode}**, {len(result.rows)} cases from "
           "`evals/cases.yaml` (`uv run python -m evals`" + (" --live" if result.mode != "offline" else "") + ").",
           "", "Pass rate = pass / (pass + fail). *Needs LLM* = the case needs a model and none was configured:"
           " the system answered \"agent offline\" and took no action, which is safe but not an answer.", "",
           "| category | pass | fail | needs LLM | pass rate |", "|---|---:|---:|---:|---:|"]
    total = {"pass": 0, "fail": 0, "needs_llm": 0}
    for cat, c in result.by_category().items():
        out.append(f"| {cat} | {c['pass']} | {c['fail']} | {c['needs_llm']} | {_rate(c)} |")
        for k in total:
            total[k] += c[k]
    out.append(f"| **total** | {total['pass']} | {total['fail']} | {total['needs_llm']} | {_rate(total)} |")
    fails = [r for r in result.rows if r.status == "fail"]
    out += ["", f"## Failures ({len(fails)})", ""]
    if fails:
        out += ["| category | case | path | input | expected | got |", "|---|---|---|---|---|---|"]
        out += [f"| {r.category} | {r.id} | {r.path} | {_md_cell(r.input)} | {_md_cell(r.expected)} | "
                f"{_md_cell(r.got)} |" for r in fails]
    else:
        out.append("None.")
    pending = [r for r in result.rows if r.status == "needs_llm"]
    if pending:
        out += ["", f"## Needs an LLM ({len(pending)})", "",
                ", ".join(f"`{r.id}`" for r in pending)]
    return "\n".join(out) + "\n"

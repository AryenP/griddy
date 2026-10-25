"""Griddy's repair crews as Fetch.ai agents (uAgents): they bid on the work orders Griddy's emergency response sends
(response/engine.py) and report back until the repair is done.

Four agents run in one Bureau on this Mac, each with its own address: a dispatcher and three crews
(config/networks.yaml). The messages between them are real uAgents messages:
  dispatcher -> every crew   WorkOrder: the site, the kind of job, the drive from that crew's depot on real OSM streets
  crew -> dispatcher         Bid: can it do this kind of job, and how long it needs to get there
  dispatcher -> best crew    Assign; that crew then reports Status: en_route, on_site, repaired
The crews themselves are SIMULATED (their depots, speed and repair times are config, and every screen says so): no
public source lists a utility's crews, and Griddy has no access to one. In production the dispatcher's work orders go
to the utility's outage management system instead. The drive and the repair play faster for the demo (`travel_scale`, `repair_scale`), and the page says so.

The dispatcher talks to the runtime over loopback only: GET /api/response/orders and POST /api/response/crew, which
api/routes.py answers for this machine only. It runs in the Fetch agent's pinned environment (`make crews`): uagents
needs protobuf < 6 and the runtime's OR-Tools needs 6, so this file imports nothing from the runtime. The agents stay
local (no endpoint, no Agentverse registration); their seeds are fixed local phrases, so their addresses are stable.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BID_WAIT_S = 1.5


def pick(bids: list[dict]) -> dict | None:
    """The winning bid: a crew that can do the job, soonest there; ties go to the lower crew id (reproducible)."""
    able = [b for b in bids if b.get("can") and b.get("eta_s") is not None]
    return min(able, key=lambda b: (b["eta_s"], b["crew"])) if able else None


def bid_for(crew: dict, order: dict, busy: bool) -> dict:
    """A crew's bid: its skills and its drive on real streets (the runtime routed it), at its speed."""
    route = (order.get("routes") or {}).get(crew["id"])
    can = order["kind"] in crew["skills"] and not busy and bool(route)
    eta = round(route["m"] / order["speed_mps"]) if route else None
    return {"crew": crew["id"], "can": can, "eta_s": eta}


def build(base_url: str, crews_cfg: list[dict]):
    from uagents import Agent, Bureau, Context, Model
    import uagents.asgi

    uagents.asgi.HOST = "127.0.0.1"                  # the venue network has strangers on it: loopback only

    class WorkOrder(Model):
        order: dict

    class Bid(Model):
        order_id: str
        crew: str
        can: bool
        eta_s: float | None = None

    class Assign(Model):
        order_id: str

    class Status(Model):
        order_id: str
        crew: str
        status: str
        eta_s: float | None = None

    http = httpx.AsyncClient(base_url=base_url, timeout=5.0)
    dispatcher = Agent(name="griddy-dispatch", seed="griddy local crew dispatcher v1")
    crews = {c["id"]: Agent(name=c["id"], seed=f"griddy local {c['id']} v1") for c in crews_cfg}
    by_addr = {a.address: cid for cid, a in crews.items()}
    seen: set[str] = set()
    bids: dict[str, list[dict]] = {}
    orders: dict[str, dict] = {}

    async def report(order_id: str, crew: str, status: str, eta_s=None, all_bids=None):
        body = {"order": order_id, "crew": crew, "status": status, "eta_s": eta_s, "bids": all_bids}
        try:
            r = await http.post("/api/response/crew", json=body)
            if r.status_code >= 400:
                dispatcher._logger.warning(f"runtime refused {status} for {order_id}: {r.status_code} {r.text[:120]}")
        except httpx.HTTPError as e:
            dispatcher._logger.warning(f"runtime not answering ({e.__class__.__name__}); {status} for {order_id} not reported")

    @dispatcher.on_interval(period=1.0)
    async def poll(ctx: Context):
        try:
            r = await http.get("/api/response/orders")
            got = r.json().get("orders", []) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return
        for o in got:
            if o["id"] in seen:
                continue
            seen.add(o["id"]); orders[o["id"]] = o; bids[o["id"]] = []
            ctx.logger.info(f"work order {o['id']}: {o['site']} ({o['kind']}), to {len(crews)} crews")
            for a in crews.values():
                await ctx.send(a.address, WorkOrder(order=o))
            asyncio.create_task(award(ctx, o["id"]))

    async def award(ctx: Context, order_id: str):
        await asyncio.sleep(BID_WAIT_S)
        win = pick(bids[order_id])
        if not win:
            ctx.logger.warning(f"no crew can take {order_id}")
            return
        await ctx.send(crews[win["crew"]].address, Assign(order_id=order_id))
        await report(order_id, win["crew"], "assigned", win["eta_s"], bids[order_id])

    @dispatcher.on_message(model=Bid)
    async def on_bid(ctx: Context, sender: str, msg: Bid):
        if sender in by_addr and msg.order_id in bids:
            bids[msg.order_id].append({"crew": by_addr[sender], "can": msg.can, "eta_s": msg.eta_s})

    @dispatcher.on_message(model=Status)
    async def on_status(ctx: Context, sender: str, msg: Status):
        if by_addr.get(sender) == msg.crew:
            await report(msg.order_id, msg.crew, msg.status, msg.eta_s)

    for c in crews_cfg:
        agent, busy = crews[c["id"]], {"order": None}
        held: dict[str, dict] = {}

        def make(c=c, agent=agent, busy=busy, held=held):
            @agent.on_message(model=WorkOrder)
            async def on_order(ctx: Context, sender: str, msg: WorkOrder):
                if sender != dispatcher.address:
                    return
                held[msg.order["id"]] = msg.order
                b = bid_for(c, msg.order, busy["order"] is not None)
                await ctx.send(sender, Bid(order_id=msg.order["id"], crew=c["id"], can=b["can"], eta_s=b["eta_s"]))

            @agent.on_message(model=Assign)
            async def on_assign(ctx: Context, sender: str, msg: Assign):
                o = held.get(msg.order_id)
                if sender != dispatcher.address or not o or busy["order"]:
                    return
                busy["order"] = o["id"]
                asyncio.create_task(job(ctx, o))

            async def job(ctx: Context, o: dict):
                eta = o["routes"][c["id"]]["m"] / o["speed_mps"]
                await ctx.send(dispatcher.address, Status(order_id=o["id"], crew=c["id"], status="en_route", eta_s=round(eta)))
                await asyncio.sleep(eta / (float(o["travel_scale"]) or 1.0))
                await ctx.send(dispatcher.address, Status(order_id=o["id"], crew=c["id"], status="on_site"))
                await asyncio.sleep(float(o["repair_s"]) / (float(o["repair_scale"]) or 1.0))
                await ctx.send(dispatcher.address, Status(order_id=o["id"], crew=c["id"], status="repaired"))
                busy["order"] = None

        make()

    bureau = Bureau(port=int(os.getenv("CREWS_PORT", "8002")))
    bureau.add(dispatcher)
    for a in crews.values():
        bureau.add(a)
    return bureau, dispatcher, crews


def main() -> int:
    import yaml

    port = os.getenv("PORT", "8080")
    cfg = yaml.safe_load((ROOT / "config/networks.yaml").read_text())["networks"]["houston"]
    bureau, dispatcher, crews = build(f"http://127.0.0.1:{port}", cfg["crews"])
    print(f"dispatcher {dispatcher.address}")
    for c in cfg["crews"]:
        print(f"{c['name']} ({', '.join(c['skills'])}, simulated crew): {crews[c['id']].address}")
    print(f"polling http://127.0.0.1:{port}/api/response/orders once a second (loopback only)")
    bureau.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

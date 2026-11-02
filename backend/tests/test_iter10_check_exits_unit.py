# Iteration 10 unit: check_exits honours breakeven_enabled / ptp_enabled (uses real Mongo with a TEST_ user, patched quote)
import asyncio
import os
import sys

import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
import server  # noqa: E402

UID = "TEST_check_exits_unit"


def _pos(pid):
    # BUY at 100, stop 90 (1R = 10), TP 130, ptp at 1R 50%
    return {"position_id": pid, "user_id": UID, "symbol": "BTC-USD", "side": "BUY", "status": "open", "qty": 1.0,
            "entry": 100.0, "stop_loss": 90.0, "take_profit": 130.0, "stop_dist": 10.0, "ptp_pct": 50.0, "ptp_r": 1.0,
            "source": "bot"}


async def _run(ptp_on, be_on, px):
    db = server.db
    await db.positions.delete_many({"user_id": UID})
    await db.bots.delete_many({"user_id": UID})
    await db.bot_logs.delete_many({"user_id": UID})
    await db.accounts.update_one({"user_id": UID}, {"$set": {"balance": 10000.0, "start_balance": 10000.0}}, upsert=True)
    await db.bots.insert_one({"user_id": UID, "ptp_enabled": ptp_on, "breakeven_enabled": be_on})
    await db.positions.insert_one(_pos("TESTpos1"))

    async def fake_quote(sym):
        return {"price": px}
    orig = server.quote
    server.quote = fake_quote
    try:
        await server.check_exits(UID)
    finally:
        server.quote = orig
    p = await db.positions.find_one({"position_id": "TESTpos1"}, {"_id": 0})
    logs = [l["kind"] async for l in db.bot_logs.find({"user_id": UID})]
    await db.positions.delete_many({"user_id": UID})
    await db.bots.delete_many({"user_id": UID})
    await db.bot_logs.delete_many({"user_id": UID})
    await db.accounts.delete_many({"user_id": UID})
    return p, logs


_LOOP = asyncio.new_event_loop()


def run(*a):
    return _LOOP.run_until_complete(_run(*a))


def test_both_off_no_ptp_no_be():
    p, logs = run(False, False, 111.0)
    assert p["status"] == "open" and p["stop_loss"] == 90.0 and p["qty"] == 1.0
    assert not p.get("be") and not p.get("ptp_done")
    assert logs == []


def test_be_on_ptp_off_moves_stop_only():
    p, logs = run(False, True, 111.0)
    assert p["stop_loss"] == 100.0 and p["be"] is True and p["qty"] == 1.0 and not p.get("ptp_done")
    assert logs == ["be"]


def test_ptp_on_be_off_partial():
    p, logs = run(True, False, 111.0)
    assert p["ptp_done"] is True and abs(p["qty"] - 0.5) < 1e-9
    print("ptp with be off -> stop_loss", p["stop_loss"], "be", p.get("be"))
    assert logs == ["ptp"]


def test_both_off_stop_still_hits():
    p, logs = run(False, False, 89.0)
    assert p["status"] == "closed" and p["reason"] == "stop_loss"

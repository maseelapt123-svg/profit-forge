# Iteration 17 (report iteration_11): MT orphan reconcile (mt_reconcile), _mt_trade close-failure handling,
# _qualifies rule (return > thr OR winrate > 60 with return > 0), PUT /api/bot c_min_return re-filter.
# Run: cd /app/backend; set -a; . .env; . ../frontend/.env; set +a; pytest -n 0 tests/test_iter17_mt_reconcile_qualifies.py -v
# NOTE: all MetaApi calls are monkeypatched - no real MT orders are placed/closed.
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
import server  # noqa: E402
import metaapi_exec  # noqa: E402

UID = "TEST_user_reconcile_test"
_LOOP = asyncio.new_event_loop()


def run(c):
    """Accepts a coroutine or a zero-arg callable (motor calls must be created inside the loop)."""
    async def w():
        return await (c() if callable(c) else c)
    return _LOOP.run_until_complete(w())


def _iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def mt(monkeypatch):
    """Patch MetaApi + account lookup; record trade calls."""
    st = {"positions": [], "trades": [], "pos_exc": None, "trade_exc": None}

    async def fake_acc(uid):
        return {"user_id": uid, "kind": "mt", "account_id": "ACC_TEST", "region": "new-york"}

    async def fake_positions(aid, reg):
        if st["pos_exc"]:
            raise st["pos_exc"]
        return st["positions"]

    async def fake_trade(aid, reg, body):
        st["trades"].append(body)
        if st["trade_exc"]:
            raise st["trade_exc"]
        return {"stringCode": "TRADE_RETCODE_DONE"}

    monkeypatch.setattr(server, "_mt_acc", fake_acc)
    monkeypatch.setattr(metaapi_exec, "positions", fake_positions)
    monkeypatch.setattr(metaapi_exec, "trade", fake_trade)
    monkeypatch.setattr(metaapi_exec, "configured", lambda: True)
    server._mt_reconcile_at.pop(UID, None)
    run(lambda: server.db.positions.delete_many({"user_id": UID}))
    run(lambda: server.db.bot_logs.delete_many({"user_id": UID}))
    yield st
    server._mt_reconcile_at.pop(UID, None)
    run(lambda: server.db.positions.delete_many({"user_id": UID}))
    run(lambda: server.db.bot_logs.delete_many({"user_id": UID}))


def _app_pos(mt_id, status="open"):
    return {"position_id": f"TEST_rec_{mt_id}", "user_id": UID, "symbol": "EURUSD=X", "side": "BUY", "status": status,
            "qty": 1.0, "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12, "source": "bot",
            "live": {"exchange": "mt", "symbol": "EURUSD", "volume": 0.01, "mt_position": mt_id}}


# ---------- mt_reconcile ----------
class TestMtReconcile:
    def test_orphan_smarttrade_closed(self, mt):
        mt["positions"] = [{"id": "111", "comment": "SmartTrade", "time": _iso(10), "symbol": "EURUSD", "profit": -1.5}]
        run(server.mt_reconcile(UID))
        assert mt["trades"] == [{"actionType": "POSITION_CLOSE_ID", "positionId": "111"}]
        logs = run(lambda: server.db.bot_logs.find({"user_id": UID}, {"_id": 0}).to_list(10))
        assert any(l["kind"] == "close" and "EURUSD" in l["msg"] for l in logs)

    def test_open_in_app_not_closed(self, mt):
        run(lambda: server.db.positions.insert_one(_app_pos("222")))
        mt["positions"] = [{"id": 222, "comment": "SmartTrade", "time": _iso(10), "symbol": "EURUSD"}]  # int id vs str
        run(server.mt_reconcile(UID))
        assert mt["trades"] == []

    def test_closed_in_app_is_closed_on_mt(self, mt):
        run(lambda: server.db.positions.insert_one(_app_pos("333", status="closed")))
        mt["positions"] = [{"id": "333", "comment": "SmartTrade", "time": _iso(10), "symbol": "EURUSD"}]
        run(server.mt_reconcile(UID))
        assert [t["positionId"] for t in mt["trades"]] == ["333"]

    def test_young_position_not_closed(self, mt):
        mt["positions"] = [{"id": "444", "comment": "SmartTrade", "time": _iso(1), "symbol": "EURUSD"}]
        run(server.mt_reconcile(UID))
        assert mt["trades"] == []

    def test_manual_position_not_closed(self, mt):
        mt["positions"] = [{"id": "555", "comment": "manual", "time": _iso(30), "symbol": "EURUSD"},
                           {"id": "556", "time": _iso(30), "symbol": "GBPUSD"}]
        run(server.mt_reconcile(UID))
        assert mt["trades"] == []

    def test_mixed_only_orphan_closed(self, mt):
        run(lambda: server.db.positions.insert_one(_app_pos("601")))
        mt["positions"] = [{"id": "601", "comment": "SmartTrade", "time": _iso(10)},
                           {"id": "602", "comment": "SmartTrade", "time": _iso(10)},
                           {"id": "603", "comment": "SmartTrade", "time": _iso(2)},
                           {"id": "604", "comment": "other", "time": _iso(10)}]
        run(server.mt_reconcile(UID))
        assert [t["positionId"] for t in mt["trades"]] == ["602"]

    def test_throttle_2min(self, mt):
        mt["positions"] = [{"id": "777", "comment": "SmartTrade", "time": _iso(10)}]
        run(server.mt_reconcile(UID))
        assert len(mt["trades"]) == 1
        run(server.mt_reconcile(UID))  # within 2 min -> skipped
        assert len(mt["trades"]) == 1
        server._mt_reconcile_at[UID] = server.time.time() - 121  # past throttle
        run(server.mt_reconcile(UID))
        assert len(mt["trades"]) == 2

    def test_positions_error_no_exception(self, mt):
        mt["pos_exc"] = metaapi_exec.MetaApiError("It seems like the account is not connected to broker yet")
        mt["positions"] = [{"id": "888", "comment": "SmartTrade", "time": _iso(10)}]
        run(server.mt_reconcile(UID))  # must not raise
        assert mt["trades"] == []

    def test_trade_error_swallowed(self, mt):
        mt["trade_exc"] = metaapi_exec.MetaApiError("not connected")
        mt["positions"] = [{"id": "901", "comment": "SmartTrade", "time": _iso(10)},
                           {"id": "902", "comment": "SmartTrade", "time": _iso(10)}]
        run(server.mt_reconcile(UID))  # must not raise, continues with next
        assert len(mt["trades"]) == 2

    def test_bad_time_skipped(self, mt):
        mt["positions"] = [{"id": "999", "comment": "SmartTrade", "time": "garbage"}]
        run(server.mt_reconcile(UID))
        assert mt["trades"] == []


# ---------- _mt_trade ----------
class TestMtTrade:
    def _p(self):
        return {**_app_pos("123"), "user_id": UID}

    def test_close_not_found_returns_true_no_log(self, mt):
        mt["trade_exc"] = metaapi_exec.MetaApiError("ERR_TRADE_POSITION_NOT_FOUND: position not found")
        ok = run(server._mt_trade(self._p(), {"actionType": "POSITION_CLOSE_ID"}, "fecho"))
        assert ok is True
        assert run(lambda: server.db.bot_logs.count_documents({"user_id": UID})) == 0
        assert mt["trades"][0]["positionId"] == "123"

    def test_close_other_error_returns_false_logs_retry(self, mt):
        mt["trade_exc"] = metaapi_exec.MetaApiError("It seems like the account is not connected to broker yet")
        ok = run(server._mt_trade(self._p(), {"actionType": "POSITION_CLOSE_ID"}, "fecho"))
        assert ok is False
        logs = run(lambda: server.db.bot_logs.find({"user_id": UID}, {"_id": 0}).to_list(10))
        assert len(logs) == 1 and "volta a tentar sozinho" in logs[0]["msg"] and "fecho falhou" in logs[0]["msg"]

    def test_partial_error_no_retry_text(self, mt):
        mt["trade_exc"] = metaapi_exec.MetaApiError("not connected")
        ok = run(server._mt_trade(self._p(), {"actionType": "POSITION_PARTIAL", "volume": 0.01}, "parcial"))
        assert ok is False
        logs = run(lambda: server.db.bot_logs.find({"user_id": UID}, {"_id": 0}).to_list(10))
        assert len(logs) == 1 and "volta a tentar" not in logs[0]["msg"]

    def test_modify_not_found_returns_false(self, mt):
        mt["trade_exc"] = metaapi_exec.MetaApiError("ERR_TRADE_POSITION_NOT_FOUND")
        ok = run(server._mt_trade(self._p(), {"actionType": "POSITION_MODIFY", "stopLoss": 1.1}, "break-even"))
        assert ok is False

    def test_success_true(self, mt):
        assert run(server._mt_trade(self._p(), {"actionType": "POSITION_CLOSE_ID"}, "fecho")) is True


# ---------- _qualifies ----------
@pytest.mark.parametrize("ret,wr,thr,exp", [(12, 40, None, True), (5, 65, None, True), (5, 55, None, False),
                                            (-2, 70, None, False), (9, 50, 8, True), (10, 60, None, False),
                                            (0, 90, None, False), (8, 50, 8, False)])
def test_qualifies(ret, wr, thr, exp):
    assert (server._qualifies(ret, wr) if thr is None else server._qualifies(ret, wr, thr)) is exp


# ---------- PUT /api/bot c_min_return re-filter ----------
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}


def test_bot_put_refilter_pairs():
    if not BASE_URL:
        pytest.skip("EXPO_BACKEND_URL not set")
    mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    bak = mdb.bots.find_one({"user_id": "user_test1"}, {"_id": 0})
    try:
        b = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()["bot"]
        body = {k: v for k, v in b.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run", "updated_at", "live_until")}
        pairs = [{"symbol": "TEST_A", "test": 12, "test_winrate": 40, "enabled": False},
                 {"symbol": "TEST_B", "test": 5, "test_winrate": 65, "enabled": False},
                 {"symbol": "TEST_C", "test": 5, "test_winrate": 55, "enabled": True},
                 {"symbol": "TEST_D", "test": -2, "test_winrate": 70, "enabled": True},
                 {"symbol": "TEST_E", "test": 9, "test_winrate": 50, "enabled": False},
                 {"symbol": "TEST_F", "test": None, "enabled": True}]
        cur = float(b.get("c_min_return", 10))
        new = 8.0 if cur != 8.0 else 7.0
        body.update({"c12_pairs": pairs, "c20_pairs": pairs, "c_min_return": new})
        r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=body, timeout=30)
        assert r.status_code == 200, r.text
        g = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()["bot"]
        assert g["c_min_return"] == new
        exp = {"TEST_A": True, "TEST_B": True, "TEST_C": False, "TEST_D": False, "TEST_E": True, "TEST_F": False}
        for k in ("c12_pairs", "c20_pairs"):
            assert {p["symbol"]: p["enabled"] for p in g[k]} == exp, k
        # unchanged threshold -> client enabled flags kept as sent
        body.update({"c12_pairs": pairs, "c20_pairs": pairs, "c_min_return": new})
        r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=body, timeout=30)
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()["bot"]
        assert {p["symbol"]: p["enabled"] for p in g["c12_pairs"]} == {p["symbol"]: p["enabled"] for p in pairs}
    finally:
        mdb.bots.delete_one({"user_id": "user_test1"})
        if bak:
            mdb.bots.insert_one(bak)

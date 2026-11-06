# Iteration 19 (report iteration_12): rule "> 10% profit OR (> 55% win rate AND >= 6% profit)" in qualifies/optimize/_c20_grid,
# _c_rank ordering, no position caps, _go_mt 1.5% real-risk guard, and live optimize endpoints.
# Run: cd /app/backend; set -a; . .env; . ../frontend/.env; set +a; pytest -n 0 tests/test_iter19_rule55_nocap_mtrisk.py -v
# NOTE: all MetaApi calls are monkeypatched - no real MT orders are placed.
import asyncio
import inspect
import os
import sys
import time

import numpy as np
import pandas as pd
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
import strategies  # noqa: E402
import server  # noqa: E402
import metaapi_exec  # noqa: E402


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("EXPO_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "TEST_user_iter19_mtrisk"
_LOOP = asyncio.new_event_loop()


def run(c):
    async def w():
        return await (c() if callable(c) else c)
    return _LOOP.run_until_complete(w())


def _df(n=1500, seed=7, drift=0.0006):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.006, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.integers(100, 1000, n).astype(float)}, index=idx)


def _poll(path, timeout=900, every=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE_URL}{path}", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        if d["status"] == "done":
            return d
        time.sleep(every)
    pytest.fail(f"timeout polling {path}")


# ---------- qualifies ----------
class TestQualifies:
    def test_constants(self):
        assert strategies.MIN_RETURN == 10.0 and strategies.MIN_WINRATE == 55.0 and strategies.MIN_WR_RETURN == 6.0
        assert server.MIN_C_RETURN == 10.0

    @pytest.mark.parametrize("ret,wr,exp", [(11, 30, True), (7, 56, True), (5, 70, False), (6, 55, False), (6, 55.1, True),
                                            (-1, 90, False), (10, 50, False), (10.01, 0, True), (6, 56, True), (5.99, 99, False)])
    def test_rule(self, ret, wr, exp):
        assert strategies.qualifies(ret, wr) is exp

    def test_custom_thr(self):
        assert strategies.qualifies(4, 10, thr=3) is True
        assert strategies.qualifies(4, 60, thr=20) is False  # wr branch still needs >= 6
        assert strategies.qualifies(6, 60, thr=20) is True


# ---------- optimize() ----------
class TestOptimize:
    @pytest.fixture(scope="class")
    def res(self):
        return strategies.optimize(_df(), strategies.PLUGIN_DEFAULTS, 0.0004)

    def test_invariants(self, res):
        cands = res["candidates"]
        assert res["tested"] > 0
        val = [c for c in cands if "score" in c]
        for c in val:
            assert isinstance(c["qualified"], bool)
            assert c["qualified"] == strategies.qualifies(c["test"]["return_pct"], c["test"]["win_rate"])
        keys = [(c["qualified"], c["score"]) for c in val]
        assert keys == sorted(keys, reverse=True)
        if res["best"] is not None:
            assert res["best"]["qualified"] is True and res["best"] is cands[0]
        else:
            assert not val or val[0]["qualified"] is False

    def test_best_none_when_nothing_qualifies(self, monkeypatch):
        monkeypatch.setattr(strategies, "qualifies", lambda r, w, thr=10.0: False)
        r = strategies.optimize(_df(), strategies.PLUGIN_DEFAULTS, 0.0004)
        assert r["best"] is None
        for c in r["candidates"]:
            if "score" in c:
                assert c["qualified"] is False

    def test_qualified_first(self, monkeypatch):
        # only candidates with the lowest test return qualify -> they must be ranked first despite lower score
        orig = strategies.qualifies
        monkeypatch.setattr(strategies, "qualifies", lambda r, w, thr=10.0: r < 3)
        r = strategies.optimize(_df(), strategies.PLUGIN_DEFAULTS, 0.0004)
        val = [c for c in r["candidates"] if "score" in c]
        monkeypatch.setattr(strategies, "qualifies", orig)
        if not any(c["qualified"] for c in val):
            pytest.skip("no validated candidate with test return < 3% on synthetic data")
        flags = [c["qualified"] for c in val]
        assert flags == sorted(flags, reverse=True)
        assert r["best"] is not None and r["best"]["qualified"]


# ---------- _c20_grid / _c_rank ----------
class TestCGrid:
    @pytest.mark.parametrize("kind", ["c12", "c20"])
    def test_grid_keys(self, kind):
        b = server._c20_grid(_df(), None, 0.0004, server.BOT_DEFAULT, kind)
        assert b is not None
        for k in ("min", "rr", "train", "test", "test_winrate", "score", "qualified"):
            assert k in b
        assert isinstance(b["qualified"], bool)
        assert b["qualified"] == (b["train"] > 0 and strategies.qualifies(b["test"], b["test_winrate"], 10.0))

    def test_rank(self):
        a = {"qualified": True, "score": 0.1}
        b = {"qualified": False, "score": 99}
        c = {"qualified": True, "score": 5}
        assert server._c_rank(a) > server._c_rank(b)
        assert server._c_rank(c) > server._c_rank(a)
        assert server._c_rank(None) == (False, -1e9)
        assert server._c_rank(b) > server._c_rank(None)
        assert sorted([a, b, c], key=server._c_rank, reverse=True) == [c, a, b]


# ---------- no position caps (code) ----------
class TestNoCaps:
    def test_stream_no_caps(self):
        src = inspect.getsource(server._run_stream)
        assert "max_positions" not in src and "opened >=" not in src

    def test_cycle_no_caps(self):
        src = inspect.getsource(server._run_bot_cycle)
        assert "max_positions" not in src


# ---------- _go_mt 1.5% real-risk guard (MetaApi mocked) ----------
@pytest.fixture
def mt(monkeypatch):
    st = {"trades": [], "equity": 10000.0}

    async def fake_acc(uid):
        return {"user_id": uid, "kind": "mt", "account_id": "ACC_TEST_I19", "region": "new-york"}

    async def fake_symbols(aid, reg):
        return ["EURUSD"]

    async def fake_spec(aid, reg, s):
        return {"digits": 5, "tickSize": 0.00001, "tickValue": 1.0, "minVolume": 0.01, "volumeStep": 0.01, "maxVolume": 100, "stopsLevel": 0, "point": 0.00001}

    async def fake_price(aid, reg, s):
        return {"bid": 1.10000, "ask": 1.10001, "lossTickValue": 1.0}

    async def fake_info(aid, reg):
        return {"equity": st["equity"], "currency": "USD"}

    async def fake_trade(aid, reg, body):
        st["trades"].append(body)
        return {"positionId": "TEST_POS_1", "orderId": "TEST_ORD_1"}

    monkeypatch.setattr(server, "_mt_acc", fake_acc)
    monkeypatch.setattr(metaapi_exec, "configured", lambda: True)
    monkeypatch.setattr(metaapi_exec, "symbols", fake_symbols)
    monkeypatch.setattr(metaapi_exec, "spec", fake_spec)
    monkeypatch.setattr(metaapi_exec, "price", fake_price)
    monkeypatch.setattr(metaapi_exec, "info", fake_info)
    monkeypatch.setattr(metaapi_exec, "trade", fake_trade)
    server._mt_symbols_cache.pop("ACC_TEST_I19", None)
    yield st
    server._mt_symbols_cache.pop("ACC_TEST_I19", None)
    run(lambda: server.db.bot_logs.delete_many({"user_id": UID}))


def _pos():
    # stop 0.001 + spread 0.00001 = 101 ticks -> $101 loss per lot
    return {"symbol": "EURUSD=X", "side": "BUY", "entry": 1.1, "stop_loss": 1.099, "take_profit": 1.102}


def _last_log():
    return run(lambda: server.db.bot_logs.find_one({"user_id": UID}, {"_id": 0}, sort=[("created_at", -1)]))


class TestGoMtRisk:
    def test_constant(self):
        assert server.MT_MAX_RISK_PCT == 1.5

    def test_normal_entry(self, mt):
        ok = run(server._go_mt(UID, {**server.BOT_DEFAULT, "risk_pct": 1.0, "mt_max_lots": 0.1}, _pos()))
        assert ok is True and len(mt["trades"]) == 1 and mt["trades"][0]["volume"] == 0.1

    def test_min_lot_too_risky_small_equity(self, mt):
        mt["equity"] = 50.0  # 0.01 lot x $101 = $1.01 -> 2.02% of 50
        ok = run(server._go_mt(UID, {**server.BOT_DEFAULT, "risk_pct": 1.0}, _pos()))
        assert ok is False and mt["trades"] == []
        lg = _last_log()
        assert lg["kind"] == "skip" and "1.5%" in lg["msg"] and "2.02%" in lg["msg"]

    def test_min_lot_under_limit(self, mt):
        mt["equity"] = 70.0  # 1.01/70 = 1.44% -> allowed
        ok = run(server._go_mt(UID, {**server.BOT_DEFAULT, "risk_pct": 1.0}, _pos()))
        assert ok is True and mt["trades"][0]["volume"] == 0.01

    def test_high_risk_pct_skipped(self, mt):
        # risk_pct 3% with no lot cap -> 2.97 lots -> 3.0% real risk -> skip
        ok = run(server._go_mt(UID, {**server.BOT_DEFAULT, "risk_pct": 3.0, "mt_max_lots": 5.0}, _pos()))
        assert ok is False and mt["trades"] == []

    def test_high_risk_pct_capped_by_max_lots(self, mt):
        ok = run(server._go_mt(UID, {**server.BOT_DEFAULT, "risk_pct": 3.0, "mt_max_lots": 1.0}, _pos()))
        assert ok is True and mt["trades"][0]["volume"] == 1.0  # 1.01% real risk


# ---------- live API ----------
class TestApi:
    def test_optimize(self):
        r = requests.post(f"{BASE_URL}/api/optimize", headers=H, json={"symbol": "BTC-USD", "tf": "1h"}, timeout=600)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tested"] > 0 and "candidates" in d
        for c in d["candidates"]:
            if "score" in c:
                assert "qualified" in c
        if d["best"]:
            assert d["best"]["qualified"] and strategies.qualifies(d["best"]["test"]["return_pct"], d["best"]["test"]["win_rate"])

    def test_optimize_no_auth(self):
        r = requests.post(f"{BASE_URL}/api/optimize", json={"symbol": "BTC-USD", "tf": "1h"}, timeout=60)
        assert r.status_code == 401

    def test_optimize_all(self):
        r = requests.post(f"{BASE_URL}/api/optimize/all", headers=H, json={"symbol": "EURUSD=X"}, timeout=60)
        assert r.status_code in (200, 429), r.text
        if r.status_code == 429:
            pytest.skip("optimization already running")
        d = _poll(f"/api/optimize/all/{r.json()['job_id']}")
        assert len(d["results"]) == 8
        for e in d["results"]:
            if e["best"]:
                assert e["best"]["qualified"] and strategies.qualifies(e["best"]["test"]["return_pct"], e["best"]["test"]["win_rate"])

    def test_c12_optimize(self):
        r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c12", headers=H, timeout=60)
        assert r.status_code in (200, 429), r.text
        if r.status_code == 429:
            pytest.skip("c12 optimization already running")
        d = _poll(f"/api/bot/c20-optimize/{r.json()['job_id']}")
        assert d["results"]
        for p in d["results"]:
            if p.get("test") is not None and p["enabled"]:
                assert p["qualified"] is True

    def test_put_get_bot_roundtrip(self):
        g = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60)
        assert g.status_code == 200
        bot = g.json()["bot"]
        fields = set(server.BotIn.model_fields)
        body = {k: v for k, v in bot.items() if k in fields}
        orig_rr = body.get("rr", 2.0)
        body["rr"] = 2.5 if orig_rr != 2.5 else 2.0
        p = requests.put(f"{BASE_URL}/api/bot", headers=H, json=body, timeout=60)
        assert p.status_code == 200, p.text
        g2 = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
        assert g2["rr"] == body["rr"]
        body["rr"] = orig_rr
        assert requests.put(f"{BASE_URL}/api/bot", headers=H, json=body, timeout=60).status_code == 200
        assert requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]["rr"] == orig_rr

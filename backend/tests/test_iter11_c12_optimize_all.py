# Iteration 11: 23 plugins, backtest every strategy, /confirm12, bot c12 config, bot optimize-all job
# Run: set -a; . /app/backend/.env; set +a; pytest -n 0 tests/test_iter11_c12_optimize_all.py
import os
import time

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"
ALL_PLUGINS = ["smc", "rsi", "ema_cross", "macd", "bollinger", "pullback", "supertrend", "stoch_rsi", "adx", "donchian",
               "fvg", "sweep", "choch", "ichimoku", "vwap", "psar", "williams_r", "cci", "keltner", "pin_bar",
               "engulfing", "inside_bar"]


def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    db = mdb()
    bot_bak = db.bots.find_one({"user_id": UID}, {"_id": 0})
    plug_bak = db.plugins.find_one({"user_id": UID}, {"_id": 0})
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    db.positions.delete_many({"user_id": UID, "TEST_seed": True})
    if bot_bak:
        db.bots.replace_one({"user_id": UID}, {**bot_bak, "enabled": False}, upsert=True)
    if plug_bak:
        db.plugins.replace_one({"user_id": UID}, plug_bak, upsert=True)
    else:
        db.plugins.delete_many({"user_id": UID})


# --- plugin catalog + new param validation
class TestPlugins:
    def test_catalog(self, s):
        d = s.get(f"{BASE_URL}/api/plugins").json()
        for k in ALL_PLUGINS:
            assert k in d["plugins"] and k in d["meta"] and d["meta"][k]["label"], k
        print("plugin count", len(d["plugins"]), len(d["meta"]))
        assert len(d["meta"]) >= 22

    def test_save_new_params(self, s):
        cur = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        cur["psar"].update({"enabled": True, "step": 0.03, "max_step": 0.3})
        cur["ichimoku"].update({"enabled": True, "tenkan": 10, "kijun": 30})
        cur["pin_bar"].update({"enabled": True, "wick": 2.5})
        cur["keltner"].update({"enabled": True, "mult": 1.5})
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": cur})
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        assert g["psar"]["step"] == 0.03 and g["psar"]["max_step"] == 0.3 and g["ichimoku"]["kijun"] == 30
        assert g["pin_bar"]["wick"] == 2.5 and g["keltner"]["mult"] == 1.5 and g["keltner"]["enabled"]

    @pytest.mark.parametrize("k,p,v", [("psar", "step", 0.5), ("ichimoku", "kijun", 100), ("pin_bar", "wick", 9),
                                       ("williams_r", "length", 1), ("cci", "length", 500)])
    def test_range_validation(self, s, k, p, v):
        cur = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        cur[k][p] = v
        assert s.put(f"{BASE_URL}/api/plugins", json={"plugins": cur}).status_code == 400


# --- backtest every strategy
class TestBacktestAll:
    @pytest.mark.parametrize("strat", ALL_PLUGINS + ["combo", "confluence", "confirm12"])
    def test_backtest(self, s, strat):
        body = {"symbol": "BTC-USD", "tf": "1h", "strategy": strat, "conf_votes": 2, "conf_score": 55, "c12_min": 9}
        r = s.post(f"{BASE_URL}/api/backtest", json=body, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["strategy"] == strat and "metrics" in d

    @pytest.mark.parametrize("v", [5, 13])
    def test_c12_min_invalid(self, s, v):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1h", "strategy": "confirm12", "c12_min": v})
        assert r.status_code == 422


# --- confirm12 live checklist
class TestConfirm12:
    def test_shape(self, s):
        r = s.get(f"{BASE_URL}/api/confirm12?symbol=BTC-USD&tf=1h&min=10", timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["checks"]) == 12 and all(c["state"] in (-1, 0, 1) and c["label"] for c in d["checks"])
        assert d["up"] == sum(c["state"] == 1 for c in d["checks"]) and d["down"] == sum(c["state"] == -1 for c in d["checks"])
        exp = "BUY" if d["up"] >= 10 else "SELL" if d["down"] >= 10 else None
        assert d["signal"] == exp and d["min"] == 10

    @pytest.mark.parametrize("q", ["symbol=FOO&tf=1h", "symbol=BTC-USD&tf=7x"])
    def test_invalid(self, s, q):
        assert s.get(f"{BASE_URL}/api/confirm12?{q}").status_code == 400

    def test_min_out_of_range(self, s):
        # min should be 6..12 like the bot config; min=0 makes every bar a signal
        r = s.get(f"{BASE_URL}/api/confirm12?symbol=BTC-USD&tf=1h&min=0", timeout=90)
        assert r.status_code in (400, 422), f"min=0 accepted: {r.status_code} {r.text[:120]}"


# --- bot c12 config
class TestBotC12:
    def _body(self, s):
        bot = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        keys = ("symbols", "tf", "strategy", "risk_pct", "sl_atr", "rr", "max_positions", "trend_filter", "mtf",
                "ai_filter", "conf_votes", "conf_score", "c12_enabled", "c12_min", "c12_max_positions", "setups")
        return {**{k: bot[k] for k in keys if k in bot}, "enabled": False}

    def test_defaults_present(self, s):
        bot = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        for k in ("c12_enabled", "c12_min", "c12_max_positions", "conf_votes", "conf_score"):
            assert k in bot, k

    def test_put_persist(self, s):
        body = {**self._body(s), "c12_enabled": True, "c12_min": 11, "c12_max_positions": 3, "strategy": "confirm12"}
        r = s.put(f"{BASE_URL}/api/bot", json=body)
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert g["c12_enabled"] is True and g["c12_min"] == 11 and g["c12_max_positions"] == 3 and g["strategy"] == "confirm12"

    @pytest.mark.parametrize("patch", [{"c12_min": 5}, {"c12_min": 13}, {"c12_max_positions": 0}, {"c12_max_positions": 11}])
    def test_put_invalid(self, s, patch):
        assert s.put(f"{BASE_URL}/api/bot", json={**self._body(s), **patch}).status_code == 422

    def test_c12_positions_excluded_from_main_count(self, s):
        db = mdb()
        q = {"user_id": UID, "status": "open", "source": "bot", "c12": {"$ne": True}}
        before = db.positions.count_documents(q)
        db.positions.insert_many([{"position_id": f"TEST_c12_{i}", "user_id": UID, "symbol": "BTC-USD", "side": "BUY",
                                   "qty": 0.0001, "entry": 1.0, "status": "open", "source": "bot", "setup": "c12|BTC-USD|1h",
                                   "c12": True, "TEST_seed": True, "opened_at": "2026-01-01T00:00:00+00:00"} for i in range(3)])
        assert db.positions.count_documents(q) == before  # same filter the main cycle uses (server.py:1028)
        db.positions.delete_many({"user_id": UID, "TEST_seed": True})


# --- one-click optimize all (main bot)
class TestOptimizeAll:
    def test_full_job(self, s):
        body = {**TestBotC12()._body(s), "symbols": ["BTC-USD"], "setups": []}
        assert s.put(f"{BASE_URL}/api/bot", json=body).status_code == 200
        r = s.post(f"{BASE_URL}/api/bot/optimize-all")
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        r2 = s.post(f"{BASE_URL}/api/bot/optimize-all")
        assert r2.status_code == 429, r2.text
        assert s.get(f"{BASE_URL}/api/bot/optimize-all/nope").status_code == 404
        t0, last, steps = time.time(), None, set()
        while time.time() - t0 < 280:
            last = s.get(f"{BASE_URL}/api/bot/optimize-all/{jid}").json()
            steps.add(last["step"])
            if last["status"] == "done":
                break
            time.sleep(4)
        print("elapsed", round(time.time() - t0), "steps seen", sorted(steps), "result", last.get("results"))
        assert last["status"] == "done" and last["total"] == 8 and last["step"] == 8  # OPT_TFS has 8 TFs (2m, 3m added)
        res = last["results"]
        assert len(res) == 1 and res[0]["symbol"] == "BTC-USD"
        g = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        if res[0]["best"]:
            assert last["applied"] == 1 and len(g["setups"]) == 1
            st = g["setups"][0]
            assert st["symbol"] == "BTC-USD" and st["tf"] == res[0]["tf"] and st["strategy"] == res[0]["best"]["strategy"]
        else:
            assert last["applied"] == 0 and g["setups"] == []
        # can start again once done
        r3 = s.post(f"{BASE_URL}/api/bot/optimize-all")
        assert r3.status_code == 200
        TestOptimizeAll.jid2 = r3.json()["job_id"]

    def test_no_symbols(self, s):
        # wait for any running job from previous test then check 400 when bot has no symbols
        for _ in range(100):
            if s.get(f"{BASE_URL}/api/bot/optimize-all/{TestOptimizeAll.jid2}").json()["status"] == "done":
                break
            time.sleep(3)
        body = {**TestBotC12()._body(s), "symbols": [], "setups": []}
        assert s.put(f"{BASE_URL}/api/bot", json=body).status_code == 200
        r = s.post(f"{BASE_URL}/api/bot/optimize-all")
        assert r.status_code == 400, r.text

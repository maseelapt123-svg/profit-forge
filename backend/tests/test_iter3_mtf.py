# Iteration 3: Multi-timeframe (MTF) confirmation, optimize-all across TFs, bot setups per symbol+tf
import os
import sys
import time
import numpy as np
import pandas as pd
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
sys.path.insert(0, "/app/backend")


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


@pytest.fixture(scope="module", autouse=True)
def restore_bot(s):
    yield
    s.put(f"{BASE_URL}/api/bot", json={"enabled": False, "symbols": ["BTC-USD", "ETH-USD", "EURUSD=X"], "tf": "1h",
                                       "strategy": "smc", "trend_filter": True, "mtf": True, "setups": []})
    s.post(f"{BASE_URL}/api/portfolio/reset")


# --- unit: HTF map + htf_trend no look-ahead
class TestHtfUnit:
    def test_htf_map(self):
        from server import HTF_MAP
        assert HTF_MAP == {"1m": "15m", "5m": "1h", "15m": "4h", "1h": "4h", "4h": "1d", "1d": None}

    def test_htf_trend_no_lookahead(self):
        from strategies import htf_trend
        idx_h = pd.date_range("2025-01-01", periods=400, freq="1h", tz="UTC")
        close = np.linspace(100, 300, 400)  # steady uptrend -> bull
        close[-1] = 1.0  # last HTF bar crashes -> would be bear/0 if looked ahead
        htf = pd.DataFrame({"close": close}, index=idx_h)
        idx_l = pd.date_range(idx_h[-1], periods=12, freq="5min", tz="UTC")  # 5m bars inside last (open) HTF bar
        ltf = pd.DataFrame({"close": np.ones(12)}, index=idx_l)
        t = htf_trend(ltf, htf)
        assert (t == 1).all(), t
        # bars inside the hour after a closed crash bar should see it
        idx_h2 = pd.date_range("2025-01-01", periods=401, freq="1h", tz="UTC")
        htf2 = pd.DataFrame({"close": np.append(close, 1.0)}, index=idx_h2)  # current (open) bar after the crash
        idx_l2 = pd.date_range(idx_h2[-1], periods=3, freq="5min", tz="UTC")
        t2 = htf_trend(pd.DataFrame({"close": np.ones(3)}, index=idx_l2), htf2)
        assert (t2 != 1).all(), t2


# --- backtest mtf flag
class TestBacktestMtf:
    def test_mtf_reduces_trades(self, s):
        base = {"symbol": "BTC-USD", "tf": "5m", "strategy": "smc", "sl_atr": 1.5, "rr": 2.0, "trend_filter": True}
        r0 = s.post(f"{BASE_URL}/api/backtest", json={**base, "mtf": False}, timeout=90)
        r1 = s.post(f"{BASE_URL}/api/backtest", json={**base, "mtf": True}, timeout=90)
        assert r0.status_code == 200, r0.text
        assert r1.status_code == 200, r1.text
        d0, d1 = r0.json(), r1.json()
        assert d0["htf"] == "1h" and d1["htf"] == "1h"
        assert d0["mtf"] is False and d1["mtf"] is True
        print("trades mtf off/on", d0["metrics"]["total_trades"], d1["metrics"]["total_trades"])
        assert d1["metrics"]["total_trades"] <= d0["metrics"]["total_trades"]

    def test_backtest_1d_htf_none(self, s):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1d", "strategy": "smc", "mtf": True}, timeout=90)
        assert r.status_code == 200, r.text
        assert r.json()["htf"] is None and r.json()["mtf"] is False


# --- signals htf
class TestSignalsHtf:
    def test_signals_5m(self, s):
        r = s.get(f"{BASE_URL}/api/signals", params={"category": "crypto", "tf": "5m"}, timeout=120)
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) > 0
        for it in items:
            assert it["htf"] == "1h"
            assert it["htf_trend"] in (-1, 0, 1), it
            if it["direction"] == "BUY":
                assert it["htf_trend"] == 1, it
            if it["direction"] == "SELL":
                assert it["htf_trend"] == -1, it
        print([(i["symbol"], i["direction"], i["htf_trend"]) for i in items])


# --- optimize all
class TestOptimizeAll:
    def test_unknown_symbol(self, s):
        r = s.post(f"{BASE_URL}/api/optimize/all", json={"symbol": "NOPE-XYZ"})
        assert r.status_code == 404

    def test_unknown_job(self, s):
        assert s.get(f"{BASE_URL}/api/optimize/all/doesnotexist").status_code == 404

    def test_full_flow(self, s):
        r = s.post(f"{BASE_URL}/api/optimize/all", json={"symbol": "BTC-USD"})
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        first = s.get(f"{BASE_URL}/api/optimize/all/{jid}").json()
        assert first["status"] in ("running", "done") and first["total"] == 6
        # other user / no auth cannot read
        other = requests.get(f"{BASE_URL}/api/optimize/all/{jid}", headers={"Authorization": "Bearer bogus"})
        assert other.status_code in (401, 404)
        t0 = time.time()
        d = first
        while d["status"] != "done" and time.time() - t0 < 150:
            time.sleep(3)
            d = s.get(f"{BASE_URL}/api/optimize/all/{jid}").json()
        print("optimize-all took", round(time.time() - t0, 1), "s")
        assert d["status"] == "done"
        tfs = [x["tf"] for x in d["results"]]
        assert tfs == ["1m", "5m", "15m", "1h", "4h", "1d"]
        for x in d["results"]:
            assert set(["tf", "htf", "best", "tested", "error"]).issubset(x)
            if x["best"]:
                assert "mtf" in x["best"] and isinstance(x["best"]["mtf"], bool)
                if x["tf"] == "1d":
                    assert x["best"]["mtf"] is False
            print(x["tf"], x["htf"], x["tested"], x["error"], x["best"] and {k: x["best"][k] for k in ("strategy", "mtf", "sl_atr", "rr")})
        assert d["results"][1]["htf"] == "1h"


# --- bot setups
BOT = {"enabled": False, "symbols": ["BTC-USD", "ETH-USD"], "tf": "1h", "strategy": "smc", "risk_pct": 1.0,
       "sl_atr": 1.5, "rr": 2.0, "max_positions": 10, "trend_filter": True, "mtf": True}


class TestBotSetups:
    def test_save_and_drop_foreign(self, s):
        setups = [{"symbol": "BTC-USD", "tf": "5m", "strategy": "smc", "sl_atr": 1.5, "rr": 2, "trend_filter": True, "mtf": True},
                  {"symbol": "BTC-USD", "tf": "1h", "strategy": "combo", "sl_atr": 2, "rr": 3, "trend_filter": True, "mtf": False},
                  {"symbol": "EURUSD=X", "tf": "15m", "strategy": "smc", "sl_atr": 1.5, "rr": 2, "trend_filter": True, "mtf": True}]
        r = s.put(f"{BASE_URL}/api/bot", json={**BOT, "setups": setups})
        assert r.status_code == 200, r.text
        b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert [(x["symbol"], x["tf"]) for x in b["setups"]] == [("BTC-USD", "5m"), ("BTC-USD", "1h")]
        assert b["mtf"] is True and "overrides" not in b

    def test_duplicate(self, s):
        st = {"symbol": "BTC-USD", "tf": "5m", "strategy": "smc"}
        assert s.put(f"{BASE_URL}/api/bot", json={**BOT, "setups": [st, st]}).status_code == 400

    def test_invalid_tf_strategy(self, s):
        assert s.put(f"{BASE_URL}/api/bot", json={**BOT, "setups": [{"symbol": "BTC-USD", "tf": "7m", "strategy": "smc"}]}).status_code == 400
        assert s.put(f"{BASE_URL}/api/bot", json={**BOT, "setups": [{"symbol": "BTC-USD", "tf": "5m", "strategy": "xx"}]}).status_code == 400

    def test_sl_range(self, s):
        assert s.put(f"{BASE_URL}/api/bot", json={**BOT, "setups": [{"symbol": "BTC-USD", "tf": "5m", "strategy": "smc", "sl_atr": 9}]}).status_code == 422

    def test_cycle_multi_tf(self, s):
        s.post(f"{BASE_URL}/api/portfolio/reset")
        setups = [{"symbol": "BTC-USD", "tf": tf, "strategy": "ema_cross", "sl_atr": 1.5, "rr": 2, "trend_filter": False, "mtf": False}
                  for tf in ("1m", "5m", "15m", "1h")]
        r = s.put(f"{BASE_URL}/api/bot", json={**BOT, "enabled": True, "symbols": ["BTC-USD"], "setups": setups})
        assert r.status_code == 200, r.text
        rr = s.post(f"{BASE_URL}/api/bot/run", timeout=120)
        assert rr.status_code == 200, rr.text
        print("run:", rr.json())
        s.put(f"{BASE_URL}/api/bot", json={**BOT, "enabled": False, "symbols": ["BTC-USD"], "setups": setups})
        pf = s.get(f"{BASE_URL}/api/portfolio").json()
        bot_pos = [p for p in pf.get("positions", []) if p.get("source") == "bot"]
        print("bot positions", [(p["symbol"], p.get("tf"), p.get("setup"), p["side"]) for p in bot_pos])
        for p in bot_pos:
            assert p["setup"] == f"{p['symbol']}|{p['tf']}"
        logs = s.get(f"{BASE_URL}/api/bot").json()["logs"]
        print("logs", [l["msg"] for l in logs[:8]])
        if bot_pos:
            assert any("BTC/USD " in l["msg"] and any(f"BTC/USD {t}" in l["msg"] for t in ("1M", "5M", "15M", "1H")) for l in logs)

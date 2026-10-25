# Iteration 4: HFX (OTC/real 1m binary trades, signals, bot) + Tools (indicators, patterns)
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


# --- HFX pairs / candles
class TestHfxMarket:
    def test_pairs_otc(self, s):
        r = s.get(f"{BASE_URL}/api/hfx/pairs", params={"source": "otc"})
        assert r.status_code == 200
        d = r.json()
        assert len(d) == 8
        eu = next(x for x in d if x["pair"] == "EURUSD=X")
        assert eu["display"] == "EUR/USD OTC"
        assert all(x["open"] is True for x in d)

    def test_pairs_real_closed_weekend(self, s):
        r = s.get(f"{BASE_URL}/api/hfx/pairs", params={"source": "real"})
        assert r.status_code == 200
        d = r.json()
        assert len(d) == 8, f"got {len(d)}"
        print("real open flags:", [x["open"] for x in d])
        assert all(x["open"] is False for x in d)

    def test_candles_otc_live(self, s):
        r1 = s.get(f"{BASE_URL}/api/hfx/candles", params={"pair": "EURUSD=X", "source": "otc"}).json()
        time.sleep(2.2)
        r2 = s.get(f"{BASE_URL}/api/hfx/candles", params={"pair": "EURUSD=X", "source": "otc"}).json()
        assert len(r1["candles"]) == 60
        ts = [c["t"] for c in r1["candles"]]
        assert all(b - a == 60 for a, b in zip(ts, ts[1:]))
        assert r1["payout"] == 0.85
        assert r1["price"] != r2["price"], "OTC price did not move in 2s"

    def test_candles_unknown_pair(self, s):
        r = s.get(f"{BASE_URL}/api/hfx/candles", params={"pair": "XXX", "source": "otc"})
        assert r.status_code == 404


# --- HFX signals
class TestHfxSignals:
    @pytest.mark.parametrize("exp", [1, 3])
    def test_signals_otc(self, s, exp):
        r = s.get(f"{BASE_URL}/api/hfx/signals", params={"source": "otc", "expiry": exp})
        assert r.status_code == 200
        d = r.json()
        assert len(d) == 8
        for x in d:
            assert abs(x["breakeven"] - 54.054) < 0.01
            if x["best"]:
                assert x["best"]["samples"] >= 30
            if x["signal"]:
                assert x["signal"] in ("CALL", "PUT")
                assert x["best"]["winrate"] > x["breakeven"]
                assert (x["best"]["fires"] > 0) == (x["signal"] == "CALL")
        print(f"exp{exp} signals:", [(x["display"], x["signal"], round(x["best"]["winrate"], 1) if x["best"] else None) for x in d])

    def test_signals_invalid_expiry(self, s):
        assert s.get(f"{BASE_URL}/api/hfx/signals", params={"source": "otc", "expiry": 2}).status_code == 400

    def test_signals_real_breakeven(self, s):
        d = s.get(f"{BASE_URL}/api/hfx/signals", params={"source": "real", "expiry": 1}).json()
        if d:
            assert abs(d[0]["breakeven"] - 100 / 1.82) < 0.01


# --- HFX trades & settlement
class TestHfxTrades:
    def test_validations(self, s):
        base = {"pair": "EURUSD=X", "source": "otc", "direction": "CALL", "amount": 10, "expiry": 1}
        assert s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "expiry": 2}).status_code == 400
        assert s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "source": "real"}).status_code == 400
        assert s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "pair": "FOO"}).status_code == 404
        assert s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "direction": "UP"}).status_code == 400
        assert s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "amount": 0}).status_code == 422
        bal = s.get(f"{BASE_URL}/api/hfx/trades").json()["balance"]
        if bal < 10000:
            r = s.post(f"{BASE_URL}/api/hfx/trade", json={**base, "amount": min(10000, bal + 1)})
            assert r.status_code == 400, r.text

    def test_open_settle_and_equity(self, s):
        before = s.get(f"{BASE_URL}/api/hfx/trades").json()["balance"]
        r = s.post(f"{BASE_URL}/api/hfx/trade", json={"pair": "GBPUSD=X", "source": "otc", "direction": "PUT", "amount": 20, "expiry": 1})
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["status"] == "open" and t["origin"] == "manual" and abs(t["expires_ts"] - t["opened_ts"] - 60) < 0.01
        d = s.get(f"{BASE_URL}/api/hfx/trades").json()
        assert any(x["trade_id"] == t["trade_id"] for x in d["open"])
        # bot may move balance too; check only our deduction roughly via portfolio locked
        p = s.get(f"{BASE_URL}/api/portfolio").json()
        assert p["hfx_locked"] >= 20
        assert abs(p["equity"] - (p["balance"] + p["unrealized"] + p["hfx_locked"])) < 0.01
        time.sleep(64)
        d = s.get(f"{BASE_URL}/api/hfx/trades").json()
        c = next((x for x in d["closed"] if x["trade_id"] == t["trade_id"]), None)
        assert c is not None, "trade not settled after 64s"
        exp_profit = {"won": 20 * 0.85, "lost": -20, "tie": 0}[c["status"]]
        assert abs(c["profit"] - exp_profit) < 1e-6
        moved = c["exit_price"] < c["entry_price"]
        assert (c["status"] == "won") == moved or c["status"] == "tie"
        print("settled:", c["status"], c["entry_price"], c["exit_price"], "balance before", before, "after", d["balance"])


# --- HFX bot
class TestHfxBot:
    def test_bot_get(self, s):
        d = s.get(f"{BASE_URL}/api/hfx/bot").json()
        for k in ("source", "pairs", "expiry", "amount", "min_winrate", "daily_stop", "daily_target", "max_per_hour", "enabled"):
            assert k in d["bot"]
        assert all(l.get("scope") == "hfx" for l in d["logs"])
        print("bot:", d["bot"], "today:", d["today"], "logs:", [l["msg"] for l in d["logs"][:8]])

    def test_bot_put_validation(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        assert s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "expiry": 2}).status_code == 400
        assert s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": True, "pairs": []}).status_code == 400
        assert s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "amount": 0}).status_code == 422

    def test_bot_trades_exist(self, s):
        d = s.get(f"{BASE_URL}/api/hfx/trades").json()
        bot_trades = [x for x in d["open"] + d["closed"] if x["origin"] == "bot"]
        print("bot trades:", len(bot_trades), [(x["display"], x["direction"], x["status"]) for x in bot_trades[:6]])
        assert len(bot_trades) > 0, "bot enabled but no bot trades"

    def test_main_bot_logs_exclude_hfx(self, s):
        d = s.get(f"{BASE_URL}/api/bot").json()
        logs = d.get("logs", [])
        assert all(l.get("scope") != "hfx" for l in logs)
        assert not any("HFX" in l.get("msg", "") for l in logs)


# --- Tools: indicators / patterns
class TestTools:
    def test_candles_indicators(self, s):
        r = s.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "1h"})
        assert r.status_code == 200, r.text
        d = r.json()
        n = len(d["candles"])
        for k in ("ema20", "ema50", "vwap", "rsi"):
            assert len(d["indicators"][k]) == n, k
        assert isinstance(d["sr_levels"], list) and isinstance(d["fib"], (dict, list))
        print("sr:", d["sr_levels"][:3], "fib:", str(d["fib"])[:200])

    def test_patterns(self, s):
        r = s.get(f"{BASE_URL}/api/patterns", params={"category": "crypto", "tf": "1h"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d, list) and len(d) > 0
        assert "patterns" in d[0]
        print("patterns sample:", str(d[0])[:300])

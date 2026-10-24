# Iteration-1 feature tests: low timeframes (1m/5m), backtest trend_filter/breakeven, walk-forward optimizer, bot trend_filter, SSE AI
import json
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
T = 120
METRIC_KEYS = {"total_trades", "win_rate", "profit_factor", "return_pct", "max_drawdown"}


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    x.headers.update(H)
    return x


# Low timeframe candles + signals
class TestLowTF:
    @pytest.mark.parametrize("tf", ["1m", "5m"])
    def test_candles_low_tf(self, s, tf):
        r = s.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": tf}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tf"] == tf and len(d["candles"]) >= 60
        ts = [c["t"] for c in d["candles"]]
        step = ts[-1] - ts[-2]
        assert step == (60 if tf == "1m" else 300), f"bar step {step}"
        for k in ("order_blocks", "fvgs", "structure", "trend"):
            assert k in d

    def test_signals_5m(self, s):
        r = s.get(f"{BASE_URL}/api/signals", params={"category": "crypto", "tf": "5m"}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d) >= 3
        assert d[0]["direction"] in ("BUY", "SELL", "NEUTRAL")
        assert "trend" in d[0] and "confidence" in d[0]


# Backtest with new options
class TestBacktest:
    @pytest.mark.parametrize("tf", ["1m", "5m", "1h"])
    def test_backtest_tfs(self, s, tf):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": tf, "strategy": "smc",
                                                     "trend_filter": True, "breakeven": True}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert METRIC_KEYS <= set(d["metrics"]), d["metrics"].keys()
        assert d["tf"] == tf and d["bars"] >= 250
        print(tf, d["metrics"])

    def test_smc_1h_filter_vs_nofilter(self, s):
        res = {}
        for tfl in (True, False):
            r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1h", "strategy": "smc",
                                                         "trend_filter": tfl, "breakeven": tfl}, timeout=T)
            assert r.status_code == 200
            res[tfl] = r.json()["metrics"]
        print("filtered", res[True], "\nunfiltered", res[False])
        assert res[True]["return_pct"] > -23, "SMC BTC 1h still as bad as before"

    def test_trades_shape(self, s):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "EURUSD=X", "tf": "1h", "strategy": "combo"}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "equity" in d or "equity_curve" in d, list(d.keys())
        assert "trades" in d


# Walk-forward optimizer
class TestOptimize:
    @pytest.mark.parametrize("sym,tf", [("BTC-USD", "1h"), ("EURUSD=X", "1h"), ("AAPL", "1d")])
    def test_optimize(self, s, sym, tf):
        r = s.post(f"{BASE_URL}/api/optimize", json={"symbol": sym, "tf": tf}, timeout=T)
        assert r.status_code in (200, 400), r.text
        if r.status_code == 400:
            pytest.skip(r.json().get("detail"))
        d = r.json()
        assert "best" in d and "candidates" in d and "tested" in d
        assert d["tested"] > 0
        b = d["best"]
        print(sym, tf, "best:", b and {k: b[k] for k in ("strategy", "trend_filter", "sl_atr", "rr")},
              b and b["test"], "tested", d["tested"])
        if b:
            assert b["test"]["return_pct"] > 0 and b["test"]["profit_factor"] > 1 and b["test"]["total_trades"] >= 5
            assert METRIC_KEYS <= set(b["train"]) and METRIC_KEYS <= set(b["test"])

    def test_optimize_unauth(self):
        assert requests.post(f"{BASE_URL}/api/optimize", json={"symbol": "BTC-USD", "tf": "1h"}).status_code == 401

    def test_optimize_bad_symbol(self, s):
        assert s.post(f"{BASE_URL}/api/optimize", json={"symbol": "ZZZ", "tf": "1h"}, timeout=T).status_code == 404


# Bot trend_filter field and run produces source=bot positions
class TestBotTrend:
    def test_bot_trend_filter_persist(self, s):
        g = s.get(f"{BASE_URL}/api/bot", timeout=T).json()["bot"]
        orig = dict(g)
        body = {k: g[k] for k in ("enabled", "symbols", "tf", "strategy", "risk_pct", "sl_atr", "rr", "max_positions")}
        body.update({"trend_filter": False, "tf": "5m", "enabled": False})
        assert s.put(f"{BASE_URL}/api/bot", json=body, timeout=T).status_code == 200
        g2 = s.get(f"{BASE_URL}/api/bot", timeout=T).json()["bot"]
        assert g2["trend_filter"] is False and g2["tf"] == "5m"
        body.update({"trend_filter": orig.get("trend_filter", True), "tf": orig["tf"], "enabled": orig["enabled"]})
        s.put(f"{BASE_URL}/api/bot", json=body, timeout=T)

    def test_bot_run_positions_source(self, s):
        r = s.post(f"{BASE_URL}/api/bot/run", timeout=T)
        assert r.status_code == 200 and "opened" in r.json()
        p = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        bots = [x for x in p["positions"] if x.get("source") == "bot"]
        print("opened", r.json()["opened"], "bot positions", len(bots))
        for x in bots:
            assert x["stop_loss"] and x["take_profit"]


# AI SSE
class TestAI:
    def test_sse_5m(self, s):
        r = s.post(f"{BASE_URL}/api/ai/analyze", json={"symbol": "ETH-USD", "tf": "5m"}, stream=True, timeout=T)
        assert r.status_code == 200
        chunks, done, err = 0, False, None
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            p = line[6:]
            if p == "[DONE]":
                done = True
                break
            j = json.loads(p)
            if "error" in j:
                err = j["error"]
            if "t" in j:
                chunks += 1
        assert err is None, err
        assert done and chunks > 3

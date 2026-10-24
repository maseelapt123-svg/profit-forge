# Trading app API regression tests: markets, candles/SMC, plugins, signals, backtest, AI SSE, paper trading, auth
import json
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
TOKEN = "test_token_123"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
T = 90


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


# ---- auth
class TestAuth:
    def test_me_no_token(self):
        assert requests.get(f"{BASE_URL}/api/auth/me").status_code == 401

    def test_me_bad_token(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_me_ok(self, s):
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        d = r.json()
        assert d["user_id"] == "user_test1" and "_id" not in d

    @pytest.mark.parametrize("method,path", [("get", "/api/plugins"), ("get", "/api/signals"), ("get", "/api/portfolio"),
                                             ("post", "/api/backtest"), ("post", "/api/orders"), ("post", "/api/ai/analyze"),
                                             ("post", "/api/portfolio/reset")])
    def test_protected(self, method, path):
        body = {"symbol": "BTC-USD", "side": "BUY", "qty": 0.001, "strategy": "smc", "tf": "1h"}
        r = getattr(requests, method)(f"{BASE_URL}{path}", json=body if method == "post" else None)
        assert r.status_code == 401, f"{path} -> {r.status_code}"


# ---- markets
class TestMarkets:
    @pytest.mark.parametrize("cat", ["crypto", "forex", "stocks"])
    def test_markets(self, cat):
        r = requests.get(f"{BASE_URL}/api/markets", params={"category": cat}, timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert len(d) >= 3
        for k in ("symbol", "display", "price", "change_pct", "spark", "decimals"):
            assert k in d[0]
        assert d[0]["price"] > 0

    def test_markets_bad(self):
        assert requests.get(f"{BASE_URL}/api/markets", params={"category": "xx"}).status_code == 400

    @pytest.mark.parametrize("tf", ["15m", "1h", "4h", "1d"])
    def test_candles(self, tf):
        r = requests.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": tf}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["candles"]) > 20
        c = d["candles"][-1]
        assert c["h"] >= c["l"]
        for k in ("order_blocks", "fvgs", "structure", "trend"):
            assert k in d
        n = len(d["candles"])
        for st in d["structure"]:
            assert 0 <= st["break_idx"] < n

    def test_candles_bad_tf(self):
        assert requests.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "7m"}).status_code == 400

    def test_candles_bad_symbol(self):
        assert requests.get(f"{BASE_URL}/api/candles", params={"symbol": "ZZZ", "tf": "1h"}).status_code == 404


# ---- plugins + signals
class TestPlugins:
    def test_get(self, s):
        r = s.get(f"{BASE_URL}/api/plugins")
        assert r.status_code == 200
        d = r.json()
        assert set(d["plugins"]) >= {"smc", "rsi", "ema_cross", "macd", "bollinger"}
        assert "meta" in d

    def test_put_and_persist(self, s):
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {"macd": {"enabled": True, "fast": 10}}})
        assert r.status_code == 200
        g = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        assert g["macd"]["enabled"] is True and g["macd"]["fast"] == 10

    def test_put_invalid(self, s):
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {"rsi": {"enabled": True, "length": "abc"}}})
        assert r.status_code == 400

    def test_put_out_of_range_param(self, s):
        # negative/zero periods should be rejected (no range validation expected to break signals)
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {"rsi": {"enabled": True, "length": -5}}})
        ok = r.status_code == 400
        if not ok:
            sig = s.get(f"{BASE_URL}/api/signals", params={"category": "crypto", "tf": "1h"}, timeout=T)
            print("signals after rsi.length=-5 ->", sig.status_code)
        assert ok, f"rsi.length=-5 accepted ({r.status_code})"

    def test_restore_defaults(self, s):
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {
            "smc": {"enabled": True, "swing": 3}, "rsi": {"enabled": True, "length": 14, "oversold": 30, "overbought": 70},
            "ema_cross": {"enabled": True, "fast": 9, "slow": 21}, "macd": {"enabled": False, "fast": 12, "slow": 26, "signal": 9},
            "bollinger": {"enabled": False, "length": 20, "mult": 2.0}}})
        assert r.status_code == 200

    @pytest.mark.parametrize("cat", ["crypto", "forex", "stocks"])
    def test_signals(self, s, cat):
        r = s.get(f"{BASE_URL}/api/signals", params={"category": cat, "tf": "1h"}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        items = d if isinstance(d, list) else d.get("signals", d)
        assert len(items) > 0
        print(cat, json.dumps(items[0])[:300])


# ---- backtest
class TestBacktest:
    @pytest.mark.parametrize("strategy", ["smc", "combo", "ema_cross", "rsi", "macd", "bollinger"])
    def test_strategies(self, s, strategy):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1h", "strategy": strategy}, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "metrics" in d
        print(strategy, d["metrics"])

    def test_invalid_strategy(self, s):
        assert s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "strategy": "x"}).status_code == 400

    def test_invalid_params(self, s):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "strategy": "smc", "risk_pct": 50})
        assert r.status_code == 400


# ---- AI
class TestAI:
    def test_sse(self, s):
        r = s.post(f"{BASE_URL}/api/ai/analyze", json={"symbol": "BTC-USD", "tf": "1h"}, stream=True, timeout=180)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        chunks, done, err = [], False, None
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
                chunks.append(j["t"])
        assert err is None, err
        assert done and len(chunks) > 3
        print("AI text:", "".join(chunks)[:300])


# ---- paper trading
class TestPaper:
    def test_flow(self, s):
        assert s.post(f"{BASE_URL}/api/portfolio/reset").status_code == 200
        p = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        assert p["balance"] == 10000 and p["positions"] == []
        price = requests.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "1h"}, timeout=T).json()["price"]
        # wrong-side SL/TP
        assert s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": 0.01,
                                                      "stop_loss": price * 1.1}).status_code == 400
        assert s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "SELL", "qty": 0.01,
                                                      "take_profit": price * 1.1}).status_code == 400
        assert s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "HOLD", "qty": 0.01}).status_code == 400
        assert s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": 0}).status_code == 422
        assert s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": 1000}).status_code == 400
        # valid
        b = s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": 0.01,
                                                   "stop_loss": price * 0.8, "take_profit": price * 1.2}, timeout=T)
        assert b.status_code == 200, b.text
        sl = s.post(f"{BASE_URL}/api/orders", json={"symbol": "ETH-USD", "side": "SELL", "qty": 0.1}, timeout=T)
        assert sl.status_code == 200, sl.text
        p = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        assert len(p["positions"]) == 2
        assert "_id" not in p["positions"][0]
        pid = b.json()["position_id"]
        c = s.post(f"{BASE_URL}/api/positions/{pid}/close", timeout=T)
        assert c.status_code == 200 and "pnl" in c.json()
        assert s.post(f"{BASE_URL}/api/positions/{pid}/close").status_code == 404
        p = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        assert len(p["positions"]) == 1 and len(p["history"]) == 1
        assert abs(p["balance"] - (10000 + c.json()["pnl"])) < 1e-6

    def test_unknown_symbol_order(self, s):
        r = s.post(f"{BASE_URL}/api/orders", json={"symbol": "ZZZ", "side": "BUY", "qty": 1})
        print("unknown symbol order ->", r.status_code, r.text)
        assert r.status_code in (400, 404)

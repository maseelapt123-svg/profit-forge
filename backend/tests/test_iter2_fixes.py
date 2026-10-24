# Iteration-2 regression tests: order validation/margin, plugin param ranges, bot run guard/lock, per-asset overrides,
# backtest skipped_cost, signals trend filter, background SL/TP of manual positions
import concurrent.futures as cf
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
T = 120


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    x.headers.update(H)
    return x


@pytest.fixture(scope="module", autouse=True)
def restore_state(s):
    bot0 = s.get(f"{BASE_URL}/api/bot", timeout=T).json()["bot"]
    plug0 = s.get(f"{BASE_URL}/api/plugins", timeout=T).json()["plugins"]
    yield
    keys = ["enabled", "symbols", "tf", "strategy", "risk_pct", "sl_atr", "rr", "max_positions", "trend_filter", "overrides"]
    body = {k: bot0[k] for k in keys if k in bot0}
    body["enabled"] = False
    s.put(f"{BASE_URL}/api/bot", json=body, timeout=T)
    s.put(f"{BASE_URL}/api/plugins", json={"plugins": plug0}, timeout=T)
    s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)


def bot_body(**kw):
    b = {"enabled": False, "symbols": ["BTC-USD", "ETH-USD"], "tf": "1h", "strategy": "smc", "risk_pct": 1.0,
         "sl_atr": 1.5, "rr": 2.0, "max_positions": 3, "trend_filter": True, "overrides": {}}
    b.update(kw)
    return b


# Orders
class TestOrders:
    def test_unknown_symbol_404(self, s):
        r = s.post(f"{BASE_URL}/api/orders", json={"symbol": "ZZZ", "side": "BUY", "qty": 1}, timeout=T)
        assert r.status_code == 404, r.text

    def test_margin_includes_open_positions(self, s):
        s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)
        px = s.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "1h"}, timeout=T).json()["candles"][-1]["c"]
        qty = (10000 * 10 * 0.6) / px  # 60% of 10x
        r1 = s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": qty}, timeout=T)
        assert r1.status_code == 200, r1.text
        r2 = s.post(f"{BASE_URL}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": qty}, timeout=T)
        assert r2.status_code == 400, r2.text
        assert "alavancagem" in r2.json()["detail"]
        s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)


# Plugins param validation
class TestPluginRanges:
    @pytest.mark.parametrize("plug", [
        {"rsi": {"enabled": True, "length": -5, "oversold": 30, "overbought": 70}},
        {"ema_cross": {"enabled": True, "fast": 30, "slow": 21}},
        {"rsi": {"enabled": True, "length": 14, "oversold": 50, "overbought": 50}},
        {"rsi": {"enabled": True, "length": "abc"}},
    ])
    def test_reject(self, s, plug):
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": plug}, timeout=T)
        assert r.status_code == 400, r.text

    def test_valid_saved(self, s):
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {"rsi": {"enabled": True, "length": 10, "oversold": 25, "overbought": 75}}}, timeout=T)
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/plugins", timeout=T).json()["plugins"]["rsi"]
        assert g["length"] == 10 and g["oversold"] == 25


# Bot run guard, overrides, lock
class TestBot:
    def test_run_disabled_400(self, s):
        s.put(f"{BASE_URL}/api/bot", json=bot_body(enabled=False), timeout=T)
        r = s.post(f"{BASE_URL}/api/bot/run", timeout=T)
        assert r.status_code == 400 and "Ativa o robô" in r.json()["detail"], r.text

    def test_overrides_saved(self, s):
        ov = {"ETH-USD": {"tf": "15m", "strategy": "rsi", "sl_atr": 2.0, "rr": 3.0, "trend_filter": False}}
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(overrides=ov), timeout=T)
        assert r.status_code == 200, r.text
        b = s.get(f"{BASE_URL}/api/bot", timeout=T).json()["bot"]
        assert b["tf"] == "1h" and b["strategy"] == "smc"
        assert b["overrides"]["ETH-USD"] == ov["ETH-USD"]

    def test_override_invalid_tf_400(self, s):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(overrides={"ETH-USD": {"tf": "7x", "strategy": "smc"}}), timeout=T)
        assert r.status_code == 400

    def test_override_bad_number_not_500(self, s):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(overrides={"ETH-USD": {"tf": "1h", "strategy": "smc", "sl_atr": "abc"}}), timeout=T)
        assert r.status_code in (400, 422), f"{r.status_code} {r.text}"

    def test_override_out_of_range_rejected(self, s):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(overrides={"ETH-USD": {"tf": "1h", "strategy": "smc", "sl_atr": 50, "rr": -1}}), timeout=T)
        assert r.status_code in (400, 422), f"{r.status_code} {r.text}"

    def test_concurrent_run_no_duplicates(self, s):
        s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)
        syms = ["BTC-USD", "ETH-USD", "SOL-USD", "EURUSD=X", "GBPUSD=X"]
        s.put(f"{BASE_URL}/api/bot", json=bot_body(enabled=True, symbols=syms, tf="1m", strategy="ema_cross", trend_filter=False, max_positions=10), timeout=T)
        with cf.ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda _: requests.post(f"{BASE_URL}/api/bot/run", headers=H, timeout=T), range(4)))
        assert all(r.status_code == 200 for r in res), [r.text for r in res]
        pos = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()["positions"]
        bot_syms = [p["symbol"] for p in pos if p.get("source") == "bot"]
        print("opened:", [r.json()["opened"] for r in res], bot_syms)
        assert len(bot_syms) == len(set(bot_syms))
        s.put(f"{BASE_URL}/api/bot", json=bot_body(enabled=False), timeout=T)
        s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)


# Backtest skipped_cost
class TestBacktest:
    def test_skipped_cost_1m(self, s):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1m", "strategy": "smc"}, timeout=T)
        assert r.status_code == 200, r.text
        m = r.json()["metrics"]
        print("metrics:", m)
        assert "skipped_cost" in m and m["skipped_cost"] > 0


# Signals
class TestSignals:
    def test_signals_trend_aligned(self, s):
        r = s.get(f"{BASE_URL}/api/signals", params={"category": "crypto", "tf": "1h"}, timeout=T)
        assert r.status_code == 200
        for x in r.json():
            if x["direction"] == "BUY":
                assert x["trend"] == "alta", x
            if x["direction"] == "SELL":
                assert x["trend"] == "baixa", x

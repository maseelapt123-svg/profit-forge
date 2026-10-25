# Iteration 5: HFX plugins (GET/PUT validation), walk-forward optimizer, HFX bot strategy/setups, payout settle, tools
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
PLUGINS = ["bb_rsi", "rsi2", "stoch", "ema_mom", "engolfo", "pinbar", "streak"]


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


@pytest.fixture(scope="module")
def opt(s):
    t = time.time()
    r = s.post(f"{BASE_URL}/api/hfx/optimize", json={"expiry": 1}, timeout=120)
    print(f"optimize took {time.time()-t:.1f}s")
    assert r.status_code == 200, r.text
    return r.json()


# --- HFX plugins
class TestHfxPlugins:
    def test_get_plugins(self, s):
        d = s.get(f"{BASE_URL}/api/hfx/plugins").json()
        assert set(PLUGINS) <= set(d["plugins"].keys())
        assert set(PLUGINS) <= set(d["meta"].keys())
        for k in PLUGINS:
            assert "enabled" in d["plugins"][k]

    def test_put_roundtrip_and_restore(self, s):
        orig = s.get(f"{BASE_URL}/api/hfx/plugins").json()["plugins"]
        mod = {k: dict(v) for k, v in orig.items()}
        mod["rsi2"]["enabled"] = not orig["rsi2"]["enabled"]
        r = s.put(f"{BASE_URL}/api/hfx/plugins", json={"plugins": mod})
        assert r.status_code == 200, r.text
        got = s.get(f"{BASE_URL}/api/hfx/plugins").json()["plugins"]
        assert got["rsi2"]["enabled"] == mod["rsi2"]["enabled"]
        assert s.put(f"{BASE_URL}/api/hfx/plugins", json={"plugins": orig}).status_code == 200

    def test_put_range_validation(self, s):
        orig = s.get(f"{BASE_URL}/api/hfx/plugins").json()["plugins"]
        num = next((k, p) for k in PLUGINS for p, v in orig[k].items() if p != "enabled" and isinstance(v, (int, float)) and not isinstance(v, bool))
        bad = {k: dict(v) for k, v in orig.items()}
        bad[num[0]][num[1]] = 999999
        r = s.put(f"{BASE_URL}/api/hfx/plugins", json={"plugins": bad})
        assert r.status_code == 400, r.text
        bad2 = {k: dict(v) for k, v in orig.items()}
        bad2[num[0]][num[1]] = "abc"
        assert s.put(f"{BASE_URL}/api/hfx/plugins", json={"plugins": bad2}).status_code == 400

    def test_put_ema_fast_ge_slow(self, s):
        orig = s.get(f"{BASE_URL}/api/hfx/plugins").json()["plugins"]
        bad = {k: dict(v) for k, v in orig.items()}
        if "fast" in bad["ema_mom"] and "slow" in bad["ema_mom"]:
            bad["ema_mom"]["fast"], bad["ema_mom"]["slow"] = bad["ema_mom"]["slow"], bad["ema_mom"]["fast"]
            assert s.put(f"{BASE_URL}/api/hfx/plugins", json={"plugins": bad}).status_code == 400


# --- HFX optimizer
class TestHfxOptimize:
    def test_invalid_expiry(self, s):
        assert s.post(f"{BASE_URL}/api/hfx/optimize", json={"expiry": 2}).status_code == 400

    def test_results_shape(self, opt):
        assert opt["expiry"] == 1 and abs(opt["payout"] - 0.82) < 1e-9
        assert len(opt["results"]) > 0
        for r in opt["results"]:
            assert "pair" in r and "best" in r and "top" in r
            if r["best"]:
                b = r["best"]
                assert {"rule", "label", "train", "test"} <= set(b)
                assert "lower_bound" in b["test"] and "winrate" in b["test"]
        print([(r["pair"], r["best"]["rule"] if r["best"] else None, r["best"]["test"] if r["best"] else None) for r in opt["results"]])


# --- HFX bot strategy / setups validation
class TestHfxBotStrategy:
    def test_bad_strategy(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        assert s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "strategy": "xyz"}).status_code == 400

    def test_bad_rule(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        r = s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": False, "setups": {"EURUSD=X": {"rule": "nope", "expiry": 1}}})
        assert r.status_code == 400

    def test_bad_setup_expiry_non_numeric(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        r = s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": False, "setups": {"EURUSD=X": {"rule": "rsi2", "expiry": "x"}}})
        assert r.status_code in (400, 422), f"got {r.status_code}"

    def test_optimized_enabled_without_setups(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        r = s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": True, "strategy": "optimized", "setups": {},
                                                    "pairs": cur["pairs"] or ["EURUSD=X"]})
        assert r.status_code == 400

    def test_setups_persist(self, s, opt):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        setups = {r["pair"]: {"rule": r["best"]["rule"], "expiry": 1} for r in opt["results"] if r["best"]}
        if not setups:
            setups = {"EURUSD=X": {"rule": "bb_rsi+rsi2", "expiry": 3}}
        r = s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": False, "strategy": "optimized", "min_votes": 2, "setups": setups})
        assert r.status_code == 200, r.text
        b = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        assert b["strategy"] == "optimized" and b["min_votes"] == 2
        assert set(b["setups"].keys()) == set(setups.keys())
        for v in b["setups"].values():
            assert "label" in v

    def test_restore(self, s):
        cur = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        r = s.put(f"{BASE_URL}/api/hfx/bot", json={**cur, "enabled": False, "strategy": "auto", "setups": {}})
        assert r.status_code == 200
        b = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        assert b["enabled"] is False and b["strategy"] == "auto" and b["setups"] == {}


# --- OTC trade payout settle (85%)
class TestHfxPayout:
    def test_otc_payout_and_deduct(self, s):
        before = s.get(f"{BASE_URL}/api/hfx/trades").json()["balance"]
        r = s.post(f"{BASE_URL}/api/hfx/trade", json={"pair": "EURUSD=X", "source": "otc", "direction": "CALL", "amount": 10, "expiry": 1})
        assert r.status_code == 200, r.text
        t = r.json()
        assert abs(t["payout"] - 0.85) < 1e-9
        after = s.get(f"{BASE_URL}/api/hfx/trades").json()["balance"]
        assert abs((before - after) - 10) < 0.01 or after < before
        deadline = time.time() + 80
        while time.time() < deadline:
            d = s.get(f"{BASE_URL}/api/hfx/trades").json()
            c = next((x for x in d["closed"] if x["trade_id"] == t["trade_id"]), None)
            if c:
                exp = 8.5 if c["status"] == "won" else -10 if c["status"] == "lost" else 0
                assert abs(c["profit"] - exp) < 0.01
                return
            time.sleep(3)
        pytest.fail("trade not settled within 80s")


# --- Tools: calculator math is client-side; patterns params
class TestTools:
    def test_candles_indicator_alignment(self, s):
        d = s.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "1h"}).json()
        n = len(d["candles"])
        for k in ("ema20", "ema50", "vwap", "rsi"):
            assert len(d["indicators"][k]) == n, k
        assert "sr_levels" in d and "fib" in d

    def test_patterns_tf(self, s):
        r = s.get(f"{BASE_URL}/api/patterns", params={"category": "forex", "tf": "1d"})
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), (list, dict))

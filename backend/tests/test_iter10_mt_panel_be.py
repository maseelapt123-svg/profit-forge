# Iteration 10: MT5 live panel endpoint + break-even toggle on bot config (read-only on MT; never places/closes orders)
import os
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    x.headers.update(H)
    return x


# MT panel: /live/mt/positions
class TestMtPositions:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/live/mt/positions", timeout=30)
        assert r.status_code == 401

    def test_shape(self, s):
        r = s.get(f"{BASE_URL}/api/live/mt/positions", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        a = d["account"]
        for k in ("balance", "equity", "free_margin", "currency", "login", "server", "margin", "type"):
            assert k in a, k
        assert isinstance(a["balance"], (int, float)) and isinstance(a["equity"], (int, float))
        assert isinstance(a["currency"], str) and a["currency"]
        assert isinstance(d["positions"], list)
        for p in d["positions"]:
            for k in ("id", "symbol", "side", "volume", "open_price", "price", "sl", "tp", "profit", "swap", "commission", "time", "bot"):
                assert k in p, k
            assert p["side"] in ("BUY", "SELL")
            assert isinstance(p["id"], str)
        exp = round(sum(p["profit"] + p["swap"] + p["commission"] for p in d["positions"]), 2)
        assert abs(d["total_profit"] - exp) < 0.02
        print("MT account", a, "positions", len(d["positions"]), "total", d["total_profit"])

    def test_no_mongo_id(self, s):
        r = s.get(f"{BASE_URL}/api/live/mt/positions", timeout=60)
        assert "_id" not in r.text


# Bot config: breakeven_enabled persists (restored after)
class TestBreakevenToggle:
    def test_toggle_persist_restore(self, s):
        orig = s.get(f"{BASE_URL}/api/bot", timeout=30).json()
        orig_cfg = orig.get("bot", orig)
        assert "breakeven_enabled" in orig_cfg
        assert orig_cfg.get("live_mode") == "paper"
        be0 = orig_cfg["breakeven_enabled"]
        body = {k: v for k, v in orig_cfg.items() if k not in ("user_id",)}
        try:
            body["breakeven_enabled"] = not be0
            r = s.put(f"{BASE_URL}/api/bot", json=body, timeout=30)
            assert r.status_code == 200, r.text
            g = s.get(f"{BASE_URL}/api/bot", timeout=30).json()
            g = g.get("bot", g)
            assert g["breakeven_enabled"] == (not be0)
            assert g["ptp_enabled"] == orig_cfg["ptp_enabled"]
            assert g["live_mode"] == "paper"
        finally:
            body["breakeven_enabled"] = be0
            s.put(f"{BASE_URL}/api/bot", json=body, timeout=30)
            g = s.get(f"{BASE_URL}/api/bot", timeout=30).json()
            g = g.get("bot", g)
            assert g["breakeven_enabled"] == be0

    def test_invalid_type_rejected(self, s):
        orig = s.get(f"{BASE_URL}/api/bot", timeout=30).json()
        orig_cfg = orig.get("bot", orig)
        body = {k: v for k, v in orig_cfg.items() if k != "user_id"}
        body["breakeven_enabled"] = "notabool"
        r = s.put(f"{BASE_URL}/api/bot", json=body, timeout=30)
        assert r.status_code == 422

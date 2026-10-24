# Auto-trading bot (paper) API regression tests: GET/PUT /api/bot, POST /api/bot/run, max_positions, logs, reset
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
T = 120
ALL_SYMS = None


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    ss.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)
    yield ss
    # teardown: disable bot + reset
    ss.put(f"{BASE_URL}/api/bot", json={"enabled": False, "symbols": ["BTC-USD"], "tf": "1h", "strategy": "combo",
                                         "risk_pct": 1, "sl_atr": 1.5, "rr": 2, "max_positions": 3}, timeout=T)
    ss.post(f"{BASE_URL}/api/portfolio/reset", timeout=T)


class TestBot:
    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/bot", timeout=30).status_code == 401
        assert requests.post(f"{BASE_URL}/api/bot/run", timeout=30).status_code == 401

    def test_get_default(self, s):
        r = s.get(f"{BASE_URL}/api/bot", timeout=T)
        assert r.status_code == 200
        d = r.json()
        for k in ("bot", "logs", "stats", "assets"):
            assert k in d
        assert "last_bar" not in d["bot"]
        assert isinstance(d["assets"], list) and len(d["assets"]) > 5
        assert set(d["stats"]) >= {"trades", "pnl", "wins", "open"}

    @pytest.mark.parametrize("payload,code", [
        ({"enabled": True, "symbols": [], "tf": "1h", "strategy": "combo"}, 400),
        ({"enabled": False, "symbols": ["BTC-USD"], "tf": "7m", "strategy": "combo"}, 400),
        ({"enabled": False, "symbols": ["BTC-USD"], "tf": "1h", "strategy": "xyz"}, 400),
        ({"enabled": False, "symbols": ["BTC-USD"], "tf": "1h", "strategy": "combo", "risk_pct": 50}, 422),
        ({"enabled": False, "symbols": ["BTC-USD"], "tf": "1h", "strategy": "combo", "max_positions": 0}, 422),
    ])
    def test_put_validation(self, s, payload, code):
        r = s.put(f"{BASE_URL}/api/bot", json=payload, timeout=T)
        assert r.status_code == code, r.text

    def test_put_persist_and_status_log(self, s):
        cfg = {"enabled": True, "symbols": ["BTC-USD", "FAKE-SYM", "ETH-USD"], "tf": "4h", "strategy": "ema_cross",
               "risk_pct": 2, "sl_atr": 2, "rr": 3, "max_positions": 2}
        r = s.put(f"{BASE_URL}/api/bot", json=cfg, timeout=T)
        assert r.status_code == 200
        d = s.get(f"{BASE_URL}/api/bot", timeout=T).json()
        b = d["bot"]
        assert b["enabled"] is True and b["tf"] == "4h" and b["strategy"] == "ema_cross"
        assert b["symbols"] == ["BTC-USD", "ETH-USD"]  # unknown filtered
        assert b["max_positions"] == 2 and b["risk_pct"] == 2
        assert any(l["kind"] == "status" and "ativado" in l["msg"] for l in d["logs"])

    def test_run_with_max_positions_1(self, s):
        global ALL_SYMS
        d = s.get(f"{BASE_URL}/api/bot", timeout=T).json()
        ALL_SYMS = [a["symbol"] for a in d["assets"]]
        cfg = {"enabled": False, "symbols": ALL_SYMS, "tf": "1h", "strategy": "combo",
               "risk_pct": 1, "sl_atr": 1.5, "rr": 2, "max_positions": 1}
        assert s.put(f"{BASE_URL}/api/bot", json=cfg, timeout=T).status_code == 200
        r = s.post(f"{BASE_URL}/api/bot/run", timeout=300)
        assert r.status_code == 200, r.text
        opened = r.json()["opened"]
        print("opened:", opened)
        assert opened <= 1
        pf = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        bot_pos = [p for p in pf["positions"] if p.get("source") == "bot"]
        assert len(bot_pos) <= 1
        for p in bot_pos:
            if p["side"] == "BUY":
                assert p["stop_loss"] < p["entry"] < p["take_profit"]
            else:
                assert p["take_profit"] < p["entry"] < p["stop_loss"]
        g = s.get(f"{BASE_URL}/api/bot", timeout=T).json()
        assert g["bot"].get("last_run")
        kinds = [l["kind"] for l in g["logs"]]
        print("log kinds:", kinds[:20])
        if opened == 1:
            assert "open" in kinds
        assert g["stats"]["open"] == len(bot_pos)

    def test_second_run_no_duplicate(self, s):
        before = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        n_before = len([p for p in before["positions"] if p.get("source") == "bot"])
        r = s.post(f"{BASE_URL}/api/bot/run", timeout=300)
        assert r.status_code == 200
        assert r.json()["opened"] == 0  # same closed bar -> skipped
        after = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        assert len([p for p in after["positions"] if p.get("source") == "bot"]) <= max(n_before, 1)

    def test_reset_clears_logs(self, s):
        assert s.post(f"{BASE_URL}/api/portfolio/reset", timeout=T).status_code == 200
        d = s.get(f"{BASE_URL}/api/bot", timeout=T).json()
        assert d["logs"] == [] and d["stats"]["open"] == 0
        pf = s.get(f"{BASE_URL}/api/portfolio", timeout=T).json()
        assert pf["balance"] == 10000 and pf["positions"] == []

# Iteration 9: simulation without 50-trade cap (days_covered), per-kind c12/c20 optimizer lock,
# generated SmartTradeAll.mq5 EA (preview / link / download), legacy SmartTrade12C.mq5.
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
SETUP = {"kind": "setup", "symbol": "BTC-USD", "tf": "1h", "strategy": "ema_cross", "sl_atr": 1.5, "rr": 2}


def poll(path, timeout=300, every=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE_URL}{path}", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        if j.get("status") == "done":
            return j
        time.sleep(every)
    pytest.fail(f"timeout polling {path}")


def run_sim(items, days, ai=False):
    for _ in range(40):
        r = requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": items, "days": days, "ai": ai, "capital": 10000, "risk_pct": 1}, timeout=60)
        if r.status_code != 429:
            break
        time.sleep(3)
    assert r.status_code == 200, r.text
    return poll(f"/api/simulate/{r.json()['job_id']}")


@pytest.fixture(scope="module", autouse=True)
def bot_backup():
    b = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    yield b
    restore = {k: v for k, v in b.items() if k not in ("user_id", "updated_at", "last_run", "fixes", "auto_fix", "last_bar", "fix_ts")}
    r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=restore, timeout=60)
    print("restore bot", r.status_code, r.text[:200])


# --- Simulation: no 50-trade cap
class TestSimulateAllTrades:
    def test_trade_counts_increase_with_days(self):
        res = {}
        for d in (30, 180, 365):
            j = run_sim([SETUP], d)
            assert not j.get("error"), j.get("error")
            row = j["rows"][0]
            assert "error" not in row, row
            res[d] = (row["no_ai"]["trades"], row["days_covered"], row["no_ai"]["pct"], j["days_covered"])
        print("sim 1h ema_cross:", res)
        assert res[30][0] < res[180][0] < res[365][0], res
        assert res[365][0] > 50
        assert res[180][2] != res[365][2]

    def test_15m_days_covered_and_avg_daily(self):
        j = run_sim([{**SETUP, "tf": "15m"}], 365)
        row = j["rows"][0]
        print("15m 365d:", row["days_covered"], j["days_covered"], row["no_ai"])
        assert 40 <= row["days_covered"] <= 75, row["days_covered"]
        assert j["days_covered"] == row["days_covered"]
        s = row["no_ai"]
        if s["final"] > 0:
            geo = ((s["final"] / 10000) ** (1 / row["days_covered"]) - 1) * 100
            assert abs(geo - s["avg_daily_pct"]) < 0.01, (geo, s["avg_daily_pct"])


# --- Per-kind optimizer lock
class TestOptimizerPerKindLock:
    def test_c12_and_c20_parallel(self):
        r12 = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c12", headers=H, timeout=60)
        r20 = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c20", headers=H, timeout=60)
        assert r12.status_code == 200, r12.text
        assert r20.status_code == 200, r20.text
        dup = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c12", headers=H, timeout=60)
        print("dup c12:", dup.status_code, dup.text[:120])
        j12 = poll(f"/api/bot/c20-optimize/{r12.json()['job_id']}")
        j20 = poll(f"/api/bot/c20-optimize/{r20.json()['job_id']}")
        assert j12["kind"] == "c12" and j20["kind"] == "c20"
        print("c12 results", j12["results"], "c20 results", j20["results"])
        assert dup.status_code in (429, 200)

    def test_invalid_kind(self):
        r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=xx", headers=H, timeout=60)
        assert r.status_code == 400


# --- Generated EA with all strategies
class TestEaAll:
    def test_preview(self, bot_backup):
        r = requests.get(f"{BASE_URL}/api/ea/all", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        print("ea/all:", j)
        assert j["count"] == len(j["setups"]) and j["count"] >= 1
        kinds = {s["kind"] for s in j["setups"]}
        assert 0 in kinds
        assert any(s["symbol"] == "BTC-USD" and s["tf"] == "5m" for s in j["setups"] if s["kind"] == 0)
        for s in j["setups"]:
            assert s["mt_symbol"] == "BTCUSD"

    def test_preview_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/ea/all", timeout=60).status_code == 401

    def test_link_and_download(self):
        r = requests.post(f"{BASE_URL}/api/ea/all/link", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        path = r.json()["path"]
        assert path.startswith("/ea/all/") and path.endswith("/SmartTradeAll.mq5")
        d = requests.get(f"{BASE_URL}/api{path}", timeout=60)
        assert d.status_code == 200, d.text[:200]
        assert "attachment" in d.headers.get("content-disposition", "")
        src = d.text
        prev = requests.get(f"{BASE_URL}/api/ea/all", headers=H, timeout=60).json()
        assert f"#define NCFG {prev['count']}" in src
        assert "CSym[]" in src and "CTf[]" in src
        assert '"BTCUSD"' in src and "PERIOD_M5" in src and '"killzone"' in src
        assert "__CONFIG__" not in src and "__USER__" not in src and "__RISK__" not in src
        assert "test@example.com" in src

    def test_invalid_token(self):
        assert requests.get(f"{BASE_URL}/api/ea/all/deadbeef/SmartTradeAll.mq5", timeout=60).status_code == 404

    def test_link_requires_auth(self):
        assert requests.post(f"{BASE_URL}/api/ea/all/link", timeout=60).status_code == 401

    def test_legacy_ea(self):
        r = requests.get(f"{BASE_URL}/api/ea/SmartTrade12C.mq5", timeout=60)
        assert r.status_code == 200 and "OnTick" in r.text

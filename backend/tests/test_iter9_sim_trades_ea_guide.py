# Iteration 9: simulation no longer capped at 50 trades, days_covered / avg_daily_pct, per-kind c12/c20 optimizer
# locks, EA .mq5 download regression.
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
RESULTS = {}


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


def run_sim(items, days, capital=10000):
    for _ in range(40):  # wait if a previous sim is still running
        r = requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": items, "days": days, "capital": capital, "risk_pct": 1, "ai": False}, timeout=60)
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
    restore["enabled"] = False
    restore["live_mode"] = "paper"
    r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=restore, timeout=60)
    print("restore bot", r.status_code, r.text[:200])


# --- EA download regression
def test_ea_download():
    r = requests.get(f"{BASE_URL}/api/ea/SmartTrade12C.mq5", timeout=60)
    assert r.status_code == 200
    assert len(r.content) > 1000
    assert "OnTick" in r.text or "OnInit" in r.text
    print("EA headers", r.headers.get("content-type"), r.headers.get("content-disposition"))


# --- Simulation: trade count must grow with the period (no 50 cap)
ITEM_1H = [{"kind": "setup", "symbol": "BTC-USD", "tf": "1h", "strategy": "ema_cross", "sl_atr": 1.5, "rr": 2}]


@pytest.mark.parametrize("days", [30, 180, 365])
def test_sim_1h_ema_cross(days):
    j = run_sim(ITEM_1H, days)
    assert not j.get("error"), j.get("error")
    row = j["rows"][0]
    assert "error" not in row, row
    n = row["no_ai"]["trades"]
    RESULTS[days] = j
    print(f"days={days} trades={n} days_covered={j.get('days_covered')} row_cov={row.get('days_covered')} "
          f"pct={row['no_ai']['pct']} avg_daily={row['no_ai']['avg_daily_pct']} trading_days={row['no_ai']['trading_days']}")
    assert j["total"]["no_ai"]["trades"] == n
    assert "days_covered" in j and isinstance(j["days_covered"], int)
    assert j["days_covered"] <= days


def test_sim_trade_count_grows():
    if not all(d in RESULTS for d in (30, 180, 365)):
        pytest.skip("previous sims failed")
    n = {d: RESULTS[d]["rows"][0]["no_ai"]["trades"] for d in (30, 180, 365)}
    print("trade counts", n)
    assert n[30] < n[180] < n[365]
    assert n[365] > 50


def test_sim_avg_daily_uses_days_covered():
    j = RESULTS.get(365)
    if not j:
        pytest.skip("no 365 run")
    s = j["total"]["no_ai"]
    cov = j["days_covered"]
    expected = ((s["final"] / 10000) ** (1 / cov) - 1) * 100
    print("cov", cov, "avg", s["avg_daily_pct"], "expected", expected)
    assert abs(s["avg_daily_pct"] - expected) < 0.01


def test_sim_15m_days_covered():
    j = run_sim([{"kind": "setup", "symbol": "BTC-USD", "tf": "15m", "strategy": "ema_cross", "sl_atr": 1.5, "rr": 2}], 365)
    assert not j.get("error"), j.get("error")
    row = j["rows"][0]
    print("15m 365d: days_covered", j["days_covered"], "trades", row["no_ai"]["trades"], "avg", row["no_ai"]["avg_daily_pct"])
    assert 45 <= j["days_covered"] <= 75
    assert row["days_covered"] == j["days_covered"]
    s = row["no_ai"]
    expected = ((s["final"] / 10000) ** (1 / j["days_covered"]) - 1) * 100
    assert abs(s["avg_daily_pct"] - expected) < 0.01


# --- c12/c20 optimizer: separate per-kind locks
def test_c12_c20_parallel_optimizers():
    r1 = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c12", headers=H, timeout=60)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c20", headers=H, timeout=60)
    assert r2.status_code == 200, f"c20 blocked by running c12: {r2.status_code} {r2.text}"
    # same kind again while running -> 429
    r3 = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=c12", headers=H, timeout=60)
    print("dup c12", r3.status_code, r3.text[:120])
    assert r3.status_code == 429
    assert "12 Confirmações" in r3.json()["detail"]
    j1 = poll(f"/api/bot/c20-optimize/{r1.json()['job_id']}")
    j2 = poll(f"/api/bot/c20-optimize/{r2.json()['job_id']}")
    assert j1["kind"] == "c12" and j2["kind"] == "c20"
    assert len(j1["results"]) >= 1 and len(j2["results"]) >= 1
    b = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    syms = {p["symbol"] for p in j1["results"]}
    assert syms <= {p["symbol"] for p in b.get("c12_pairs", [])}
    assert {p["symbol"] for p in j2["results"]} <= {p["symbol"] for p in b.get("c20_pairs", [])}
    print("c12", j1["results"], "c20", j2["results"])


def test_optimizer_invalid_kind():
    r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=xx", headers=H, timeout=60)
    assert r.status_code == 400

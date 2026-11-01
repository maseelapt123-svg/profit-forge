# Iteration 8: Simulate (monthly sim, negopt), c12/c20 per-pair optimizers, daily-results, bot PUT limits,
# live execution modes (not configured), MQL5 EA download, confirm20 backtest with partial TP.
import os
import time
import copy
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
BOT_FIELDS = None

ITEMS = [{"kind": "setup", "symbol": "BTC-USD", "tf": "1h", "strategy": "donchian", "sl_atr": 1.5, "rr": 2},
         {"kind": "c20", "symbol": "ETH-USD", "tf": "1h", "min": 16, "rr": 5}]


def poll(path, timeout=240, every=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE_URL}{path}", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        if j.get("status") == "done":
            return j
        time.sleep(every)
    pytest.fail(f"timeout polling {path}")


@pytest.fixture(scope="module", autouse=True)
def bot_backup():
    b = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    yield b
    restore = {k: v for k, v in b.items() if k not in ("user_id", "updated_at", "last_run", "fixes", "auto_fix", "last_bar", "fix_ts")}
    restore["enabled"] = False
    restore["live_mode"] = "paper"
    r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=restore, timeout=60)
    print("restore bot", r.status_code, r.text[:200])


def bot_payload(base, **over):
    p = {k: v for k, v in copy.deepcopy(base).items() if k not in ("user_id", "updated_at", "last_run", "fixes", "auto_fix")}
    p["enabled"] = False
    p.update(over)
    return p


# --- EA download
def test_ea_download():
    r = requests.get(f"{BASE_URL}/api/ea/SmartTrade12C.mq5", timeout=60)
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    assert len(r.text) > 500 and ("OnTick" in r.text or "OnInit" in r.text)


# --- Simulate
@pytest.mark.parametrize("days,capital", [(30, 10), (180, 10000), (365, 10000), (30, 10000)])
def test_simulate(days, capital):
    r = requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": ITEMS, "days": days, "capital": capital, "ai": False}, timeout=60)
    assert r.status_code == 200, r.text
    j = poll(f"/api/simulate/{r.json()['job_id']}")
    assert not j.get("error"), j.get("error")
    assert len(j["rows"]) == 2
    t = j["total"]["no_ai"]
    for k in ("pnl", "pct", "final", "max_dd", "avg_daily_pct", "trading_days"):
        assert k in t, k
    print(days, capital, {k: t[k] for k in ("trades", "pnl", "pct", "final", "max_dd", "avg_daily_pct", "trading_days")})
    assert abs(t["final"] - capital - t["pnl"]) < 0.05
    assert t["final"] >= 0
    assert t["pct"] < 2000, f"absurd growth {t['pct']}%"
    assert -10 < t["avg_daily_pct"] < 10
    assert t["trading_days"] <= days + 1
    assert 0 <= t["max_dd"] <= 100


def test_simulate_validation():
    assert requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": ITEMS, "capital": 5}, timeout=60).status_code == 422
    assert requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": ITEMS, "days": 400}, timeout=60).status_code == 422
    assert requests.post(f"{BASE_URL}/api/simulate", headers=H, json={"items": []}, timeout=60).status_code == 400
    assert requests.get(f"{BASE_URL}/api/simulate/nope", headers=H, timeout=60).status_code == 404


# --- Optimize negatives + apply
def test_optimize_negatives_and_apply(bot_backup):
    r = requests.post(f"{BASE_URL}/api/simulate/optimize-negatives", headers=H, json={"items": ITEMS}, timeout=60)
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    j = poll(f"/api/simulate/optimize-negatives/{jid}", timeout=300)
    assert len(j["results"]) == 2
    print("negopt", [(x["label"], x["best"]) for x in j["results"]])
    a = requests.post(f"{BASE_URL}/api/simulate/optimize-negatives/{jid}/apply", headers=H, timeout=60)
    assert a.status_code == 200, a.text
    assert set(a.json()) >= {"replaced", "removed"}
    assert a.json()["replaced"] + a.json()["removed"] == 2
    bot = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    assert any(p["symbol"] == "ETH-USD" for p in bot["c20_pairs"])


def test_optimize_negatives_invalid():
    r = requests.post(f"{BASE_URL}/api/simulate/optimize-negatives", headers=H, json={"items": [{"kind": "c12", "symbol": "BTC-USD", "tf": "1h"}]}, timeout=60)
    assert r.status_code == 400


# --- c12 / c20 per-pair optimizers
@pytest.mark.parametrize("kind", ["c12", "c20"])
def test_pair_optimizer(kind):
    r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind={kind}", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = poll(f"/api/bot/c20-optimize/{r.json()['job_id']}", timeout=300)
    assert j["kind"] == kind and len(j["results"]) >= 1
    print(kind, j["results"])
    bot = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    pairs = bot[f"{kind}_pairs"]
    for res in j["results"]:
        p = next(x for x in pairs if x["symbol"] == res["symbol"])
        assert p["tf"] == res["tf"] and p["rr"] == res["rr"] and p["min"] == res["min"]


def test_pair_optimizer_invalid_kind():
    assert requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=x", headers=H, timeout=60).status_code == 400


# --- Daily results
@pytest.mark.parametrize("scope", ["all", "bot", "hfx", "portfolio"])
def test_daily_results(scope):
    r = requests.get(f"{BASE_URL}/api/bot/daily-results?scope={scope}&days=30", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["scope"] == scope and isinstance(j["daily"], list)
    for k in ("pnl", "pct", "trades", "winrate", "trading_days", "green_days", "red_days", "avg_day_pnl", "avg_day_pct"):
        assert k in j["total"], k
    assert abs(sum(d["pnl"] for d in j["daily"]) - j["total"]["pnl"]) < 0.1


def test_daily_results_invalid_scope():
    assert requests.get(f"{BASE_URL}/api/bot/daily-results?scope=xx", headers=H, timeout=60).status_code == 400


# --- PUT /bot limits & new fields
def test_bot_put_limits(bot_backup):
    ok = bot_payload(bot_backup, max_positions=30, c12_max_positions=30, c20_max_positions=30, ptp_enabled=True, ptp_pct=40, ptp_r=1.5,
                     c20_rr=10, c20_ptp_r=3, c20_min=18, live_mode="metatrader", mt_max_lots=0.2, mt_suffix=".m")
    r = requests.put(f"{BASE_URL}/api/bot", headers=H, json=ok, timeout=60)
    assert r.status_code == 200, r.text
    b = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=60).json()["bot"]
    assert b["ptp_pct"] == 40 and b["ptp_r"] == 1.5 and b["c20_rr"] == 10 and b["live_mode"] == "metatrader" and b["mt_suffix"] == ".m"
    for f in ("max_positions", "c12_max_positions", "c20_max_positions"):
        assert requests.put(f"{BASE_URL}/api/bot", headers=H, json=bot_payload(bot_backup, **{f: 31}), timeout=60).status_code == 422, f
    assert requests.put(f"{BASE_URL}/api/bot", headers=H, json=bot_payload(bot_backup, live_mode="ibkr"), timeout=60).status_code == 422
    for m in ("binance", "paper"):
        assert requests.put(f"{BASE_URL}/api/bot", headers=H, json=bot_payload(bot_backup, live_mode=m), timeout=60).status_code == 200


# --- Live modes not configured
def test_live_status_not_configured():
    r = requests.get(f"{BASE_URL}/api/live/status", headers=H, timeout=60)
    assert r.status_code == 200 and r.json()["configured"] is False
    r = requests.get(f"{BASE_URL}/api/live/mt/status", headers=H, timeout=60)
    assert r.status_code == 200 and r.json()["configured"] is False and r.json()["account"] is None


def test_mt_connect_no_token():
    r = requests.post(f"{BASE_URL}/api/live/mt/connect", headers=H,
                      json={"login": "123456", "password": "x", "server": "Demo-Server", "platform": "mt5"}, timeout=60)
    assert r.status_code == 400 and "Falta o token MetaApi" in r.json()["detail"]


# --- Backtest confirm20 rr 10 partial 50
def test_backtest_confirm20_partial():
    r = requests.post(f"{BASE_URL}/api/backtest", headers=H, json={"symbol": "BTC-USD", "tf": "1h", "strategy": "confirm20", "rr": 10,
                                                                    "partial_pct": 50, "partial_r": 2, "c20_min": 16}, timeout=120)
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    print("bt", m)
    assert "total_trades" in m and "return_pct" in m

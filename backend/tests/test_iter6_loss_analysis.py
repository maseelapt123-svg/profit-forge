# Iteration 6: loss analysis (HFX + main bot), apply/reset fixes, auto-fix toggle, iteration_4 validation fixes
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"
mdb = MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]
NOW_H = datetime.now(timezone.utc).hour


def hfx_doc(pair, rule, label, won, hour, aligned, vol, origin="bot", days_ago=2):
    ts = time.time() - days_ago * 86400
    return {"trade_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "pair": pair, "source": "otc",
            "direction": "CALL", "amount": 10.0, "payout": 0.85, "expiry": 1, "entry_price": 1.1,
            "opened_ts": ts, "expires_ts": ts + 60, "status": "won" if won else "lost",
            "profit": 8.5 if won else -10.0, "origin": origin, "rule": rule, "rule_label": label,
            "closed_at": datetime.fromtimestamp(ts + 60, timezone.utc).isoformat(),
            "ctx": {"hour": hour, "aligned": aligned, "vol_pct": vol, "rsi": 45.0}}


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


@pytest.fixture(scope="module")
def seeded():
    docs = [hfx_doc("EURUSD=X", "TESTrule", "Regra Teste", i < 2, 3, False, 10) for i in range(10)]
    docs += [hfx_doc("GBPUSD=X", "TESTok", "Regra OK", True, 15, True, 50) for _ in range(6)]
    docs += [hfx_doc("USDJPY=X", None, None, False, 20, True, 50, origin="manual") for _ in range(6)]
    mdb.hfx_trades.insert_many(docs)
    pos = []
    for i in range(8):
        pos.append({"position_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "symbol": "BTC-USD", "side": "BUY",
                    "qty": 0.01, "entry": 100.0, "exit": 90.0, "status": "closed", "source": "bot", "setup": "BTC-USD|1h",
                    "tf": "1h", "pnl": 5.0 if i == 0 else -10.0, "reason": "take_profit" if i == 0 else "stop_loss",
                    "ctx": {"hour": 4, "htf_aligned": False},
                    "opened_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                    "closed_at": (datetime.now(timezone.utc) - timedelta(days=2, minutes=-i)).isoformat()})
    mdb.positions.insert_many(pos)
    yield
    mdb.hfx_trades.delete_many({"trade_id": {"$regex": "^TEST_"}})
    mdb.positions.delete_many({"position_id": {"$regex": "^TEST_"}})


# --- HFX analysis
def test_hfx_analysis_bot_scope(s, seeded):
    d = s.get(f"{BASE_URL}/api/hfx/analysis?scope=bot").json()
    assert d["trades"] == 16 and d["losses"] == 8
    kinds = {p["kind"] for p in d["problems"]}
    assert {"pair_rule", "hour", "against", "low_vol"} <= kinds, kinds
    for p in d["problems"]:
        assert p["n"] >= 6 and p["winrate"] < d["breakeven"] and p["text"] and "label" in p
    assert len(d["recent_losses"]) == 8 and d["recent_losses"][0]["ctx"]["vol_pct"] == 10
    assert "fixes" in d and "auto_fix" in d


def test_hfx_analysis_manual_and_all(s, seeded):
    m = s.get(f"{BASE_URL}/api/hfx/analysis?scope=manual").json()
    assert m["trades"] == 6 and m["losses"] == 6
    assert any(p["kind"] == "pair_rule" and "manual" in p["label"] for p in m["problems"])
    a = s.get(f"{BASE_URL}/api/hfx/analysis?scope=all").json()
    assert a["trades"] == 22


def test_hfx_apply_and_reset(s, seeded):
    r = s.post(f"{BASE_URL}/api/hfx/analysis/apply")
    assert r.status_code == 200, r.text
    fx = r.json()["fixes"]
    assert fx["hours"] == [3] and fx["pair_rules"] == ["EURUSD=X|TESTrule"]
    assert fx["trend_align"] is True and fx["skip_low_vol"] is True and fx["skip_high_vol"] is False
    assert s.get(f"{BASE_URL}/api/hfx/analysis").json()["fixes"] == fx
    logs = list(mdb.bot_logs.find({"user_id": UID, "scope": "hfx", "kind": "fix"}).sort("created_at", -1).limit(1))
    assert logs and "problema" in logs[0]["msg"]
    assert s.post(f"{BASE_URL}/api/hfx/analysis/reset").json()["ok"] is True
    assert s.get(f"{BASE_URL}/api/hfx/analysis").json()["fixes"] == {}


def test_hfx_apply_no_bot_400(s):
    bak = mdb.hfx_bots.find_one({"user_id": UID})
    mdb.hfx_bots.delete_one({"user_id": UID})
    try:
        r = s.post(f"{BASE_URL}/api/hfx/analysis/apply")
        assert r.status_code == 400, r.text
    finally:
        if bak:
            mdb.hfx_bots.insert_one(bak)


# --- Main bot analysis
def test_bot_analysis(s, seeded):
    d = s.get(f"{BASE_URL}/api/bot/analysis").json()
    assert d["trades"] == 8 and d["losses"] == 7
    kinds = {p["kind"] for p in d["problems"]}
    assert {"setup", "hour", "against_htf", "stops"} <= kinds, kinds
    assert d["recent_losses"][0]["reason"] == "stop_loss"


def test_bot_apply_reset(s, seeded):
    fx = s.post(f"{BASE_URL}/api/bot/analysis/apply").json()["fixes"]
    assert fx == {"paused": ["BTC-USD|1h"], "hours": [4], "force_mtf": True, "widen_stop": True}
    assert s.get(f"{BASE_URL}/api/bot/analysis").json()["fixes"] == fx
    s.post(f"{BASE_URL}/api/bot/analysis/reset")
    assert s.get(f"{BASE_URL}/api/bot/analysis").json()["fixes"] == {}


# --- auto-fix toggle
def test_auto_fix_toggle(s):
    for scope, path in (("bot", "/api/bot/analysis"), ("hfx", "/api/hfx/analysis")):
        assert s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": scope, "enabled": False}).status_code == 200
        assert s.get(BASE_URL + path).json()["auto_fix"] is False
        s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": scope, "enabled": True})
        assert s.get(BASE_URL + path).json()["auto_fix"] is True
    assert s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": "foo", "enabled": True}).status_code == 400


def test_hfx_bot_put_preserves_auto_fix(s):
    """PUT /api/hfx/bot without auto_fix must not silently re-enable auto-fix."""
    s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": "hfx", "enabled": False})
    cfg = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
    body = {k: cfg[k] for k in ("enabled", "source", "pairs", "expiry", "amount", "min_winrate", "daily_stop",
                                "daily_target", "max_per_hour", "strategy", "min_votes")}
    s.put(f"{BASE_URL}/api/hfx/bot", json=body)
    val = s.get(f"{BASE_URL}/api/hfx/analysis").json()["auto_fix"]
    s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": "hfx", "enabled": True})
    assert val is False, "PUT /api/hfx/bot reset auto_fix to True"


# --- iteration_4 fixes
def test_pairs_invalid_source(s):
    assert s.get(f"{BASE_URL}/api/hfx/pairs?source=foo").status_code == 400


def test_setup_expiry_abc_400(s):
    cfg = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
    body = {"enabled": False, "source": "otc", "pairs": cfg["pairs"], "strategy": "optimized",
            "setups": {"EURUSD=X": {"rule": "x", "expiry": "abc"}}}
    r = s.put(f"{BASE_URL}/api/hfx/bot", json=body)
    assert r.status_code == 400, r.text


def test_enable_when_daily_stop_hit_400(s):
    doc = hfx_doc("EURUSD=X", "TESTrule", "Regra Teste", False, NOW_H, True, 50, days_ago=0)
    doc["profit"] = -150.0
    mdb.hfx_trades.insert_one(doc)
    try:
        body = {"enabled": True, "source": "otc", "pairs": ["EURUSD=X"], "daily_stop": 100, "daily_target": 200}
        r = s.put(f"{BASE_URL}/api/hfx/bot", json=body)
        assert r.status_code == 400 and "Limite" in r.json()["detail"], r.text
    finally:
        mdb.hfx_trades.delete_one({"trade_id": doc["trade_id"]})
        s.put(f"{BASE_URL}/api/hfx/bot", json={"enabled": False, "source": "otc", "pairs": ["EURUSD=X", "GBPUSD=X"]})


def test_optimize_strength(s):
    r = s.post(f"{BASE_URL}/api/hfx/optimize", json={"expiry": 1}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    rows = d.get("results") or d.get("pairs") or []
    bests = [x.get("best") for x in rows if isinstance(x, dict) and x.get("best")]
    for b in bests:
        assert b.get("strength") in ("forte", "moderada"), b


def test_hfx_state_stats(s):
    d = s.get(f"{BASE_URL}/api/hfx/trades").json()
    st = d["stats"]
    assert set(st) >= {"trades", "wins", "winrate", "profit"}

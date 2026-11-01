# Iteration 12: SL/TP fill at order level (bug "tudo red"), c12_tf config, 2m/3m backtests, daily-summary apply (hfx min_winrate)
# Run: set -a; . /app/backend/.env; . /app/frontend/.env; set +a; pytest -n 0 tests/test_iter12_sl_fill_c12tf.py
import os
import time
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"


def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    db = mdb()
    bot_bak = db.bots.find_one({"user_id": UID}, {"_id": 0})
    hb_bak = db.hfx_bots.find_one({"user_id": UID}, {"_id": 0})
    acc_bak = db.accounts.find_one({"user_id": UID}, {"_id": 0})
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    db.positions.delete_many({"user_id": UID, "TEST_seed": True})
    db.daily_summaries.delete_many({"user_id": UID, "date": "2001-01-01"})
    db.bot_logs.delete_many({"user_id": UID, "msg": {"$regex": "TEST_"}})
    if bot_bak:
        bot_bak["enabled"] = False
        db.bots.replace_one({"user_id": UID}, bot_bak, upsert=True)
    if hb_bak:
        db.hfx_bots.replace_one({"user_id": UID}, hb_bak, upsert=True)
    if acc_bak:
        db.accounts.replace_one({"user_id": UID}, acc_bak, upsert=True)


def seed_pos(pid, side, entry, sl, tp):
    mdb().positions.insert_one({"position_id": pid, "user_id": UID, "symbol": "BTC-USD", "side": side, "qty": 0.01,
                                "entry": entry, "stop_loss": sl, "take_profit": tp, "status": "open", "source": "bot",
                                "setup": "BTC-USD|5m", "tf": "5m", "stop_dist": abs(entry - sl), "TEST_seed": True,
                                "opened_at": datetime.now(timezone.utc).isoformat()})


def current_px():
    # last known BTC price from candles endpoint (public)
    r = requests.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "5m"}, headers=H)
    if r.status_code == 200:
        d = r.json()
        c = d.get("candles") if isinstance(d, dict) else d
        if c:
            last = c[-1]
            return float(last["c"])
    return 90000.0


# --- Bug fix: exits fill at stop/target level (check_exits via /bot/run) ---
class TestExitFill:
    def test_sl_and_tp_fill_exact_via_bot_run(self, s):
        db = mdb()
        px = current_px()
        db.bots.update_one({"user_id": UID}, {"$set": {"enabled": True, "symbols": [], "setups": [], "c12_enabled": False}}, upsert=True)
        # long whose stop is far ABOVE current price -> crossed; long whose TP is far BELOW price -> crossed
        seed_pos("TEST_sl_long", "BUY", px + 20000, px + 10000, px + 60000)
        seed_pos("TEST_sl_short", "SELL", px - 20000, px - 10000, px - 60000)
        seed_pos("TEST_tp_long", "BUY", px - 20000, px - 40000, px - 10000)
        r = s.post(f"{BASE_URL}/api/bot/run")
        assert r.status_code == 200, r.text
        for pid, field, reason in (("TEST_sl_long", "stop_loss", "stop_loss"), ("TEST_sl_short", "stop_loss", "stop_loss"),
                                   ("TEST_tp_long", "take_profit", "take_profit")):
            p = db.positions.find_one({"position_id": pid}, {"_id": 0})
            assert p["status"] == "closed", pid
            assert p["reason"] == reason
            assert p["exit"] == p[field], f"{pid} exit {p['exit']} != {field} {p[field]}"
            sign = 1 if p["side"] == "BUY" else -1
            exp = (p[field] - p["entry"]) * p["qty"] * sign
            assert abs(p["pnl"] - exp) < 1.0, f"{pid} pnl {p['pnl']} vs {exp} (fees?)"

    def test_sl_fill_exact_via_portfolio(self, s):
        # GET /api/portfolio also auto-closes on SL/TP -> must also fill at stop level
        px = current_px()
        seed_pos("TEST_sl_port", "BUY", px + 20000, px + 10000, px + 60000)
        r = s.get(f"{BASE_URL}/api/portfolio")
        assert r.status_code == 200
        p = mdb().positions.find_one({"position_id": "TEST_sl_port"}, {"_id": 0})
        assert p["status"] == "closed"
        assert p["exit"] == p["stop_loss"], f"portfolio path filled at polled price {p['exit']} instead of stop {p['stop_loss']}"


# --- c12 config ---
class TestC12Config:
    def test_default_tf(self, s):
        d = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        for k in ("c12_tf", "c12_enabled", "c12_min", "c12_max_positions"):
            assert k in d
        if not (mdb().bots.find_one({"user_id": UID}) or {}).get("c12_tf"):
            assert d["c12_tf"] == "1h"

    def test_put_persist(self, s):
        cur = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: v for k, v in cur.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run")}
        body.update({"c12_tf": "4h", "c12_enabled": True, "c12_min": 8, "c12_max_positions": 3, "enabled": False})
        r = s.put(f"{BASE_URL}/api/bot", json=body)
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert (g["c12_tf"], g["c12_enabled"], g["c12_min"], g["c12_max_positions"]) == ("4h", True, 8, 3)

    @pytest.mark.parametrize("patch", [{"c12_min": 5}, {"c12_min": 13}, {"c12_max_positions": 0}])
    def test_put_invalid(self, s, patch):
        cur = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: v for k, v in cur.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run")}
        body.update(patch)
        assert s.put(f"{BASE_URL}/api/bot", json=body).status_code == 422

    def test_put_invalid_tf(self, s):
        cur = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: v for k, v in cur.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run")}
        body.update({"c12_tf": "xyz", "enabled": False})
        r = s.put(f"{BASE_URL}/api/bot", json=body)
        assert r.status_code in (400, 422), f"c12_tf 'xyz' accepted ({r.status_code})"


# --- 2m/3m backtests ---
class TestShortTF:
    @pytest.mark.parametrize("tf", ["2m", "3m"])
    def test_backtest(self, s, tf):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": tf, "strategy": "ema_cross"}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tf"] == tf and d["bars"] > 100


# --- daily-summary apply with seeded doc ---
class TestDailyApply:
    def test_apply_hfx_min_winrate(self, s):
        db = mdb()
        frm = (db.hfx_bots.find_one({"user_id": UID}) or {}).get("min_winrate", 56)
        db.daily_summaries.delete_many({"user_id": UID, "date": "2001-01-01"})
        db.daily_summaries.insert_one({"user_id": UID, "date": "2001-01-01", "text": "TEST_", "adjustments": [
            {"scope": "hfx", "field": "min_winrate", "value": 60, "label": "Winrate mínimo", "from": frm, "to": 60,
             "reason": "TEST_", "applied": False}]})
        r = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": "2001-01-01", "ids": [0]})
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == 1
        assert db.hfx_bots.find_one({"user_id": UID})["min_winrate"] == 60
        assert db.daily_summaries.find_one({"user_id": UID, "date": "2001-01-01"})["adjustments"][0]["applied"] is True
        r2 = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": "2001-01-01", "ids": [0]})
        assert r2.status_code == 200 and r2.json()["applied"] == 0

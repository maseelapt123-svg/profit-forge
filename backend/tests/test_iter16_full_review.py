# Iteration 16 (report iteration_8): full review of plugins, confluence/confirm12, bot c12/conf fields, optimize-all (live push),
# daily AI adjustments (seeded trades), AI filter stats.
# Run: cd /app/backend; set -a; . .env; . ../frontend/.env; set +a; pytest -n 0 tests/test_iter16_full_review.py -v
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"
TAG = "TEST_it16"
NEW_PLUGINS = ["pullback", "supertrend", "stoch_rsi", "adx", "donchian", "fvg", "sweep", "choch", "ote", "breaker", "eq_liquidity",
               "sweep_choch", "killzone", "ichimoku", "vwap", "psar", "williams_r", "cci", "keltner", "pin_bar", "engulfing", "inside_bar"]


def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    db = mdb()
    bak = {c: db[c].find_one({"user_id": UID}, {"_id": 0}) for c in ("bots", "hfx_bots", "plugins")}
    sums = [x["date"] for x in db.daily_summaries.find({"user_id": UID}, {"date": 1})]
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    db.hfx_trades.delete_many({"tag": TAG})
    db.positions.delete_many({"tag": TAG})
    for c, doc in bak.items():
        db[c].delete_one({"user_id": UID})
        if doc:
            doc.pop("updated_at", None) if c == "plugins" else None
            db[c].insert_one({**doc, **({"enabled": False} if c in ("bots", "hfx_bots") else {})})
    db.daily_summaries.delete_many({"user_id": UID, "date": {"$nin": sums}})


def bot_body(s, **patch):
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    body = {k: v for k, v in b.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run", "updated_at")}
    body.update({"enabled": False, **patch})
    return body


# --- plugin catalog
def test_plugins_catalog(s):
    d = s.get(f"{BASE_URL}/api/plugins").json()
    missing = [p for p in NEW_PLUGINS if p not in d["plugins"] or p not in d["meta"]]
    assert not missing, missing
    assert all("label" in d["meta"][p] for p in NEW_PLUGINS)


# --- backtest each new strategy + confluence + confirm12
@pytest.mark.parametrize("strat", NEW_PLUGINS + ["confluence", "confirm12"])
def test_backtest_strategy(s, strat):
    body = {"symbol": "BTC-USD", "tf": "1h", "strategy": strat}
    if strat == "confirm12":
        body["c12_min"] = 8
    r = s.post(f"{BASE_URL}/api/backtest", json=body, timeout=120)
    assert r.status_code == 200, r.text[:200]
    m = r.json()["metrics"]
    assert isinstance(m["return_pct"], (int, float)) and m["total_trades"] >= 0


@pytest.mark.parametrize("tf", ["2m", "3m"])
def test_backtest_new_tfs(s, tf):
    r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": tf, "strategy": "supertrend"}, timeout=120)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["tf"] == tf and r.json()["bars"] >= 250


# --- confluence / confirm12 endpoints
def test_confluence(s):
    d = s.get(f"{BASE_URL}/api/confluence", params={"symbol": "BTC-USD", "tf": "1h"}).json()
    assert d["signal"] in ("BUY", "SELL", None) and isinstance(d["plugins"], list) and d["plugins"]
    assert {"votes_up", "votes_dn", "score_up", "score_dn", "trend"} <= set(d)


def test_confirm12(s):
    d = s.get(f"{BASE_URL}/api/confirm12", params={"symbol": "BTC-USD", "tf": "1h", "min": 10}).json()
    assert len(d["checks"]) == 12 and d["up"] + d["down"] <= 12 and d["min"] == 10


@pytest.mark.parametrize("v", [0, 13])
def test_confirm12_min_range(s, v):
    r = s.get(f"{BASE_URL}/api/confirm12", params={"symbol": "BTC-USD", "tf": "1h", "min": v})
    assert r.status_code in (400, 422), f"min={v} accepted: {r.status_code}"


# --- bot config fields
def test_bot_put_fields(s):
    body = bot_body(s, strategy="confluence", conf_votes=3, conf_score=65, c12_enabled=True, c12_min=9, c12_max_positions=3, c12_tf="4h")
    assert s.put(f"{BASE_URL}/api/bot", json=body).status_code == 200
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    assert (b["strategy"], b["conf_votes"], b["conf_score"], b["c12_enabled"], b["c12_min"], b["c12_max_positions"], b["c12_tf"]) == \
        ("confluence", 3, 65, True, 9, 3, "4h")


@pytest.mark.parametrize("tf", ["xyz", "1m"])
def test_bot_c12_tf_invalid(s, tf):
    r = s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf=tf))
    assert r.status_code in (400, 422), f"c12_tf={tf} accepted: {r.status_code}"


# --- optimize-all: clears old setups, pushes >6% winners live, apply removes unticked
def test_optimize_all_live(s):
    seed_setup = {"symbol": "ETH-USD", "tf": "1d", "strategy": "supertrend", "sl_atr": 1.5, "rr": 2.0, "trend_filter": True, "mtf": False}
    assert s.put(f"{BASE_URL}/api/bot", json=bot_body(s, symbols=["BTC-USD", "ETH-USD"], setups=[seed_setup])).status_code == 200
    assert s.put(f"{BASE_URL}/api/bot", json=bot_body(s, symbols=["BTC-USD"], setups=[])).status_code == 200
    mdb().bots.update_one({"user_id": UID}, {"$set": {"setups": [{**seed_setup, "symbol": "BTC-USD"}]}})
    jid = s.post(f"{BASE_URL}/api/bot/optimize-all").json()["job_id"]
    time.sleep(3)
    # 1d is the last TF optimised, so after 3s the seeded BTC-USD|1d setup must already be gone (cleared at start)
    assert not [x for x in s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"] if x["tf"] == "1d"], "old setups not cleared"
    t0, live_ok, j = time.time(), True, None
    while time.time() - t0 < 290:
        j = s.get(f"{BASE_URL}/api/bot/optimize-all/{jid}").json()
        keys = {f"{x['symbol']}|{x['tf']}" for x in s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"]}
        if not {f"{x['symbol']}|{x['tf']}" for x in j["results"]} <= keys:
            live_ok = False
        if j["status"] == "done":
            break
        time.sleep(5)
    print("optimize-all", round(time.time() - t0), "s", [(x["tf"], x["best"]["strategy"], x["best"]["test"]["return_pct"]) for x in j["results"]])
    assert j["status"] == "done" and j["total"] == 8 and j["step"] == 8
    assert live_ok
    assert all(x["best"]["test"]["return_pct"] > 6 for x in j["results"])
    setups = s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"]
    assert len(setups) == len(j["results"]) == j["applied"]
    test_optimize_all_live.jid, test_optimize_all_live.res = jid, j["results"]


def test_optimize_all_apply_unticked(s):
    res = getattr(test_optimize_all_live, "res", None)
    if not res:
        pytest.skip("no qualifying setups")
    jid = test_optimize_all_live.jid
    keep = [f"{x['symbol']}|{x['tf']}" for x in res][1:]
    r = s.post(f"{BASE_URL}/api/bot/optimize-all/{jid}/apply", json={"keys": keep, "replace": True})
    assert r.status_code == 200 and r.json()["total"] == len(keep)
    assert {f"{x['symbol']}|{x['tf']}" for x in s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"]} == set(keep)
    r = s.post(f"{BASE_URL}/api/bot/optimize-all/{jid}/apply", json={"keys": [], "replace": True})
    assert r.status_code == 200 and s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"] == []


# --- daily adjustments (seeded closed trades today; hfx_trades with trade_id/entry_price/payout)
def seed_today():
    db = mdb()
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    nh = max(datetime.now(timezone.utc).hour, 1)
    hf, pos = [], []
    for i in range(10):
        ts = (base + timedelta(hours=i % nh, minutes=5 + i)).timestamp()
        won = i in (0, 3, 7)
        tid = f"{TAG}_{uuid.uuid4().hex[:8]}"
        hf.append({"id": tid, "trade_id": tid, "tag": TAG, "user_id": UID, "origin": "bot", "status": "won" if won else "lost",
                   "entry_price": 1.1, "exit_price": 1.1001, "payout": 85, "opened_ts": ts, "expires_ts": ts + 60, "pair": "EURUSD=X",
                   "source": "otc", "direction": "call" if i % 2 else "put", "expiry": 1, "rule_label": "RSI reversão",
                   "amount": 10, "profit": 8.5 if won else -10.0, "ctx": {"hour": i % nh, "aligned": False, "rsi": 40, "vol_pct": 0.03}})
    for i, pnl in enumerate([-40.0, -35.0, 12.0, -50.0]):
        pid = f"{TAG}_{uuid.uuid4().hex[:8]}"
        pos.append({"position_id": pid, "tag": TAG, "user_id": UID, "source": "bot", "status": "closed", "symbol": "BTC-USD", "tf": "1h",
                    "side": "BUY", "qty": 0.01, "entry": 90000, "exit": 89900, "pnl": pnl, "reason": "take_profit" if pnl > 0 else "stop_loss",
                    "opened_at": (base + timedelta(hours=i % nh)).isoformat(), "closed_at": (base + timedelta(hours=i % nh, minutes=30)).isoformat(),
                    "ctx": {"hour": i % nh, "aligned": False}})
    db.hfx_trades.insert_many(hf)
    db.positions.insert_many(pos)
    return base.strftime("%Y-%m-%d")


def test_daily_summary_adjustments_apply(s):
    day = seed_today()
    text, err = [], None
    with s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": day}, stream=True, timeout=180) as r:
        assert r.status_code == 200, r.text[:200]
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[6:])
            text.append(ev.get("t", ""))
            err = ev.get("error") or err
    assert not err and len("".join(text)) > 200
    doc = next(x for x in s.get(f"{BASE_URL}/api/ai/daily-summaries").json() if x["date"] == day)
    adjs = doc.get("adjustments") or []
    print("adjustments", [(a["scope"], a["field"], a["from"], a["to"]) for a in adjs])
    assert adjs, "LLM produced no valid adjustments"
    assert all({"label", "from", "to", "scope", "field"} <= set(a) and a["applied"] is False for a in adjs)
    r = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": day, "ids": [0]})
    assert r.status_code == 200 and r.json()["applied"] == 1 and r.json()["adjustments"][0]["applied"] is True
    assert s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": day, "ids": [0]}).json()["applied"] == 0
    assert s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": "1999-01-01", "ids": [0]}).status_code == 404
    test_daily_summary_adjustments_apply.day = day


# --- AI filter stats
@pytest.mark.parametrize("scope", ["hfx", "bot"])
def test_filter_stats(s, scope):
    d = s.get(f"{BASE_URL}/api/ai/filter-stats", params={"scope": scope, "days": 7}).json()
    assert d["scope"] == scope and d["evaluated"] == d["approved"] + d["rejected"]
    assert s.get(f"{BASE_URL}/api/ai/filter-stats", params={"scope": "x"}).status_code == 400

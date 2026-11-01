# Iteration 14 (report iteration_8): EURUSD backtest for every strategy, optimize-all selective apply (>6% only), confluence/confirm12 shapes
# Run: set -a; . /app/backend/.env; . /app/frontend/.env; set +a; EXPO_BACKEND_URL=$EXPO_PUBLIC_BACKEND_URL pytest -n 0 tests/test_iter14_review.py
import os
import sys
import time

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from strategies import STRATEGIES  # noqa: E402

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"


def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    db = mdb()
    bak = db.bots.find_one({"user_id": UID}, {"_id": 0})
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    if bak:
        bak["enabled"] = False
        db.bots.replace_one({"user_id": UID}, bak, upsert=True)


def bot_body(s, **patch):
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    body = {k: v for k, v in b.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run", "updated_at")}
    body.update({"enabled": False, **patch})
    return body


# --- backtest every strategy on forex
class TestBacktestEURUSD:
    @pytest.mark.parametrize("strat", STRATEGIES)
    def test_backtest(self, s, strat):
        body = {"symbol": "EURUSD=X", "tf": "1h", "strategy": strat, "conf_votes": 2, "conf_score": 55, "c12_min": 10}
        r = s.post(f"{BASE_URL}/api/backtest", json=body, timeout=120)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["strategy"] == strat and "metrics" in d


# --- live confluence / confirm12 detail
class TestLiveDetail:
    def test_confluence(self, s):
        r = s.get(f"{BASE_URL}/api/confluence?symbol=BTC-USD&tf=1h&votes=2&score=55", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        print({k: v for k, v in d.items() if k != "plugins"})
        items = d.get("plugins") or d.get("items") or d.get("votes")
        assert isinstance(items, list) and items
        assert all("weight" in x for x in items), items[0]

    def test_confirm12(self, s):
        d = s.get(f"{BASE_URL}/api/confirm12?symbol=BTC-USD&tf=1h&min=10", timeout=90).json()
        assert len(d["checks"]) == 12 and d["min"] == 10


# --- bot persists confluence + c12 fields
class TestBotPersist:
    def test_put_get(self, s):
        body = bot_body(s, conf_votes=3, conf_score=60, c12_enabled=True, c12_min=11, c12_max_positions=2, c12_tf="4h")
        r = s.put(f"{BASE_URL}/api/bot", json=body)
        assert r.status_code == 200, r.text[:300]
        g = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert (g["conf_votes"], g["conf_score"], g["c12_enabled"], g["c12_min"], g["c12_max_positions"], g["c12_tf"]) == \
            (3, 60, True, 11, 2, "4h")
        s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_enabled=False))


# --- one-click optimize all: results only >6%, user picks keys
class TestOptimizeAllSelective:
    def test_job_and_apply(self, s):
        assert s.put(f"{BASE_URL}/api/bot", json=bot_body(s, symbols=["BTC-USD"], setups=[])).status_code == 200
        # wait if a previous job is still running
        for _ in range(60):
            r = s.post(f"{BASE_URL}/api/bot/optimize-all")
            if r.status_code != 429:
                break
            time.sleep(5)
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        assert s.post(f"{BASE_URL}/api/bot/optimize-all").status_code == 429
        t0, last = time.time(), None
        while time.time() - t0 < 400:
            last = s.get(f"{BASE_URL}/api/bot/optimize-all/{jid}").json()
            if last["status"] == "done":
                break
            time.sleep(5)
        print("elapsed", round(time.time() - t0), [(x["tf"], x["best"]["strategy"], x["best"]["test"]["return_pct"]) for x in last["results"]])
        assert last["status"] == "done" and last["total"] == 8 and last["step"] == 8
        assert all(x["best"]["test"]["return_pct"] > 6 for x in last["results"])
        # not auto-applied
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"] == []
        # key that is not an eligible result -> 400
        bad = [f"BTC-USD|{tf}" for tf in ["1m", "2m", "3m", "5m", "15m", "1h", "4h", "1d"]
               if tf not in {x["tf"] for x in last["results"]}]
        if bad:
            rb = s.post(f"{BASE_URL}/api/bot/optimize-all/{jid}/apply", json={"keys": bad[:1]})
            assert rb.status_code == 400, rb.text
        assert s.post(f"{BASE_URL}/api/bot/optimize-all/{jid}/apply", json={"keys": []}).status_code == 400
        if not last["results"]:
            pytest.skip("no setup above 6% for BTC-USD — apply success path not exercised")
        pick = last["results"][0]
        key = f"{pick['symbol']}|{pick['tf']}"
        ra = s.post(f"{BASE_URL}/api/bot/optimize-all/{jid}/apply", json={"keys": [key]})
        assert ra.status_code == 200, ra.text
        assert ra.json()["applied"] == 1
        st = s.get(f"{BASE_URL}/api/bot").json()["bot"]["setups"]
        assert len(st) == 1 and st[0]["tf"] == pick["tf"] and st[0]["strategy"] == pick["best"]["strategy"]

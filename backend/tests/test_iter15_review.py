# Iteration 15 (report iteration_8): regression for validation gaps + SL/TP fill on every exit path + optimize-all apply edge cases
# Run: set -a; . /app/backend/.env; . /app/frontend/.env; set +a; pytest -n 0 tests/test_iter15_review.py
import os
import uuid
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
    bak = db.bots.find_one({"user_id": UID}, {"_id": 0})
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    db.positions.delete_many({"user_id": UID, "TEST_seed": True})
    if bak:
        db.bots.replace_one({"user_id": UID}, {**bak, "enabled": False}, upsert=True)


def bot_body(s, **patch):
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    body = {k: v for k, v in b.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run", "updated_at")}
    body.update({"enabled": False, **patch})
    return body


def px_btc(s):
    c = s.get(f"{BASE_URL}/api/candles", params={"symbol": "BTC-USD", "tf": "5m"}).json()
    c = c.get("candles") if isinstance(c, dict) else c
    return float(c[-1]["c"])


# --- confirm12 'min' must be 6..12 (same range as bot c12_min)
class TestConfirm12:
    def test_twelve_checks(self, s):
        r = s.get(f"{BASE_URL}/api/confirm12", params={"symbol": "BTC-USD", "tf": "1h", "min": 10})
        assert r.status_code == 200
        d = r.json()
        assert len(d["checks"]) == 12 and d["up"] + d["down"] <= 12

    @pytest.mark.parametrize("m", [0, 13])
    def test_min_range(self, s, m):
        r = s.get(f"{BASE_URL}/api/confirm12", params={"symbol": "BTC-USD", "tf": "1h", "min": m})
        assert r.status_code in (400, 422), f"min={m} accepted"


# --- PUT /bot c12_tf must be a valid TF (UI offers 5m..1d)
class TestC12Tf:
    @pytest.mark.parametrize("tf", ["xyz", "1m"])
    def test_invalid(self, s, tf):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf=tf))
        ok = r.status_code in (400, 422)
        s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf="1h"))
        assert ok, f"c12_tf={tf} accepted ({r.status_code})"

    def test_persist(self, s):
        assert s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_enabled=True, c12_min=8, c12_max_positions=3, c12_tf="4h")).status_code == 200
        b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert (b["c12_enabled"], b["c12_min"], b["c12_max_positions"], b["c12_tf"]) == (True, 8, 3, "4h")
        s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_enabled=False, c12_min=10, c12_max_positions=2, c12_tf="1h"))


# --- exits fill at SL/TP level on GET /portfolio path too
class TestPortfolioExitFill:
    def _seed(self, side, sl, tp, entry):
        pid = "TEST_" + uuid.uuid4().hex[:8]
        mdb().positions.insert_one({"position_id": pid, "user_id": UID, "symbol": "BTC-USD", "side": side, "qty": 0.001,
                                    "entry": entry, "stop_loss": sl, "take_profit": tp, "status": "open", "source": "manual",
                                    "TEST_seed": True, "opened_at": datetime.now(timezone.utc).isoformat()})
        return pid

    def test_tp_fill_portfolio(self, s):
        px = px_btc(s)
        pid = self._seed("BUY", px - 30000, px - 5000, px - 10000)  # TP already crossed
        assert s.get(f"{BASE_URL}/api/portfolio").status_code == 200
        p = mdb().positions.find_one({"position_id": pid}, {"_id": 0})
        assert p["status"] == "closed" and p["reason"] == "take_profit"
        assert p["exit"] == p["take_profit"], f"filled at {p['exit']} not TP {p['take_profit']}"


# --- optimize-all apply / status guards
class TestOptimizeAllGuards:
    def test_unknown_job(self, s):
        assert s.get(f"{BASE_URL}/api/bot/optimize-all/doesnotexist").status_code == 404
        assert s.post(f"{BASE_URL}/api/bot/optimize-all/doesnotexist/apply", json={"keys": ["BTC-USD|1h"]}).status_code == 404

    def test_requires_auth(self):
        assert requests.post(f"{BASE_URL}/api/bot/optimize-all").status_code == 401


# --- filter-stats empty scope shape
class TestFilterStats:
    def test_bot_scope_shape(self, s):
        r = s.get(f"{BASE_URL}/api/ai/filter-stats", params={"scope": "bot", "days": 7})
        assert r.status_code == 200
        d = r.json()
        for k in ("evaluated", "approved", "rejected", "approved_perf", "no_ai_perf", "by_confidence", "top_reasons"):
            assert k in d

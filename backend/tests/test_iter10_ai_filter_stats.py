# Iteration 10: AI filter stats endpoint (/api/ai/filter-stats) — seeded approved trades + rejections, delta math vs baseline
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123"}
UID = "user_test1"
TAG = "TEST_aistats"


def db():
    return MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]


def clean():
    d = db()
    for c in ("hfx_trades", "positions", "ai_decisions"):
        d[c].delete_many({"tag": TAG})


def get(scope, days=7):
    r = requests.get(f"{BASE_URL}/api/ai/filter-stats", params={"scope": scope, "days": days}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def bucket(j, b):
    return next((x for x in j["by_confidence"] if x["bucket"] == b), {"trades": 0, "wins": 0, "pnl": 0})


@pytest.fixture(scope="module")
def seeded():
    clean()
    base = {s: {d: get(s, d) for d in (7, 30)} for s in ("hfx", "bot")}
    d = db()
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).timestamp()

    def hf(status, profit, conf=None):
        doc = {"trade_id": f"{TAG}_{uuid.uuid4().hex[:8]}", "id": uuid.uuid4().hex, "tag": TAG, "user_id": UID, "origin": "bot",
               "status": status, "opened_ts": ts, "expires_ts": ts + 60, "pair": "EURUSD=X", "source": "otc",
               "direction": "call", "expiry": 1, "amount": 10, "profit": profit}
        if conf is not None:
            doc["ai"] = {"confidence": conf, "reason": "TEST ok"}
        return doc
    d.hfx_trades.insert_many([hf("won", 8.5, 90), hf("won", 8.5, 88), hf("lost", -10, 75), hf("won", 8.5, 60),
                              hf("open", 0, 80), hf("won", 8.5), hf("lost", -10), hf("lost", -10)])

    def pos(status, pnl, conf=None):
        doc = {"id": f"{TAG}_{uuid.uuid4().hex[:8]}", "tag": TAG, "user_id": UID, "source": "bot", "status": status,
               "symbol": "BTC-USD", "tf": "1h", "side": "long", "qty": 0.01, "entry": 90000, "pnl": pnl,
               "opened_at": (now - timedelta(hours=2)).isoformat()}
        if status == "closed":
            doc["closed_at"] = (now - timedelta(hours=1)).isoformat()
        if conf is not None:
            doc["ai"] = {"confidence": conf, "reason": "TEST ok"}
        return doc
    d.positions.insert_many([pos("closed", 20.0, 86), pos("closed", -10.0, 72), pos("open", 0, 90), pos("closed", 5.0)])

    def rej(scope, reason, age_days=0):
        return {"tag": TAG, "user_id": UID, "scope": scope, "symbol": "EURUSD=X", "side": "call", "confidence": 40,
                "reason": reason, "created_at": (now - timedelta(days=age_days, minutes=5)).isoformat()}
    d.ai_decisions.insert_many([rej("hfx", "TEST_A"), rej("hfx", "TEST_A"), rej("hfx", "TEST_B"),
                                rej("hfx", "TEST_OLD", 10), rej("bot", "TEST_BOT")])
    yield base
    clean()


class TestFilterStats:
    def test_shape(self, seeded):
        j = get("hfx")
        for k in ("evaluated", "approved", "rejected", "approval_rate", "open", "approved_perf", "no_ai_perf",
                  "by_confidence", "top_reasons", "recent_rejections"):
            assert k in j, k
        assert j["scope"] == "hfx" and j["days"] == 7

    def test_hfx_counts(self, seeded):
        b, j = seeded["hfx"][7], get("hfx")
        assert j["approved"] - b["approved"] == 5
        assert j["rejected"] - b["rejected"] == 3
        assert j["evaluated"] - b["evaluated"] == 8
        assert j["open"] - b["open"] == 1
        assert abs(j["approval_rate"] - j["approved"] / j["evaluated"] * 100) < 0.01

    def test_hfx_perf(self, seeded):
        b, j = seeded["hfx"][7], get("hfx")
        ap, bp = j["approved_perf"], b["approved_perf"]
        assert ap["trades"] - bp["trades"] == 4 and ap["wins"] - bp["wins"] == 3
        assert abs((ap["pnl"] - bp["pnl"]) - 15.5) < 0.01
        na, bn = j["no_ai_perf"], b["no_ai_perf"]
        assert na["trades"] - bn["trades"] == 3 and na["wins"] - bn["wins"] == 1
        assert abs((na["pnl"] - bn["pnl"]) + 11.5) < 0.01

    def test_hfx_buckets(self, seeded):
        b, j = seeded["hfx"][7], get("hfx")
        assert bucket(j, "85%+")["trades"] - bucket(b, "85%+")["trades"] == 2
        assert bucket(j, "70–84%")["trades"] - bucket(b, "70–84%")["trades"] == 1
        assert bucket(j, "<70%")["trades"] - bucket(b, "<70%")["trades"] == 1

    def test_hfx_reasons_and_recent(self, seeded):
        j = get("hfx")
        r = {x["reason"]: x["count"] for x in j["top_reasons"]}
        assert r.get("TEST_A") == 2 and r.get("TEST_B") == 1
        assert "TEST_OLD" not in r and "TEST_BOT" not in r
        assert j["recent_rejections"] and set(j["recent_rejections"][0]) == {"symbol", "side", "confidence", "reason", "created_at"}

    def test_days_window(self, seeded):
        b, j = seeded["hfx"][30], get("hfx", 30)
        assert j["rejected"] - b["rejected"] == 4  # includes the 10-day-old rejection

    def test_bot_scope(self, seeded):
        b, j = seeded["bot"][7], get("bot")
        assert j["approved"] - b["approved"] == 3 and j["rejected"] - b["rejected"] == 1 and j["open"] - b["open"] == 1
        ap, bp = j["approved_perf"], b["approved_perf"]
        assert ap["trades"] - bp["trades"] == 2 and ap["wins"] - bp["wins"] == 1 and abs((ap["pnl"] - bp["pnl"]) - 10) < 0.01
        assert j["no_ai_perf"]["trades"] - b["no_ai_perf"]["trades"] == 1

    def test_invalid_scope(self):
        r = requests.get(f"{BASE_URL}/api/ai/filter-stats", params={"scope": "xx"}, headers=H, timeout=30)
        assert r.status_code == 400

    def test_days_clamped(self):
        assert get("hfx", 500)["days"] == 90 and get("hfx", 0)["days"] == 1

    def test_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/ai/filter-stats", timeout=30).status_code == 401


# --- regression: LLM returns prefixed field names ("hfx.min_winrate") from the allowed list -> must still be accepted
def test_sanitize_prefixed_field():
    import sys
    sys.path.insert(0, "/app/backend")
    import server
    hb = {**server.hfx.HFX_BOT_DEFAULT, "min_winrate": 56, "pairs": ["EURUSD=X", "GBPUSD=X"]}
    a = server.sanitize_adj({"scope": "hfx", "field": "hfx.min_winrate", "value": 60, "reason": "x"}, hb, {}, {})
    assert a and a["field"] == "min_winrate" and a["value"] == 60
    assert server.sanitize_adj({"scope": "hfx", "field": "bot.min_winrate", "value": 60}, hb, {}, {}) is None

# Seed / clean AI filter stats data for UI checks (reuses test_iter10 seed shapes). Usage: python manual_seed_aistats.py [seed|clean]
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
UID, TAG = "user_test1", "TEST_aistats"
d = MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]


def clean():
    for c in ("hfx_trades", "positions", "ai_decisions"):
        d[c].delete_many({"tag": TAG})


def seed():
    clean()
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).timestamp()

    def hf(status, profit, conf=None):
        doc = {"trade_id": f"{TAG}_{uuid.uuid4().hex[:8]}", "tag": TAG, "user_id": UID, "origin": "bot", "status": status,
               "opened_ts": ts, "expires_ts": ts + 60, "pair": "EURUSD=X", "source": "otc", "direction": "call", "expiry": 1,
               "amount": 10, "profit": profit, "entry_price": 1.1, "exit_price": 1.1001}
        if conf is not None:
            doc["ai"] = {"confidence": conf, "reason": "TEST ok"}
        return doc
    d.hfx_trades.insert_many([hf("won", 8.5, 90), hf("won", 8.5, 88), hf("lost", -10, 75), hf("won", 8.5, 60),
                              hf("open", 0, 80), hf("won", 8.5), hf("lost", -10), hf("lost", -10)])
    d.ai_decisions.insert_many([{"tag": TAG, "user_id": UID, "scope": "hfx", "symbol": "EURUSD=X", "side": "call", "confidence": 40,
                                 "reason": r, "created_at": (now - timedelta(minutes=5 + i)).isoformat()}
                                for i, r in enumerate(["Tendência contrária", "Tendência contrária", "Volatilidade baixa"])])


if __name__ == "__main__":
    (clean if (sys.argv[1:] or ["seed"])[0] == "clean" else seed)()
    print("ok")

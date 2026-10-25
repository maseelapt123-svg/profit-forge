# Seed/clean TEST_ closed hfx trades for AI loss-review UI testing. Usage: python manual_seed_ai_review.py seed|clean
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
UID = "user_test1"
if sys.argv[1] == "seed":
    now = time.time()
    docs = []
    for i in range(6):
        ts = now - 600 * (i + 1)
        won = i % 3 == 0
        docs.append({"trade_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "pair": "EURUSD=X", "source": "otc",
                     "direction": "CALL" if i % 2 else "PUT", "amount": 10.0, "payout": 0.85, "expiry": 1, "entry_price": 1.1,
                     "opened_ts": ts, "expires_ts": ts + 60, "status": "won" if won else "lost", "profit": 8.5 if won else -10.0,
                     "origin": "bot", "rule": "rsi", "rule_label": "RSI reversão",
                     "closed_at": datetime.fromtimestamp(ts + 60, timezone.utc).isoformat(),
                     "ctx": {"aligned": i % 2 == 0, "rsi": 72.0, "vol_pct": 90, "hour": 14}})
    db.hfx_trades.insert_many(docs)
    print("seeded", len(docs))
else:
    print("deleted", db.hfx_trades.delete_many({"user_id": UID, "trade_id": {"$regex": "^TEST_"}}).deleted_count)
    print("reviews deleted", db.ai_reviews.delete_many({"user_id": UID}).deleted_count if "--reviews" in sys.argv else 0)

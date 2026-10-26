# Seed / clean bot trades for the Daily AI Summary feature (today + yesterday, UTC). Usage: python manual_seed_daily.py [seed|clean]
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

UID = "user_test1"
TAG = "TEST_daily"


def db():
    return MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]


def day_start(offset: int) -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)


def seed(offsets=(0, 1)):
    d = db()
    clean()
    for off in offsets:
        base = day_start(off)
        hf, pos = [], []
        # today: 6 hfx (3 won / 3 lost), 3 bot positions; yesterday: 4 hfx + 2 positions; plus boundary rows
        n_hfx = 6 if off == 0 else 4
        for i in range(n_hfx):
            hour = 1 + i  # keep within the past for today
            ts = (base + timedelta(hours=hour, minutes=5)).timestamp()
            won = i % 2 == 0
            hf.append({"id": f"{TAG}_{uuid.uuid4().hex[:8]}", "tag": TAG, "user_id": UID, "origin": "bot",
                       "status": "won" if won else "lost", "opened_ts": ts, "expires_ts": ts + 60,
                       "pair": "EURUSD=X", "source": "otc", "direction": "call" if won else "put", "expiry": 1,
                       "rule_label": "RSI reversão" if i % 3 else "EMA cruzamento", "amount": 10,
                       "profit": 8.5 if won else -10.0, "ctx": {"hour": hour}})
        n_pos = 3 if off == 0 else 2
        for i in range(n_pos):
            hour = 2 + i
            pnl = [25.0, -40.0, 12.5][i]
            pos.append({"id": f"{TAG}_{uuid.uuid4().hex[:8]}", "tag": TAG, "user_id": UID, "source": "bot",
                        "status": "closed", "symbol": "BTC-USD", "tf": "1h", "side": "long" if pnl > 0 else "short",
                        "qty": 0.01, "entry": 90000, "exit": 90100, "pnl": pnl, "reason": "tp" if pnl > 0 else "sl",
                        "opened_at": (base + timedelta(hours=hour - 1)).isoformat(),
                        "closed_at": (base + timedelta(hours=hour, minutes=10)).isoformat(), "ctx": {"hour": hour}})
        d.hfx_trades.insert_many(hf)
        d.positions.insert_many(pos)
    # boundary/noise rows that MUST NOT count: manual hfx trade today, open bot trade today, open position today
    b = day_start(0)
    d.hfx_trades.insert_many([
        {"id": f"{TAG}_m", "tag": TAG, "user_id": UID, "origin": "manual", "status": "won", "opened_ts": (b + timedelta(hours=1)).timestamp(),
         "expires_ts": (b + timedelta(hours=1)).timestamp() + 60, "pair": "EURUSD=X", "source": "otc", "direction": "call", "expiry": 1, "profit": 8.5},
        {"id": f"{TAG}_o", "tag": TAG, "user_id": UID, "origin": "bot", "status": "open", "opened_ts": (b + timedelta(hours=1)).timestamp(),
         "expires_ts": (b + timedelta(hours=1)).timestamp() + 60, "pair": "EURUSD=X", "source": "otc", "direction": "call", "expiry": 1, "profit": 0},
    ])


def clean():
    d = db()
    d.hfx_trades.delete_many({"tag": TAG})
    d.positions.delete_many({"tag": TAG})
    d.daily_summaries.delete_many({"user_id": UID})


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    (clean if (sys.argv[1:] or ["seed"])[0] == "clean" else seed)()
    print("ok")

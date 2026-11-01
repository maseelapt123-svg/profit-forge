# Iteration 9: backup/restore bot configs + seed closed bot trades today (hfx + main bot). Usage: python manual_seed_adjust.py [backup|seed|clean|restore]
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

UID = "user_test1"
TAG = "TEST_adj"
BACKUP = "/tmp/iter9_backup.json"


def db():
    return MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]


def backup():
    d = db()
    if os.path.exists(BACKUP):
        return
    data = {c: d[c].find_one({"user_id": UID}, {"_id": 0}) for c in ("hfx_bots", "bots", "plugins")}
    data["summaries"] = [s["date"] for s in d.daily_summaries.find({"user_id": UID}, {"date": 1})]
    with open(BACKUP, "w") as f:
        json.dump(data, f, default=str)


def restore():
    d = db()
    if not os.path.exists(BACKUP):
        return
    with open(BACKUP) as f:
        data = json.load(f)
    for c in ("hfx_bots", "bots", "plugins"):
        d[c].delete_one({"user_id": UID})
        if data.get(c):
            doc = data[c]
            if c == "plugins" and "updated_at" in doc:
                doc.pop("updated_at")
            d[c].insert_one(doc)
    d.daily_summaries.delete_many({"user_id": UID, "date": {"$nin": data.get("summaries", [])}})
    d.bot_logs.delete_many({"user_id": UID, "msg": {"$regex": "^Ajuste IA aplicado"}})
    os.remove(BACKUP)


def seed():
    d = db()
    clean()
    base = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now_h = max(datetime.now(timezone.utc).hour, 1)
    hf, pos = [], []
    for i in range(10):
        hour = i % now_h
        ts = (base + timedelta(hours=hour, minutes=5 + i)).timestamp()
        won = i in (0, 3, 7)  # 30% winrate -> poor day, triggers adjustments
        tid = f"{TAG}_{uuid.uuid4().hex[:8]}"
        hf.append({"id": tid, "trade_id": tid, "entry_price": 1.1, "exit_price": 1.1001, "tag": TAG, "user_id": UID, "origin": "bot",
                   "status": "won" if won else "lost", "opened_ts": ts, "expires_ts": ts + 60, "pair": "EURUSD=X",
                   "source": "otc", "direction": "call" if i % 2 else "put", "expiry": 1,
                   "rule_label": "RSI reversão" if i % 2 else "EMA cruzamento", "amount": 10,
                   "profit": 8.5 if won else -10.0,
                   "ctx": {"hour": hour, "aligned": i % 3 == 0, "rsi": 30 + i * 4, "vol_pct": 0.02 + i * 0.01}})
    for i, pnl in enumerate([-40.0, -35.0, 12.0, -50.0]):
        hour = i % now_h
        pid = f"{TAG}_{uuid.uuid4().hex[:8]}"
        pos.append({"id": pid, "position_id": pid, "tag": TAG, "user_id": UID, "source": "bot", "status": "closed",
                    "symbol": "BTC-USD", "tf": "1h", "side": "BUY", "qty": 0.01, "entry": 90000, "exit": 89900, "pnl": pnl,
                    "reason": "take_profit" if pnl > 0 else "stop_loss",
                    "opened_at": (base + timedelta(hours=hour)).isoformat(),
                    "closed_at": (base + timedelta(hours=hour, minutes=30)).isoformat(),
                    "ctx": {"hour": hour, "aligned": False, "rsi": 55, "vol_pct": 0.3}})
    d.hfx_trades.insert_many(hf)
    d.positions.insert_many(pos)


def clean():
    d = db()
    d.hfx_trades.delete_many({"tag": TAG})
    d.positions.delete_many({"tag": TAG})


if __name__ == "__main__":
    {"backup": backup, "seed": seed, "clean": clean, "restore": restore}[sys.argv[1] if len(sys.argv) > 1 else "seed"]()

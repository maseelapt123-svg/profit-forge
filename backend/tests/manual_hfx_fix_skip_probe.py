# Manual probe: HFX bot loop must skip entries blocked by auto-fix (hours fix = current hour) and log 'ignorado pela correção automática'
import os, sys, time, uuid
from datetime import datetime, timezone
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(__file__))
from test_iter6_loss_analysis import hfx_doc, BASE_URL, H, UID  # noqa

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
h = datetime.now(timezone.utc).hour
docs = [hfx_doc("AUDUSD=X", "TESTprobe", "Probe", False, h, True, 50) for _ in range(8)]
mdb.hfx_trades.insert_many(docs)
start = datetime.now(timezone.utc).isoformat()
try:
    fx = requests.post(f"{BASE_URL}/api/hfx/analysis/apply", headers=H).json()["fixes"]
    print("fixes", fx)
    pairs = [p["pair"] for p in requests.get(f"{BASE_URL}/api/hfx/pairs?source=otc", headers=H).json()]
    r = requests.put(f"{BASE_URL}/api/hfx/bot", headers=H, json={"enabled": True, "source": "otc", "pairs": pairs, "min_winrate": 50,
                                                               "min_votes": 1, "strategy": "auto", "max_per_hour": 60})
    print("enable", r.status_code, r.text)
    for i in range(16):
        time.sleep(15)
        skips = list(mdb.bot_logs.find({"user_id": UID, "scope": "hfx", "created_at": {"$gte": start}, "msg": {"$regex": "correção automática"}}, {"_id": 0, "msg": 1}))
        opened = mdb.hfx_trades.count_documents({"user_id": UID, "origin": "bot", "opened_ts": {"$gte": time.time() - 400}})
        print(i, "skips", len(skips), "opened", opened, skips[:2])
        if skips and i > 6:
            break
finally:
    requests.put(f"{BASE_URL}/api/hfx/bot", headers=H, json={"enabled": False, "source": "otc", "pairs": ["EURUSD=X", "GBPUSD=X"]})
    requests.post(f"{BASE_URL}/api/hfx/analysis/reset", headers=H)
    mdb.hfx_trades.delete_many({"trade_id": {"$regex": "^TEST_"}})
    print("cleanup done")

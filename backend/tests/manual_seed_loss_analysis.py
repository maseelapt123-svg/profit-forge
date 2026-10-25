# Manual helper: seed/cleanup synthetic loss-analysis data for UI testing. Usage: python manual_seed_loss_analysis.py seed|clean
import os, sys, uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(__file__))
from test_iter6_loss_analysis import hfx_doc, UID  # noqa

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
if sys.argv[1] == "seed":
    docs = [hfx_doc("EURUSD=X", "TESTrule", "Regra Teste", i < 2, 3, False, 10) for i in range(10)]
    docs += [hfx_doc("GBPUSD=X", "TESTok", "Regra OK", True, 15, True, 50) for _ in range(6)]
    mdb.hfx_trades.insert_many(docs)
    pos = [{"position_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "symbol": "BTC-USD", "side": "BUY", "qty": 0.01,
            "entry": 100.0, "exit": 90.0, "status": "closed", "source": "bot", "setup": "BTC-USD|1h", "tf": "1h",
            "pnl": 5.0 if i == 0 else -10.0, "reason": "take_profit" if i == 0 else "stop_loss",
            "ctx": {"hour": 4, "htf_aligned": False}, "opened_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            "closed_at": (datetime.now(timezone.utc) - timedelta(days=2, minutes=-i)).isoformat()} for i in range(8)]
    mdb.positions.insert_many(pos)
else:
    mdb.hfx_trades.delete_many({"trade_id": {"$regex": "^TEST_"}})
    mdb.positions.delete_many({"position_id": {"$regex": "^TEST_"}})
print("done", sys.argv[1])

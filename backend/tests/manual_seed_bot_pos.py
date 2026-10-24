# Seed/cleanup a fake open bot position (tf=5m) for user_test1 to verify Portfolio 'ROBÔ 5M' tag. Usage: python manual_seed_bot_pos.py seed|clean
import asyncio
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def main(cmd):
    if cmd == "seed":
        await db.positions.insert_one({"position_id": "TEST_botpos_5m", "user_id": "user_test1", "symbol": "BTC-USD", "side": "BUY", "qty": 0.01,
                                       "entry": 80000.0, "stop_loss": 70000.0, "take_profit": 95000.0, "status": "open", "source": "bot",
                                       "setup": "BTC-USD|5m", "tf": "5m", "stop_dist": 10000.0, "opened_at": datetime.now(timezone.utc).isoformat()})
    else:
        await db.positions.delete_many({"position_id": "TEST_botpos_5m"})
    print(cmd, "ok")

asyncio.run(main(sys.argv[1]))

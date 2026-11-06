"""One-off: attach test metrics to existing bot setups (from saved optimisation jobs) and drop those failing the rule."""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
from strategies import qualifies  # noqa: E402

db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def main():
    kept = dropped = 0
    async for bot in db.bots.find({}):
        uid = bot["user_id"]
        metrics = {}
        async for j in db.bot_opt_jobs.find({"user_id": uid}).sort("started", 1):
            for r in j.get("results") or []:
                b = r.get("best") or {}
                if b.get("test"):
                    metrics[(r["symbol"], r["tf"], b["strategy"])] = (b["test"]["return_pct"], b["test"]["win_rate"])
        async for j in db.mt_opt_jobs.find({"user_id": uid}).sort("started", 1):
            for r in (j.get("results") or {}).get("setups", []) if isinstance(j.get("results"), dict) else []:
                metrics[(r["symbol"], r["tf"], r["strategy"])] = (r["test"], r.get("wr", 0))
        new = []
        for s in bot.get("setups") or []:
            m = (s["test"], s.get("wr") or 0) if s.get("test") is not None else metrics.get((s["symbol"], s["tf"], s["strategy"]))
            if m and not qualifies(m[0], m[1]):
                dropped += 1
                continue
            if m:
                s = {**s, "test": round(m[0], 2), "wr": round(m[1], 1)}
            new.append(s)
            kept += 1
        await db.bots.update_one({"_id": bot["_id"]}, {"$set": {"setups": new}})
    print(f"kept {kept}, dropped {dropped}")


asyncio.run(main())

# Probe: bot cycle with setups opens independent positions per symbol+tf (forced signal via monkeypatch)
import asyncio
import sys
import numpy as np
sys.path.insert(0, "/app/backend")
import server  # noqa: E402

UID = "user_test1"


async def main():
    db = server.db
    await db.positions.delete_many({"user_id": UID, "source": "bot"})
    await db.bots.update_one({"user_id": UID}, {"$unset": {"last_bar": ""}})
    setups = [{"symbol": "BTC-USD", "tf": tf, "strategy": "smc", "sl_atr": 5.0 if tf == "5m" else 1.5, "rr": 2.0, "trend_filter": True, "mtf": tf == "5m"}
              for tf in ("5m", "1h")]
    await db.bots.update_one({"user_id": UID}, {"$set": {"enabled": False, "symbols": ["BTC-USD", "ETH-USD"], "tf": "1h",
                                                         "strategy": "smc", "max_positions": 10, "setups": setups, "mtf": True}}, upsert=True)
    server.strategy_signals = lambda df, strat, plugins: np.ones(len(df), dtype=int)
    server.apply_filters = lambda df, sig, *a, **k: sig
    bot = await server.get_bot(UID)
    n = await server.run_bot_cycle(bot)
    pos = await db.positions.find({"user_id": UID, "source": "bot", "status": "open"}, {"_id": 0}).to_list(50)
    print("opened", n)
    for p in pos:
        print(p["symbol"], p.get("tf"), p.get("setup"), p["side"])
    logs = await db.bot_logs.find({"user_id": UID}, {"_id": 0}).sort("created_at", -1).to_list(5)
    for l in logs:
        print("LOG", l["msg"])
    # second cycle must not duplicate (same closed bar)
    n2 = await server.run_bot_cycle(await server.get_bot(UID))
    print("second cycle opened", n2)
    # cleanup
    await db.positions.delete_many({"user_id": UID, "source": "bot"})
    await db.bots.update_one({"user_id": UID}, {"$set": {"enabled": False, "setups": [], "symbols": ["BTC-USD", "ETH-USD", "EURUSD=X"]},
                                                "$unset": {"last_bar": ""}})

asyncio.run(main())

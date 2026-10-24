# Probe: manual position with near SL/TP for a user without enabled bot should be closed by background loop (<= ~70s)
import os
import time

import requests

B = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
s = requests.Session()
s.headers.update({"Authorization": "Bearer test_token_123", "Content-Type": "application/json"})
s.post(f"{B}/api/portfolio/reset")
b = s.get(f"{B}/api/bot").json()["bot"]
print("bot enabled:", b["enabled"])
px = s.get(f"{B}/api/candles", params={"symbol": "BTC-USD", "tf": "1m"}).json()["candles"][-1]["c"]
r = s.post(f"{B}/api/orders", json={"symbol": "BTC-USD", "side": "BUY", "qty": 0.001})
print("order:", r.status_code, r.text[:200])
pid = r.json().get("position_id")
# Verify via DB-free path: poll /api/bot logs? Use history count but avoid /api/portfolio (it also auto-closes).
# So we query mongo directly to see if background loop closed it.
from pymongo import MongoClient  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
env = dotenv_values("/app/backend/.env")
db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
db.positions.update_one({"position_id": pid}, {"$set": {"stop_loss": px * 1.5}})  # simulate SL hit
for i in range(16):
    p = db.positions.find_one({"position_id": pid}, {"_id": 0, "status": 1, "reason": 1, "closed_at": 1})
    print(i * 5, "s:", p)
    if p and p["status"] == "closed":
        print("CLOSED BY BACKGROUND LOOP")
        break
    time.sleep(5)
s.post(f"{B}/api/portfolio/reset")

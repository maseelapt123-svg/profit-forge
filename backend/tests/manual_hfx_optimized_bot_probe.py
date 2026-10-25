# Manual probe: HFX bot in 'optimized' strategy opens trades using per-pair setups (run: python tests/manual_hfx_optimized_bot_probe.py)
import os
import time
import requests

B = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
s = requests.Session()
s.headers.update({"Authorization": "Bearer test_token_123"})

sig = s.get(f"{B}/hfx/signals", params={"source": "otc", "expiry": 1}).json()
setups = {x["pair"]: {"rule": x["best"]["rule"], "expiry": 1} for x in sig if x.get("best")}
print("setups:", setups)
cur = s.get(f"{B}/hfx/bot").json()["bot"]
start = time.time()
r = s.put(f"{B}/hfx/bot", json={**cur, "enabled": True, "source": "otc", "strategy": "optimized", "pairs": list(setups),
                                 "setups": setups, "min_winrate": 50, "max_per_hour": 3, "amount": 5})
print("put:", r.status_code, r.text[:200])
opened = []
while time.time() - start < 200:
    d = s.get(f"{B}/hfx/trades").json()
    opened = [t for t in d["open"] + d["closed"] if t.get("origin") == "bot" and t["opened_ts"] >= start]
    if len(opened) >= 1 and time.time() - start > 130:
        break
    time.sleep(10)
print("bot trades since start:", [(t["pair"], t["direction"], t["amount"], t["status"]) for t in opened])
print("max_per_hour respected (<=3):", len(opened) <= 3)
logs = s.get(f"{B}/hfx/bot").json()["logs"][:6]
print("hfx logs:", [l.get("message") for l in logs])
main = s.get(f"{B}/bot").json()
ml = [l.get("message", "") for l in main.get("logs", [])]
print("main bot logs containing HFX:", [m for m in ml if "HFX" in m][:3])
s.put(f"{B}/hfx/bot", json={**cur, "enabled": False, "strategy": "auto", "setups": {}})
print("restored:", s.get(f"{B}/hfx/bot").json()["bot"]["enabled"])

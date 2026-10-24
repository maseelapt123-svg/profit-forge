# Probe: try each strategy/tf to make bot open at least one position (verifies open path, source='bot', max_positions)
import os
import requests

B = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
s = requests.Session()
s.headers.update({"Authorization": "Bearer test_token_123"})
s.post(f"{B}/api/portfolio/reset")
assets = [a["symbol"] for a in s.get(f"{B}/api/bot").json()["assets"]]
total = 0
for tf in ("15m", "1h", "4h"):
    for st in ("smc", "rsi", "ema_cross", "macd", "bollinger", "combo"):
        s.put(f"{B}/api/bot", json={"enabled": False, "symbols": assets, "tf": tf, "strategy": st,
                                     "risk_pct": 1, "sl_atr": 1.5, "rr": 2, "max_positions": 2})
        r = s.post(f"{B}/api/bot/run", timeout=280)
        o = r.json().get("opened") if r.ok else r.text[:100]
        print(tf, st, r.status_code, o)
        if r.ok:
            total += o
        if total:
            break
    if total:
        break
pf = s.get(f"{B}/api/portfolio").json()
bp = [p for p in pf["positions"] if p.get("source") == "bot"]
print("bot positions:", len(bp), [(p["symbol"], p["side"], round(p["entry"], 4), round(p["stop_loss"], 4), round(p["take_profit"], 4), round(p["qty"], 6)) for p in bp])
logs = s.get(f"{B}/api/bot").json()
print("stats:", logs["stats"])
print("logs:", [(l["kind"], l["msg"]) for l in logs["logs"][:8]])

# Probe: fire concurrent /api/bot/run calls and verify per-user lock prevents duplicate bot positions per symbol
import collections
import concurrent.futures as cf
import os

import requests

B = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
s = requests.Session()
s.headers.update(H)
s.post(f"{B}/api/portfolio/reset")
assets = [a["symbol"] for a in s.get(f"{B}/api/bot").json()["assets"]]
done = False
for tf in ("15m", "1h", "4h", "5m"):
    for st in ("rsi", "ema_cross", "macd", "bollinger", "smc", "combo"):
        s.put(f"{B}/api/bot", json={"enabled": True, "symbols": assets, "tf": tf, "strategy": st, "trend_filter": False,
                                     "risk_pct": 0.1, "sl_atr": 1.5, "rr": 2, "max_positions": 10, "overrides": {}})
        with cf.ThreadPoolExecutor(5) as ex:
            res = list(ex.map(lambda _: requests.post(f"{B}/api/bot/run", headers=H, timeout=280), range(5)))
        opened = [r.json().get("opened") if r.ok else r.status_code for r in res]
        print(tf, st, opened)
        if any(isinstance(o, int) and o > 0 for o in opened):
            done = True
            break
    if done:
        break
pf = s.get(f"{B}/api/portfolio").json()
c = collections.Counter(p["symbol"] for p in pf["positions"] if p.get("source") == "bot")
print("bot positions per symbol:", dict(c))
print("DUPLICATES:" if any(v > 1 for v in c.values()) else "NO DUPLICATES", {k: v for k, v in c.items() if v > 1})
s.put(f"{B}/api/bot", json={"enabled": False, "symbols": ["BTC-USD", "EURUSD=X"], "tf": "1h", "strategy": "smc", "trend_filter": True,
                             "risk_pct": 1, "sl_atr": 1.5, "rr": 2, "max_positions": 3, "overrides": {}})
s.post(f"{B}/api/portfolio/reset")
